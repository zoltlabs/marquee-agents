"""qa_agent/errors.py

qa-agent error hierarchy and centralised exception handler.

Raise QAAgentError subclasses from anywhere in the codebase.
Call handle_exception(exc, provider) at the top-level dispatch layer.
"""

from __future__ import annotations

import sys
import traceback


# ─────────────────────────────────────────────────────────────────────────────
# Exception hierarchy
# ─────────────────────────────────────────────────────────────────────────────

class QAAgentError(Exception):
    """Base for all qa-agent errors. Always carries a user-readable message."""
    exit_code: int = 1


class ProviderAuthError(QAAgentError):
    """Missing or invalid credentials for a provider."""


class ProviderConnectionError(QAAgentError):
    """Network or process-level failure reaching a provider."""


class ProviderResponseError(QAAgentError):
    """Provider returned an unexpected / malformed response."""


class PathError(QAAgentError):
    """File or directory argument does not exist or is not accessible."""


class ConfigError(QAAgentError):
    """Invalid or missing configuration."""


# ─────────────────────────────────────────────────────────────────────────────
# Central handler
# ─────────────────────────────────────────────────────────────────────────────

def handle_exception(
    exc: BaseException,
    provider: str | None = None,
    *,
    verbose: bool = False,
    log: object = None,
) -> int:
    """Map any exception to a user-friendly error message and return an exit code.

    Args:
        exc:      The exception to handle.
        provider: Name of the active provider (used for auth tips), or None.
        verbose:  If True, print the full Python traceback to stderr.
        log:      Optional SessionLog instance — error is written there if given.

    Returns:
        An integer exit code (caller should pass to sys.exit).
    """
    from qa_agent.output import print_rich_error, yellow

    # ── Write to session log if one is active ────────────────────────────────
    if log is not None:
        try:
            log.error(exc)
        except Exception:
            pass

    # ── Verbose: always print full traceback to stderr ───────────────────────
    if verbose:
        traceback.print_exc(file=sys.stderr)

    # ── Keyboard interrupt ────────────────────────────────────────────────────
    if isinstance(exc, KeyboardInterrupt):
        print(f"\n  {yellow('⚠')}  Interrupted.\n", file=sys.stderr)
        return 1

    # ── Our own error hierarchy ───────────────────────────────────────────────
    if isinstance(exc, ProviderAuthError):
        tip = _auth_tip(provider)
        msg = str(exc)
        if tip:
            msg = f"{msg}\n{tip}"
        print_rich_error(msg)
        return 1

    if isinstance(exc, ProviderConnectionError):
        print_rich_error(str(exc))
        return 1

    if isinstance(exc, QAAgentError):
        print_rich_error(str(exc))
        return exc.exit_code

    # ── Claude Agent SDK errors (duck-typed to avoid hard import) ─────────────
    exc_type_name = type(exc).__name__

    if exc_type_name == "CLINotFoundError":
        print_rich_error(
            "Claude Code CLI not found.\n"
            "  Install: npm install -g @anthropic-ai/claude-code\n"
            "  Or set:  ANTHROPIC_API_KEY=sk-ant-..."
        )
        return 1

    if exc_type_name == "CLIConnectionError":
        print_rich_error(f"Connection to Claude Code failed.\n  {exc}")
        return 1

    if exc_type_name == "ProcessError":
        exit_code = getattr(exc, "exit_code", 1)
        print_rich_error(f"Agent process failed (exit {exit_code}).\n  {exc}")
        return 1

    if exc_type_name == "CLIJSONDecodeError":
        print_rich_error(f"Unexpected SDK response.\n  {exc}")
        return 1

    # ── Generic runtime errors ────────────────────────────────────────────────
    if isinstance(exc, RuntimeError):
        print_rich_error(str(exc))
        return 1

    # ── Catch-all — unexpected error ──────────────────────────────────────────
    log_hint = ""
    if log is not None:
        try:
            log_hint = f"\n  Session log: {log.path}"
        except AttributeError:
            pass
    print_rich_error(
        f"Unexpected error: {type(exc).__name__}: {exc}"
        + (log_hint or "\n  Re-run with --verbose for a full traceback.")
    )
    return 2


# ─────────────────────────────────────────────────────────────────────────────
# Provider-specific auth tips
# ─────────────────────────────────────────────────────────────────────────────

def _auth_tip(provider: str | None) -> str:
    """Return a one-para setup tip for the given provider, or empty string."""
    if provider == "claude":
        return (
            "  Option 1 — API key:\n"
            "    export ANTHROPIC_API_KEY=sk-ant-...\n\n"
            "  Option 2 — Claude Code CLI OAuth:\n"
            "    npm install -g @anthropic-ai/claude-code && claude login"
        )
    if provider == "openai":
        return (
            "  Option 1 — API key:\n"
            "    export OPENAI_API_KEY=sk-...\n\n"
            "  Option 2 — Codex CLI OAuth:\n"
            "    npm install -g @openai/codex && codex login"
        )
    if provider == "gemini":
        return (
            "  Option 1 — Gemini API key:\n"
            "    export GEMINI_API_KEY=AIza...\n\n"
            "  Option 2 — Vertex AI ADC:\n"
            "    gcloud auth application-default login\n"
            "    export GOOGLE_CLOUD_PROJECT=your-project"
        )
    return ""
