"""qa_agent/report_prefetch.py

Pre-fetches all simulation data for the AI debug report.

Reads simulation output files directly (compile.log, sim.log, tracker, etc.)
with security validation (path containment, output caps, path sanitization).
Results are assembled into a single Markdown context block embedded in the
AI prompt.

Security:
  - All file access validated via tools/report/security.validate_path()
  - Absolute paths in log content are sanitized (sim_dir prefix stripped)
  - Per-section output caps enforced
  - No credentials, hostnames, or user-identifiable info forwarded

This module is the data-collection layer for the stream-based report flow:
    collect_sim_data(sim_dir) -> str   (Markdown context block)
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from qa_agent.tools.report import build_report_tools
from qa_agent.tools.report.security import validate_path, truncate_output


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

# Per-section character cap — generous for one-shot prompt (not agentic loop)
_SECTION_CAP = 32_000

# Overall context cap — prevents exceeding model context window
_TOTAL_CONTEXT_CAP = 150_000

# Max bytes to read from a single log file
_MAX_FILE_BYTES = 2_000_000


# ─────────────────────────────────────────────────────────────────────────────
# Path / PII sanitization
# ─────────────────────────────────────────────────────────────────────────────

_HOME_RE = re.compile(r"/(?:home|Users)/\w+/", re.IGNORECASE)
_CREDENTIAL_RE = re.compile(
    r"(?:sk-ant-|sk-[A-Za-z0-9]{20,}|AIza[A-Za-z0-9_-]{30,}|"
    r"ANTHROPIC_API_KEY|OPENAI_API_KEY|GEMINI_API_KEY)\S*",
)


def _sanitize(text: str, sim_dir: Path) -> str:
    """Strip sensitive info from collected data before embedding in the prompt.

    Replaces:
      - The sim_dir absolute path with <SIM_DIR>
      - Home directory paths (/home/<user>/, /Users/<user>/) with <HOME>/
      - The machine hostname with <HOST>
      - Credential-like strings (API keys)
    """
    sim_str = str(sim_dir)
    text = text.replace(sim_str + "/", "<SIM_DIR>/")
    text = text.replace(sim_str, "<SIM_DIR>")
    text = _HOME_RE.sub("<HOME>/", text)
    text = _CREDENTIAL_RE.sub("<REDACTED>", text)

    try:
        hostname = os.uname().nodename
        if hostname and len(hostname) > 2:
            text = text.replace(hostname, "<HOST>")
    except Exception:
        pass

    return text


# ─────────────────────────────────────────────────────────────────────────────
# File reading helpers
# ─────────────────────────────────────────────────────────────────────────────

def _find_file(sim_dir: Path, name: str) -> Path | None:
    """Locate a file in sim_dir, sim_dir/logs/, or sim_dir/qrun.out/."""
    for parent in [sim_dir, sim_dir / "logs", sim_dir / "qrun.out"]:
        candidate = parent / name
        try:
            validated = validate_path(str(candidate.relative_to(sim_dir)), sim_dir)
            if validated.exists():
                return validated
        except Exception:
            continue
    return None


def _safe_read(path: Path, sim_dir: Path, max_bytes: int = _MAX_FILE_BYTES) -> str | None:
    """Read a file within sim_dir. Returns None if not found or inaccessible."""
    try:
        validate_path(str(path.relative_to(sim_dir)), sim_dir)
    except Exception:
        return None

    if not path.exists():
        return None

    try:
        raw = path.read_bytes()[:max_bytes]
        return raw.decode("utf-8", errors="replace")
    except OSError:
        return None


def _cap_section(text: str, limit: int = _SECTION_CAP) -> str:
    """Truncate a section to the cap, appending a notice if truncated."""
    text, was_truncated = truncate_output(text, limit)
    if was_truncated:
        text += "\n\n*[Section truncated at size limit]*"
    return text


# ─────────────────────────────────────────────────────────────────────────────
# Section collectors
# ─────────────────────────────────────────────────────────────────────────────

def _collect_file_listing(sim_dir: Path) -> str:
    """List files in sim_dir top level, qrun.out/, and logs/."""
    registry = build_report_tools(sim_dir, max_output_chars=_SECTION_CAP)
    parts: list[str] = []

    for label, kwargs in [
        ("Top level", {}),
        ("qrun.out/", {"subdir": "qrun.out"}),
        ("logs/", {"subdir": "logs"}),
    ]:
        result = registry.execute(f"prefetch_{label}", "list_sim_files", kwargs)
        parts.append(f"### {label}\n```json\n{result.content.strip()}\n```\n")

    return "\n".join(parts)


def _collect_test_config(sim_dir: Path) -> str:
    """Read test configuration from qrun.out/ metadata files."""
    parts: list[str] = []

    for name in ["big_argv", "version", "stats_log", "top_dus"]:
        meta_path = sim_dir / "qrun.out" / name
        content = _safe_read(meta_path, sim_dir, max_bytes=8_000)
        if content:
            parts.append(f"### {name}\n```\n{content.strip()}\n```\n")
        else:
            parts.append(f"### {name}\n*Not found*\n")

    return "\n".join(parts)


def _collect_compile_log(sim_dir: Path) -> str:
    """Analyse compile.log — full error blocks if errors, else brief summary."""
    path = _find_file(sim_dir, "compile.log")
    if path is None:
        return "*compile.log not found*\n"

    content = _safe_read(path, sim_dir)
    if content is None:
        return "*Could not read compile.log*\n"

    lines = content.splitlines()

    # Detect compilation errors
    error_re = re.compile(
        r"(?i)\*\*\s*(error|fatal)"
        r"|compilation\s+failed"
        r"|fatal\s+error"
        r"|syntax\s+error"
    )

    has_errors = any(error_re.search(line) for line in lines)

    if not has_errors:
        # Clean compile — show last 30 lines (summary)
        tail_n = min(30, len(lines))
        tail = lines[-tail_n:]
        return (
            f"*Compilation clean ({len(lines)} lines total, no errors)*\n\n"
            f"**Compile Log Tail (last {tail_n} lines):**\n"
            f"```\n{chr(10).join(tail)}\n```\n"
        )

    # Has errors — extract error blocks with generous context (8 lines before, 5 after)
    error_blocks: list[str] = []
    covered: set[int] = set()

    for i, line in enumerate(lines):
        if error_re.search(line) and i not in covered:
            start = max(0, i - 8)
            end = min(len(lines), i + 6)
            for j in range(start, end):
                covered.add(j)
            block_lines = lines[start:end]
            error_blocks.append(f"[Line {i + 1}]\n" + "\n".join(block_lines))

    # Also include the last 20 lines (compilation summary)
    tail = lines[-20:] if len(lines) > 20 else lines

    result = (
        f"**Compilation FAILED** ({len(lines)} lines total, "
        f"{len(error_blocks)} error block(s) found)\n\n"
        "### Error Blocks\n```\n"
        + "\n\n---\n".join(error_blocks)
        + "\n```\n\n### Compile Log Tail\n```\n"
        + "\n".join(tail)
        + "\n```\n"
    )

    return _cap_section(result)


def _collect_sim_errors(sim_dir: Path) -> str:
    """Extract ALL error/warning/fatal lines from sim.log with context.

    Unlike the tool handler (which caps at 50 matches with 3 context lines),
    this collects comprehensively for the one-shot AI analysis.
    """
    path = _find_file(sim_dir, "sim.log")
    if path is None:
        return "*sim.log not found*\n"

    content = _safe_read(path, sim_dir)
    if content is None:
        return "*Could not read sim.log*\n"

    lines = content.splitlines()

    # Error patterns (higher priority)
    error_re = re.compile(
        r"(?i)(\*\*\s*(error|fatal)"
        r"|UVM_(ERROR|FATAL)"
        r"|assertion\s+(fail|error)"
        r"|scoreboard.*mismatch"
        r"|FAILED"
        r"|timeout.*(?:abort|fatal|limit))"
    )
    # Warning patterns (tracked separately)
    warning_re = re.compile(r"(?i)(\*\*\s*warning|UVM_WARNING)")

    error_blocks: list[str] = []
    warning_count = 0
    covered: set[int] = set()

    for i, line in enumerate(lines):
        if error_re.search(line):
            if i in covered:
                continue
            # 5 lines before, 8 lines after for context
            start = max(0, i - 5)
            end = min(len(lines), i + 9)
            for j in range(start, end):
                covered.add(j)
            block_lines = lines[start:end]
            error_blocks.append(f"[Line {i + 1}]\n" + "\n".join(block_lines))
        elif warning_re.search(line):
            warning_count += 1

    if not error_blocks:
        return (
            f"*No errors found in sim.log "
            f"({len(lines)} lines, {warning_count} warning(s))*\n"
        )

    result = (
        f"**{len(error_blocks)} error block(s) found** "
        f"({len(lines)} total lines, {warning_count} warning(s))\n\n```\n"
        + "\n\n---\n".join(error_blocks)
        + "\n```\n"
    )

    return _cap_section(result)


def _collect_uvm_summary(sim_dir: Path) -> str:
    """Extract the UVM Report Summary table from the end of sim.log.

    The UVM summary typically appears near the end and contains error/warning
    counts per component — critical for understanding failure scope.
    """
    path = _find_file(sim_dir, "sim.log")
    if path is None:
        return "*sim.log not found*\n"

    content = _safe_read(path, sim_dir)
    if content is None:
        return "*Could not read sim.log*\n"

    lines = content.splitlines()

    # Search backwards from end for UVM summary markers
    summary_patterns = [
        re.compile(r"(?i)[-=]+\s*UVM\s+Report\s+Summary\s*[-=]+"),
        re.compile(r"(?i)UVM\s+Report\s+Summary"),
        re.compile(r"(?i)[-=]+\s*Report\s+Summary\s*[-=]+"),
    ]

    # Also look for the count table lines: "UVM_INFO : 42"
    count_re = re.compile(r"(?i)^\s*UVM_(INFO|WARNING|ERROR|FATAL)\s*[:/]\s*\d+")

    summary_start = None
    search_range = range(len(lines) - 1, max(0, len(lines) - 500) - 1, -1)

    for i in search_range:
        for pat in summary_patterns:
            if pat.search(lines[i]):
                summary_start = i
                break
        if summary_start is not None:
            break

    if summary_start is not None:
        # Grab from summary header to end of file (or at most 80 lines)
        end = min(summary_start + 80, len(lines))
        summary_lines = lines[summary_start:end]
        return f"```\n{chr(10).join(summary_lines)}\n```\n"

    # Fallback: look for count table lines without a header
    count_lines: list[str] = []
    for i in range(max(0, len(lines) - 100), len(lines)):
        if count_re.search(lines[i]):
            count_lines.append(lines[i])

    if count_lines:
        return (
            "*No formal UVM Report Summary header found, but count lines detected:*\n\n"
            f"```\n{chr(10).join(count_lines)}\n```\n"
        )

    return "*No UVM Report Summary found in sim.log*\n"


def _collect_sim_tail(sim_dir: Path) -> str:
    """Get the last 150 lines of sim.log — test verdict, phase info, exit status."""
    path = _find_file(sim_dir, "sim.log")
    if path is None:
        return "*sim.log not found*\n"

    content = _safe_read(path, sim_dir)
    if content is None:
        return "*Could not read sim.log*\n"

    lines = content.splitlines()
    tail_n = min(150, len(lines))
    tail = lines[-tail_n:]

    return (
        f"*Last {tail_n} of {len(lines)} lines:*\n\n"
        f"```\n{chr(10).join(tail)}\n```\n"
    )


def _collect_assertions(sim_dir: Path) -> str:
    """Extract structured assertion failures via the existing tool handler."""
    registry = build_report_tools(sim_dir, max_output_chars=_SECTION_CAP)
    result = registry.execute("prefetch_assertions", "get_assertion_failures", {})
    if result.error:
        return f"*Error: {result.content}*\n"
    return f"```json\n{result.content.strip()}\n```\n"


def _collect_scoreboard(sim_dir: Path) -> str:
    """Extract structured scoreboard mismatches via the existing tool handler."""
    registry = build_report_tools(sim_dir, max_output_chars=_SECTION_CAP)
    result = registry.execute("prefetch_scoreboard", "get_scoreboard_mismatches", {})
    if result.error:
        return f"*Error: {result.content}*\n"
    return f"```json\n{result.content.strip()}\n```\n"


def _collect_tracker(sim_dir: Path) -> str:
    """Extract tracker failure events via the existing tool handler."""
    registry = build_report_tools(sim_dir, max_output_chars=_SECTION_CAP)
    result = registry.execute("prefetch_tracker", "extract_tracker_failures", {})
    if result.error:
        return f"*Error: {result.content}*\n"
    return f"```json\n{result.content.strip()}\n```\n"


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

# Sections ordered by debugging priority
_SECTIONS: list[tuple[str, object]] = [
    ("Available Simulation Files", _collect_file_listing),
    ("Test Configuration & Metadata", _collect_test_config),
    ("Compile Log Analysis", _collect_compile_log),
    ("Simulation Errors & Failures", _collect_sim_errors),
    ("UVM Report Summary", _collect_uvm_summary),
    ("Simulation Log — Final Output", _collect_sim_tail),
    ("Assertion Failures (Structured)", _collect_assertions),
    ("Scoreboard Mismatches (Structured)", _collect_scoreboard),
    ("Tracker Events (Failure-Related)", _collect_tracker),
]


def collect_sim_data(sim_dir: Path) -> str:
    """Run all collectors against *sim_dir* and return a Markdown context block.

    Each collector reads simulation output files with security validation
    (path containment via validate_path(), output caps, PII sanitization).
    Results are assembled in debugging priority order.

    Args:
        sim_dir: Resolved Path to the simulation output directory.

    Returns:
        A Markdown-formatted string with all collected sim data embedded, ready
        to drop into an AI prompt.
    """
    parts: list[str] = [
        "# Simulation Data\n",
    ]

    for title, collector in _SECTIONS:
        parts.append(f"\n## {title}\n")
        try:
            section = collector(sim_dir)
            parts.append(section)
        except Exception as exc:
            parts.append(
                f"*Error collecting {title}: {type(exc).__name__}: {exc}*\n"
            )

    full_text = "\n".join(parts)

    # Sanitize all sensitive paths and PII
    full_text = _sanitize(full_text, sim_dir)

    # Apply overall context cap — truncate less-critical trailing sections first
    if len(full_text) > _TOTAL_CONTEXT_CAP:
        full_text = full_text[:_TOTAL_CONTEXT_CAP]
        full_text += (
            "\n\n*[Total context truncated at "
            f"{_TOTAL_CONTEXT_CAP // 1000}KB limit]*\n"
        )

    return full_text
