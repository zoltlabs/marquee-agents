"""qa_agent/tools/report/__init__.py

Assembles the ToolRegistry for the report command.

Entry point:
    registry = build_report_tools(sim_dir)

All tool handlers are bound to *sim_dir* at construction time — the registry
itself is then passed to the agentic loop and provider calls.
"""

from __future__ import annotations

from pathlib import Path

from qa_agent.tools.registry import ToolDef, ToolRegistry
from qa_agent.tools.report.assertions import build_assertion_tools
from qa_agent.tools.report.log_errors import build_log_error_tools
from qa_agent.tools.report.scoreboard import build_scoreboard_tools
from qa_agent.tools.report.signals import build_signal_tools
from qa_agent.tools.report.sim_metadata import build_sim_metadata_tools
from qa_agent.tools.report.tracker import build_tracker_tools


def build_report_tools(sim_dir: str | Path, max_output_chars: int = 8_000) -> ToolRegistry:
    """Build and return a ToolRegistry with all report-command tools.

    All handlers are bound to *sim_dir* at creation time.  The registry is
    passed to run_tool_loop() and to provider schema-conversion methods.

    Args:
        sim_dir:          Path to the simulation output directory (sandbox root).
        max_output_chars: Hard cap per tool result (default: 8,000 chars).

    Returns:
        Populated ToolRegistry ready for use.
    """
    sim_path = Path(sim_dir).resolve()
    registry = ToolRegistry(max_output_chars=max_output_chars)

    # Collect all tool spec tuples: (name, description, parameters, handler)
    all_tool_specs = (
        build_sim_metadata_tools(sim_path)
        + build_log_error_tools(sim_path)
        + build_assertion_tools(sim_path)
        + build_scoreboard_tools(sim_path)
        + build_tracker_tools(sim_path)
        + build_signal_tools(sim_path)
    )

    for name, description, parameters, handler in all_tool_specs:
        registry.register(ToolDef(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
        ))

    return registry
