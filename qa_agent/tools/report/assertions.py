"""qa_agent/tools/report/assertions.py

Tool: get_assertion_failures

Extracts SystemVerilog assertion failures from simulation logs.
Returns structured JSON — not raw log lines.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from qa_agent.tools.report.security import validate_path

# Patterns that match SVA assertion failures in common simulators (Questa, VCS, Xcelium)
_SVA_PATTERNS = [
    # Questa: ** Error: (vsim-XXXX) /path/to/file.sv(42): Assertion error: <name>
    re.compile(
        r"(?i)\*+\s*(error|failure).*?assert.*?(?:at|in)?\s*(?P<file>[^\s:]+\.sv[h]?)\((?P<line>\d+)\)"
        r"[^\n]*?:\s*(?P<msg>.*?)(?:\s*Time:\s*(?P<time>[\d]+))?$",
        re.MULTILINE,
    ),
    # Generic: "Assertion failed: <name> at time <N>"
    re.compile(
        r"(?i)assertion\s+(?:failed|error)[:\s]+(?P<msg>[^\n]+?)(?:\s+at\s+time\s+(?P<time>\d+))?$",
        re.MULTILINE,
    ),
    # Questa UVM assertion: "UVM_ERROR ... Assertion"
    re.compile(
        r"(?i)UVM_(?:ERROR|FATAL)\s+(?P<file>[^\s]+)\((?P<line>\d+)\)\s+@\s+(?P<time>\d+)[^:]*:\s+(?P<msg>[^\n]+)",
        re.MULTILINE,
    ),
]


def _build_get_assertion_failures_handler(sim_dir: Path):
    """Return a handler for get_assertion_failures bound to *sim_dir*."""

    def get_assertion_failures(log_file: str = "sim.log") -> str:
        """Extract SystemVerilog assertion failures from a simulation log.

        Args:
            log_file: Log file to scan (default: sim.log).

        Returns:
            JSON array of {assertion, time, module, message} objects.
        """
        basename = Path(log_file).name
        allowed = {"sim.log", "run.log", "questa.log"}
        if basename not in allowed:
            return json.dumps({
                "error": f"Not allowed: '{log_file}'. Use one of: {', '.join(sorted(allowed))}"
            })

        # Find the log file
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

        failures = []
        seen_msgs: set[str] = set()

        for pattern in _SVA_PATTERNS:
            for m in pattern.finditer(text):
                msg = m.group("msg").strip() if "msg" in pattern.groupindex else m.group(0).strip()
                # Deduplicate
                if msg in seen_msgs:
                    continue
                seen_msgs.add(msg)

                entry = {
                    "assertion": msg[:200],
                    "time": m.group("time").strip() if "time" in pattern.groupindex and m.group("time") else "unknown",
                    "module": m.group("file") if "file" in pattern.groupindex and m.group("file") else "unknown",
                    "message": msg[:300],
                }
                failures.append(entry)

                if len(failures) >= 50:
                    break
            if len(failures) >= 50:
                break

        return json.dumps({
            "assertion_failures": failures,
            "total": len(failures),
        }, indent=2)

    return get_assertion_failures


def build_assertion_tools(sim_dir: Path) -> list[tuple]:
    """Return tool spec tuples for assertion tools."""
    return [
        (
            "get_assertion_failures",
            (
                "Extract SystemVerilog assertion failures from simulation logs. "
                "Returns structured {assertion, time, module, message} entries — not raw lines. "
                "Use after extract_log_errors if assertion failures are mentioned."
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
            _build_get_assertion_failures_handler(sim_dir),
        ),
    ]
