"""qa_agent/tools/report/log_errors.py

Tool: extract_log_errors

Greps error/warning/fatal lines from simulation log files with surrounding
context lines. Only returns lines matching known failure patterns — never
returns full log files.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from qa_agent.tools.report.security import validate_path

# Allowlisted log file basenames the agent may read
_LOG_ALLOWLIST = {"sim.log", "compile.log", "run.log", "questa.log"}

# Maximum number of error matches to return
_MAX_MATCHES = 50

# Default patterns that indicate errors/warnings/failures
_DEFAULT_PATTERN = r"(?i)(error|warning|fatal|fail|assert|mismatch|timeout)"


def _build_extract_log_errors_handler(sim_dir: Path):
    """Return a handler for extract_log_errors bound to *sim_dir*."""

    def extract_log_errors(
        log_file: str = "sim.log",
        pattern: str = "",
        context_lines: int = 3,
    ) -> str:
        """Grep error/warning lines from simulation logs.

        Args:
            log_file:      One of: sim.log, compile.log, run.log, questa.log.
            pattern:       Custom regex pattern to search for (optional).
                           Defaults to matching error/warning/fatal/fail/assert/mismatch/timeout.
            context_lines: Number of surrounding context lines to include (0-10).

        Returns:
            JSON: {matches: [{line_number, line, context_before, context_after}],
                   total_found, truncated}
        """
        # Validate log file against allowlist
        basename = Path(log_file).name
        if basename not in _LOG_ALLOWLIST:
            return json.dumps({
                "error": (
                    f"'{log_file}' is not an allowed log file. "
                    f"Allowed: {', '.join(sorted(_LOG_ALLOWLIST))}"
                )
            })

        # Try finding the log — check both the top level and logs/ subdir
        log_path = None
        candidates = [
            sim_dir / basename,
            sim_dir / "logs" / basename,
        ]
        for c in candidates:
            try:
                c_resolved = validate_path(str(c.relative_to(sim_dir)), sim_dir)
                if c_resolved.exists():
                    log_path = c_resolved
                    break
            except Exception:
                continue

        if log_path is None:
            return json.dumps({"error": f"Log file not found: {log_file}"})

        # Clamp context_lines
        context_lines = max(0, min(context_lines, 10))

        # Compile the search pattern
        search_pattern = pattern if pattern else _DEFAULT_PATTERN
        try:
            regex = re.compile(search_pattern, re.IGNORECASE)
        except re.error as exc:
            return json.dumps({"error": f"Invalid regex pattern: {exc}"})

        # Read and search
        try:
            all_lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            return json.dumps({"error": f"Read error: {exc}"})

        matches = []
        total_found = 0
        for i, line in enumerate(all_lines):
            if regex.search(line):
                total_found += 1
                if len(matches) < _MAX_MATCHES:
                    start = max(0, i - context_lines)
                    end = min(len(all_lines), i + context_lines + 1)
                    matches.append({
                        "line_number": i + 1,
                        "line": line,
                        "context_before": all_lines[start:i],
                        "context_after": all_lines[i + 1:end],
                    })

        return json.dumps({
            "matches": matches,
            "total_found": total_found,
            "truncated": total_found > _MAX_MATCHES,
        }, indent=2)

    return extract_log_errors


def build_log_error_tools(sim_dir: Path) -> list[tuple]:
    """Return (name, description, parameters_schema, handler) tuples for log tools."""
    return [
        (
            "extract_log_errors",
            (
                "Grep error/warning/fatal lines from simulation logs. "
                "Only returns lines matching failure patterns — not the full log. "
                "Check compile.log first (synthesis errors), then sim.log (runtime errors). "
                "Use a specific pattern to narrow results."
            ),
            {
                "type": "object",
                "properties": {
                    "log_file": {
                        "type": "string",
                        "enum": ["sim.log", "compile.log", "run.log", "questa.log"],
                        "description": "Log file to search (default: sim.log).",
                    },
                    "pattern": {
                        "type": "string",
                        "description": (
                            "Optional regex pattern. Defaults to matching "
                            "error|warning|fatal|fail|assert|mismatch|timeout."
                        ),
                    },
                    "context_lines": {
                        "type": "integer",
                        "description": "Lines of context around each match (0-10, default: 3).",
                        "minimum": 0,
                        "maximum": 10,
                    },
                },
                "required": [],
            },
            _build_extract_log_errors_handler(sim_dir),
        ),
    ]
