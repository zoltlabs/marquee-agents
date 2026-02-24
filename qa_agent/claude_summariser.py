"""qa_agent/claude_summariser.py

Claude Agent SDK provider for `qa-agent summarise`.

Exposes the standard provider interface consumed by summarise.py:
    PROVIDER_NAME  — display name
    stream(cwd, paths)    — async generator yielding text chunks

`paths` is a list of absolute paths:
  - []              → summarise the entire cwd directory
  - ["/a/dir"]      → summarise that directory
  - ["/f1", "/f2"]  → summarise those specific files
"""

from __future__ import annotations

import os
import shutil
from typing import AsyncIterator

PROVIDER_NAME = "Claude (Anthropic)"

# ─────────────────────────────────────────────────────────────────────────────
# Prompts
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
# Auth resolution
# ─────────────────────────────────────────────────────────────────────────────
def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv(dotenv_path=os.path.join(os.getcwd(), ".env"), override=False)
    except ImportError:
        pass


def _resolve_auth() -> dict[str, str]:
    """
    Return env-override dict for ClaudeAgentOptions.

    Priority:
      1. ANTHROPIC_API_KEY in environment (or .env)
      2. Claude Code CLI OAuth session (`claude login`)
      3. Raise RuntimeError with instructions
    """
    _load_dotenv()

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if api_key:
        return {"ANTHROPIC_API_KEY": api_key}

    if shutil.which("claude") is not None:
        # OAuth session managed by the CLI; pass no key override
        return {}

    raise RuntimeError(
        "Authentication failed.\n\n"
        "  Option 1 — API key:\n"
        "    export ANTHROPIC_API_KEY=sk-ant-...\n\n"
        "  Option 2 — Claude Code CLI OAuth:\n"
        "    npm install -g @anthropic-ai/claude-code\n"
        "    claude login"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Provider interface
# ─────────────────────────────────────────────────────────────────────────────
async def stream(cwd: str, paths: list[str]) -> AsyncIterator[str]:
    """Yield text chunks streamed from Claude Agent SDK.

    Args:
        cwd:   The working directory (always set to os.getcwd() by the caller).
        paths: Absolute paths to summarise. Empty list means 'summarise cwd'.
               A single path that is a directory also means 'summarise that dir'.
               One or more file paths means 'read exactly those files'.
    """
    from claude_agent_sdk import (  # type: ignore
        query,
        ClaudeAgentOptions,
        AssistantMessage,
        ResultMessage,
    )

    env_override = _resolve_auth()

    # Decide mode: directory (glob) vs explicit files (read only)
    if not paths or (len(paths) == 1 and os.path.isdir(paths[0])):
        # Directory mode
        target_dir = paths[0] if paths else cwd
        system_prompt = _SYSTEM_PROMPT_DIRECTORY
        user_prompt = _USER_PROMPT_DIRECTORY
        agent_cwd = target_dir
        allowed_tools = ["Glob", "Read"]
    else:
        # Explicit files mode
        system_prompt = _SYSTEM_PROMPT_FILES
        user_prompt = _user_prompt_files(paths)
        agent_cwd = cwd
        allowed_tools = ["Read"]

    options = ClaudeAgentOptions(
        allowed_tools=allowed_tools,
        system_prompt=system_prompt,
        cwd=agent_cwd,
        env=env_override,
        max_turns=10,
    )

    async for message in query(prompt=user_prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if hasattr(block, "text") and block.text:
                    yield block.text
        elif isinstance(message, ResultMessage):
            # Do not `return` here — letting the SDK iterator exhaust naturally
            # avoids the anyio-cancel-scope task-affinity error that occurs when
            # GeneratorExit is thrown into the generator mid-scope.
            pass
