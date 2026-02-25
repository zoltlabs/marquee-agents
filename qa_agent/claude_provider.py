"""qa_agent/claude_provider.py

Claude Agent SDK provider.

Implements the standard provider interface (see qa_agent/providers.py):

    PROVIDER_NAME: str
    async def stream(request: ProviderRequest) -> AsyncIterator[str]

Responsibilities of THIS module
────────────────────────────────
  • Resolve Anthropic credentials (API key or OAuth via Claude Code CLI).
  • Wire up the Claude Agent SDK (ClaudeAgentOptions + query()).
  • Yield raw text chunks from AssistantMessage blocks.

What this module does NOT do
─────────────────────────────
  • Build system/user prompts — that is the caller's responsibility.
  • Decide which tools to allow — passed in via ProviderRequest.allowed_tools.
  • Know anything about commands like `summarise` — it is a generic Claude driver.
"""

from __future__ import annotations

import os
import shutil
from typing import AsyncIterator

from qa_agent.errors import ProviderAuthError, ProviderConnectionError, ProviderResponseError
from qa_agent.providers import ProviderRequest

PROVIDER_NAME = "Claude (Anthropic)"


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
    """Return an env-override dict for ClaudeAgentOptions.

    Priority:
      1. ANTHROPIC_API_KEY in environment (or .env in cwd)
      2. Claude Code CLI OAuth session  (`claude login`)
      3. Raise RuntimeError with setup instructions
    """
    _load_dotenv()

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if api_key:
        return {"ANTHROPIC_API_KEY": api_key}

    if shutil.which("claude") is not None:
        # OAuth session is managed by the CLI; no key override needed.
        return {}

    raise ProviderAuthError(
        "Authentication failed.\n\n"
        "  Option 1 — API key:\n"
        "    export ANTHROPIC_API_KEY=sk-ant-...\n\n"
        "  Option 2 — Claude Code CLI OAuth:\n"
        "    npm install -g @anthropic-ai/claude-code\n"
        "    claude login"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Provider entry point
# ─────────────────────────────────────────────────────────────────────────────

async def stream(request: ProviderRequest) -> AsyncIterator[str]:
    """Yield text chunks streamed from the Claude Agent SDK.

    Args:
        request: A ProviderRequest containing system_prompt, user_prompt,
                 agent_cwd, allowed_tools, and max_turns.
                 Build this in the command orchestrator (e.g. summarise.py),
                 not here.
    """
    from claude_agent_sdk import (  # type: ignore
        query,
        ClaudeAgentOptions,
        AssistantMessage,
        ResultMessage,
    )

    env_override = _resolve_auth()

    options = ClaudeAgentOptions(
        allowed_tools=request.allowed_tools,
        system_prompt=request.system_prompt,
        cwd=request.agent_cwd,
        env=env_override,
        max_turns=request.max_turns,
    )

    async for message in query(prompt=request.user_prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if hasattr(block, "text") and block.text:
                    yield block.text
        elif isinstance(message, ResultMessage):
            # Do not `return` here — letting the SDK iterator exhaust naturally
            # avoids the anyio-cancel-scope task-affinity error that occurs when
            # GeneratorExit is thrown into the generator mid-scope.
            pass
