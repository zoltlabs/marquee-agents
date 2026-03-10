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
import tempfile
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


# Field names Claude Code CLI may store the OAuth token under in ~/.claude.json
_CLAUDE_JSON_TOKEN_FIELDS = (
    "oauthToken",      # current Claude Code CLI (v1.x)
    "accessToken",     # older builds
    "sessionToken",    # possible alias
    "primaryApiKey",   # possible alias in some builds
    "apiKey",          # fallback
)


def _read_claude_json_token() -> str:
    """Read the OAuth access token from ~/.claude.json.

    Tries both ``os.path.expanduser('~/.claude.json')`` and
    ``/home/$USER/.claude.json`` so that the code works correctly on
    servers using csh/tcsh where $HOME may differ from /home/$USER.

    Returns the token string, or "" if not found / not parseable.
    """
    import json as _json

    candidates = [
        os.path.expanduser("~/.claude.json"),
    ]
    # csh / tcsh servers: $HOME can be /home/$USER but expanduser uses /root etc.
    env_user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
    if env_user:
        candidates.append(f"/home/{env_user}/.claude.json")

    for path in candidates:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = _json.load(fh)
        except (OSError, ValueError):
            continue

        # Try known field names in order
        for field in _CLAUDE_JSON_TOKEN_FIELDS:
            token = data.get(field, "")
            if isinstance(token, str) and token.strip():
                return token.strip()

        # Also check one level inside nested dicts (some versions nest under "auth")
        for nested_key in ("auth", "session", "credentials"):
            nested = data.get(nested_key)
            if isinstance(nested, dict):
                for field in _CLAUDE_JSON_TOKEN_FIELDS:
                    token = nested.get(field, "")
                    if isinstance(token, str) and token.strip():
                        return token.strip()

    return ""


def _resolve_auth() -> dict[str, str]:
    """Return an env-override dict for ClaudeAgentOptions (SDK stream path).

    Priority:
      1. ANTHROPIC_API_KEY in environment (or .env in cwd)
      2. OAuth token from ~/.claude.json  (Claude Code CLI — ``claude login``)
      3. Claude Code CLI binary present (SDK manages OAuth transparently)
      4. Raise ProviderAuthError with setup instructions
    """
    _load_dotenv()

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if api_key:
        return {"ANTHROPIC_API_KEY": api_key}

    # Try ~/.claude.json OAuth token
    token = _read_claude_json_token()
    if token:
        return {"ANTHROPIC_API_KEY": token}

    if shutil.which("claude") is not None:
        # OAuth session is managed by the CLI; no key override needed.
        return {}

    raise ProviderAuthError(
        "Authentication failed.\n\n"
        "  Option 1 — API key:\n"
        "    export ANTHROPIC_API_KEY=sk-ant-...\n\n"
        "  Option 2 — Claude Code CLI OAuth (auto-detected):\n"
        "    npm install -g @anthropic-ai/claude-code\n"
        "    claude login\n\n"
        "  Option 3 — Manual token:\n"
        "    The OAuth token is read automatically from ~/.claude.json\n"
        "    after running 'claude login'."
    )

def _get_sandbox_dir() -> str:
    """Return the absolute path to the secure empty sandbox directory."""
    sandbox = os.path.join(tempfile.gettempdir(), ".qa-agent")
    os.makedirs(sandbox, exist_ok=True)
    return sandbox


# ─────────────────────────────────────────────────────────────────────────────
# Provider entry point
# ─────────────────────────────────────────────────────────────────────────────

async def stream(request: ProviderRequest) -> AsyncIterator[str]:
    """Yield text chunks streamed from the Claude Agent SDK.

    Args:
        request: A ProviderRequest containing system_prompt, user_prompt,
                 allowed_tools, and max_turns.
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
    sandbox_dir = _get_sandbox_dir()

    options = ClaudeAgentOptions(
        allowed_tools=request.allowed_tools,
        system_prompt=request.system_prompt,
        env=env_override,
        max_turns=request.max_turns,
        cwd=sandbox_dir,  # FORCED SANDBOX: prevents SDK built-in tools from seeing project files
    )

    async for message in query(prompt=request.user_prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if hasattr(block, "text") and block.text:
                    yield block.text
        elif isinstance(message, ResultMessage):
            pass


async def chat_with_tools(request: "ToolCallRequest") -> dict:  # type: ignore[name-defined]  # noqa: F821
    """Send one turn of the agentic conversation to Claude via the Messages API.

    Uses the Anthropic Messages API directly (NOT claude-agent-sdk) so that
    tool calls are intercepted locally rather than executed by Claude's runtime.
    This is the security boundary: our tool handlers run, not Claude's.

    Args:
        request: ToolCallRequest with messages, tools registry, model, max_tokens.

    Returns:
        dict with keys:
            role      → "assistant"
            content   → str | None  (text response on the final turn)
            tool_calls → list[dict] | None  (tool call requests on intermediate turns)
                         Each dict: {id, name, arguments (dict)}
    """
    try:
        import anthropic  # type: ignore
    except ImportError as exc:
        raise ProviderAuthError(
            "anthropic SDK is not installed.\n"
            "  Run:  pip install anthropic"
        ) from exc

    from qa_agent.providers import ToolCallRequest  # local import to avoid circular

    api_key = _resolve_auth()

    # Change current working directory of Python process as a secondary fail-safe sandbox.
    # Because tools use absolute paths, chdir does not break them!
    sandbox_dir = _get_sandbox_dir()
    original_cwd = os.getcwd()
    os.chdir(sandbox_dir)

    try:
        api_key_str = (
            api_key.get("ANTHROPIC_API_KEY")
            or os.environ.get("ANTHROPIC_API_KEY")
            or None
        )
        client = anthropic.AsyncAnthropic(api_key=api_key_str)

        model = request.model or "claude-3-5-sonnet-20241022"
        tools_schema = request.tools.to_claude_schema()

        system_msg = ""
        messages = []
        for msg in request.messages:
            if msg.get("role") == "system":
                system_msg = msg.get("content", "")
            else:
                messages.append(msg)

        response = await client.messages.create(
            model=model,
            max_tokens=request.max_tokens,
            system=system_msg,
            messages=messages,
            tools=tools_schema,
            tool_choice={"type": "auto"},
        )

        text_parts = []
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "name": block.name,
                    "arguments": block.input,
                })

        return {
            "role": "assistant",
            "content": "\n".join(text_parts) if text_parts else None,
            "tool_calls": tool_calls if tool_calls else None,
        }
    finally:
        os.chdir(original_cwd)
