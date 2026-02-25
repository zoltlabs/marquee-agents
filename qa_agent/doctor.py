"""qa_agent/doctor.py

Environment health checker for `qa-agent doctor`.

Validates that every dependency and auth credential needed by `qa-agent`
is correctly set up before a real command is attempted.

Public API:
    run(verbose: bool = False) -> None
"""

from __future__ import annotations

import importlib.metadata
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from qa_agent.output import (
    bold, cyan, dim, green, red, yellow, print_doctor_banner, rule,
)


# ─────────────────────────────────────────────────────────────────────────────
# Check result types
# ─────────────────────────────────────────────────────────────────────────────

class Status(Enum):
    OK    = "ok"
    WARN  = "warn"
    ERROR = "error"


@dataclass
class CheckResult:
    label:  str           # Short display label, e.g. "ANTHROPIC_API_KEY"
    status: Status
    detail: str           # One-line human message, e.g. "set" / "not set"
    fix:    str = ""      # Optional fix instruction printed indented below detail
    raw:    str = ""      # Raw value printed in verbose mode


# ─────────────────────────────────────────────────────────────────────────────
# Individual checks
# ─────────────────────────────────────────────────────────────────────────────

def check_python_version() -> list[CheckResult]:
    info = sys.version_info
    version_str = f"Python {info.major}.{info.minor}.{info.micro}"
    if info >= (3, 10):
        return [CheckResult(
            label=version_str, status=Status.OK, detail="≥ 3.10 required",
            raw=sys.executable,
        )]
    return [CheckResult(
        label=version_str, status=Status.ERROR,
        detail="Python ≥ 3.10 is required",
        fix="Upgrade to Python ≥ 3.10",
        raw=sys.executable,
    )]


def check_claude() -> list[CheckResult]:
    results: list[CheckResult] = []

    # SDK presence
    try:
        ver = importlib.metadata.version("claude-agent-sdk")
        sdk_ok = True
        results.append(CheckResult(
            label="Claude SDK", status=Status.OK,
            detail=f"claude-agent-sdk {ver} installed",
            raw=ver,
        ))
    except importlib.metadata.PackageNotFoundError:
        sdk_ok = False
        results.append(CheckResult(
            label="Claude SDK", status=Status.ERROR,
            detail="claude-agent-sdk not installed",
            fix="pip install claude-agent-sdk",
        ))

    if not sdk_ok:
        return results

    # Auth check
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if api_key:
        masked = api_key[:8] + "…" if len(api_key) > 8 else api_key
        results.append(CheckResult(
            label="ANTHROPIC_API_KEY", status=Status.OK,
            detail="set", raw=masked,
        ))
    elif shutil.which("claude") is not None:
        results.append(CheckResult(
            label="ANTHROPIC_API_KEY", status=Status.WARN,
            detail="not set — Claude Code CLI login detected",
            raw="(CLI OAuth)",
        ))
    else:
        results.append(CheckResult(
            label="ANTHROPIC_API_KEY", status=Status.ERROR,
            detail="not set",
            fix=(
                "export ANTHROPIC_API_KEY=sk-ant-...\n"
                "            → OR:  npm install -g @anthropic-ai/claude-code && claude login"
            ),
        ))

    return results


def check_openai() -> list[CheckResult]:
    results: list[CheckResult] = []

    # SDK presence
    try:
        ver = importlib.metadata.version("openai")
        sdk_ok = True
        results.append(CheckResult(
            label="OpenAI SDK", status=Status.OK,
            detail=f"openai {ver} installed",
            raw=ver,
        ))
    except importlib.metadata.PackageNotFoundError:
        sdk_ok = False
        results.append(CheckResult(
            label="OpenAI SDK", status=Status.ERROR,
            detail="openai not installed",
            fix="pip install openai",
        ))

    if not sdk_ok:
        return results

    # Auth check
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if api_key:
        masked = api_key[:8] + "…" if len(api_key) > 8 else api_key
        results.append(CheckResult(
            label="OPENAI_API_KEY", status=Status.OK,
            detail="set", raw=masked,
        ))
    elif shutil.which("codex") is not None:
        results.append(CheckResult(
            label="OPENAI_API_KEY", status=Status.WARN,
            detail="not set — Codex CLI login detected",
            raw="(CLI OAuth)",
        ))
    else:
        results.append(CheckResult(
            label="OPENAI_API_KEY", status=Status.ERROR,
            detail="not set",
            fix=(
                "export OPENAI_API_KEY=sk-...\n"
                "            → OR:  npm install -g @openai/codex && codex login"
            ),
        ))

    return results


def check_gemini() -> list[CheckResult]:
    results: list[CheckResult] = []

    # SDK presence
    try:
        ver = importlib.metadata.version("google-genai")
        sdk_ok = True
        results.append(CheckResult(
            label="Gemini SDK", status=Status.OK,
            detail=f"google-genai {ver} installed",
            raw=ver,
        ))
    except importlib.metadata.PackageNotFoundError:
        sdk_ok = False
        results.append(CheckResult(
            label="Gemini SDK", status=Status.ERROR,
            detail="google-genai not installed",
            fix="pip install google-genai",
        ))

    if not sdk_ok:
        return results

    # Auth check — Gemini API key
    api_key = (
        os.environ.get("GEMINI_API_KEY", "").strip()
        or os.environ.get("GOOGLE_API_KEY", "").strip()
    )
    if api_key:
        masked = api_key[:8] + "…" if len(api_key) > 8 else api_key
        results.append(CheckResult(
            label="GEMINI_API_KEY", status=Status.OK,
            detail="set", raw=masked,
        ))
    else:
        results.append(CheckResult(
            label="GEMINI_API_KEY", status=Status.WARN if _gcloud_ok() else Status.ERROR,
            detail="not set" + (" — gcloud ADC detected" if _gcloud_ok() else ""),
            fix=(
                "export GEMINI_API_KEY=AIza...\n"
                "            → OR:  gcloud auth application-default login"
            ) if not _gcloud_ok() else "",
        ))

    # Vertex AI check
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
    if project:
        results.append(CheckResult(
            label="GOOGLE_CLOUD_PROJECT", status=Status.OK,
            detail="set", raw=project,
        ))
    elif _gcloud_ok():
        results.append(CheckResult(
            label="GOOGLE_CLOUD_PROJECT", status=Status.WARN,
            detail="not set (optional for Vertex AI)",
            fix="export GOOGLE_CLOUD_PROJECT=your-project",
        ))

    return results


def _gcloud_ok() -> bool:
    return shutil.which("gcloud") is not None


def check_log_dir() -> list[CheckResult]:
    try:
        from qa_agent.session_log import _log_dir
        log_dir = _log_dir()
    except Exception:
        return [CheckResult(
            label="Log directory", status=Status.ERROR,
            detail="Could not determine log directory",
        )]

    if log_dir.exists():
        # Get disk usage with `du -sh`, fall back to manual count
        try:
            result = subprocess.run(
                ["du", "-sh", str(log_dir)],
                capture_output=True, text=True, timeout=5,
            )
            size = result.stdout.split()[0] if result.returncode == 0 else "?"
        except Exception:
            size = "?"
        return [CheckResult(
            label="Log directory", status=Status.OK,
            detail=f"{log_dir}  ({size} used)",
            raw=str(log_dir),
        )]
    else:
        return [CheckResult(
            label="Log directory", status=Status.WARN,
            detail=f"{log_dir}  (will be created on first debug/crash run)",
            raw=str(log_dir),
        )]


# ─────────────────────────────────────────────────────────────────────────────
# Sections registry
# ─────────────────────────────────────────────────────────────────────────────

SECTIONS: list[tuple[str, list[Callable[[], list[CheckResult]]]]] = [
    ("Runtime",    [check_python_version]),
    ("Providers",  [check_claude, check_openai, check_gemini]),
    ("Log system", [check_log_dir]),
]


# ─────────────────────────────────────────────────────────────────────────────
# Renderer
# ─────────────────────────────────────────────────────────────────────────────

def _status_icon(status: Status) -> str:
    if status == Status.OK:
        return green("✓")
    if status == Status.WARN:
        return yellow("⚠")
    return red("✗")


def _print_section(title: str, results: list[CheckResult], verbose: bool) -> tuple[int, int]:
    """Print one section; return (errors, warnings) counts."""
    errors = warnings = 0
    print(f"  {bold(title)}")
    for r in results:
        icon = _status_icon(r.status)
        label_field = f"{r.label:<30}" if len(r.label) < 30 else r.label
        raw_suffix = f"  {dim(r.raw)}" if verbose and r.raw else ""
        print(f"    {icon}  {label_field}  {dim(r.detail)}{raw_suffix}")
        if r.fix:
            for fix_line in r.fix.splitlines():
                print(f"          {cyan('→')} {fix_line}")
        if r.status == Status.ERROR:
            errors += 1
        elif r.status == Status.WARN:
            warnings += 1
    print()
    return errors, warnings


def _print_summary(errors: int, warnings: int) -> None:
    print(rule())
    parts: list[str] = []
    if errors:
        parts.append(red(f"{errors} error{'s' if errors != 1 else ''}"))
    if warnings:
        parts.append(yellow(f"{warnings} warning{'s' if warnings != 1 else ''}"))
    if not parts:
        parts.append(green("all checks passed"))
    print(f"  {' · '.join(parts)}")
    print(rule())
    print()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def run(verbose: bool = False) -> None:
    """Entry point called from cli.py."""
    print_doctor_banner()

    total_errors = total_warnings = 0

    for section_title, check_fns in SECTIONS:
        section_results: list[CheckResult] = []
        for fn in check_fns:
            section_results.extend(fn())

        errors, warnings = _print_section(section_title, section_results, verbose)
        total_errors += errors
        total_warnings += warnings

    _print_summary(total_errors, total_warnings)

    if total_errors:
        sys.exit(1)
