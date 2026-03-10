"""qa_agent/tools/report/tracker.py

Tool: get_tracker_data

Reads per-component Questa tracker files (tracker_phy_rc.txt,
tracker_dll_rc.txt, tracker_tl_rc.txt, tracker_cfg_rc.txt, etc.).

The AI must first call list_sim_files() to discover which tracker files
exist, then call get_tracker_data() with a specific file_name and optional
filter parameters.  Only tracker_*.txt files inside sim_dir are accessible.

Security:
  - file_name is validated: must match tracker_*.txt pattern AND exist
    inside sim_dir (via validate_path).
  - Output lines capped at max_lines (hard limit 3000).
  - No design files or source RTL are ever accessible.
"""

from __future__ import annotations

import re
from pathlib import Path

from qa_agent.tools.report.security import validate_path

# Pattern that matches the 5 failure categories of interest
_FAILURE_RE = re.compile(
    r"(?i)"
    r"(assert.*fail|fail.*assert"
    r"|scoreboard.*mismatch|mismatch.*scoreboard"
    r"|timeout"
    r"|\bfatal\b"
    r"|transaction.*mismatch|mismatch.*transaction"
    r"|ASSERT|SCOREBOARD_ERR|SB_ERR"
    r")"
)

_MAX_LINES_HARD = 3000
_PREVIEW_CONTEXT_BEFORE = 10
_PREVIEW_CONTEXT_AFTER = 5


def _build_get_tracker_data_handler(sim_dir: Path):
    """Return handler for get_tracker_data bound to sim_dir."""

    def get_tracker_data(
        file_name: str,
        pattern: str = "",
        filter_failures_only: bool = True,
        max_lines: int = 500,
        context_lines: int = 10,
    ) -> str:
        """Read a specific Questa tracker file.

        Tracker files record per-layer protocol events:
          tracker_phy_rc.txt   — PHY layer (link training, LTSSM states)
          tracker_dll_rc.txt   — DLL layer (flow control, ACK/NAK)
          tracker_tl_rc.txt    — Transaction layer (TLP events)
          tracker_cfg_rc.txt   — Configuration space transactions
          tracker_phy_flit_rc.txt, tracker_dll_flit_rc.txt — Flit logs
          tracker_tl_ep_app_bfm.txt, tracker_cfg_ep_app_bfm.txt — EP side

        Use list_sim_files() first to see which tracker files exist.

        IMPORTANT: Only tracker_*.txt files may be read.  Do NOT request
        design files, source RTL (.sv, .v), work/ directories, or any
        binary file (design.bin, qwave.db).

        Args:
            file_name:            Tracker filename (e.g. 'tracker_phy_rc.txt').
                                  Must match the tracker_*.txt naming pattern.
            pattern:              Optional regex to filter lines further
                                  (e.g. 'DETECT_QUIET', 'LTSSM', '@4\\.2').
                                  Leave empty to use the default failure pattern.
            filter_failures_only: If True (default), return only failure/
                                  mismatch/timeout/assert lines with context.
                                  If False, returns up to max_lines raw lines.
            max_lines:            Max output lines (1–3000, default 500).
            context_lines:        Lines of context around each failure match
                                  (0–50, default 10). Ignored when
                                  filter_failures_only=False.

        Returns:
            Plain text: filtered tracker content with line numbers and
            context, or an error string if the file cannot be read.
        """
        # Security: basename only, must match tracker_*.txt
        basename = Path(file_name).name
        if not re.match(r"^tracker_[a-z0-9_.]+\.txt$", basename, re.IGNORECASE):
            return (
                f"ERROR: '{file_name}' is not a valid tracker file name. "
                "Tracker files must match: tracker_*.txt "
                "(e.g. tracker_phy_rc.txt). "
                "Use list_sim_files() to see which files are available."
            )

        # Validate path is inside sim_dir
        try:
            resolved = validate_path(basename, sim_dir)
        except Exception as exc:
            return f"ERROR: Path validation failed for '{basename}': {exc}"

        if not resolved.is_file():
            return (
                f"ERROR: '{basename}' not found in simulation directory. "
                "Use list_sim_files() to check what files exist."
            )

        try:
            content = resolved.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"ERROR: Cannot read '{basename}': {exc}"

        max_lines = max(1, min(max_lines, _MAX_LINES_HARD))
        context_lines = max(0, min(context_lines, 50))
        lines = content.splitlines()
        total_lines = len(lines)

        # Build match regex
        if pattern:
            try:
                match_re = re.compile(pattern, re.IGNORECASE)
            except re.error as exc:
                return f"ERROR: Invalid pattern '{pattern}': {exc}"
        else:
            match_re = _FAILURE_RE

        header = (
            f"=== {basename} ({total_lines} lines total) "
            f"filter={'failures+context' if filter_failures_only else 'raw'}"
        )
        if pattern:
            header += f" pattern='{pattern}'"
        header += " ==="

        if filter_failures_only:
            # Find failure lines
            error_indices = [
                i for i, line in enumerate(lines) if match_re.search(line)
            ]

            if not error_indices:
                return (
                    f"{header}\n"
                    f"No matching events found in {basename}.\n"
                    f"Tried pattern: {'default failures' if not pattern else pattern}\n"
                    f"Top 5 lines of file:\n" + "\n".join(lines[:5])
                )

            # Always include top 50 lines for config context + error windows
            output_lines: list[str] = []
            # Config header
            output_lines.append("--- File header (config context) ---")
            output_lines.extend(lines[:min(50, total_lines)])
            if error_indices[0] > 50:
                output_lines.append("... [lines skipped] ...")

            covered: set[int] = set(range(min(50, total_lines)))
            blocks_added = 0

            for idx in error_indices:
                start = max(0, idx - context_lines)
                end = min(total_lines, idx + context_lines + 1)

                if start > 0 and (start - 1) not in covered:
                    output_lines.append("... [lines skipped] ...")

                for j in range(start, end):
                    if j not in covered:
                        marker = ">>>" if j in set(error_indices) else "   "
                        output_lines.append(f"[L{j+1}] {marker} {lines[j]}")
                        covered.add(j)

                blocks_added += 1
                if len(output_lines) >= max_lines:
                    remaining = len(error_indices) - blocks_added
                    if remaining > 0:
                        output_lines.append(
                            f"... [{remaining} more failure event(s) not shown — "
                            "increase max_lines to see more] ..."
                        )
                    break

            return f"{header}\n{len(error_indices)} failure event(s) found.\n\n" + "\n".join(output_lines)

        else:
            # Raw mode with optional pattern filter
            if pattern:
                matched = [
                    f"[L{i+1}] {l}" for i, l in enumerate(lines)
                    if match_re.search(l)
                ][:max_lines]
                return (
                    f"{header}\n{len(matched)} matching lines:\n\n"
                    + "\n".join(matched)
                )
            else:
                return (
                    f"{header}\n"
                    + "\n".join(f"[L{i+1}] {l}" for i, l in enumerate(lines[:max_lines]))
                    + (
                        f"\n... [{total_lines - max_lines} more lines, "
                        "increase max_lines to see more] ..."
                        if total_lines > max_lines else ""
                    )
                )

    return get_tracker_data


def build_tracker_tools(sim_dir: Path) -> list[tuple]:
    """Return tool spec tuples for tracker tools."""
    return [
        (
            "get_tracker_data",
            (
                "Read a specific Questa per-layer tracker file. "
                "Call list_sim_files() first to see available tracker files. "
                "Tracker files: tracker_phy_rc.txt (PHY/LTSSM), "
                "tracker_dll_rc.txt (DLL/flow-control), "
                "tracker_tl_rc.txt (TL/TLP events), "
                "tracker_cfg_rc.txt (config transactions), "
                "tracker_*_ep_app_bfm.txt (EP side). "
                "By default returns only failure/assert/timeout events with context. "
                "IMPORTANT: Only tracker_*.txt files are accessible — "
                "never source RTL, design files, or work/ directories."
            ),
            {
                "type": "object",
                "properties": {
                    "file_name": {
                        "type": "string",
                        "description": (
                            "Exact tracker filename (e.g. 'tracker_phy_rc.txt'). "
                            "Must match tracker_*.txt. Use list_sim_files() to discover names."
                        ),
                    },
                    "pattern": {
                        "type": "string",
                        "description": (
                            "Optional regex filter (e.g. 'DETECT_QUIET', "
                            "'LTSSM', 'ASSERT', '@4\\.2'). "
                            "Leave empty for default failure patterns."
                        ),
                    },
                    "filter_failures_only": {
                        "type": "boolean",
                        "description": (
                            "True (default): return only failure/assert/timeout lines + context. "
                            "False: return raw lines up to max_lines."
                        ),
                    },
                    "max_lines": {
                        "type": "integer",
                        "description": "Max output lines (1–3000, default 500).",
                        "minimum": 1,
                        "maximum": 3000,
                    },
                    "context_lines": {
                        "type": "integer",
                        "description": "Lines of context around each failure (0–50, default 10).",
                        "minimum": 0,
                        "maximum": 50,
                    },
                },
                "required": ["file_name"],
            },
            _build_get_tracker_data_handler(sim_dir),
        ),
    ]
