"""qa_agent/report_prefetch.py

Pre-fetches all simulation data for the AI debug report.

Discovers and reads actual Questa/Visualizer output files from the simulation
directory — debug.log, mti.log, tracker_*.txt, sfi_*.txt, coverage reports,
and qrun.out/ metadata.

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

from qa_agent.tools.report.security import validate_path, truncate_output


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

# Per-section character cap
_SECTION_CAP = 32_000

# Overall context cap — prevents exceeding model context window
_TOTAL_CONTEXT_CAP = 150_000

# Max bytes to read from a single file
_MAX_FILE_BYTES = 2_000_000

# Readable text extensions (skip binaries)
_TEXT_EXTENSIONS = {".txt", ".log", ".doc", ".f", ".sv", ".v", ".vh", ".cmd"}

# Files/dirs to skip entirely
_SKIP_NAMES = {"work", "design.bin", "qwave.db", "qrun.out", "sessions", "snapshot"}


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

def _safe_read(path: Path, sim_dir: Path, max_bytes: int = _MAX_FILE_BYTES) -> str | None:
    """Read a file within sim_dir. Returns None if not found or inaccessible."""
    try:
        validate_path(str(path.relative_to(sim_dir)), sim_dir)
    except Exception:
        return None

    if not path.exists() or not path.is_file():
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


def _discover_files(sim_dir: Path) -> dict[str, list[Path]]:
    """Discover and categorise readable files in the simulation directory.

    Returns a dict with categories:
      - 'debug_logs': debug.log and similar main simulation logs
      - 'mti_logs': mti.log, mti.cmd
      - 'tracker': tracker_*.txt files
      - 'sfi': sfi_*.txt files
      - 'coverage': *coverage*.txt files
      - 'other_logs': any other .log or .txt files
    """
    categories: dict[str, list[Path]] = {
        "debug_logs": [],
        "mti_logs": [],
        "tracker": [],
        "sfi": [],
        "coverage": [],
        "other_logs": [],
    }

    try:
        entries = sorted(sim_dir.iterdir())
    except PermissionError:
        return categories

    for entry in entries:
        if not entry.is_file():
            continue
        name = entry.name.lower()

        # Skip known binary/unreadable files
        if name in _SKIP_NAMES:
            continue

        # Check extension
        suffix = entry.suffix.lower()
        if suffix not in _TEXT_EXTENSIONS and entry.suffix:
            continue

        # Categorise
        if name == "debug.log":
            categories["debug_logs"].append(entry)
        elif name.startswith("mti."):
            categories["mti_logs"].append(entry)
        elif name.startswith("tracker_"):
            categories["tracker"].append(entry)
        elif name.startswith("sfi_"):
            categories["sfi"].append(entry)
        elif "coverage" in name:
            categories["coverage"].append(entry)
        elif suffix in {".log", ".txt"}:
            categories["other_logs"].append(entry)

    return categories


# ─────────────────────────────────────────────────────────────────────────────
# Section collectors
# ─────────────────────────────────────────────────────────────────────────────

def _read_big_argv(sim_dir: Path) -> str | None:
    """Read the vlog filelist from qrun.out/big_argv/.

    big_argv is a directory containing a single .f file (e.g.
    vlog_work_b402oC34PUd0F1NA1.f) with the full vlog command line.
    Falls back to reading big_argv as a plain file if the directory
    form is not found.
    """
    big_argv_path = sim_dir / "qrun.out" / "big_argv"

    # New form: big_argv is a directory containing a .f file
    if big_argv_path.is_dir():
        try:
            f_files = sorted(big_argv_path.glob("*.f"))
            if f_files:
                f_file = f_files[0]
                try:
                    validate_path(
                        str(f_file.relative_to(sim_dir)), sim_dir
                    )
                except Exception:
                    return None
                return _safe_read(f_file, sim_dir, max_bytes=8_000)
        except Exception:
            return None
        return None

    # Legacy form: big_argv is a plain file
    return _safe_read(big_argv_path, sim_dir, max_bytes=8_000)


def _collect_test_config(sim_dir: Path) -> str:
    """Read test configuration from qrun.out/ metadata files."""
    parts: list[str] = []

    # big_argv — may be a directory (new Questa form) or a plain file
    big_argv = _read_big_argv(sim_dir)
    if big_argv:
        parts.append(f"### big_argv\n```\n{big_argv.strip()}\n```\n")
    else:
        parts.append("### big_argv\n*Not found*\n")

    for name in ["version", "stats_log", "top_dus"]:
        meta_path = sim_dir / "qrun.out" / name
        content = _safe_read(meta_path, sim_dir, max_bytes=8_000)
        if content:
            parts.append(f"### {name}\n```\n{content.strip()}\n```\n")
        else:
            parts.append(f"### {name}\n*Not found*\n")

    return "\n".join(parts)


def _extract_errors_from_log(content: str, log_name: str) -> str:
    """Extract all error/warning/fatal blocks from a log file with context.

    Returns a formatted string with error blocks and surrounding context lines.
    """
    lines = content.splitlines()

    # Error patterns (high priority)
    error_re = re.compile(
        r"(?i)(\*\*\s*(error|fatal)"
        r"|UVM_(ERROR|FATAL)"
        r"|assertion\s+(fail|error)"
        r"|scoreboard.*mismatch"
        r"|FAILED"
        r"|timeout.*(?:abort|fatal|limit)"
        r"|\bfatal\b"
        r"|Error:)"
    )
    # Warning patterns
    warning_re = re.compile(r"(?i)(\*\*\s*warning|UVM_WARNING|Warning:)")

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
            f"*No errors found in {log_name} "
            f"({len(lines)} lines, {warning_count} warning(s))*\n"
        )

    result = (
        f"**{len(error_blocks)} error block(s) found in {log_name}** "
        f"({len(lines)} total lines, {warning_count} warning(s))\n\n```\n"
        + "\n\n---\n".join(error_blocks)
        + "\n```\n"
    )

    return _cap_section(result)


def _collect_debug_log(sim_dir: Path, files: dict[str, list[Path]]) -> str:
    """Collect errors and tail from debug.log — the main simulation log."""
    debug_logs = files.get("debug_logs", [])
    if not debug_logs:
        return "*debug.log not found*\n"

    path = debug_logs[0]
    content = _safe_read(path, sim_dir)
    if content is None:
        return "*Could not read debug.log*\n"

    parts: list[str] = []

    # Extract errors with context
    errors_section = _extract_errors_from_log(content, "debug.log")
    parts.append("### Errors & Failures\n" + errors_section)

    # UVM Report Summary (search from end)
    lines = content.splitlines()
    uvm_summary = _extract_uvm_summary(lines)
    if uvm_summary:
        parts.append("### UVM Report Summary\n" + uvm_summary)

    # Last 150 lines — contains test verdict, phase info, exit status
    tail_n = min(150, len(lines))
    tail = lines[-tail_n:]
    parts.append(
        f"### Log Tail (last {tail_n} of {len(lines)} lines)\n"
        f"```\n{chr(10).join(tail)}\n```\n"
    )

    return _cap_section("\n".join(parts))


def _extract_uvm_summary(lines: list[str]) -> str:
    """Extract UVM Report Summary table from log lines (searched from end)."""
    summary_patterns = [
        re.compile(r"(?i)[-=]+\s*UVM\s+Report\s+Summary\s*[-=]+"),
        re.compile(r"(?i)UVM\s+Report\s+Summary"),
        re.compile(r"(?i)[-=]+\s*Report\s+Summary\s*[-=]+"),
    ]
    count_re = re.compile(r"(?i)^\s*UVM_(INFO|WARNING|ERROR|FATAL)\s*[:/]\s*\d+")

    # Search backwards from end
    summary_start = None
    for i in range(len(lines) - 1, max(0, len(lines) - 500) - 1, -1):
        for pat in summary_patterns:
            if pat.search(lines[i]):
                summary_start = i
                break
        if summary_start is not None:
            break

    if summary_start is not None:
        end = min(summary_start + 80, len(lines))
        summary_lines = lines[summary_start:end]
        return f"```\n{chr(10).join(summary_lines)}\n```\n"

    # Fallback: count table lines without header
    count_lines = [
        lines[i] for i in range(max(0, len(lines) - 100), len(lines))
        if count_re.search(lines[i])
    ]
    if count_lines:
        return (
            "*No formal UVM Report Summary header, but count lines found:*\n\n"
            f"```\n{chr(10).join(count_lines)}\n```\n"
        )

    return ""


def _collect_mti_log(sim_dir: Path, files: dict[str, list[Path]]) -> str:
    """Collect errors from mti.log — Questa/MTI diagnostic log."""
    mti_logs = files.get("mti_logs", [])
    if not mti_logs:
        return "*mti.log not found*\n"

    parts: list[str] = []
    for path in mti_logs:
        content = _safe_read(path, sim_dir)
        if content is None:
            parts.append(f"*Could not read {path.name}*\n")
            continue
        parts.append(
            f"### {path.name}\n"
            + _extract_errors_from_log(content, path.name)
        )

    return "\n".join(parts)


# Pattern matching only the 5 failure categories of interest in tracker files.
# Matches: ASSERT failures, SCOREBOARD mismatches, TIMEOUT events,
# FATAL errors, and transaction mismatches.
_TRACKER_FAILURE_RE = re.compile(
    r"(?i)"
    r"(assert.*fail|fail.*assert"          # ASSERT failures
    r"|scoreboard.*mismatch|mismatch.*scoreboard"  # SCOREBOARD mismatches
    r"|timeout"                            # TIMEOUT events
    r"|\bfatal\b"                          # FATAL errors
    r"|transaction.*mismatch|mismatch.*transaction"  # Transaction mismatches
    r"|ASSERT|SCOREBOARD_ERR|SB_ERR"      # Common tracker tags
    r")"
)


def _collect_tracker_data(sim_dir: Path, files: dict[str, list[Path]]) -> str:
    """Extract failure events from tracker_*.txt files.

    Only collects:
      - ASSERT failures
      - SCOREBOARD mismatches
      - TIMEOUT events
      - FATAL errors
      - Transaction mismatches
    """
    tracker_files = files.get("tracker", [])
    if not tracker_files:
        return "*No tracker files found*\n"

    parts: list[str] = []

    for path in tracker_files:
        content = _safe_read(path, sim_dir)
        if content is None:
            continue

        lines = content.splitlines()
        failure_lines = [
            line for line in lines if _TRACKER_FAILURE_RE.search(line)
        ]

        if failure_lines:
            parts.append(
                f"### {path.name} — {len(failure_lines)} failure event(s) "
                f"(of {len(lines)} total lines)\n"
                f"```\n{chr(10).join(failure_lines[:200])}\n```\n"
            )
        # Skip files with no matching failures entirely — no noise

    if not parts:
        return (
            "*No tracker failure events found across "
            f"{len(tracker_files)} tracker file(s). "
            "No ASSERT / SCOREBOARD / TIMEOUT / FATAL / transaction mismatch entries.*\n"
        )

    return _cap_section("\n".join(parts))


def _collect_sfi_data(sim_dir: Path, files: dict[str, list[Path]]) -> str:
    """Read SFI (Scalable Fabric Interface) data files."""
    sfi_files = files.get("sfi", [])
    if not sfi_files:
        return "*No SFI data files found*\n"

    parts: list[str] = []

    for path in sfi_files:
        content = _safe_read(path, sim_dir, max_bytes=16_000)
        if content is None:
            continue

        lines = content.splitlines()
        # For SFI data, show first 50 lines + error lines
        display_lines = lines[:50]
        if len(lines) > 50:
            display_lines.append(f"... ({len(lines) - 50} more lines) ...")

        parts.append(
            f"### {path.name} ({len(lines)} lines)\n"
            f"```\n{chr(10).join(display_lines)}\n```\n"
        )

    if not parts:
        return "*No readable SFI files*\n"

    return _cap_section("\n".join(parts))


def _collect_coverage(sim_dir: Path, files: dict[str, list[Path]]) -> str:
    """Read coverage report files."""
    coverage_files = files.get("coverage", [])
    if not coverage_files:
        return "*No coverage report found*\n"

    parts: list[str] = []

    for path in coverage_files:
        content = _safe_read(path, sim_dir, max_bytes=32_000)
        if content is None:
            continue

        lines = content.splitlines()
        parts.append(
            f"### {path.name} ({len(lines)} lines)\n"
            f"```\n{chr(10).join(lines)}\n```\n"
        )

    if not parts:
        return "*No readable coverage files*\n"

    return _cap_section("\n".join(parts))


def _collect_stats_summary(sim_dir: Path) -> str:
    """Parse stats_log for a quick error/warning count summary per tool."""
    stats_path = sim_dir / "qrun.out" / "stats_log"
    content = _safe_read(stats_path, sim_dir, max_bytes=4_000)
    if content is None:
        return "*stats_log not found*\n"

    # Parse lines like "vlog: Errors: 0, Warnings: 4"
    lines = content.strip().splitlines()
    has_errors = any(
        re.search(r"Errors:\s*[1-9]", line) for line in lines
    )

    status = "**ERRORS DETECTED**" if has_errors else "*All stages clean*"
    return f"{status}\n\n```\n{content.strip()}\n```\n"


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def collect_sim_data(sim_dir: Path) -> str:
    """Run all collectors against *sim_dir* and return a Markdown context block.

    Discovers actual files in the Questa/Visualizer output directory (debug.log,
    mti.log, tracker_*.txt, sfi_*.txt, coverage reports, qrun.out/ metadata)
    and reads them with security validation.

    Args:
        sim_dir: Resolved Path to the simulation output directory.

    Returns:
        A Markdown-formatted string with all collected sim data embedded, ready
        to drop into an AI prompt.
    """
    # Discover what files actually exist
    files = _discover_files(sim_dir)

    parts: list[str] = [
        "# Simulation Data\n",
    ]

    # Section 1: Quick error summary from stats_log
    parts.append("\n## Build & Simulation Status\n")
    try:
        parts.append(_collect_stats_summary(sim_dir))
    except Exception as exc:
        parts.append(f"*Error: {type(exc).__name__}: {exc}*\n")

    # Section 2: Test configuration and metadata
    parts.append("\n## Test Configuration & Metadata\n")
    try:
        parts.append(_collect_test_config(sim_dir))
    except Exception as exc:
        parts.append(f"*Error: {type(exc).__name__}: {exc}*\n")

    # Section 3: Main simulation log (debug.log) — errors, UVM summary, tail
    parts.append("\n## Simulation Log (debug.log)\n")
    try:
        parts.append(_collect_debug_log(sim_dir, files))
    except Exception as exc:
        parts.append(f"*Error: {type(exc).__name__}: {exc}*\n")

    # Section 4: MTI/Questa diagnostics (mti.log)
    parts.append("\n## Questa Diagnostics (mti.log)\n")
    try:
        parts.append(_collect_mti_log(sim_dir, files))
    except Exception as exc:
        parts.append(f"*Error: {type(exc).__name__}: {exc}*\n")

    # Section 5: Tracker data (per-component)
    parts.append("\n## Tracker Data (Per-Component Events)\n")
    try:
        parts.append(_collect_tracker_data(sim_dir, files))
    except Exception as exc:
        parts.append(f"*Error: {type(exc).__name__}: {exc}*\n")

    # Section 6: SFI interface data
    parts.append("\n## SFI Interface Data\n")
    try:
        parts.append(_collect_sfi_data(sim_dir, files))
    except Exception as exc:
        parts.append(f"*Error: {type(exc).__name__}: {exc}*\n")

    # Section 7: Coverage report
    parts.append("\n## Coverage Report\n")
    try:
        parts.append(_collect_coverage(sim_dir, files))
    except Exception as exc:
        parts.append(f"*Error: {type(exc).__name__}: {exc}*\n")

    full_text = "\n".join(parts)

    # Sanitize all sensitive paths and PII
    full_text = _sanitize(full_text, sim_dir)

    # Apply overall context cap
    if len(full_text) > _TOTAL_CONTEXT_CAP:
        full_text = full_text[:_TOTAL_CONTEXT_CAP]
        full_text += (
            "\n\n*[Total context truncated at "
            f"{_TOTAL_CONTEXT_CAP // 1000}KB limit]*\n"
        )

    return full_text
