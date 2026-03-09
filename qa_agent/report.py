"""qa_agent/report.py

Orchestrator for the `qa-agent report` command — stream-based (prefetch model).

Flow:
  1. Validate simulation directory or discover `debug_` subdirectories.
  2. Pre-fetch all sim data via report_prefetch.collect_sim_data() — pure Python,
     no AI involved. All tool security rules (path containment, output caps,
     allowlists) still apply.
  3. Optionally show the assembled prompt in gvim for review (--gvim).
  4. Stream the AI response via agents/dv_debug_agent.run_dv_debug_agent() which
     uses claude-agent-sdk under the hood.
  5. Write the individual structured Markdown report to disk containing sim data,
     metadata, and the AI's analysis without prompt text.
  6. Aggregate results into a summary `QA-AGENT_REPORT_<timestamp>.md`.

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


def _extract_section(markdown: str, section_title: str) -> str:
    """Extract a specific ## section from a Markdown string."""
    lines = markdown.splitlines()
    capturing = False
    content = []
    for line in lines:
        if line.startswith("## ") and section_title.lower() in line.lower():
            capturing = True
            continue
        elif line.startswith("## ") and capturing:
            break
        if capturing:
            content.append(line)
    return "\n".join(content).strip() or "*Not found*"


def run(
    sim_dir: str | None,
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
        sim_dir:   Path to the simulation output directory, or None for batch mode.
        provider:  AI provider name ("claude", "openai", "gemini").
        output:    Output markdown file path (single dir mode only).
        max_turns: Unused in stream mode — kept for CLI compatibility.
        verbose:   Print detailed progress and stream AI output to stdout.
        debug:     Developer mode (+ session log).
        gvim:      Show assembled prompt in gvim for review before sending to AI.
        log:       Active SessionLog instance.
    """
    if verbose or debug:
        print_header("qa-agent report", f"AI-driven DV triage via {provider}")

    cwd = Path.cwd()
    targets: list[Path] = []

    # 1. Directory Discovery
    if sim_dir is not None:
        try:
            target_path = Path(sim_dir).resolve(strict=True)
        except OSError:
            raise ValueError(f"Target directory does not exist: {sim_dir}")

        if not target_path.is_dir():
            raise ValueError(f"Target is not a directory: {sim_dir}")
            
        targets.append(target_path)
    else:
        # Search for debug_ prefixed subdirectories
        for entry in cwd.iterdir():
            if entry.is_dir() and entry.name.startswith("debug_"):
                targets.append(entry)
        
        targets.sort()

        # If none found, check if current directory is debug_ prefixed
        if not targets:
            if cwd.name.startswith("debug_"):
                targets.append(cwd)
            else:
                raise ValueError(
                    "No directory with 'debug_' prefix found in current directory, "
                    "and the current directory itself does not have a 'debug_' prefix."
                )

    total_count = len(targets)
    if verbose or total_count > 1:
        print(f"  {cyan('Discovered targets:')} {total_count} directory(s)")

    # 2. Setup Summary Report
    run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_lines = [
        f"# QA Regression Analysis Report",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Mode:** Batch Report",
        f"",
        f"## Summary",
        f"**[SUMMARY_PLACEHOLDER]**",
        f"",
        f"---",
        f"",
    ]
    
    processed_count = 0
    failed_count = 0

    # 3. Process Each Target
    for idx, sim_path in enumerate(targets, 1):
        if verbose or debug or total_count > 1:
            print(f"\n{bold(cyan(f'[{idx}/{total_count}] Processing:'))} {sim_path.name}")
            
        if log:
            log.event("report start", sim_dir=str(sim_path), provider=provider)

        print(f"  {dim('Collecting simulation data...')} ", end="", flush=True)
        try:
            from qa_agent.report_prefetch import collect_sim_data
            sim_data = collect_sim_data(sim_path)
            data_lines = sim_data.count("\n")
            print(f"{green('OK')} {dim(f'({data_lines} lines)')}")
        except Exception as exc:
            print(f"{red('FAILED')}")
            print_rich_error(f"Data collection failed: {exc}")
            failed_count += 1
            summary_lines.append(f"### [{idx}] {sim_path.name}")
            summary_lines.append(f"**Error:** Data collection failed: {exc}\n")
            continue

        from qa_agent.agents.dv_debug_agent import build_prompt
        request = build_prompt(sim_data)

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

            total_chars = len(request.system_prompt) + len(request.user_prompt)
            estimated_tokens = total_chars // 4
            total_lines = request.system_prompt.count("\n") + request.user_prompt.count("\n")

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
                    f"{bold('?')} Review complete. Prompt size: ~{total_lines:,} lines (~{estimated_tokens:,} tokens). Send this prompt to the AI?",
                    [("Proceed", "send to AI"), ("Stop", "abort and exit")],
                )
                if ans != 0:
                    print("  Aborted by user.")
                    sys.exit(0)
            except KeyboardInterrupt:
                print("\n  Aborted by user.")
                sys.exit(0)

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
            processed_count += 1
        except Exception as exc:
            if log:
                log.error(exc)
            print()
            print_rich_error(f"Investigation failed: {type(exc).__name__}: {exc}")
            if not verbose:
                print(f"  {dim('Run with')} {bold('--verbose')} {dim('for a full traceback.')}")
            failed_count += 1
            summary_lines.append(f"### [{idx}] {sim_path.name}")
            summary_lines.append(f"**Error:** AI investigation failed: {exc}\n")
            continue

        if verbose:
            print()

        # 4. Write Individual Report
        out_name = output if output and total_count == 1 else f"QA-AGENT_REPORT_{run_timestamp}.md"
        out_path = sim_path / out_name
        
        print(f"  {dim('Writing individual directory report...')} ", end="", flush=True)
        try:
            # Reformat to exclude prompt, keep metadata/sim_data, and append AI report
            out_content = (
                f"# QA Agent Debug Report\n"
                f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"**Target:** {sim_path.name}\n\n"
                f"---\n\n"
                f"## AI Analysis Report\n\n"
                f"{report_text}\n\n"
                f"---\n\n"
                f"{sim_data}\n"
            )
            out_path.write_text(out_content, encoding="utf-8")
            print(f"{green('OK')}")
            print(f"  {bold('Saved to:')} {cyan(str(out_path))}")
            if log:
                log.event("report complete", path=str(out_path), bytes=len(out_content))
        except OSError as exc:
            print(f"{red('FAILED')}")
            print_rich_error(f"Could not write report to {out_path}: {exc}")
            if log:
                log.error(exc)
            failed_count += 1
            summary_lines.append(f"### [{idx}] {sim_path.name}")
            summary_lines.append(f"**Error:** Could not write individual report: {exc}\n")
            continue

        # 5. Append to Summary log
        exec_summary = _extract_section(report_text, "Executive Summary")
        classification = _extract_section(report_text, "Failure Classification")
        
        testcase = sim_path.name.replace("debug_", "", 1)
        summary_lines.append(f"### [{idx}] {testcase}")
        summary_lines.append(f"**Executive Summary:**\n{exec_summary}\n")
        summary_lines.append(f"**Classification:**\n{classification}\n")
        summary_lines.append(f"**Full Report:** [Link]({out_path.resolve()})\n")
        summary_lines.append(f"---\n")

    print()
    
    # 6. Write Summary Report in parent directory
    if total_count > 0:
        summary_out_path = cwd / f"QA-AGENT_REPORT_{run_timestamp}.md"
        print(f"  {dim('Writing aggregate summary report...')} ", end="", flush=True)
        try:
            metrics = f"- Total: {total_count} | Processed: {processed_count} | Failed: {failed_count}"
            idx_placeholder = summary_lines.index("**[SUMMARY_PLACEHOLDER]**")
            summary_lines[idx_placeholder] = metrics
            
            summary_out_path.write_text("\n".join(summary_lines), encoding="utf-8")
            print(f"{green('OK')}")
            print(f"  {bold('Summary Report saved to:')} {cyan(str(summary_out_path))}")
            print()
        except OSError as exc:
            print(f"{red('FAILED')}")
            print_rich_error(f"Could not write summary report: {exc}")


async def _run_agent(sim_data: str, provider: str, verbose: bool) -> str:
    """Async wrapper around run_dv_debug_agent."""
    from qa_agent.agents.dv_debug_agent import run_dv_debug_agent
    return await run_dv_debug_agent(sim_data, provider=provider, verbose=verbose)
