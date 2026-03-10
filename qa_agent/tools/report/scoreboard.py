"""qa_agent/tools/report/scoreboard.py

Tool: get_scoreboard_mismatches

Extracts scoreboard mismatch entries from debug.log.
Only debug.log is accessible — never source RTL or design files.
"""

from __future__ import annotations

import re
from pathlib import Path

from qa_agent.tools.report.security import validate_path

_MISMATCH_RE = re.compile(
    r"(?i)(?:scoreboard|SB|checker).*?mismatch"
    r"|(?:expected|actual|got)[\s:]+(?P<val>[0-9a-fx_']+)"
    r"|UVM_ERROR.*?mismatch",
)
_VALUE_RE = re.compile(
    r"(?i)expected[\s:=]+(?P<expected>[0-9a-fx_']+).*?(?:actual|got|received)[\s:=]+(?P<actual>[0-9a-fx_']+)",
)
_TIME_RE = re.compile(r"@\s*(?P<time>[\d.]+)\s*(?:ns)?")
_COMPONENT_RE = re.compile(
    r"(?i)(?:component|checker|monitor|SB|scoreboard)[:\s_]+(?P<name>\w+)",
)


def _find_debug_log(sim_dir: Path) -> Path | None:
    for candidate in [sim_dir / "debug.log", sim_dir / "logs" / "debug.log"]:
        try:
            r = validate_path(str(candidate.relative_to(sim_dir)), sim_dir)
            if r.is_file():
                return r
        except Exception:
            continue
    return None


def _build_get_scoreboard_mismatches_handler(sim_dir: Path):
    def get_scoreboard_mismatches(
        max_mismatches: int = 50,
        pattern: str = "",
    ) -> str:
        """Extract scoreboard mismatch summary from debug.log.

        Aggregates mismatches by component and returns time range,
        expected vs. actual values, and per-component counts.

        IMPORTANT: Only debug.log is read — never source RTL or design files.

        Args:
            max_mismatches: Max individual mismatches to capture (1–200, default 50).
            pattern:        Optional regex to filter mismatch lines
                            (e.g. 'TLP', 'CplD', 'data_checker').

        Returns:
            Formatted text: aggregate stats + up to max_mismatches entries.
        """
        log_path = _find_debug_log(sim_dir)
        if log_path is None:
            return "ERROR: debug.log not found. Use list_sim_files() to check available files."

        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"ERROR: Cannot read debug.log: {exc}"

        max_mismatches = max(1, min(max_mismatches, 200))

        if pattern:
            try:
                user_re = re.compile(pattern, re.IGNORECASE)
            except re.error as exc:
                return f"ERROR: Invalid pattern '{pattern}': {exc}"
        else:
            user_re = None

        components: dict[str, dict] = {}
        times: list[float] = []
        sample_entries: list[str] = []
        total = 0

        for line in text.splitlines():
            if not _MISMATCH_RE.search(line):
                continue
            if user_re and not user_re.search(line):
                continue

            total += 1

            tm = _TIME_RE.search(line)
            t = float(tm.group("time")) if tm else None
            if t is not None:
                times.append(t)

            cm = _COMPONENT_RE.search(line)
            comp = cm.group("name") if cm else "unknown"

            vm = _VALUE_RE.search(line)
            expected = vm.group("expected") if vm else "?"
            actual = vm.group("actual") if vm else "?"

            if comp not in components:
                components[comp] = {"name": comp, "expected": expected, "actual": actual, "count": 0}
            components[comp]["count"] += 1

            if len(sample_entries) < max_mismatches:
                sample_entries.append(
                    f"  [t={t}ns] comp={comp} "
                    f"expected={expected} actual={actual}"
                )

        if total == 0:
            return (
                "=== Scoreboard Mismatches in debug.log ===\n"
                "No scoreboard mismatches found"
                + (f" matching pattern '{pattern}'" if pattern else "")
                + ".\n"
                "Use get_debug_log(pattern='mismatch') for broader search."
            )

        lines = [
            f"=== Scoreboard Mismatches in debug.log"
            + (f" [pattern='{pattern}']" if pattern else "")
            + " ===",
            f"Total: {total} mismatch(es)",
            f"Time range: {min(times):.1f}ns — {max(times):.1f}ns" if times else "Time: unknown",
            "",
            "Per-component breakdown:",
        ]
        for c in sorted(components.values(), key=lambda x: -x["count"]):
            lines.append(
                f"  {c['name']}: {c['count']} mismatch(es)  "
                f"(expected={c['expected']}, actual={c['actual']})"
            )
        lines.append(
            f"\nFirst {len(sample_entries)} entries"
            + (f" (of {total})" if total > max_mismatches else "")
            + ":"
        )
        lines.extend(sample_entries)
        return "\n".join(lines)

    return get_scoreboard_mismatches


def build_scoreboard_tools(sim_dir: Path) -> list[tuple]:
    return [
        (
            "get_scoreboard_mismatches",
            (
                "Extract scoreboard mismatch summary from debug.log. "
                "Returns aggregate stats: total count, time range, per-component breakdown. "
                "Use pattern to filter by TLP type, component name, or data field. "
                "IMPORTANT: Only reads debug.log — never source RTL or design files."
            ),
            {
                "type": "object",
                "properties": {
                    "max_mismatches": {
                        "type": "integer",
                        "description": "Max mismatch entries to return (1–200, default 50).",
                        "minimum": 1,
                        "maximum": 200,
                    },
                    "pattern": {
                        "type": "string",
                        "description": (
                            "Optional regex to filter mismatch lines "
                            "(e.g. 'TLP', 'CplD', 'data_checker')."
                        ),
                    },
                },
                "required": [],
            },
            _build_get_scoreboard_mismatches_handler(sim_dir),
        ),
    ]
