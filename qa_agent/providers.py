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
        agent_cwd:      Working directory the AI agent should operate in.
        allowed_tools:  Tool names the AI may call (provider-specific names).
                        Defaults to an empty list (no tools).
        max_turns:      Maximum agentic turns / round-trips.
        extra:          Provider-specific extra kwargs (e.g. model name, temperature).
                        Ignored by providers that don't understand them.
    """

    system_prompt: str
    user_prompt: str
    agent_cwd: str
    allowed_tools: list[str] = field(default_factory=list)
    max_turns: int = 10
    extra: dict = field(default_factory=dict)
