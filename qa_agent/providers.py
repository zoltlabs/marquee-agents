"""qa_agent/providers.py

Shared types for the provider interface.

Every AI provider module (claude_provider.py, openai_provider.py, …)
must implement:

    PROVIDER_NAME: str
        Human-readable display name, e.g. "Claude (Anthropic)".

    async def stream(request: ProviderRequest) -> AsyncIterator[str]:
        Yield plain-text chunks as the AI streams its response.

The orchestrator (summarise.py, or any future command) builds a
ProviderRequest and hands it to the active provider.  All prompt
construction and tool-list decisions live in the orchestrator, NOT
inside the provider module.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ProviderRequest:
    """Everything a provider needs to fulfil one AI request.

    Attributes:
        system_prompt:  Instruction text placed in the system role.
        user_prompt:    The user-facing message / task description.
        allowed_tools:  Tool names the AI may call (provider-specific names).
                        Defaults to an empty list (no tools).
        max_turns:      Maximum agentic turns / round-trips.
        extra:          Provider-specific extra kwargs (e.g. model name, temperature).
                        Ignored by providers that don't understand them.
    """

    system_prompt: str
    user_prompt: str
    allowed_tools: list[str] = field(default_factory=list)
    max_turns: int = 10
    extra: dict = field(default_factory=dict)


@dataclass
class ToolCallRequest:
    """Request type for agentic tool-calling loops.

    Unlike ProviderRequest (which is for simple streaming), ToolCallRequest
    carries the full message history and the available tool schemas so that
    each provider can implement multi-turn tool-calling via its native API.

    Attributes:
        messages:    Full conversation history as a list of role/content dicts.
        tools:       ToolRegistry providing schema conversion per provider.
        model:       Optional model override (provider-specific string).
        max_tokens:  Maximum tokens for each individual completion call.
    """

    messages: list[dict]
    tools: object   # ToolRegistry — typed as object to avoid circular import
    model: str = ""
    max_tokens: int = 4096
