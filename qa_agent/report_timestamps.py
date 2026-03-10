"""qa_agent/report_timestamps.py

Extract machine-readable waveform timestamps from agentic debug reports.

The agentic AI is instructed to include a JSON block like:

    ```json
    {
      "waveform_timestamps": [
        {"time_ns": 4.2, "event": "First PHY error", "signals": ["phy_rx_valid"]}
      ]
    }
    ```

This module parses that block and writes a standalone JSON file alongside
the debug report file.

File naming:
    QA-AGENT_TIMESTAMPS_<YYYY-MM-DD_HHMMSS>.json

Usage:
    from qa_agent.report_timestamps import extract_timestamps, write_timestamps
    ts_list = extract_timestamps(report_text)
    if ts_list:
        out_path = write_timestamps(ts_list, sim_dir, report_timestamp)
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path


# JSON block pattern — looks for ```json ... ``` containing waveform_timestamps
_JSON_BLOCK_RE = re.compile(
    r"```json\s*(\{[^`]*\"waveform_timestamps\"[^`]*\})\s*```",
    re.DOTALL | re.IGNORECASE,
)


def extract_timestamps(report_text: str) -> list[dict]:
    """Extract waveform timestamp entries from a debug report.

    Finds the first ```json block containing a "waveform_timestamps" key
    and returns the list of timestamp entries.

    Args:
        report_text: Full Markdown report text from the AI.

    Returns:
        List of {time_ns, event, signals} dicts, or [] if not found/invalid.
    """
    m = _JSON_BLOCK_RE.search(report_text)
    if not m:
        return []

    raw_json = m.group(1).strip()
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        return []

    entries = data.get("waveform_timestamps", [])
    if not isinstance(entries, list):
        return []

    # Validate and normalise entries
    valid: list[dict] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        time_ns = entry.get("time_ns")
        event = entry.get("event", "")
        signals = entry.get("signals", [])
        if time_ns is None:
            continue
        valid.append({
            "time_ns": float(time_ns),
            "event": str(event),
            "signals": [str(s) for s in signals] if isinstance(signals, list) else [],
        })

    return sorted(valid, key=lambda x: x["time_ns"])


def write_timestamps(
    timestamps: list[dict],
    sim_dir: str | Path,
    report_timestamp: datetime | None = None,
    test_name: str = "",
) -> Path:
    """Write extracted timestamps to a JSON file alongside the sim directory.

    Args:
        timestamps:        List of {time_ns, event, signals} dicts.
        sim_dir:           The simulation output directory path.
        report_timestamp:  Datetime for the filename (default: now).
        test_name:         Optional test name for metadata.

    Returns:
        Path to the written JSON file.
    """
    sim_path = Path(sim_dir).resolve()
    ts = report_timestamp or datetime.now()
    ts_str = ts.strftime("%Y-%m-%d_%H%M%S")

    output_data = {
        "generated": ts.isoformat(),
        "sim_dir": str(sim_path),
        "test_name": test_name,
        "timestamp_count": len(timestamps),
        "timestamps": timestamps,
    }

    out_path = sim_path / f"QA-AGENT_TIMESTAMPS_{ts_str}.json"
    out_path.write_text(
        json.dumps(output_data, indent=2),
        encoding="utf-8",
    )
    return out_path
