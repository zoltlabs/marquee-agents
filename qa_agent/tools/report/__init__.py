"""qa_agent/tools/report/__init__.py

Assembles the ToolRegistry for the agentic report command.

Entry point:
    registry = build_report_tools(sim_dir)

All tool handlers are bound to *sim_dir* at construction time.  The registry
is passed to run_tool_loop() — the AI may only call these tools and has no
other mechanism to access the filesystem.

Tool catalogue (what the AI may call):
  list_sim_files        — discover readable files (always call first)
  read_sim_metadata     — read qrun.out/stats_log, big_argv, version, etc.
  get_debug_log         — read debug.log with error filtering and tail
  get_mti_log           — read mti.log (Questa MTI diagnostics)
  get_tracker_data      — read a specific tracker_*.txt file with filtering
  get_sfi_data          — read a specific sfi_*.txt file
  get_coverage_report   — read *coverage*.txt functional coverage report
  get_assertion_failures — extract SVA assertion failures from debug.log
  get_scoreboard_mismatches — extract scoreboard mismatches from debug.log
  read_signal_values    — read signal values from text signal logs (if present)
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


def build_report_tools(sim_dir: str | Path, max_output_chars: int = 32_000) -> ToolRegistry:
    """Build and return a ToolRegistry with all agentic report-command tools.

    All handlers are bound to *sim_dir* at creation time.  The registry is
    passed to run_tool_loop() and to provider schema-conversion methods.

    The AI has NO other filesystem access — all data flows through these tools.

    Args:
        sim_dir:          Path to the Questa simulation output directory (sandbox root).
        max_output_chars: Hard cap per tool result (default: 32,000 chars — generous
                          for tracker files but within context limits).

    Returns:
        Populated ToolRegistry ready for use in the agentic loop.
    """
    sim_path = Path(sim_dir).resolve()
    registry = ToolRegistry(max_output_chars=max_output_chars)

    all_tool_specs = (
        build_sim_metadata_tools(sim_path)   # list_sim_files, read_sim_metadata, get_sfi_data, get_coverage_report
        + build_log_error_tools(sim_path)    # get_debug_log, get_mti_log
        + build_tracker_tools(sim_path)      # get_tracker_data
        + build_assertion_tools(sim_path)    # get_assertion_failures
        + build_scoreboard_tools(sim_path)   # get_scoreboard_mismatches
        + build_signal_tools(sim_path)       # read_signal_values
    )

    for name, description, parameters, handler in all_tool_specs:
        registry.register(ToolDef(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
        ))

    return registry
