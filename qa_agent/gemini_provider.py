"""qa_agent/gemini_provider.py

Google Gemini provider (via the `google-genai` Python SDK).

Implements the standard provider interface (see qa_agent/providers.py):

    PROVIDER_NAME: str
    async def stream(request: ProviderRequest) -> AsyncIterator[str]

Responsibilities of THIS module
────────────────────────────────
  • Resolve Google credentials (API key or gcloud ADC / Vertex AI).
  • Call the Gemini `generate_content` streaming API.
  • Yield raw text chunks back to the caller.

What this module does NOT do
─────────────────────────────
  • Build system/user prompts — that is the caller's responsibility.
  • Know anything about the `summarise` command — it is a generic Gemini driver.

Dependencies
────────────
    pip install google-genai

Auth — two methods
──────────────────
  Option 1 — Gemini API key (Google AI Studio):
      export GEMINI_API_KEY=AIza...
      (or GOOGLE_API_KEY — both are checked)

  Option 2 — Vertex AI + gcloud Application Default Credentials:
      gcloud auth application-default login
      export GOOGLE_CLOUD_PROJECT=your-project
      export GOOGLE_CLOUD_LOCATION=us-central1   # optional, defaults to global
"""

from __future__ import annotations

import os
import shutil
from typing import AsyncIterator

from qa_agent.errors import ProviderAuthError
from qa_agent.providers import ProviderRequest

PROVIDER_NAME = "Google Gemini"

# Default model — override via ProviderRequest.extra["model"]
_DEFAULT_MODEL = "gemini-2.5-flash"


# ─────────────────────────────────────────────────────────────────────────────
# Auth resolution
# ─────────────────────────────────────────────────────────────────────────────

def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv(dotenv_path=os.path.join(os.getcwd(), ".env"), override=False)
    except ImportError:
        pass


def _resolve_auth() -> dict:
    """Return a dict of kwargs for genai.Client().

    Priority:
      1. GEMINI_API_KEY (or GOOGLE_API_KEY) env var — uses Google AI Studio
      2. GOOGLE_CLOUD_PROJECT + gcloud ADC — uses Vertex AI
      3. Raise RuntimeError with setup instructions

    Returns a dict suitable for unpacking into genai.Client(**kwargs).
    """
    _load_dotenv()

    # Option 1: Direct API key (Google AI Studio)
    api_key = (
        os.environ.get("GEMINI_API_KEY", "").strip()
        or os.environ.get("GOOGLE_API_KEY", "").strip()
    )
    if api_key:
        return {"api_key": api_key}

    # Option 2: Vertex AI via gcloud ADC
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
    if project and shutil.which("gcloud") is not None:
        location = os.environ.get("GOOGLE_CLOUD_LOCATION", "global").strip()
        return {
            "vertexai": True,
            "project": project,
            "location": location,
        }

    raise ProviderAuthError(
        "Authentication failed.\n\n"
        "  Option 1 — Gemini API key (Google AI Studio):\n"
        "    export GEMINI_API_KEY=AIza...\n\n"
        "  Option 2 — Vertex AI (gcloud ADC):\n"
        "    gcloud auth application-default login\n"
        "    export GOOGLE_CLOUD_PROJECT=your-project\n"
        "    export GOOGLE_CLOUD_LOCATION=us-central1"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Provider entry point
# ─────────────────────────────────────────────────────────────────────────────

async def stream(request: ProviderRequest) -> AsyncIterator[str]:
    """Yield text chunks streamed from the Gemini API.

    Args:
        request: A ProviderRequest containing system_prompt, user_prompt,
                 agent_cwd, allowed_tools, and max_turns.
                 Build this in the command orchestrator (e.g. summarise.py).

    Extra keys (ProviderRequest.extra):
        model (str): Override default model, e.g. "gemini-2.5-flash", "gemini-1.5-pro".
    """
    try:
        from google import genai  # type: ignore
        from google.genai import types  # type: ignore
    except ImportError as exc:
        raise ProviderAuthError(
            "Google Gen AI SDK is not installed.\n"
            "  Run:  pip install google-genai"
        ) from exc

    client_kwargs = _resolve_auth()
    model = request.extra.get("model", _DEFAULT_MODEL)

    client = genai.Client(**client_kwargs)

    # Combine system prompt with the cwd context
    system_instruction = (
        f"{request.system_prompt}\n\n"
        f"Working directory: {request.agent_cwd}"
    )

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        max_output_tokens=request.extra.get("max_tokens", 4096),
        temperature=request.extra.get("temperature", 0.2),
    )

    # google-genai streaming — generate_content_stream returns an iterable
    # of GenerateContentResponse chunks. We run it in a thread executor so
    # we don't block the asyncio event loop.
    import asyncio

    loop = asyncio.get_event_loop()

    def _run_stream():
        return list(client.models.generate_content_stream(
            model=model,
            contents=request.user_prompt,
            config=config,
        ))

    chunks = await loop.run_in_executor(None, _run_stream)

    for chunk in chunks:
        if chunk.text:
            yield chunk.text
