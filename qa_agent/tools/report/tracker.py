"""qa_agent/tools/report/tracker.py

Tool: extract_tracker_failures

Extracts failure/mismatch entries from tracker log files within a specified
time window. Returns only failure/mismatch events — not all tracker entries.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from qa_agent.tools.report.security import validate_path

# Common tracker log filenames
_TRACKER_NAMES = {"tracker.log", "tracker.txt", "tracker.out", "apci_tracker.log"}

# Patterns for failure/mismatch events in tracker output
_FAILURE_RE = re.compile(
    r"(?i)(fail|error|mismatch|assert|fatal|timeout)",
)

# Time extraction pattern: "@ 12345ns" or "time=12345" or "at 12345"
_TIME_RE = re.compile(r"@\s*(?P<time>\d+)|time[=\s]+(?P<time2>\d+)")

# Component extraction
_COMPONENT_RE = re.compile(r"\[(?P<component>[A-Z_][A-Z0-9_]+)\]", re.IGNORECASE)


def _extract_time(line: str) -> int | None:
    m = _TIME_RE.search(line)
    if m:
        t = m.group("time") or m.group("time2")
        return int(t) if t else None
    return None


def _build_extract_tracker_failures_handler(sim_dir: Path):
    """Return a handler for extract_tracker_failures bound to *sim_dir*."""

    def extract_tracker_failures(
        time_start: int | None = None,
        time_end: int | None = None,
        component: str = "",
    ) -> str:
        """Get tracker entries around the failure time.

        Args:
            time_start: Optional start of time window (simulation time units).
            time_end:   Optional end of time window.
            component:  Optional component name filter (e.g. "APCI", "RX").

        Returns:
            JSON array of {time, component, signal, event, message} objects.
        """
        # Find the tracker file
        tracker_path = None
        for name in _TRACKER_NAMES:
            candidates = [
                sim_dir / name,
                sim_dir / "logs" / name,
                sim_dir / "qrun.out" / name,
            ]
            for c in candidates:
                try:
                    r = validate_path(str(c.relative_to(sim_dir)), sim_dir)
                    if r.exists():
                        tracker_path = r
                        break
                except Exception:
                    continue
            if tracker_path:
                break

        if tracker_path is None:
            return json.dumps({
                "error": "No tracker file found. Looked for: " + ", ".join(_TRACKER_NAMES)
            })

        try:
            lines = tracker_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            return json.dumps({"error": str(exc)})

        entries = []
        for raw_line in lines:
            # Filter: only failure/mismatch events
            if not _FAILURE_RE.search(raw_line):
                continue

            # Time filter
            t = _extract_time(raw_line)
            if time_start is not None and t is not None and t < time_start:
                continue
            if time_end is not None and t is not None and t > time_end:
                continue

            # Component filter
            comp_m = _COMPONENT_RE.search(raw_line)
            comp = comp_m.group("component") if comp_m else "unknown"
            if component and component.lower() not in comp.lower():
                continue

            entries.append({
                "time": t,
                "component": comp,
                "signal": "",       # field for future enrichment
                "event": "failure",
                "message": raw_line.strip()[:200],
            })

            if len(entries) >= 100:
                break

        return json.dumps({
            "entries": entries,
            "total": len(entries),
            "truncated": len(entries) >= 100,
        }, indent=2)

    return extract_tracker_failures


def build_tracker_tools(sim_dir: Path) -> list[tuple]:
    """Return tool spec tuples for tracker tools."""
    return [
        (
            "extract_tracker_failures",
            (
                "Get tracker entries around failure time. "
                "Returns only failure/mismatch/error events — not all tracker data. "
                "Use time_start/time_end to narrow the window to events near the failure timestamp."
            ),
            {
                "type": "object",
                "properties": {
                    "time_start": {
                        "type": "integer",
                        "description": "Start of the time window in simulation time units (optional).",
                    },
                    "time_end": {
                        "type": "integer",
                        "description": "End of the time window (optional).",
                    },
                    "component": {
                        "type": "string",
                        "description": "Filter by component name, e.g. 'APCI', 'RX' (optional).",
                    },
                },
                "required": [],
            },
            _build_extract_tracker_failures_handler(sim_dir),
        ),
    ]
