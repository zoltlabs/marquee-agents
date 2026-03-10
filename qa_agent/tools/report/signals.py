"""qa_agent/tools/report/signals.py

Tool: read_signal_values

Reads signal values from text-based signal logs in the simulation directory.
Binary waveform files (.vcd, .fsdb, qwave.db) are NOT accessible — only
text-based logs.  The tool informs the AI if no signal log is available.
"""

from __future__ import annotations

import re
from pathlib import Path

from qa_agent.tools.report.security import validate_path

# Text-based signal log filenames that may exist in Questa output
_SIGNAL_LOG_NAMES = ["signals.log", "wave.log", "dump.log", "signals.txt"]

# Questa wave log format: "# 12345 ns signal = 8'hAB"
_QUESTA_RE = re.compile(
    r"#\s*(?P<time>[\d.]+)\s+ns\s+(?P<signal>[\w./]+)\s*=\s*(?P<value>[^\s]+)"
)
# Generic: "12345 signal = 8'hAB"
_GENERIC_RE = re.compile(
    r"(?P<time>\d+)\s+(?P<signal>[\w./]+)\s*[=:]\s*(?P<value>[^\s]+)"
)

_MAX_RESULTS = 500


def _find_signal_log(sim_dir: Path) -> Path | None:
    for name in _SIGNAL_LOG_NAMES:
        for base in [sim_dir, sim_dir / "logs", sim_dir / "qrun.out"]:
            candidate = base / name
            try:
                r = validate_path(str(candidate.relative_to(sim_dir)), sim_dir)
                if r.is_file():
                    return r
            except Exception:
                continue
    return None


def _build_read_signal_values_handler(sim_dir: Path):
    def read_signal_values(
        signals: list[str],
        time_ns: float,
        window_ns: float = 10.0,
    ) -> str:
        """Read signal values from a text-based signal log near a simulation time.

        NOTE: Binary waveform files (qwave.db, .vcd, .fsdb) cannot be read.
        Only text-based signal logs (signals.log, wave.log) are accessible.
        If no signal log exists, the tool reports this clearly.

        For waveform inspection, the Debugging Recommendations section should
        reference Visualizer with exact timestamps extracted from debug.log.

        Args:
            signals:   Signal names to look up (max 20).
                       E.g. ['phy_rx_valid', 'ltssm_state', 'clk'].
            time_ns:   The simulation time of interest (nanoseconds).
            window_ns: Time window around time_ns to search
                       (±window_ns, default ±10ns).

        Returns:
            Formatted text: {signal, time_ns, value} rows or not-found message.
        """
        if not signals:
            return "ERROR: No signals specified."

        signals = signals[:20]
        signal_set = {s.lower() for s in signals}

        log_path = _find_signal_log(sim_dir)
        if log_path is None:
            return (
                "INFO: No text-based signal log found.\n"
                f"Looked for: {', '.join(_SIGNAL_LOG_NAMES)}\n"
                "Signal values in binary waveform files (qwave.db, .vcd, .fsdb) "
                "cannot be read by this tool.\n"
                "Recommendation: open Visualizer and navigate to the timestamps "
                "identified in debug.log/tracker files."
            )

        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"ERROR: Cannot read {log_path.name}: {exc}"

        t_min = max(0.0, time_ns - window_ns)
        t_max = time_ns + window_ns

        rows: list[dict] = []
        for pat in [_QUESTA_RE, _GENERIC_RE]:
            for m in pat.finditer(text):
                t = float(m.group("time"))
                if not (t_min <= t <= t_max):
                    continue
                sig = m.group("signal")
                if sig.lower() not in signal_set and not any(
                    sig.lower().endswith(s) for s in signal_set
                ):
                    continue
                rows.append({
                    "signal": sig,
                    "time_ns": t,
                    "value": m.group("value"),
                })
                if len(rows) >= _MAX_RESULTS:
                    break
            if len(rows) >= _MAX_RESULTS:
                break

        if not rows:
            return (
                f"=== Signal Values near t={time_ns}ns (±{window_ns}ns) ===\n"
                f"No values found for: {', '.join(signals)}\n"
                f"Time window searched: [{t_min}ns, {t_max}ns]\n"
                f"Source: {log_path.name}"
            )

        header = (
            f"=== Signal Values near t={time_ns}ns (±{window_ns}ns) ===\n"
            f"Source: {log_path.name}  |  {len(rows)} result(s)\n"
        )
        result_lines = [
            f"  t={r['time_ns']}ns  {r['signal']} = {r['value']}"
            for r in rows
        ]
        return header + "\n".join(result_lines)

    return read_signal_values


def build_signal_tools(sim_dir: Path) -> list[tuple]:
    return [
        (
            "read_signal_values",
            (
                "Read signal values at a specific simulation time from a text-based signal log. "
                "Returns values within ±window_ns of the target time. "
                "NOTE: Binary waveform files (qwave.db, .vcd) cannot be read. "
                "If no signal log exists, the tool provides waveform guidance instead. "
                "Use only when error messages reference specific signal names."
            ),
            {
                "type": "object",
                "properties": {
                    "signals": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Signal names to look up (max 20), e.g. ['phy_rx_valid', 'ltssm_state'].",
                    },
                    "time_ns": {
                        "type": "number",
                        "description": "Simulation time of interest in nanoseconds.",
                    },
                    "window_ns": {
                        "type": "number",
                        "description": "Time window around time_ns to search (default ±10ns).",
                    },
                },
                "required": ["signals", "time_ns"],
            },
            _build_read_signal_values_handler(sim_dir),
        ),
    ]
