"""qa_agent/tools/__init__.py

Re-exports the core agentic tool primitives.

Usage:
    from qa_agent.tools import ToolDef, ToolResult, ToolRegistry
"""

from qa_agent.tools.registry import ToolDef, ToolResult, ToolRegistry

__all__ = ["ToolDef", "ToolResult", "ToolRegistry"]
