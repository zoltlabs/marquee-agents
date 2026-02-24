"""qa_agent/summarise.py

Orchestrator for `qa-agent summarise`.

Handles:
  - Provider routing (-claude, future: -openai, -gemini, …)
  - Path resolution: file(s), directory, or pwd (default)
  - Pretty ANSI terminal output
  - Error display

Each provider module must expose:
    async def stream(cwd: str, paths: list[str]) -> AsyncIterator[str]
        Yields text chunks as the AI streams its response.
        `paths` is a list of absolute paths to files/dirs to summarise.
        When it contains a single directory, the agent explores that dir.
        When it contains one or more files, the agent reads exactly those.
    PROVIDER_NAME: str
        Display name for the provider.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import AsyncIterator

# ─────────────────────────────────────────────────────────────────────────────
# ANSI helpers
# ─────────────────────────────────────────────────────────────────────────────
_USE_COLOR = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    """Wrap text in an ANSI escape code (no-op if not a TTY)."""
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text


def bold(t: str) -> str:       return _c("1", t)
def cyan(t: str) -> str:       return _c("1;36", t)
def green(t: str) -> str:      return _c("1;32", t)
def yellow(t: str) -> str:     return _c("1;33", t)
def red(t: str) -> str:        return _c("1;31", t)
def dim(t: str) -> str:        return _c("2", t)
def magenta(t: str) -> str:    return _c("1;35", t)


def _rule(char: str = "─", width: int = 60) -> str:
    return dim(char * width)


def _print_banner(target_label: str, provider_name: str) -> None:
    print()
    print(_rule())
    print(f"  {cyan('qa-agent summarise')}  {dim('·')}  {magenta(provider_name)}")
    print(f"  {dim('Target:')} {bold(target_label)}")
    print(_rule())
    print()


def _print_success() -> None:
    print()
    print(_rule())
    print(f"  {green('✓')} {bold('Summary complete.')}")
    print(_rule())
    print()


def _print_error(msg: str) -> None:
    print()
    print(_rule("─", 60))
    for line in msg.strip().splitlines():
        print(f"  {red('✗')} {line}")
    print(_rule("─", 60))
    print()


# ─────────────────────────────────────────────────────────────────────────────
# Path resolution
# ─────────────────────────────────────────────────────────────────────────────
def _resolve_paths(raw_paths: list[str]) -> tuple[list[str], str]:
    """
    Resolve CLI path arguments to absolute paths and a human-readable label.

    Returns:
        (abs_paths, label)
        abs_paths — list of absolute paths (files or dirs) to summarise.
                    Empty list signals "use cwd as directory".
        label     — string for display in the banner.
    """
    cwd = os.getcwd()

    if not raw_paths:
        # No args: summarise pwd as a directory
        return [], cwd

    abs_paths: list[str] = []
    for p in raw_paths:
        abs_p = p if os.path.isabs(p) else os.path.join(cwd, p)
        abs_p = os.path.normpath(abs_p)
        if not os.path.exists(abs_p):
            _print_error(f"Path not found: {p!r}")
            sys.exit(1)
        abs_paths.append(abs_p)

    if len(abs_paths) == 1 and os.path.isdir(abs_paths[0]):
        label = abs_paths[0]
    elif len(abs_paths) == 1:
        label = abs_paths[0]
    else:
        label = f"{len(abs_paths)} files"

    return abs_paths, label


# ─────────────────────────────────────────────────────────────────────────────
# Provider registry
# ─────────────────────────────────────────────────────────────────────────────
def _get_provider(name: str):
    """Return the provider module for the given name."""
    if name == "claude":
        from qa_agent import claude_summariser  # type: ignore
        return claude_summariser

    _print_error(
        f"Unknown provider: '{name}'\n"
        f"  Available providers: claude"
    )
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# Streaming output renderer
# ─────────────────────────────────────────────────────────────────────────────
async def _render_stream(gen: AsyncIterator[str]) -> None:
    """Consume the provider's async generator and pretty-print the output."""
    in_header = False
    buffer = ""

    async for chunk in gen:
        buffer += chunk
        # Flush line by line so we can colour markdown headers
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            _render_line(line)
            in_header = line.startswith("#")

    # Flush remainder
    if buffer:
        _render_line(buffer)


def _render_line(line: str) -> None:
    """Apply light ANSI colour to markdown section headers; pass rest through."""
    if line.startswith("## "):
        print(f"\n{cyan(bold(line))}")
    elif line.startswith("### "):
        print(f"\n{bold(line)}")
    elif line.startswith("#### "):
        print(f"{yellow(line)}")
    else:
        print(line)


# ─────────────────────────────────────────────────────────────────────────────
# Main entry points
# ─────────────────────────────────────────────────────────────────────────────
async def _run_async(provider_name: str, paths: list[str]) -> None:
    abs_paths, label = _resolve_paths(paths)
    cwd = os.getcwd()
    provider = _get_provider(provider_name)

    _print_banner(label, provider.PROVIDER_NAME)

    print(f"  {dim('Analysing …')}\n")

    await _render_stream(provider.stream(cwd=cwd, paths=abs_paths))
    _print_success()


def run(provider: str = "claude", paths: list[str] | None = None) -> None:
    """Sync entry point called from cli.py."""
    try:
        from claude_agent_sdk import (  # noqa: F401  # type: ignore
            CLINotFoundError,
            CLIConnectionError,
            ProcessError,
            CLIJSONDecodeError,
        )
    except ImportError:
        _print_error(
            "Claude Agent SDK is not installed.\n"
            "  Run:  pip install claude-agent-sdk"
        )
        sys.exit(1)

    try:
        asyncio.run(_run_async(provider, paths or []))
    except RuntimeError as exc:
        # Auth errors surfaced from resolve_auth()
        _print_error(str(exc))
        sys.exit(1)
    except CLINotFoundError:
        _print_error(
            "Claude Code CLI not found.\n"
            "  Install: npm install -g @anthropic-ai/claude-code\n"
            "  Or set:  ANTHROPIC_API_KEY=sk-ant-..."
        )
        sys.exit(1)
    except CLIConnectionError as exc:
        _print_error(f"Connection to Claude Code failed.\n  {exc}")
        sys.exit(1)
    except ProcessError as exc:
        _print_error(
            f"Agent process failed (exit {exc.exit_code}).\n  {exc}"
        )
        sys.exit(1)
    except CLIJSONDecodeError as exc:
        _print_error(f"Unexpected SDK response.\n  {exc}")
        sys.exit(1)
    except KeyboardInterrupt:
        print(f"\n  {yellow('⚠')}  Interrupted.\n", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:  # pylint: disable=broad-except
        _print_error(f"Unexpected error: {exc}")
        sys.exit(1)
