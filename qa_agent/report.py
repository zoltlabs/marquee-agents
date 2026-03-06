"""qa_agent/report.py

Orchestrator for the `qa-agent report` command.

Coordinates the CLI arguments, the AI provider, the ToolRegistry, and the
DV debug agent. Runs the agentic loop and writes the final markdown report.
"""

from __future__ import annotations

import asyncio
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
        max_turns: Maximum number of agentic tool turns.
        verbose:   Print detailed progress and tool calls.
        debug:     Developer mode (+ session log).
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
        log.info(action="report_start", sim_dir=str(sim_path), provider=provider)

    # 3. Build tool registry
    from qa_agent.tools.report import build_report_tools
    print(f"\n  {dim('Building tool registry...')} ", end="", flush=True)
    tools = build_report_tools(sim_path)
    print(f"{green('OK')} {dim(f'({len(tools.all_defs())} tools bound to target)')}")

    # 4. Run the inner async investigation loop
    print(f"  {dim('Starting AI investigation (max turns:')} {max_turns}{dim(')...')}")
    print()

    from qa_agent.agents.dv_debug_agent import run_dv_debug_agent

    try:
        report_text = asyncio.run(
            run_dv_debug_agent(
                sim_dir=sim_path,
                tools=tools,
                provider=provider,
                max_turns=max_turns,
                verbose=verbose,
                gvim=gvim,
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

    # 5. Write the final report
    print()
    print(f"  {dim('Writing report...')} ", end="", flush=True)

    try:
        out_path.write_text(report_text, encoding="utf-8")
        print(f"{green('OK')}")
        print()
        print(f"  {bold('Report saved to:')} {cyan(str(out_path))}")
        if log:
            log.info(action="report_complete", path=str(out_path), bytes=len(report_text))
    except OSError as exc:
        print(f"{red('FAILED')}")
        print_rich_error(f"Could not write report to {out_path}: {exc}")
        if log:
            log.error(exc)
        raise

    print()
