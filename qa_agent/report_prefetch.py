"""qa_agent/report_prefetch.py

Pre-fetches all simulation data by calling tool handlers directly — no AI tool-calling.

All handlers from qa_agent/tools/report/ are run eagerly against the simulation
directory.  Results are assembled into a single Markdown context block that can be
embedded in one large prompt for the stream-based agent.

This module is the data-collection layer for the stream-based report flow:
    collect_sim_data(sim_dir) → str   (Markdown context block)
"""

from __future__ import annotations

from pathlib import Path

from qa_agent.tools.report import build_report_tools


# ─────────────────────────────────────────────────────────────────────────────
# Sections to collect — ordered as the DV expert would investigate
# ─────────────────────────────────────────────────────────────────────────────

_SECTIONS: list[tuple[str, str, dict]] = [
    # (display_title, tool_name, kwargs)
    ("Simulation Files — top level",      "list_sim_files",             {}),
    ("Simulation Files — qrun.out/",      "list_sim_files",             {"subdir": "qrun.out"}),
    ("Simulation Files — logs/",          "list_sim_files",             {"subdir": "logs"}),
    ("Metadata: big_argv",                "read_sim_metadata",          {"file": "big_argv"}),
    ("Metadata: version",                 "read_sim_metadata",          {"file": "version"}),
    ("Metadata: stats_log",               "read_sim_metadata",          {"file": "stats_log"}),
    ("Compile Log — errors/warnings",     "extract_log_errors",         {"log_file": "compile.log"}),
    ("Sim Log — errors/warnings",         "extract_log_errors",         {"log_file": "sim.log"}),
    ("Assertion Failures",                "get_assertion_failures",     {}),
    ("Scoreboard Mismatches",             "get_scoreboard_mismatches",  {}),
    ("Tracker Failures",                  "extract_tracker_failures",   {}),
]


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def collect_sim_data(sim_dir: Path) -> str:
    """Run all tool handlers against *sim_dir* and return a Markdown context block.

    Each tool handler from tools/report/ is called with the kwargs defined in
    _SECTIONS above.  Results — including errors — are embedded verbatim.  The
    same security rules apply: path containment, output caps, allowlists.

    Args:
        sim_dir: Resolved Path to the simulation output directory.

    Returns:
        A Markdown-formatted string with all collected sim data embedded, ready
        to drop into an AI prompt.
    """
    registry = build_report_tools(sim_dir)

    parts: list[str] = [
        "# Simulation Data\n",
        f"**Simulation directory:** `{sim_dir}`\n",
    ]

    for title, tool_name, kwargs in _SECTIONS:
        parts.append(f"\n## {title}\n")
        result = registry.execute(f"prefetch_{tool_name}", tool_name, kwargs)
        content = result.content.strip()
        if result.error:
            parts.append(f"*Error: {content}*\n")
        else:
            if result.truncated:
                content += "\n\n*[Output truncated at size limit]*"
            parts.append(f"```\n{content}\n```\n")

    return "\n".join(parts)
