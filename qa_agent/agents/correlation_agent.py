"""qa_agent/agents/correlation_agent.py

Second AI pass: cross-failure correlation.

Takes all individual per-test summaries from a batch run and identifies:
  - Shared root causes (same first error at same timestamp across tests)
  - Common failing components
  - Independent vs. cascading failures

This is a lightweight streaming pass (not agentic — no tools needed).
It runs after all individual reports complete.  Only used when 2+ tests
are processed in batch mode.
"""

from __future__ import annotations

_CORRELATION_SYSTEM_PROMPT = """\
You are a senior DV verification lead reviewing failure summaries from
multiple simulation test runs that all ran in the same regression batch.

Your task: identify patterns, shared root causes, and correlations across
the failures described below.

## Output Format

Write a concise Markdown section:

```
## Cross-Failure Correlation Analysis

### Shared Root Cause(s)
List test pairs/groups that appear to share the same root cause.
Be specific: same PHY error at the same timestamp, same UVM component
failing, same signal state.

### Common Failing Components
Which RTL modules, UVM components, or protocol layers appear across
multiple failures?

### Failure Classification
| Test | Type | First Error Time | Likely Independent? |
|------|------|-----------------|---------------------|
| ... | ... | ... | Yes / No (cascading from <other test>) |

### Correlation Confidence
**X/10** — one-line rationale.

### Recommended Action
1–3 concrete next steps based on the pattern observed.
```

## Rules
- Be concise — this is appended to an existing report.
- Do NOT repeat the individual failure details already in each summary.
- If there is insufficient information to identify correlations, say so explicitly.
- If all failures appear independent, state that clearly.
"""


async def run_correlation_agent(
    summaries: list[dict[str, str]],
    *,
    provider: str = "claude",
) -> str:
    """Identify cross-failure correlations across multiple test summaries.

    Args:
        summaries: List of dicts, each with:
                   {"test_name": str, "executive_summary": str, "classification": str}
        provider:  AI provider to use.

    Returns:
        Markdown string with the correlation analysis section.
    """
    if len(summaries) < 2:
        return ""

    # Build the user message with all summaries
    lines = [
        f"Analyse these {len(summaries)} simulation failure summaries "
        "from the same regression batch and identify correlations:\n"
    ]
    for i, s in enumerate(summaries, 1):
        lines.append(
            f"\n---\n### Simulation {i}: {s.get('test_name', 'unknown')}\n"
            f"**Classification**: {s.get('classification', 'unknown')}\n\n"
            f"{s.get('executive_summary', '(no summary)')}"
        )
    lines.append("\n\nNow write the Cross-Failure Correlation Analysis section.")

    user_message = "\n".join(lines)

    messages = [
        {"role": "system", "content": _CORRELATION_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    try:
        if provider == "claude":
            from qa_agent import claude_provider as mod
        elif provider == "openai":
            from qa_agent import openai_provider as mod
        elif provider == "gemini":
            from qa_agent import gemini_provider as mod
        else:
            return ""

        # Use the streaming call if available, else chat
        if hasattr(mod, "chat_stream"):
            chunks = []
            async for chunk in mod.chat_stream(messages, max_tokens=2048):
                chunks.append(chunk)
            return "".join(chunks)
        elif hasattr(mod, "chat"):
            return await mod.chat(messages, max_tokens=2048)
        else:
            return ""
    except Exception as exc:
        return f"\n\n> ⚠ Cross-failure correlation unavailable: {exc}\n"
