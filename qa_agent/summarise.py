"""qa_agent/summarise.py

Orchestrator for `qa-agent summarise`.

Handles:
  - Provider routing (-claude, future: -openai, -gemini, …)
  - Path resolution: file(s), directory, or pwd (default)
  - Prompt construction for directory mode vs explicit-file mode
  - Building a ProviderRequest and calling provider.stream(request)
  - Pretty ANSI terminal output
  - Centralised error handling

Each provider module must expose:
    PROVIDER_NAME: str
    async def stream(request: ProviderRequest) -> AsyncIterator[str]
        Yields text chunks as the AI streams its response.

See qa_agent/providers.py for the ProviderRequest definition.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import AsyncIterator

from qa_agent.providers import ProviderRequest

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
# Prompts (summarise-specific; providers are unaware of these)
# ─────────────────────────────────────────────────────────────────────────────
_SYSTEM_PROMPT_DIRECTORY = (
    "You are a codebase explainer. "
    "You have access to Glob and Read tools for the current directory only. "
    "Do NOT access paths outside the working directory. "
    "Output ONLY in the following format:\n\n"
    "## Directory Structure\n"
    "<ASCII tree of the directory>\n\n"
    "## File Explanations\n"
    "<For each file: use '### <relative path>' as a heading, then 1–3 sentences "
    "describing its purpose and what it does. Be concise and precise.>"
)

_SYSTEM_PROMPT_FILES = (
    "You are a codebase explainer. "
    "You have access to the Read tool only. "
    "Do NOT access paths outside those explicitly given to you. "
    "Output ONLY in the following format:\n\n"
    "## File Explanations\n"
    "<For each file: use '### <file path>' as a heading, then 1–3 sentences "
    "describing its purpose and what it does. Be concise and precise.>"
)

_USER_PROMPT_DIRECTORY = (
    "Summarise this directory. "
    "First glob all files recursively, then read each one, "
    "and produce the ASCII directory tree followed by per-file explanations."
)


def _user_prompt_files(paths: list[str]) -> str:
    paths_list = "\n".join(f"  - {p}" for p in paths)
    return (
        f"Summarise the following files:\n{paths_list}\n\n"
        "Read each file and produce per-file explanations."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Path resolution
# ─────────────────────────────────────────────────────────────────────────────
def _resolve_paths(raw_paths: list[str]) -> tuple[list[str], str]:
    """Resolve CLI path arguments to absolute paths and a human-readable label.

    Returns:
        (abs_paths, label)
        abs_paths — list of absolute paths (files or dirs) to summarise.
                    Empty list signals "use cwd as directory".
        label     — string for display in the banner.
    """
    cwd = os.getcwd()

    if not raw_paths:
        return [], cwd

    abs_paths: list[str] = []
    for p in raw_paths:
        abs_p = p if os.path.isabs(p) else os.path.join(cwd, p)
        abs_p = os.path.normpath(abs_p)
        if not os.path.exists(abs_p):
            _print_error(f"Path not found: {p!r}")
            sys.exit(1)
        abs_paths.append(abs_p)

    if len(abs_paths) == 1:
        label = abs_paths[0]
    else:
        label = f"{len(abs_paths)} files"

    return abs_paths, label


# ─────────────────────────────────────────────────────────────────────────────
# Request builder
# ─────────────────────────────────────────────────────────────────────────────
def _build_request(cwd: str, abs_paths: list[str]) -> ProviderRequest:
    """Construct a ProviderRequest from resolved paths.

    Directory mode — triggered when paths is empty or a single directory:
        Uses Glob + Read tools; agent cwd is the target directory.

    File mode — triggered when paths contains one or more file paths:
        Uses Read tool only; agent cwd is the original working directory.
    """
    if not abs_paths or (len(abs_paths) == 1 and os.path.isdir(abs_paths[0])):
        target_dir = abs_paths[0] if abs_paths else cwd
        return ProviderRequest(
            system_prompt=_SYSTEM_PROMPT_DIRECTORY,
            user_prompt=_USER_PROMPT_DIRECTORY,
            agent_cwd=target_dir,
            allowed_tools=["Glob", "Read"],
        )
    else:
        return ProviderRequest(
            system_prompt=_SYSTEM_PROMPT_FILES,
            user_prompt=_user_prompt_files(abs_paths),
            agent_cwd=cwd,
            allowed_tools=["Read"],
        )


# ─────────────────────────────────────────────────────────────────────────────
# Provider registry
# ─────────────────────────────────────────────────────────────────────────────
def _get_provider(name: str):
    """Return the provider module for the given name."""
    if name == "claude":
        from qa_agent import claude_provider  # type: ignore
        return claude_provider
    if name == "openai":
        from qa_agent import openai_provider  # type: ignore
        return openai_provider
    if name == "gemini":
        from qa_agent import gemini_provider  # type: ignore
        return gemini_provider

    _print_error(
        f"Unknown provider: '{name}'\n"
        f"  Available providers: claude, openai, gemini"
    )
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# Streaming output renderer
# ─────────────────────────────────────────────────────────────────────────────
async def _render_stream(gen: AsyncIterator[str]) -> None:
    """Consume the provider's async generator and pretty-print the output."""
    buffer = ""

    async for chunk in gen:
        buffer += chunk
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            _render_line(line)

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
    cwd = os.getcwd()
    abs_paths, label = _resolve_paths(paths)
    provider = _get_provider(provider_name)
    request = _build_request(cwd, abs_paths)

    _print_banner(label, provider.PROVIDER_NAME)
    print(f"  {dim('Analysing …')}\n")

    await _render_stream(provider.stream(request))
    _print_success()


def run(provider: str = "claude", paths: list[str] | None = None) -> None:
    """Sync entry point called from cli.py."""
    # Import Claude SDK error types — only relevant when using Claude provider.
    # Other providers surface errors as RuntimeError or built-in exceptions.
    _claude_sdk_errors: tuple = ()
    CLINotFoundError = CLIConnectionError = ProcessError = CLIJSONDecodeError = None
    if provider == "claude":
        try:
            from claude_agent_sdk import (  # type: ignore
                CLINotFoundError,
                CLIConnectionError,
                ProcessError,
                CLIJSONDecodeError,
            )
            _claude_sdk_errors = (CLINotFoundError, CLIConnectionError, ProcessError, CLIJSONDecodeError)  # type: ignore
        except ImportError:
            _print_error(
                "Claude Agent SDK is not installed.\n"
                "  Run:  pip install claude-agent-sdk"
            )
            sys.exit(1)

    try:
        asyncio.run(_run_async(provider, paths or []))
    except RuntimeError as exc:
        _print_error(str(exc))
        sys.exit(1)
    except BaseException as exc:  # pylint: disable=broad-except
        if isinstance(exc, KeyboardInterrupt):
            print(f"\n  {yellow('⚠')}  Interrupted.\n", file=sys.stderr)
            sys.exit(1)
        # Re-raise and handle Claude SDK-specific errors
        if CLINotFoundError and isinstance(exc, CLINotFoundError):  # type: ignore
            _print_error(
                "Claude Code CLI not found.\n"
                "  Install: npm install -g @anthropic-ai/claude-code\n"
                "  Or set:  ANTHROPIC_API_KEY=sk-ant-..."
            )
            sys.exit(1)
        if CLIConnectionError and isinstance(exc, CLIConnectionError):  # type: ignore
            _print_error(f"Connection to Claude Code failed.\n  {exc}")
            sys.exit(1)
        if ProcessError and isinstance(exc, ProcessError):  # type: ignore
            _print_error(f"Agent process failed (exit {exc.exit_code}).\n  {exc}")  # type: ignore
            sys.exit(1)
        if CLIJSONDecodeError and isinstance(exc, CLIJSONDecodeError):  # type: ignore
            _print_error(f"Unexpected SDK response.\n  {exc}")
            sys.exit(1)
        _print_error(f"Unexpected error: {exc}")
        sys.exit(1)
