"""qa_agent/report.py

Orchestrator for the `qa-agent report` command.

Supports two modes:

Stream mode (default):
  Pre-fetches all simulation data into a single prompt and sends to AI.
  Fast, no user interaction required during generation.

Agentic mode (--agentic):
  AI starts with zero context, uses tools to discover and fetch data.
  Each tool result is shown to the user for preview before feeding to AI
  (Run → Show → Accept/Reject).
  Includes: confidence scoring, waveform timestamp extraction,
  cross-failure correlation (batch), and regression comparison (--compare).

Report naming:
  Individual debug case:   DEBUG_CASE_REPORT_<timestamp>.md   (inside sim_dir)
  Batch regression summary: QA-REGRESSION-SUMMARY_<timestamp>.md (in cwd)
  Regression comparison:   QA-REGRESSION-COMPARISON_<timestamp>.md
  Waveform timestamps:     QA-AGENT_TIMESTAMPS_<timestamp>.json
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from qa_agent.output import (
    bold, cyan, dim, green, print_header, print_footer, print_rich_error, red, console
)
from qa_agent.session_log import SessionLog


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

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


def _extract_confidence(report_text: str) -> str:
    """Extract the confidence score line from the report."""
    import re
    m = re.search(r"\*\*(\d+)/10\*\*[^\n]*", report_text)
    return m.group(0) if m else ""


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def run(
    sim_dir: str | None,
    provider: str = "claude",
    output: str | None = None,
    max_turns: int = 20,
    verbose: bool = False,
    debug: bool = False,
    gvim: bool = False,
    agentic: bool = False,
    auto_accept: bool = False,
    compare: tuple[str, str] | None = None,
    log: SessionLog | None = None,
) -> None:
    """Entry point for the report command.

    Args:
        sim_dir:      Path to simulation directory, or None for batch mode.
        provider:     AI provider name ("claude", "openai", "gemini").
        output:       Optional output file path (single dir mode only).
        max_turns:    Max AI investigation turns (agentic mode only).
        verbose:      Show detailed progress and tool details in preview card.
        debug:        Developer mode (--verbose + session log).
        gvim:         Open tool results in gvim instead of terminal preview.
        agentic:      Use agentic tool-calling mode (default: stream mode).
        auto_accept:  Auto-accept all tool results without user review.
        compare:      Tuple (old_report, new_report) for --compare mode.
        log:          Active SessionLog instance.
    """
    # ── Comparison mode ───────────────────────────────────────────────────────
    if compare is not None:
        from qa_agent.report_compare import run_compare
        asyncio.run(run_compare(
            compare[0], compare[1],
            provider=provider,
            output=output or "",
            verbose=verbose or debug,
        ))
        return

    print_header("qa-agent report", f"{'agentic' if agentic else 'stream'} mode · {provider}")

    cwd = Path.cwd()
    targets: list[Path] = []

    # ── Directory discovery ───────────────────────────────────────────────────
    if sim_dir is not None:
        try:
            target_path = Path(sim_dir).resolve(strict=True)
        except OSError:
            raise ValueError(f"Target directory does not exist: {sim_dir}")
        if not target_path.is_dir():
            raise ValueError(f"Target is not a directory: {sim_dir}")
        targets.append(target_path)
    else:
        for entry in sorted(cwd.iterdir()):
            if entry.is_dir() and entry.name.startswith("debug_"):
                targets.append(entry)
        if not targets:
            if cwd.name.startswith("debug_"):
                targets.append(cwd)
            else:
                raise ValueError(
                    "No directory with 'debug_' prefix found in current directory, "
                    "and the current directory itself does not have a 'debug_' prefix."
                )

    total_count = len(targets)
    console.print(
        f"  [bright_cyan]Discovered:[/bright_cyan] {total_count} simulation director{'y' if total_count == 1 else 'ies'}  "
        f"[dim]({'agentic' if agentic else 'stream'} · {provider})[/dim]"
    )

    run_timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── Batch summary report header ───────────────────────────────────────────
    summary_lines = [
        "# QA Regression Summary Report",
        f"",
        f"**Generated:** {now_str}  ",
        f"**Mode:** {'Agentic' if agentic else 'Stream'} · {provider}  ",
        f"**Targets:** {total_count}  ",
        f"",
        "## Summary Table",
        "",
        "| # | Test Case | Status | Failure Type | Confidence | Report |",
        "|---|-----------|--------|--------------|------------|--------|",
    ]

    processed_count = 0
    failed_count = 0
    individual_summaries: list[dict[str, str]] = []  # for correlation pass

    # ─── Process each target ─────────────────────────────────────────────
    for idx, sim_path in enumerate(targets, 1):
        console.print(
            f"\n  [bold bright_cyan][{idx}/{total_count}][/bold bright_cyan] "
            f"[white]{sim_path.name}[/white]"
        )

        if log:
            log.event("report start", sim_dir=str(sim_path), provider=provider)

        test_name = sim_path.name.replace("debug_", "", 1)

        # ── Branch: agentic vs stream ─────────────────────────────────────
        if agentic:
            report_text = _run_agentic(
                sim_path=sim_path,
                provider=provider,
                max_turns=max_turns,
                verbose=verbose or debug,
                gvim=gvim,
                auto_accept=auto_accept,
                log=log,
                idx=idx,
                total=total_count,
            )
        else:
            report_text = _run_stream(
                sim_path=sim_path,
                provider=provider,
                verbose=verbose or debug,
                gvim=gvim,
                log=log,
                idx=idx,
                total=total_count,
            )

        if report_text is None:
            failed_count += 1
            summary_lines.append(
                f"| {idx} | {test_name} | ❌ ERROR | — | — | — |"
            )
            continue

        processed_count += 1

        # ── Write individual per-case debug report ────────────────────────
        case_ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        out_name = (
            output
            if output and total_count == 1
            else f"DEBUG_CASE_REPORT_{case_ts}.md"
        )
        out_path = sim_path / out_name

        exec_summary = _extract_section(report_text, "Executive Summary")
        classification = _extract_section(report_text, "Failure Classification")
        confidence = _extract_confidence(report_text)

        out_content = (
            f"# Debug Case Report — {test_name}\n\n"
            f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  \n"
            f"**Target:** `{sim_path.name}`  \n"
            f"**Provider:** {provider}  \n"
            f"**Mode:** {'Agentic' if agentic else 'Stream'}  \n"
            f"\n---\n\n"
            f"{report_text}\n"
        )

        try:
            out_path.write_text(out_content, encoding="utf-8")
            console.print(
                f"  [bold green]✓[/bold green]  Report saved: "
                f"[bright_cyan]{out_path.name}[/bright_cyan]"
            )
            if confidence:
                console.print(f"  [dim]Confidence: {confidence}[/dim]")
            if log:
                log.event("report complete", path=str(out_path), bytes=len(out_content))
        except OSError as exc:
            print_rich_error(f"Could not write report to {out_path}: {exc}")
            failed_count += 1
            summary_lines.append(
                f"| {idx} | {test_name} | ❌ WRITE ERROR | — | — | — |"
            )
            continue

        # ── Extract and write waveform timestamps (agentic mode only) ─────
        if agentic:
            from qa_agent.report_timestamps import extract_timestamps, write_timestamps
            ts_list = extract_timestamps(report_text)
            if ts_list:
                try:
                    ts_path = write_timestamps(
                        ts_list, sim_path,
                        report_timestamp=datetime.now(),
                        test_name=test_name,
                    )
                    console.print(
                        f"  [dim]Timestamps:[/dim] "
                        f"[bright_cyan]{ts_path.name}[/bright_cyan] "
                        f"[dim]({len(ts_list)} event(s))[/dim]"
                    )
                except OSError as e:
                    console.print(f"  [dim yellow]Warning: could not write timestamps: {e}[/dim yellow]")

        # ── Collect summary for batch aggregation ─────────────────────────
        # Parse failure type from classification block
        import re
        type_m = re.search(r"\*\*Type\*\*:\s*(.+)", classification)
        failure_type = type_m.group(1).strip() if type_m else "—"
        verdict = "❌ FAIL" if "FAIL" in exec_summary.upper() or "fail" in report_text.lower()[:500] else "✅ PASS"

        summary_lines.append(
            f"| {idx} | {test_name} | {verdict} | {failure_type} | "
            f"{confidence or '—'} | "
            f"[report]({out_path.resolve()}) |"
        )

        # Collect for correlation
        individual_summaries.append({
            "test_name": test_name,
            "executive_summary": exec_summary[:1000],
            "classification": classification[:200],
        })

    # ─── Cross-failure correlation (agentic batch, 2+ targets) ───────────────
    if agentic and len(individual_summaries) >= 2:
        console.print(
            "\n  [bright_cyan]Running cross-failure correlation analysis…[/bright_cyan]"
        )
        with console.status("Correlation pass…", spinner="dots"):
            from qa_agent.agents.correlation_agent import run_correlation_agent
            correlation_text = asyncio.run(
                run_correlation_agent(individual_summaries, provider=provider)
            )
        if correlation_text.strip():
            summary_lines.extend([
                "",
                "---",
                "",
                correlation_text,
            ])

    # ─── Write aggregate summary report ──────────────────────────────────────
    console.print()
    suffix = (
        f"{processed_count}/{total_count} processed · {failed_count} failed"
    )

    summary_lines.extend([
        "",
        "---",
        "",
        f"*{suffix}  ·  Generated by qa-agent {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
    ])

    summary_path = cwd / f"QA-REGRESSION-SUMMARY_{run_timestamp}.md"
    try:
        summary_path.write_text("\n".join(summary_lines), encoding="utf-8")
        console.print(
            f"  [bold green]✓[/bold green]  Summary report: "
            f"[bright_cyan]{summary_path.name}[/bright_cyan]"
        )
    except OSError as exc:
        print_rich_error(f"Could not write summary report: {exc}")

    print_footer(
        f"Done — {processed_count}/{total_count} reports generated.",
        success=(failed_count == 0),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Agentic runner
# ─────────────────────────────────────────────────────────────────────────────

def _run_agentic(
    sim_path: Path,
    provider: str,
    max_turns: int,
    verbose: bool,
    gvim: bool,
    auto_accept: bool,
    log: SessionLog | None,
    idx: int,
    total: int,
) -> str | None:
    """Run the agentic agent on one simulation directory.

    Returns the report text, or None on failure.
    """
    console.print(
        f"  [dim]Mode: agentic · max_turns={max_turns}"
        f"{' · gvim' if gvim else ''}"
        f"{' · auto-accept' if auto_accept else ''}[/dim]"
    )
    try:
        report_text = asyncio.run(
            _run_agentic_async(
                sim_path=sim_path,
                provider=provider,
                max_turns=max_turns,
                verbose=verbose,
                gvim=gvim,
                auto_accept=auto_accept,
            )
        )
        return report_text
    except Exception as exc:
        if log:
            log.error(exc)
        print_rich_error(f"Agentic investigation failed: {type(exc).__name__}: {exc}")
        if not verbose:
            console.print(
                f"  [dim]Run with[/dim] [bold]--verbose[/bold] [dim]for a full traceback.[/dim]"
            )
        return None


async def _run_agentic_async(
    sim_path: Path,
    provider: str,
    max_turns: int,
    verbose: bool,
    gvim: bool,
    auto_accept: bool,
) -> str:
    from qa_agent.agents.dv_debug_agent_agentic import run_dv_debug_agent_agentic
    return await run_dv_debug_agent_agentic(
        str(sim_path),
        provider=provider,
        max_turns=max_turns,
        verbose=verbose,
        use_gvim=gvim,
        auto_accept=auto_accept,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Stream runner (original flow — unchanged)
# ─────────────────────────────────────────────────────────────────────────────

def _run_stream(
    sim_path: Path,
    provider: str,
    verbose: bool,
    gvim: bool,
    log: SessionLog | None,
    idx: int,
    total: int,
) -> str | None:
    """Run the stream-based (prefetch) agent on one simulation directory.

    Returns the report text, or None on failure.
    """
    console.print(f"  [dim]Collecting simulation data…[/dim]", end="")
    try:
        from qa_agent.report_prefetch import collect_sim_data
        sim_data = collect_sim_data(sim_path)
        data_lines = sim_data.count("\n")
        console.print(f" [bold green]OK[/bold green] [dim]({data_lines} lines)[/dim]")
    except Exception as exc:
        console.print(f" [bold red]FAILED[/bold red]")
        print_rich_error(f"Data collection failed: {exc}")
        return None

    from qa_agent.agents.dv_debug_agent import build_prompt
    request = build_prompt(sim_data)

    if gvim:
        _gvim_preview_prompt(request, sim_path, provider)

    console.print(f"  [dim]Sending to AI ({provider})…[/dim]")
    try:
        report_text = asyncio.run(_run_stream_async(sim_data, provider, verbose))
        return report_text
    except Exception as exc:
        if log:
            log.error(exc)
        print_rich_error(f"AI investigation failed: {type(exc).__name__}: {exc}")
        if not verbose:
            console.print(
                f"  [dim]Run with[/dim] [bold]--verbose[/bold] [dim]for a full traceback.[/dim]"
            )
        return None


async def _run_stream_async(sim_data: str, provider: str, verbose: bool) -> str:
    from qa_agent.agents.dv_debug_agent import run_dv_debug_agent
    return await run_dv_debug_agent(sim_data, provider=provider, verbose=verbose)


def _gvim_preview_prompt(request, sim_path: Path, provider: str) -> None:
    """Open the assembled prompt in gvim for review before sending to AI."""
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
        console.print(f"  [dim yellow]Warning: could not open gvim: {exc}[/dim yellow]")

    from qa_agent.output import arrow_select
    total_chars = len(request.system_prompt) + len(request.user_prompt)
    estimated_tokens = total_chars // 4
    try:
        ans = arrow_select(
            f"Send this prompt to the AI? (~{estimated_tokens:,} tokens)",
            [("Proceed", "send to AI"), ("Stop", "abort and exit")],
        )
        if ans != 0:
            console.print("  Aborted by user.")
            sys.exit(0)
    except KeyboardInterrupt:
        console.print("\n  Aborted by user.")
        sys.exit(0)
