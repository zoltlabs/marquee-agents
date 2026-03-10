"""qa_agent/tools/report/assertions.py

Tool: get_assertion_failures

Extracts SystemVerilog assertion (SVA) failures from debug.log.
Only debug.log is accessible — never source RTL or design files.
"""

from __future__ import annotations

import re
from pathlib import Path

from qa_agent.tools.report.security import validate_path

# SVA failure patterns for Questa/vsim output
_SVA_PATTERNS = [
    # Questa: ** Error: (vsim-XXXX) /path/file.sv(42): Assertion error: <name>
    re.compile(
        r"(?i)\*+\s*(error|failure).*?assert.*?"
        r"(?:at|in)?\s*(?P<file>[^\s:]+\.svh?)(?:\((?P<line>\d+)\))?"
        r"[^\n]*?:\s*(?P<msg>[^\n]+?)(?:\s+Time:\s*(?P<time>[\d.]+))?$",
        re.MULTILINE,
    ),
    # Generic: "Assertion failed: <name> at time <N>"
    re.compile(
        r"(?i)assertion\s+(?:failed|error)[:\s]+(?P<msg>[^\n]+?)"
        r"(?:\s+at\s+time\s+(?P<time>[\d.]+))?$",
        re.MULTILINE,
    ),
    # Questa UVM: "UVM_ERROR/FATAL <file>(<line>) @ <time>ns: <msg>"
    re.compile(
        r"(?i)UVM_(?:ERROR|FATAL)\s+(?P<file>[^\s]+)\((?P<line>\d+)\)"
        r"\s+@\s+(?P<time>[\d.]+)[^:]*:\s+(?P<msg>[^\n]+)",
        re.MULTILINE,
    ),
]


def _find_debug_log(sim_dir: Path) -> Path | None:
    for candidate in [sim_dir / "debug.log", sim_dir / "logs" / "debug.log"]:
        try:
            r = validate_path(str(candidate.relative_to(sim_dir)), sim_dir)
            if r.is_file():
                return r
        except Exception:
            continue
    return None


def _build_get_assertion_failures_handler(sim_dir: Path):
    def get_assertion_failures(
        pattern: str = "",
        max_failures: int = 50,
    ) -> str:
        """Extract SystemVerilog assertion failures from debug.log.

        Searches for SVA property violations, UVM_FATAL/UVM_ERROR assertion
        messages, and Questa vsim assertion error codes.

        IMPORTANT: Only debug.log is read — not source RTL or design files.

        Args:
            pattern:      Optional regex to further filter failure messages
                          (e.g. 'phy_rx_valid', 'pcie_link_test').
            max_failures: Max failures to return (1–100, default 50).

        Returns:
            Formatted text: one failure block per SVA assertion found.
        """
        log_path = _find_debug_log(sim_dir)
        if log_path is None:
            return "ERROR: debug.log not found. Use list_sim_files() to check available files."

        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"ERROR: Cannot read debug.log: {exc}"

        max_failures = max(1, min(max_failures, 100))

        if pattern:
            try:
                user_re = re.compile(pattern, re.IGNORECASE)
            except re.error as exc:
                return f"ERROR: Invalid pattern '{pattern}': {exc}"
        else:
            user_re = None

        failures: list[dict] = []
        seen: set[str] = set()

        for pat in _SVA_PATTERNS:
            for m in pat.finditer(text):
                msg = (m.group("msg").strip() if "msg" in pat.groupindex and m.group("msg")
                       else m.group(0).strip())[:300]
                if msg in seen:
                    continue
                if user_re and not user_re.search(msg):
                    continue
                seen.add(msg)
                failures.append({
                    "message": msg,
                    "time": (m.group("time").strip()
                             if "time" in pat.groupindex and m.group("time")
                             else "unknown"),
                    "file": (m.group("file")
                             if "file" in pat.groupindex and m.group("file")
                             else "unknown"),
                    "line": (m.group("line")
                             if "line" in pat.groupindex and m.group("line")
                             else "?"),
                })
                if len(failures) >= max_failures:
                    break
            if len(failures) >= max_failures:
                break

        if not failures:
            return (
                f"=== Assertion Failures in debug.log ===\n"
                f"No SVA assertion failures found"
                + (f" matching pattern '{pattern}'" if pattern else "")
                + ".\n"
                "Use get_debug_log(pattern='UVM_FATAL') for broad failure search."
            )

        lines = [
            f"=== {len(failures)} SVA Assertion Failure(s) in debug.log "
            + (f"[pattern='{pattern}'] " if pattern else "")
            + "==="
        ]
        for i, f in enumerate(failures, 1):
            lines.append(
                f"\n[{i}] Time: {f['time']}ns  File: {f['file']}:{f['line']}\n"
                f"    {f['message']}"
            )
        return "\n".join(lines)

    return get_assertion_failures


def build_assertion_tools(sim_dir: Path) -> list[tuple]:
    return [
        (
            "get_assertion_failures",
            (
                "Extract SystemVerilog SVA assertion failures from debug.log. "
                "Returns structured failure entries: time, file, line, message. "
                "Use pattern to filter by assertion/signal name. "
                "IMPORTANT: Only reads debug.log — never source RTL or design files."
            ),
            {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": (
                            "Optional regex to filter by message content "
                            "(e.g. 'phy_rx_valid', 'pcie_link', 'LTSSM'). "
                            "Leave empty to return all assertion failures."
                        ),
                    },
                    "max_failures": {
                        "type": "integer",
                        "description": "Max failures to return (1–100, default 50).",
                        "minimum": 1,
                        "maximum": 100,
                    },
                },
                "required": [],
            },
            _build_get_assertion_failures_handler(sim_dir),
        ),
    ]
