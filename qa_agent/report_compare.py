"""qa_agent/report_compare.py

Orchestrator for --compare mode.

Reads two QA-REGRESSION-SUMMARY_*.md files, runs the comparison agent,
and writes a QA-REGRESSION-COMPARISON_<timestamp>.md file.

Usage (from cli.py):
    from qa_agent.report_compare import run_compare
    await run_compare(old_path, new_path, provider=args.provider, output=args.output)
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from qa_agent.agents.comparison_agent import run_comparison_agent
from qa_agent.output import console, print_header, print_footer


async def run_compare(
    old_report: str | Path,
    new_report: str | Path,
    *,
    provider: str = "claude",
    output: str = "",
    verbose: bool = False,
) -> Path:
    """Compare two aggregate regression reports and write a diff report.

    Args:
        old_report: Path to the older QA-REGRESSION-SUMMARY_*.md.
        new_report: Path to the newer QA-REGRESSION-SUMMARY_*.md.
        provider:   AI provider: "claude", "openai", or "gemini".
        output:     Optional output file path (default: auto-named in cwd).
        verbose:    If True, show extra detail.

    Returns:
        Path to the written QA-REGRESSION-COMPARISON_*.md file.
    """
    old_path = Path(old_report).resolve()
    new_path = Path(new_report).resolve()

    print_header("report --compare", f"{old_path.name} vs {new_path.name}")

    if not old_path.exists():
        raise FileNotFoundError(f"Old report not found: {old_path}")
    if not new_path.exists():
        raise FileNotFoundError(f"New report not found: {new_path}")

    console.print(
        f"\n  [bold bright_cyan]Old report:[/bold bright_cyan]  {old_path.name}\n"
        f"  [bold bright_cyan]New report:[/bold bright_cyan]  {new_path.name}\n"
    )

    with console.status("Running comparison analysis…", spinner="dots"):
        comparison_text = await run_comparison_agent(
            old_path, new_path, provider=provider
        )

    # Build the output report
    now = datetime.now()
    ts_str = now.strftime("%Y-%m-%d_%H%M%S")

    report_lines = [
        f"# QA Regression Comparison Report",
        f"",
        f"**Generated**: {now.strftime('%Y-%m-%d %H:%M:%S')}  ",
        f"**Provider**: {provider}  ",
        f"**Old report**: `{old_path.name}`  ",
        f"**New report**: `{new_path.name}`  ",
        f"",
        "---",
        "",
        comparison_text,
    ]

    report_body = "\n".join(report_lines)

    # Determine output path
    if output:
        out_path = Path(output).resolve()
    else:
        out_path = Path.cwd() / f"QA-REGRESSION-COMPARISON_{ts_str}.md"

    out_path.write_text(report_body, encoding="utf-8")

    console.print(
        f"\n  [bold green]✓[/bold green]  Comparison report written:\n"
        f"     [bright_cyan]{out_path}[/bright_cyan]\n"
    )
    print_footer("Comparison complete.", success=True)

    return out_path
