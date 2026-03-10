"""qa_agent/tools/report/log_errors.py

Tools: get_debug_log, get_mti_log

Reads the main simulation log (debug.log) and the Questa MTI diagnostic
log (mti.log) from Questa/Visualizer output directories.

The AI must request a specific file and may filter by pattern and line count.
Only debug.log and mti.log are accessible — NOT design files, source RTL,
or any other file.  All reads are validated through security.validate_path().

Security:
  - Allowlisted to debug.log and mti.log only (no design files, no RTL).
  - All paths validated inside sim_dir sandbox.
  - Output capped at max_output_chars by ToolRegistry.
"""

from __future__ import annotations

import re
from pathlib import Path

from qa_agent.tools.report.security import validate_path


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

# ONLY these log files may be accessed — never source RTL or design files
_LOG_ALLOWLIST = {"debug.log", "mti.log"}

# Default error/failure pattern
_DEFAULT_ERROR_RE = re.compile(
    r"(?i)(\*\*\s*(error|fatal)"
    r"|UVM_(ERROR|FATAL)"
    r"|assertion\s+(fail|error)"
    r"|scoreboard.*mismatch"
    r"|FAILED"
    r"|timeout.*(?:abort|fatal|limit)"
    r"|\bfatal\b"
    r"|Error:)",
)

_MAX_LINES_HARD_LIMIT = 2000


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _find_log(name: str, sim_dir: Path) -> Path | None:
    """Locate name in sim_dir or sim_dir/logs/ (security-validated)."""
    for candidate in [sim_dir / name, sim_dir / "logs" / name]:
        try:
            resolved = validate_path(str(candidate.relative_to(sim_dir)), sim_dir)
            if resolved.is_file():
                return resolved
        except Exception:
            continue
    return None


def _extract_errors_with_context(
    lines: list[str],
    error_re: re.Pattern,
    context_before: int = 5,
    context_after: int = 8,
    max_blocks: int = 30,
) -> list[str]:
    """Return formatted error blocks with surrounding context lines."""
    blocks: list[str] = []
    covered: set[int] = set()
    for i, line in enumerate(lines):
        if error_re.search(line) and i not in covered:
            start = max(0, i - context_before)
            end = min(len(lines), i + context_after + 1)
            for j in range(start, end):
                covered.add(j)
            block = f"[Line {i + 1}]\n" + "\n".join(lines[start:end])
            blocks.append(block)
            if len(blocks) >= max_blocks:
                break
    return blocks


# ─────────────────────────────────────────────────────────────────────────────
# Handler builders
# ─────────────────────────────────────────────────────────────────────────────

def _build_get_debug_log_handler(sim_dir: Path):
    """Return handler for get_debug_log bound to sim_dir."""

    def get_debug_log(
        filter_errors_only: bool = True,
        pattern: str = "",
        max_lines: int = 300,
        include_uvm_summary: bool = True,
        include_tail: bool = True,
        tail_lines: int = 100,
    ) -> str:
        """Read debug.log — the main Questa simulation output.

        IMPORTANT: Only debug.log is accessible. Do NOT attempt to read
        design files (.sv, .v, work/, design.bin) — they are blocked.

        Args:
            filter_errors_only:  If True (default), return only error/fatal/
                                 assertion blocks with context.  If False,
                                 return raw content up to max_lines.
            pattern:             Optional regex to further filter lines.
                                 Applied on top of the default error pattern.
            max_lines:           Maximum output lines (1–2000, default 300).
            include_uvm_summary: If True, append UVM Report Summary if found.
            include_tail:        If True, append last tail_lines of the log
                                 (contains test verdict and exit status).
            tail_lines:          How many lines from the end to include (max 200).

        Returns:
            Plain text: error blocks or raw lines from debug.log.
        """
        log_path = _find_log("debug.log", sim_dir)
        if log_path is None:
            return "ERROR: debug.log not found in simulation directory."

        try:
            content = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"ERROR: Cannot read debug.log: {exc}"

        max_lines = max(1, min(max_lines, _MAX_LINES_HARD_LIMIT))
        tail_lines = max(1, min(tail_lines, 200))
        lines = content.splitlines()
        parts: list[str] = []

        # Build the match regex
        if pattern:
            try:
                match_re = re.compile(pattern, re.IGNORECASE)
            except re.error as exc:
                return f"ERROR: Invalid pattern '{pattern}': {exc}"
        else:
            match_re = _DEFAULT_ERROR_RE

        if filter_errors_only:
            blocks = _extract_errors_with_context(lines, match_re)
            if blocks:
                parts.append(
                    f"=== debug.log: {len(blocks)} error block(s) "
                    f"(of {len(lines)} total lines) ===\n"
                )
                parts.append("\n\n---\n".join(blocks[:max_lines // 10 + 1]))
            else:
                parts.append(
                    f"=== debug.log: No errors found ({len(lines)} lines) ===\n"
                )
        else:
            # Raw mode — filter by pattern if given, else return first max_lines
            if pattern:
                matched = [
                    f"[L{i+1}] {l}" for i, l in enumerate(lines)
                    if match_re.search(l)
                ][:max_lines]
                parts.append(
                    f"=== debug.log: pattern='{pattern}' "
                    f"({len(matched)} matching lines) ===\n"
                )
                parts.append("\n".join(matched))
            else:
                parts.append(
                    f"=== debug.log: first {min(max_lines, len(lines))} lines ===\n"
                )
                parts.append("\n".join(lines[:max_lines]))

        # UVM Report Summary
        if include_uvm_summary:
            summary_re = re.compile(
                r"(?i)([-=]+\s*UVM\s+Report\s+Summary\s*[-=]+|UVM\s+Report\s+Summary)",
            )
            summary_start = None
            for i in range(len(lines) - 1, max(0, len(lines) - 500) - 1, -1):
                if summary_re.search(lines[i]):
                    summary_start = i
                    break
            if summary_start is not None:
                summary_block = "\n".join(lines[summary_start:min(summary_start + 60, len(lines))])
                parts.append(f"\n\n=== UVM Report Summary ===\n{summary_block}")

        # Log tail (test verdict)
        if include_tail and tail_lines > 0:
            tail = lines[-tail_lines:]
            parts.append(
                f"\n\n=== Log Tail (last {len(tail)} of {len(lines)} lines) ===\n"
                + "\n".join(tail)
            )

        return "\n".join(parts)

    return get_debug_log


def _build_get_mti_log_handler(sim_dir: Path):
    """Return handler for get_mti_log bound to sim_dir."""

    def get_mti_log(
        filter_errors_only: bool = True,
        max_lines: int = 200,
    ) -> str:
        """Read mti.log — Questa/MTI internal diagnostic messages.

        IMPORTANT: Only mti.log may be read. Do NOT attempt to read
        design files or source code.

        Args:
            filter_errors_only: If True (default), return only error/warning
                                 blocks.  If False, return up to max_lines raw.
            max_lines:          Maximum output lines (1–500, default 200).

        Returns:
            Plain text from mti.log.
        """
        log_path = _find_log("mti.log", sim_dir)
        if log_path is None:
            return "INFO: mti.log not found (not always present in Questa output)."

        try:
            content = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"ERROR: Cannot read mti.log: {exc}"

        max_lines = max(1, min(max_lines, 500))
        lines = content.splitlines()

        if filter_errors_only:
            blocks = _extract_errors_with_context(lines, _DEFAULT_ERROR_RE)
            if not blocks:
                return (
                    f"=== mti.log: No errors found ({len(lines)} lines) ===\n"
                    "MTI log is clean."
                )
            return (
                f"=== mti.log: {len(blocks)} error block(s) ===\n\n"
                + "\n\n---\n".join(blocks[:max_lines // 10 + 1])
            )
        else:
            return (
                f"=== mti.log: first {min(max_lines, len(lines))} lines ===\n"
                + "\n".join(lines[:max_lines])
            )

    return get_mti_log


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def build_log_error_tools(sim_dir: Path) -> list[tuple]:
    """Return (name, description, parameters_schema, handler) tuples."""
    return [
        (
            "get_debug_log",
            (
                "Read debug.log — the main Questa/vsim simulation output. "
                "By default returns only error/fatal/assertion blocks with context. "
                "Use filter_errors_only=false with a specific pattern to search for "
                "particular messages. Use include_tail=true to see the test verdict. "
                "IMPORTANT: Only debug.log is accessible — never source RTL or design files."
            ),
            {
                "type": "object",
                "properties": {
                    "filter_errors_only": {
                        "type": "boolean",
                        "description": "True (default): return only error/fatal blocks. False: return raw lines.",
                    },
                    "pattern": {
                        "type": "string",
                        "description": (
                            "Optional regex to filter lines (e.g. 'UVM_FATAL', "
                            "'scoreboard.*mismatch', '@[0-9]+ns'). "
                            "Leave empty to use the default error pattern."
                        ),
                    },
                    "max_lines": {
                        "type": "integer",
                        "description": "Max output lines (1–2000, default 300).",
                        "minimum": 1,
                        "maximum": 2000,
                    },
                    "include_uvm_summary": {
                        "type": "boolean",
                        "description": "Append UVM Report Summary if found (default: true).",
                    },
                    "include_tail": {
                        "type": "boolean",
                        "description": "Append last N lines of log (test verdict, exit status). Default: true.",
                    },
                    "tail_lines": {
                        "type": "integer",
                        "description": "Lines from end of log to include (default 100, max 200).",
                        "minimum": 1,
                        "maximum": 200,
                    },
                },
                "required": [],
            },
            _build_get_debug_log_handler(sim_dir),
        ),
        (
            "get_mti_log",
            (
                "Read mti.log — Questa/MTI internal diagnostic messages. "
                "Returns only error/warning blocks by default. "
                "Use when debug.log mentions MTI-specific error codes (vsim-XXXX). "
                "IMPORTANT: Only mti.log may be read — never source RTL or design files."
            ),
            {
                "type": "object",
                "properties": {
                    "filter_errors_only": {
                        "type": "boolean",
                        "description": "True (default): errors only.  False: first max_lines raw lines.",
                    },
                    "max_lines": {
                        "type": "integer",
                        "description": "Max lines to return (1–500, default 200).",
                        "minimum": 1,
                        "maximum": 500,
                    },
                },
                "required": [],
            },
            _build_get_mti_log_handler(sim_dir),
        ),
    ]
