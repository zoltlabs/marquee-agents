"""qa_agent/agents/dv_debug_agent.py

DV Debug Expert agent: system prompt, investigation strategy, and orchestration.

This module defines the expert DV engineer persona that drives the report
command's agentic loop.  It builds the initial message list and calls
run_tool_loop() to completion, then returns the markdown report.
"""

from __future__ import annotations

from pathlib import Path

from qa_agent.tools.registry import ToolRegistry
from qa_agent.tools.loop import run_tool_loop

# ─────────────────────────────────────────────────────────────────────────────
# System prompt — DV debug expert persona
# ─────────────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are an expert Design Verification (DV) engineer specialising in PCIe / APCI \
silicon verification using Questa Sim. Your task is to investigate a failing simulation \
run and produce a structured Markdown debug report.

## Simulation Data Access

You have NO direct access to files. All data arrives through tool calls:

- list_sim_files       — discover what files exist
- read_sim_metadata    — read metadata (argv, history, stats, DU list, version)
- extract_log_errors   — grep error/warning lines from log files (with context)
- get_assertion_failures  — extract SVA assertion failures (structured)
- get_scoreboard_mismatches — extract scoreboard mismatch summary
- extract_tracker_failures  — get tracker events around the failure time
- read_signal_values   — read signal values at a specific simulation time

## Investigation Strategy

Follow these steps IN ORDER. Stop early when you have enough evidence.

1. **List available files** — call list_sim_files() and list_sim_files("qrun.out").
   Understand what data is available before diving in.

2. **Read metadata** — call read_sim_metadata("big_argv") to get the full simulation
   command (flags, seeds, test name). Also read "version" for tool version context.

3. **Check compile log first** — call extract_log_errors("compile.log").
   Compilation errors explain many failures before simulation even starts.

4. **Check sim log** — call extract_log_errors("sim.log") with the default pattern,
   then optionally with a more specific pattern if needed.

5. **Check assertions** — if assertion keywords appeared in step 4, call
   get_assertion_failures().

6. **Check scoreboard** — if mismatch keywords appeared, call
   get_scoreboard_mismatches().

7. **Check tracker around failure time** — use extract_tracker_failures() with a
   time window centred on the first failure. This gives temporal context.

8. **Check signals only if necessary** — call read_signal_values() ONLY if a specific
   signal name was mentioned in an error message AND you need its value at failure time.

## Efficiency Rules

- Request only the data you need — do not dump entire logs.
- Use specific regex patterns when searching (e.g. "assertion|SVA" not just "error").
- Stop investigating when you have identified the root cause with sufficient evidence.
- If compile errors exist, report them immediately without investigating sim logs.

## Output Format

Write your final report in Markdown using EXACTLY this structure:

```markdown
## Root Cause Summary

One to three sentences: what failed and why.

## Failure Classification

One of: Assertion Failure | Scoreboard Mismatch | Compile Error | Timeout | Protocol Violation | Unknown

## Affected Component / Module

Name the specific module, component, or DU involved (e.g. "apci_rx.sv line 142").

## Evidence

A concise summary of the key evidence found:
- What error messages appeared (file, line, time)
- Expected vs actual values (if scoreboard mismatch)
- Assertion name and failing condition (if SVA)
- Time of first failure

## Suggested Debugging Direction

Two to four specific, actionable next steps. Be concrete — name files, signals,
or waveform timestamps the engineer should examine.
```

Do NOT include any text before the `## Root Cause Summary` header.
Do NOT include unnecessary tool output in the report — summarise findings concisely.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Agent runner
# ─────────────────────────────────────────────────────────────────────────────

async def run_dv_debug_agent(
    sim_dir: Path,
    tools: ToolRegistry,
    *,
    provider: str = "claude",
    max_turns: int = 15,
    model: str = "",
    verbose: bool = False,
    gvim: bool = False,
) -> str:
    """Run the DV debug expert agent on a simulation output directory.

    Args:
        sim_dir:   Path to the simulation output directory (for display only;
                   tool handlers are already bound to it in the registry).
        tools:     Pre-built ToolRegistry from build_report_tools().
        provider:  AI provider: "claude", "openai", or "gemini".
        max_turns: Maximum agentic investigation turns.
        model:     Optional model override.
        verbose:   If True, print tool calls and results to stdout.

    Returns:
        Markdown string containing the structured debug report.
    """
    messages: list[dict] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Please investigate the failing simulation in: {sim_dir}\n\n"
                "Start by listing available files to understand what data exists, "
                "then follow the investigation strategy in your instructions. "
                "Write the structured Markdown report when you have sufficient evidence."
            ),
        },
    ]

    def _on_tool_call(name: str, args: dict) -> None:
        from qa_agent.output import dim, cyan
        args_preview = ", ".join(f"{k}={repr(v)}" for k, v in list(args.items())[:3])
        print(f"  {dim('→')} {cyan(name)}({args_preview})")

    def _on_tool_result(name: str, content: str, truncated: bool) -> None:
        from qa_agent.output import dim, yellow
        lines = content.strip().count("\n") + 1
        trunc_note = f" {yellow('[TRUNCATED]')}" if truncated else ""
        print(f"  {dim('←')} {name}: {lines} lines{trunc_note}")

    report = await run_tool_loop(
        provider_name=provider,
        messages=messages,
        tools=tools,
        max_turns=max_turns,
        model=model,
        verbose=verbose,
        use_gvim=gvim,
        on_tool_call=_on_tool_call if verbose else None,
        on_tool_result=_on_tool_result if verbose else None,
    )

    return report
