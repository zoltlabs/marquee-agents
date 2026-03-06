"""qa_agent/tools/report/scoreboard.py

Tool: get_scoreboard_mismatches

Extracts scoreboard mismatch summaries from simulation logs.
Returns aggregated stats — not raw comparison data.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from qa_agent.tools.report.security import validate_path

# Common scoreboard mismatch patterns
_MISMATCH_LINE_RE = re.compile(
    r"(?i)(?:scoreboard|sb).*?mismatch"
    r"|(?:expected|actual|got)[\s:]+(?P<val>[0-9a-fx]+)"
    r"|UVM_ERROR.*?mismatch",
    re.IGNORECASE,
)

_COMPONENT_RE = re.compile(
    r"(?i)(?:component|checker|monitor|sb)[\s:_]+(?P<name>\w+)",
)

_VALUE_RE = re.compile(
    r"(?i)expected[\s:=]+(?P<expected>[0-9a-fx_]+).*?(?:actual|got|received)[\s:=]+(?P<actual>[0-9a-fx_]+)",
)

_TIME_RE = re.compile(r"@\s*(?P<time>\d+)")


def _build_get_scoreboard_mismatches_handler(sim_dir: Path):
    """Return a handler for get_scoreboard_mismatches bound to *sim_dir*."""

    def get_scoreboard_mismatches(log_file: str = "sim.log") -> str:
        """Extract scoreboard mismatch summary from a simulation log.

        Args:
            log_file: Log file to scan (default: sim.log).

        Returns:
            JSON: {total_mismatches, first_time, last_time,
                   components: [{name, expected, actual, count}]}
        """
        basename = Path(log_file).name
        allowed = {"sim.log", "run.log", "questa.log"}
        if basename not in allowed:
            return json.dumps({
                "error": f"Not allowed: '{log_file}'. Use one of: {', '.join(sorted(allowed))}"
            })

        candidates = [sim_dir / basename, sim_dir / "logs" / basename]
        log_path = None
        for c in candidates:
            try:
                r = validate_path(str(c.relative_to(sim_dir)), sim_dir)
                if r.exists():
                    log_path = r
                    break
            except Exception:
                continue

        if log_path is None:
            return json.dumps({"error": f"Log file not found: {log_file}"})

        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return json.dumps({"error": str(exc)})

        # Aggregate by component
        components: dict[str, dict] = {}
        times: list[int] = []

        for line in text.splitlines():
            if not _MISMATCH_LINE_RE.search(line):
                continue

            # Extract time
            time_m = _TIME_RE.search(line)
            t = int(time_m.group("time")) if time_m else None
            if t is not None:
                times.append(t)

            # Extract component name
            comp_m = _COMPONENT_RE.search(line)
            comp_name = comp_m.group("name") if comp_m else "unknown"

            # Extract expected/actual values
            val_m = _VALUE_RE.search(line)
            expected = val_m.group("expected") if val_m else "?"
            actual = val_m.group("actual") if val_m else "?"

            if comp_name not in components:
                components[comp_name] = {
                    "name": comp_name,
                    "expected": expected,
                    "actual": actual,
                    "count": 0,
                }
            components[comp_name]["count"] += 1

        result = {
            "total_mismatches": sum(c["count"] for c in components.values()),
            "first_time": min(times) if times else None,
            "last_time": max(times) if times else None,
            "components": list(components.values()),
        }

        return json.dumps(result, indent=2)

    return get_scoreboard_mismatches


def build_scoreboard_tools(sim_dir: Path) -> list[tuple]:
    """Return tool spec tuples for scoreboard tools."""
    return [
        (
            "get_scoreboard_mismatches",
            (
                "Extract scoreboard mismatch summary from simulation logs. "
                "Returns aggregated stats (total count, time range, per-component breakdown) — "
                "not raw comparison data. Use when error extraction mentions scoreboard mismatches."
            ),
            {
                "type": "object",
                "properties": {
                    "log_file": {
                        "type": "string",
                        "enum": ["sim.log", "run.log", "questa.log"],
                        "description": "Log file to scan (default: sim.log).",
                    }
                },
                "required": [],
            },
            _build_get_scoreboard_mismatches_handler(sim_dir),
        ),
    ]
