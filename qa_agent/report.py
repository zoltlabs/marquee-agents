"""qa_agent/report.py

Orchestrator for the `qa-agent report` command — stream-based (prefetch model).

Flow:
  1. Validate simulation directory.
  2. Pre-fetch all sim data via report_prefetch.collect_sim_data() — pure Python,
     no AI involved.  All tool security rules (path containment, output caps,
     allowlists) still apply.
  3. Optionally show the assembled prompt in gvim for review (--gvim).
  4. Stream the AI response via agents/dv_debug_agent.run_dv_debug_agent() which
     uses claude-agent-sdk under the hood — no ANTHROPIC_API_KEY required in code.
  5. Write the structured Markdown report to disk.

The original agentic (tool-calling) approach is preserved — its loop, registry,
and agent are in:
    qa_agent/tools/loop.py
    qa_agent/tools/report/
    qa_agent/agents/dv_debug_agent_agentic.py
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from qa_agent.output import bold, cyan, dim, green, print_header, print_rich_error, red
from qa_agent.session_log import SessionLog


def run(
    sim_dir: str,
    provider: str = "claude",
    output: str | None = None,
    max_turns: int = 15,
    verbose: bool = False,
    debug: bool = False,
    gvim: bool = False,
    log: SessionLog | None = None,
) -> None:
    """Entry point for the report command.

    Args:
        sim_dir:   Path to the simulation output directory.
        provider:  AI provider name ("claude", "openai", "gemini").
        output:    Output markdown file path. Defaults to debug_report_<ts>.md.
        max_turns: Unused in stream mode — kept for CLI compatibility.
        verbose:   Print detailed progress and stream AI output to stdout.
        debug:     Developer mode (+ session log).
        gvim:      Show assembled prompt in gvim for review before sending to AI.
        log:       Active SessionLog instance.
    """
    if verbose or debug:
        print_header("qa-agent report", f"AI-driven DV triage via {provider}")

    # 1. Validate simulation directory
    try:
        sim_path = Path(sim_dir).resolve(strict=True)
    except OSError:
        raise ValueError(f"Target directory does not exist: {sim_dir}")

    if not sim_path.is_dir():
        raise ValueError(f"Target is not a directory: {sim_dir}")

    if verbose:
        print(f"  {cyan('Target:')} {sim_path}")

    # 2. Build output path
    if output:
        out_path = Path(output)
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = Path(f"debug_report_{ts}.md")

    if log:
        log.event("report start", sim_dir=str(sim_path), provider=provider)

    # 3. Pre-fetch all simulation data
    print(f"\n  {dim('Collecting simulation data...')} ", end="", flush=True)
    try:
        from qa_agent.report_prefetch import collect_sim_data
        sim_data = collect_sim_data(sim_path)
    except Exception as exc:
        print(f"{red('FAILED')}")
        print_rich_error(f"Data collection failed: {exc}")
        raise

    data_lines = sim_data.count("\n")
    print(f"{green('OK')} {dim(f'({data_lines} lines collected)')}")

    # 4. Build the full prompt for review / sending
    from qa_agent.agents.dv_debug_agent import build_prompt
    request = build_prompt(sim_data)

    # 5. Optional gvim review — show the full assembled prompt before sending
    if gvim:
        dump_file = Path(tempfile.gettempdir()) / "qa_agent_report_prompt.md"
        dump_text = (
            "# qa-agent report — Assembled Prompt\n\n"
            f"**Provider:** {provider}\n"
            f"**Sim dir:** {sim_path}\n\n"
            "---\n\n"
            "## SYSTEM PROMPT\n\n"
            f"{request.system_prompt}\n\n"
            "---\n\n"
            "## USER PROMPT (with embedded sim data)\n\n"
            f"{request.user_prompt}\n"
        )
        dump_file.write_text(dump_text, encoding="utf-8")

        try:
            subprocess.run(
                ["gvim", "-f", str(dump_file)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            print(f"  {dim(f'Warning: could not open gvim: {exc}')}")

        from qa_agent.output import arrow_select
        try:
            ans = arrow_select(
                f"{bold('?')} Review complete. Send this prompt to the AI?",
                [("Proceed", "send to AI"), ("Stop", "abort and exit")],
            )
            if ans != 0:
                print("  Aborted by user.")
                sys.exit(0)
        except KeyboardInterrupt:
            print("\n  Aborted by user.")
            sys.exit(0)

    # 6. Run the stream-based AI agent
    print(f"  {dim('Sending to AI')} {dim('(' + provider + ')...')}")
    if verbose:
        print()

    try:
        report_text = asyncio.run(
            _run_agent(
                sim_data=sim_data,
                provider=provider,
                verbose=verbose,
            )
        )
    except Exception as exc:
        if log:
            log.error(exc)
        print()
        print_rich_error(f"Investigation failed: {type(exc).__name__}: {exc}")
        if not verbose:
            print(f"  {dim('Run with')} {bold('--verbose')} {dim('for a full traceback.')}")
        raise

    if verbose:
        print()

    # 7. Write the final report
    print(f"\n  {dim('Writing report...')} ", end="", flush=True)
    try:
        out_path.write_text(report_text, encoding="utf-8")
        print(f"{green('OK')}")
        print()
        print(f"  {bold('Report saved to:')} {cyan(str(out_path))}")
        if log:
            log.event("report complete", path=str(out_path), bytes=len(report_text))
    except OSError as exc:
        print(f"{red('FAILED')}")
        print_rich_error(f"Could not write report to {out_path}: {exc}")
        if log:
            log.error(exc)
        raise

    print()


async def _run_agent(sim_data: str, provider: str, verbose: bool) -> str:
    """Async wrapper around run_dv_debug_agent."""
    from qa_agent.agents.dv_debug_agent import run_dv_debug_agent
    return await run_dv_debug_agent(sim_data, provider=provider, verbose=verbose)
