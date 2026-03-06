"""qa_agent/tools/report/signals.py

Tool: read_signal_values

Reads specific signal values at specific simulation times from waveform
dump files or signal logs. Returns only the requested signals in a short
time window — no full waveform dumps.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from qa_agent.tools.report.security import validate_path

# Common signal value log filenames
_SIGNAL_LOG_NAMES = {"signals.log", "wave.log", "dump.log", "signals.txt"}

# Patterns for signal values in various formats
# VCD-style: "#12345\n$dumpvars\nb0101 signal_name"
# Questa wave log: "# 12345 ns signal = 8'h0A"
_QUESTA_SIGNAL_RE = re.compile(
    r"#\s*(?P<time>\d+)\s+ns\s+(?P<signal>[\w./]+)\s*=\s*(?P<value>[^\s]+)"
)
_GENERIC_SIGNAL_RE = re.compile(
    r"(?P<time>\d+)\s+(?P<signal>[\w./]+)\s*[=:]\s*(?P<value>[^\s]+)"
)


def _build_read_signal_values_handler(sim_dir: Path):
    """Return a handler for read_signal_values bound to *sim_dir*."""

    def read_signal_values(
        signals: list[str],
        time: int,
        window: int = 100,
    ) -> str:
        """Read specific signal values at a specific simulation time.

        Args:
            signals: List of signal names to look up (e.g. ["apci_rx.state", "clk"]).
            time:    The simulation time of interest.
            window:  Time window in simulation units around *time* (default: 100).
                     Values from [time-window, time+window] are returned.

        Returns:
            JSON table of {signal, time, value} rows.
        """
        if not signals:
            return json.dumps({"error": "No signals specified."})

        # Limit signal list to prevent abuse
        signals = signals[:20]
        signal_set = {s.lower() for s in signals}

        # Find the signal log file
        signal_path = None
        for name in _SIGNAL_LOG_NAMES:
            candidates = [
                sim_dir / name,
                sim_dir / "logs" / name,
                sim_dir / "qrun.out" / name,
            ]
            for c in candidates:
                try:
                    r = validate_path(str(c.relative_to(sim_dir)), sim_dir)
                    if r.exists():
                        signal_path = r
                        break
                except Exception:
                    continue
            if signal_path:
                break

        if signal_path is None:
            return json.dumps({
                "error": (
                    "No signal log file found. Looked for: "
                    + ", ".join(_SIGNAL_LOG_NAMES)
                    + ". Signal values may only be available in waveform files (.vcd, .fsdb) "
                    "which require a waveform viewer."
                )
            })

        time_min = max(0, time - window)
        time_max = time + window

        try:
            text = signal_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return json.dumps({"error": str(exc)})

        rows = []
        for pattern in [_QUESTA_SIGNAL_RE, _GENERIC_SIGNAL_RE]:
            for m in pattern.finditer(text):
                t = int(m.group("time"))
                if not (time_min <= t <= time_max):
                    continue
                sig = m.group("signal")
                if sig.lower() not in signal_set and not any(
                    sig.lower().endswith(s) for s in signal_set
                ):
                    continue
                rows.append({
                    "signal": sig,
                    "time": t,
                    "value": m.group("value"),
                })

        if not rows:
            return json.dumps({
                "rows": [],
                "message": (
                    f"No values found for signals {signals} in time window "
                    f"[{time_min}, {time_max}]."
                ),
            })

        return json.dumps({"rows": rows[:200]}, indent=2)

    return read_signal_values


def build_signal_tools(sim_dir: Path) -> list[tuple]:
    """Return tool spec tuples for signal tools."""
    return [
        (
            "read_signal_values",
            (
                "Read specific signal values at a specific simulation time from signal logs. "
                "Only returns requested signals within a short time window. "
                "Use only when error messages mention specific signals by name. "
                "Note: full waveform files (.vcd, .fsdb) cannot be read — only text signal logs."
            ),
            {
                "type": "object",
                "properties": {
                    "signals": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Signal names to look up (max 20), e.g. ['apci_rx.state', 'clk'].",
                    },
                    "time": {
                        "type": "integer",
                        "description": "Simulation time of interest.",
                    },
                    "window": {
                        "type": "integer",
                        "description": "Time window around the target time (default: 100 time units).",
                    },
                },
                "required": ["signals", "time"],
            },
            _build_read_signal_values_handler(sim_dir),
        ),
    ]
