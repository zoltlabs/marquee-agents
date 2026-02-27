"""qa_agent/summarise.py

Orchestrator for `qa-agent summarise`.

Handles:
  - Provider routing (--provider / -p  {claude, openai, gemini})
  - Path resolution: file(s), directory, or pwd (default)
  - Prompt construction for directory mode vs explicit-file mode
  - Building a ProviderRequest and calling provider.stream(request)
  - Pretty ANSI terminal output (via qa_agent.output)
  - Centralised error handling (via qa_agent.errors)

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
from typing import TYPE_CHECKING, AsyncIterator

from qa_agent.output import print_header, print_footer, render_line, dim, console
from qa_agent.providers import ProviderRequest

if TYPE_CHECKING:
    from qa_agent.session_log import SessionLog


# ─────────────────────────────────────────────────────────────────────────────
# Provider capability flags
# ─────────────────────────────────────────────────────────────────────────────
# ⚠ SECURITY: No providers are granted direct filesystem access via SDK tools.
# All file content is collected by this module (the Python agent) and inlined
# into the prompt. This ensures the AI model only ever sees files that the
# orchestrator explicitly chooses to send — it cannot glob, read, or traverse
# the disk on its own.
#
# Previously "claude" was listed here to use its Glob + Read tools, but that
# granted the model unbounded read access to the filesystem from agent_cwd.
# All providers now use the inline (non-agentic) path exclusively.
_AGENTIC_PROVIDERS: set[str] = set()  # intentionally empty — see note above


# ─────────────────────────────────────────────────────────────────────────────
# Prompts (summarise-specific; providers are unaware of these)
# ─────────────────────────────────────────────────────────────────────────────

# ── Agentic variants (Claude) — model reads files via tools ──────────────────
_SYSTEM_PROMPT_DIRECTORY_AGENTIC = (
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

_USER_PROMPT_DIRECTORY_AGENTIC = (
    "Summarise this directory. "
    "First glob all files recursively, then read each one, "
    "and produce the ASCII directory tree followed by per-file explanations."
)

_SYSTEM_PROMPT_FILES_AGENTIC = (
    "You are a codebase explainer. "
    "You have access to the Read tool only. "
    "Do NOT access paths outside those explicitly given to you. "
    "Output ONLY in the following format:\n\n"
    "## File Explanations\n"
    "<For each file: use '### <file path>' as a heading, then 1–3 sentences "
    "describing its purpose and what it does. Be concise and precise.>"
)

# ── Inline variants (Gemini, OpenAI) — file content embedded in the prompt ───
_SYSTEM_PROMPT_INLINE = (
    "You are a codebase explainer. "
    "The user will provide the full content of every file below. "
    "Base your answer ONLY on the files provided — do not invent or assume any"
    " files that are not shown. "
    "Output ONLY in the following format:\n\n"
    "## Directory Structure\n"
    "<ASCII tree built from the file list below>\n\n"
    "## File Explanations\n"
    "<For each file: use '### <relative path>' as a heading, then 1–3 sentences "
    "describing its purpose and what it does. Be concise and precise.>"
)

_SYSTEM_PROMPT_INLINE_FILES = (
    "You are a codebase explainer. "
    "The user will provide the full content of every file below. "
    "Base your answer ONLY on the files provided — do not invent or assume any"
    " files that are not shown. "
    "Output ONLY in the following format:\n\n"
    "## File Explanations\n"
    "<For each file: use '### <file path>' as a heading, then 1–3 sentences "
    "describing its purpose and what it does. Be concise and precise.>"
)


# ─────────────────────────────────────────────────────────────────────────────
# File reading helpers (for non-agentic providers)
# ─────────────────────────────────────────────────────────────────────────────

# File extensions to skip when reading inline (binary / generated / large).
_SKIP_EXTENSIONS = {
    ".pyc", ".pyo", ".so", ".dylib", ".dll", ".exe", ".bin",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
    ".zip", ".tar", ".gz", ".bz2", ".whl",
    ".lock",
}

# Skip these directory names entirely.
_SKIP_DIRS = {
    "__pycache__", ".git", ".svn", ".hg",
    ".venv", "venv", "env", "node_modules",
    ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "dist", "build", "*.egg-info",
}

_MAX_FILE_BYTES = 64 * 1024  # 64 KB per file — truncate larger files


def _read_file_safe(path: str) -> str:
    """Read a text file, truncating at _MAX_FILE_BYTES. Returns empty string on error."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(_MAX_FILE_BYTES)
        if os.path.getsize(path) > _MAX_FILE_BYTES:
            content += "\n... [truncated] ..."
        return content
    except OSError:
        return ""


def _collect_dir_files(root: str) -> list[tuple[str, str]]:
    """Walk *root* recursively and return [(rel_path, content), …].

    Skips binary extensions, hidden dirs, and virtualenv dirs.
    """
    results: list[tuple[str, str]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune skip-dirs in-place so os.walk doesn't descend into them.
        dirnames[:] = [
            d for d in dirnames
            if d not in _SKIP_DIRS and not d.startswith(".")
        ]
        for fname in sorted(filenames):
            ext = os.path.splitext(fname)[1].lower()
            if ext in _SKIP_EXTENSIONS or fname.startswith("."):
                continue
            abs_path = os.path.join(dirpath, fname)
            rel_path = os.path.relpath(abs_path, root)
            content = _read_file_safe(abs_path)
            results.append((rel_path, content))
    return results


def _build_inline_prompt(root: str, files: list[tuple[str, str]]) -> str:
    """Build a user prompt with the full file tree and content embedded."""
    lines: list[str] = [f"Directory: {root}\n"]
    lines.append("Files provided:\n")
    for rel_path, _ in files:
        lines.append(f"  {rel_path}")
    lines.append("")
    for rel_path, content in files:
        lines.append(f"\n=== {rel_path} ===\n{content}")
    return "\n".join(lines)


def _build_inline_files_prompt(files: list[tuple[str, str]]) -> str:
    """Build a user prompt embedding explicit file contents."""
    lines: list[str] = []
    for path, content in files:
        lines.append(f"=== {path} ===\n{content}")
    return "\n\n".join(lines)


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
    from qa_agent.errors import PathError

    cwd = os.getcwd()

    if not raw_paths:
        return [], cwd

    abs_paths: list[str] = []
    for p in raw_paths:
        abs_p = p if os.path.isabs(p) else os.path.join(cwd, p)
        abs_p = os.path.normpath(abs_p)
        if not os.path.exists(abs_p):
            raise PathError(f"Path not found: {p!r}")
        abs_paths.append(abs_p)

    if len(abs_paths) == 1:
        label = abs_paths[0]
    else:
        label = f"{len(abs_paths)} files"

    return abs_paths, label


# ─────────────────────────────────────────────────────────────────────────────
# Request builder
# ─────────────────────────────────────────────────────────────────────────────
def _build_request(
    cwd: str,
    abs_paths: list[str],
    *,
    provider_name: str,
    verbose: bool = False,
) -> ProviderRequest:
    """Construct a ProviderRequest from resolved paths.

    Agentic providers (Claude) receive a short tool-call prompt and the SDK
    will use Glob + Read to explore the filesystem itself.

    Non-agentic providers (Gemini, OpenAI) receive the full file contents
    inlined into the prompt so they cannot hallucinate files.
    """
    extra: dict = {"verbose": verbose}
    is_agentic = provider_name in _AGENTIC_PROVIDERS
    is_dir_mode = not abs_paths or (len(abs_paths) == 1 and os.path.isdir(abs_paths[0]))

    if is_agentic:
        # ── Claude: let the SDK handle file access ────────────────────────────
        if is_dir_mode:
            target_dir = abs_paths[0] if abs_paths else cwd
            return ProviderRequest(
                system_prompt=_SYSTEM_PROMPT_DIRECTORY_AGENTIC,
                user_prompt=_USER_PROMPT_DIRECTORY_AGENTIC,
                agent_cwd=target_dir,
                allowed_tools=["Glob", "Read"],
                extra=extra,
            )
        else:
            return ProviderRequest(
                system_prompt=_SYSTEM_PROMPT_FILES_AGENTIC,
                user_prompt=(
                    "Summarise the following files:\n"
                    + "\n".join(f"  - {p}" for p in abs_paths)
                    + "\n\nRead each file and produce per-file explanations."
                ),
                agent_cwd=cwd,
                allowed_tools=["Read"],
                extra=extra,
            )
    else:
        # ── Gemini / OpenAI: inline all file content in the prompt ────────────
        if is_dir_mode:
            target_dir = abs_paths[0] if abs_paths else cwd
            files = _collect_dir_files(target_dir)
            user_prompt = _build_inline_prompt(target_dir, files)
            return ProviderRequest(
                system_prompt=_SYSTEM_PROMPT_INLINE,
                user_prompt=user_prompt,
                agent_cwd=target_dir,
                allowed_tools=[],
                extra=extra,
            )
        else:
            files = [(p, _read_file_safe(p)) for p in abs_paths]
            user_prompt = _build_inline_files_prompt(files)
            return ProviderRequest(
                system_prompt=_SYSTEM_PROMPT_INLINE_FILES,
                user_prompt=user_prompt,
                agent_cwd=cwd,
                allowed_tools=[],
                extra=extra,
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

    from qa_agent.errors import ConfigError
    raise ConfigError(
        f"Unknown provider: '{name}'\n"
        f"  Available providers: claude, openai, gemini"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Streaming output renderer
# ─────────────────────────────────────────────────────────────────────────────
async def _render_stream(gen: AsyncIterator[str], log) -> None:
    """Consume the provider's async generator and pretty-print the output."""
    buffer = ""

    async for chunk in gen:
        log.chunk(chunk)
        buffer += chunk
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            render_line(line)

    if buffer:
        render_line(buffer)


# ─────────────────────────────────────────────────────────────────────────────
# Async entry point
# ─────────────────────────────────────────────────────────────────────────────
async def _run_async(
    provider_name: str,
    paths: list[str],
    *,
    verbose: bool,
    log,
) -> None:
    cwd = os.getcwd()
    abs_paths, label = _resolve_paths(paths)
    provider = _get_provider(provider_name)
    request = _build_request(cwd, abs_paths, provider_name=provider_name, verbose=verbose)

    log.event("provider_selected", provider=provider_name)

    subtitle = f"{provider.PROVIDER_NAME}  ·  {label}"
    print_header("summarise", subtitle)

    with console.status(f"Analysing with {provider.PROVIDER_NAME}...", spinner="dots"):
        # Collect first chunk inside the spinner then stream the rest
        gen = provider.stream(request)
        first_chunk = None
        async for chunk in gen:
            log.chunk(chunk)
            first_chunk = chunk
            break

    # Spinner has exited — start printing
    if first_chunk is not None:
        print()
        # Process first chunk through renderer
        buffer = first_chunk
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            render_line(line)

        # Stream the rest
        async for chunk in gen:
            log.chunk(chunk)
            buffer += chunk
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                render_line(line)

        if buffer:
            render_line(buffer)

    log.event("stream_complete")
    print_footer("Summary complete.")


# ─────────────────────────────────────────────────────────────────────────────
# Sync entry point (called from cli.py)
# ─────────────────────────────────────────────────────────────────────────────
def run(
    provider: str = "claude",
    paths: list[str] | None = None,
    *,
    verbose: bool = False,
    log=None,
) -> None:
    """Sync entry point called from cli.py."""
    from qa_agent.errors import handle_exception
    from qa_agent.session_log import _NullLog

    if log is None:
        log = _NullLog()

    try:
        asyncio.run(_run_async(provider, paths or [], verbose=verbose, log=log))
    except SystemExit:
        raise
    except Exception as exc:
        exit_code = handle_exception(exc, provider=provider, verbose=verbose, log=log)
        sys.exit(exit_code)
