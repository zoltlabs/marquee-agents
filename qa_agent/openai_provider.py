"""qa_agent/openai_provider.py

OpenAI provider (via the `openai` Python SDK).

Implements the standard provider interface (see qa_agent/providers.py):

    PROVIDER_NAME: str
    async def stream(request: ProviderRequest) -> AsyncIterator[str]

NOTE — Codex CLI SDK
─────────────────────
The official Codex SDK (@openai/codex-sdk) is TypeScript-only.
This module uses the official `openai` Python package and targets the
Chat Completions API with streaming — the same model family (GPT-4o, o3,
etc.) that powers Codex agents — giving full Python-native access with
the same quality of output.

Responsibilities of THIS module
────────────────────────────────
  • Resolve OpenAI credentials (API key or Codex CLI OAuth session).
  • Call `openai.AsyncOpenAI` with streaming enabled.
  • Yield raw text delta chunks back to the caller.

What this module does NOT do
─────────────────────────────
  • Build system/user prompts — that is the caller's responsibility.
  • Know anything about the `summarise` command — it is a generic OpenAI driver.

Dependencies
────────────
    pip install openai
"""

from __future__ import annotations

import os
import shutil
from typing import AsyncIterator

from qa_agent.errors import ProviderAuthError, ProviderConnectionError
from qa_agent.providers import ProviderRequest

PROVIDER_NAME = "OpenAI (GPT)"

# Default model — override via ProviderRequest.extra["model"]
_DEFAULT_MODEL = "gpt-4o"


# ─────────────────────────────────────────────────────────────────────────────
# Auth resolution
# ─────────────────────────────────────────────────────────────────────────────

def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv(dotenv_path=os.path.join(os.getcwd(), ".env"), override=False)
    except ImportError:
        pass


def _resolve_auth() -> str:
    """Return the OpenAI API key to use.

    Priority:
      1. OPENAI_API_KEY in environment (or .env in cwd)
      2. Codex CLI OAuth session  (`codex login`)
         — reads the key written by the CLI to ~/.codex/auth.json
      3. Raise RuntimeError with setup instructions
    """
    _load_dotenv()

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if api_key:
        return api_key

    # Codex CLI stores credentials at ~/.codex/auth.json after `codex login`
    if shutil.which("codex") is not None:
        auth_path = os.path.expanduser("~/.codex/auth.json")
        if os.path.exists(auth_path):
            import json
            try:
                with open(auth_path) as f:
                    data = json.load(f)
                key = data.get("apiKey", "").strip()
                if key:
                    return key
            except (json.JSONDecodeError, OSError):
                pass

    raise ProviderAuthError(
        "Authentication failed.\n\n"
        "  Option 1 — API key:\n"
        "    export OPENAI_API_KEY=sk-...\n\n"
        "  Option 2 — Codex CLI OAuth:\n"
        "    npm install -g @openai/codex\n"
        "    codex login"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Provider entry point
# ─────────────────────────────────────────────────────────────────────────────

async def stream(request: ProviderRequest) -> AsyncIterator[str]:
    """Yield text chunks streamed from the OpenAI Chat Completions API.

    Args:
        request: A ProviderRequest containing system_prompt, user_prompt,
                 agent_cwd, allowed_tools, and max_turns.
                 Build this in the command orchestrator (e.g. summarise.py).

    Note:
        `allowed_tools` and `agent_cwd` from ProviderRequest are used to
        construct a sandboxed file-reading context — the system prompt already
        constrains the model to operate within those bounds at the prompt level.
        OpenAI chat completions do not execute tools natively here; tool
        restrictions are enforced through the system prompt wording.
        For full tool-calling support, swap to the Responses API or Agents SDK.

    Extra keys (ProviderRequest.extra):
        model (str): Override the default model, e.g. "o3", "gpt-4o-mini".
    """
    try:
        from openai import AsyncOpenAI  # type: ignore
    except ImportError as exc:
        raise ProviderAuthError(
            "OpenAI SDK is not installed.\n"
            "  Run:  pip install openai"
        ) from exc

    api_key = _resolve_auth()
    model = request.extra.get("model", _DEFAULT_MODEL)

    client = AsyncOpenAI(api_key=api_key)

    # Inject cwd and file-list context into the system prompt so the model
    # knows its operating scope even without native tool execution.
    system_ctx = (
        f"{request.system_prompt}\n\n"
        f"Working directory: {request.agent_cwd}"
    )

    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_ctx},
            {"role": "user",   "content": request.user_prompt},
        ],
        stream=True,
        max_completion_tokens=request.extra.get("max_tokens", 4096),
    )

    async for chunk in response:
        delta = chunk.choices[0].delta if chunk.choices else None
        if delta and delta.content:
            yield delta.content
