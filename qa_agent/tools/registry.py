"""qa_agent/tools/registry.py

Core agentic tool infrastructure: ToolDef, ToolResult, ToolRegistry.

ToolRegistry is the security enforcement point — every tool call made by
the AI agent is validated and executed here before the result is appended
to the conversation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable


# ─────────────────────────────────────────────────────────────────────────────
# Data types
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ToolDef:
    """Definition of a single agentic tool.

    Attributes:
        name:        Unique identifier used by the AI (e.g. "extract_log_errors").
        description: Shown to the AI in the tool schema.
        parameters:  JSON Schema dict describing the input parameters.
        handler:     Synchronous callable(**kwargs) → str that performs the
                     actual work.  Must NEVER modify the filesystem — read-only.
    """

    name: str
    description: str
    parameters: dict
    handler: Callable[..., str]


@dataclass
class ToolResult:
    """Result returned by ToolRegistry.execute().

    Attributes:
        tool_call_id: Correlates the result with the AI's request.
        name:         Name of the tool that was called.
        content:      Sanitized, size-capped string result.
        truncated:    True if output was cut at max_output_chars.
        error:        True if the handler raised an exception.
    """

    tool_call_id: str
    name: str
    content: str
    truncated: bool = False
    error: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────

class ToolRegistry:
    """Manages tool registration, schema conversion, and safe execution.

    Args:
        max_output_chars: Hard cap applied to every tool result.  Defaults to
                          8,000 characters as described in the security model.
    """

    def __init__(self, max_output_chars: int = 8_000) -> None:
        self._tools: dict[str, ToolDef] = {}
        self.max_output_chars = max_output_chars

    # ── Registration ──────────────────────────────────────────────────────────

    def register(self, tool: ToolDef) -> None:
        """Register a tool.  Raises ValueError if the name is already taken."""
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered.")
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDef | None:
        """Return the ToolDef for *name*, or None if not registered."""
        return self._tools.get(name)

    def all_defs(self) -> list[ToolDef]:
        """Return all registered ToolDefs in insertion order."""
        return list(self._tools.values())

    # ── Schema conversion ─────────────────────────────────────────────────────

    def to_openai_schema(self) -> list[dict]:
        """Return tools in OpenAI function-calling format."""
        schema = []
        for t in self._tools.values():
            schema.append({
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            })
        return schema

    def to_claude_schema(self) -> list[dict]:
        """Return tools in Anthropic Messages API format."""
        schema = []
        for t in self._tools.values():
            schema.append({
                "name": t.name,
                "description": t.description,
                "input_schema": t.parameters,
            })
        return schema

    def to_gemini_schema(self) -> list[dict]:
        """Return tools in Google Gemini function-declaration format."""
        schema = []
        for t in self._tools.values():
            schema.append({
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            })
        return schema

    # ── Execution ─────────────────────────────────────────────────────────────

    def execute(
        self,
        tool_call_id: str,
        name: str,
        arguments: dict[str, Any],
    ) -> ToolResult:
        """Validate and execute a tool call safely.

        Security enforcement point:
          1. Validates the tool name exists in the registry.
          2. Calls the handler with the provided arguments.
          3. Truncates output to max_output_chars.
          4. Catches all handler exceptions and returns an error result —
             the agentic loop never crashes due to a bad tool call.

        Args:
            tool_call_id: Correlation ID from the AI's tool-call request.
            name:         Tool name to execute.
            arguments:    Parsed kwargs to pass to the handler.

        Returns:
            ToolResult with the handler's output (or an error message).
        """
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(
                tool_call_id=tool_call_id,
                name=name,
                content=f"Unknown tool: '{name}'. Available: {', '.join(self._tools)}",
                error=True,
            )

        try:
            raw = tool.handler(**arguments)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                tool_call_id=tool_call_id,
                name=name,
                content=f"Tool error: {type(exc).__name__}: {exc}",
                error=True,
            )

        content = str(raw)
        truncated = False
        if len(content) > self.max_output_chars:
            content = content[: self.max_output_chars]
            truncated = True

        return ToolResult(
            tool_call_id=tool_call_id,
            name=name,
            content=content,
            truncated=truncated,
        )
