"""qa_agent/agents/dv_debug_agent.py

DV Debug Expert agent — stream-based (prefetch model).

All simulation data is pre-fetched by report_prefetch.collect_sim_data() and
embedded directly into the user prompt.  The AI receives one large context block
and produces the debug report in a single streaming pass.

Uses claude-agent-sdk under the hood (via claude_provider.stream), so auth is
handled by `claude login` or ANTHROPIC_API_KEY env var — no direct API key
reference in code.

The original agentic (tool-calling) agent is preserved at:
    qa_agent/agents/dv_debug_agent_agentic.py
"""

from __future__ import annotations

from qa_agent.providers import ProviderRequest


# ─────────────────────────────────────────────────────────────────────────────
# System prompt — DV debug expert persona (single-pass analysis)
# ─────────────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are an expert Design Verification (DV) engineer specialising in PCIe / APCI \
silicon verification using Questa Sim. Your task is to analyse the simulation output \
data provided in the context block below and produce a structured Markdown debug report.

## Analysis Guidelines

- All simulation data is provided below — there are no tool calls in this session.
- Analyse the **Compile Log** first. If compile errors are present, classify and \
report them immediately — do not look further into the sim log.
- If the compile log is clean, analyse **Sim Log** errors, assertion failures, and \
scoreboard mismatches.
- Use **Tracker Failures** for temporal context around the first failure timestamp.
- Summarise findings concisely — do not repeat raw log output verbatim in the report.

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
Do NOT repeat raw log lines — summarise what they mean.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Prompt helpers
# ─────────────────────────────────────────────────────────────────────────────

def build_prompt(sim_data: str) -> ProviderRequest:
    """Build the ProviderRequest from pre-fetched sim data.

    Args:
        sim_data: Markdown context block from report_prefetch.collect_sim_data().

    Returns:
        A ProviderRequest ready to pass to any provider's stream() function.
    """
    user_prompt = (
        "Please analyse the following simulation output data and write the "
        "structured Markdown debug report as instructed.\n\n"
        + sim_data
    )
    return ProviderRequest(
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        allowed_tools=[],
        max_turns=1,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Agent runner
# ─────────────────────────────────────────────────────────────────────────────

async def run_dv_debug_agent(
    sim_data: str,
    *,
    provider: str = "claude",
    verbose: bool = False,
) -> str:
    """Run the DV debug expert agent with pre-fetched sim data.

    Calls the chosen provider's stream() interface — no tool-calling or API key
    required beyond what the provider's auth layer expects (claude-agent-sdk
    handles auth via `claude login` or ANTHROPIC_API_KEY env var).

    Args:
        sim_data: Pre-fetched simulation context from collect_sim_data().
        provider: AI provider name — "claude", "openai", or "gemini".
        verbose:  If True, stream chunks to stdout as they arrive.

    Returns:
        Markdown string: the complete structured debug report.
    """
    if provider == "claude":
        from qa_agent import claude_provider as mod
    elif provider == "openai":
        from qa_agent import openai_provider as mod
    elif provider == "gemini":
        from qa_agent import gemini_provider as mod
    else:
        raise ValueError(
            f"Unknown provider '{provider}'. Choose: claude, openai, gemini."
        )

    request = build_prompt(sim_data)

    chunks: list[str] = []
    async for chunk in mod.stream(request):
        chunks.append(chunk)
        if verbose:
            print(chunk, end="", flush=True)

    return "".join(chunks)
