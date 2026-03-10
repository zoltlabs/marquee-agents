"""qa_agent/agents/comparison_agent.py

Regression comparison AI pass.

Compares two QA-REGRESSION-SUMMARY_*.md aggregate reports and classifies:
  - New failures (regressions): PASS → FAIL
  - Fixed failures:             FAIL → PASS
  - Recurring failures:         FAIL → FAIL
  - Stable passes:              PASS → PASS (brief mention)
"""

from __future__ import annotations

import re
from pathlib import Path

_COMPARISON_SYSTEM_PROMPT = """\
You are a senior DV verification engineer comparing two regression run summaries.

Your task: produce a structured regression comparison report identifying
what changed between the old run and the new run.

## Output Format

```
## Regression Comparison Report

### Summary
| Category | Count |
|----------|-------|
| New failures (regressions) | N |
| Fixed failures | N |
| Recurring failures | N |
| Stable passes | N |

### 🔴 New Failures (Regressions)
Tests that PASSED in the old run but FAIL in the new run.
- `<test_name>` — <brief failure description if available>

### 🟢 Fixed Failures
Tests that FAILED in the old run but PASS in the new run.
- `<test_name>` — <brief note if patterns suggest why it was fixed>

### 🟡 Recurring Failures
Tests that FAIL in both runs.
- `<test_name>` — <note if the failure type is the same or different>

### ⚪ Attention Items
Any tests with unexpected pattern changes or divergent failure types.

### Trend Analysis
1–3 sentences: overall direction (improving / regressing / stable?),
any systemic component showing new failures, any quick-win fixes visible.
```

## Rules
- List test names exactly as they appear in the summaries.
- Do NOT invent test results not present in the data.
- If information is sparse, say so rather than guessing.
"""


def _extract_test_results(report_text: str) -> dict[str, str]:
    """Extract test name → status from a QA-REGRESSION-SUMMARY Markdown table.

    Looks for markdown table rows with PASS/FAIL in them.
    Returns {test_name: "PASS" | "FAIL"}.
    """
    results: dict[str, str] = {}
    # Match table rows: | test_name | ... PASS/FAIL ... |
    row_re = re.compile(
        r"\|\s*(?P<name>[^\|]+?)\s*\|[^\|]*(?P<status>PASS|FAIL)[^\|]*\|",
        re.IGNORECASE,
    )
    for m in row_re.finditer(report_text):
        name = m.group("name").strip()
        status = m.group("status").upper()
        if name and name.lower() not in {"test", "name", "testcase", "simulation", "---"}:
            results[name] = status
    return results


async def run_comparison_agent(
    old_report_path: str | Path,
    new_report_path: str | Path,
    *,
    provider: str = "claude",
) -> str:
    """Compare two aggregate regression reports and produce a diff analysis.

    Args:
        old_report_path: Path to QA-REGRESSION-SUMMARY_<old>.md
        new_report_path: Path to QA-REGRESSION-SUMMARY_<new>.md
        provider:        AI provider to use.

    Returns:
        Markdown string: the comparison report body.
    """
    old_path = Path(old_report_path)
    new_path = Path(new_report_path)

    if not old_path.exists():
        raise FileNotFoundError(f"Old report not found: {old_path}")
    if not new_path.exists():
        raise FileNotFoundError(f"New report not found: {new_path}")

    old_text = old_path.read_text(encoding="utf-8", errors="replace")
    new_text = new_path.read_text(encoding="utf-8", errors="replace")

    # Extract structured results for the AI to work with
    old_results = _extract_test_results(old_text)
    new_results = _extract_test_results(new_text)

    all_tests = sorted(set(old_results) | set(new_results))

    rows: list[str] = []
    for test in all_tests:
        old_s = old_results.get(test, "UNKNOWN")
        new_s = new_results.get(test, "UNKNOWN")
        rows.append(f"| {test} | {old_s} | {new_s} |")

    table = (
        "| Test | Old Status | New Status |\n"
        "|------|-----------|------------|\n"
        + "\n".join(rows)
    )

    user_message = (
        f"Old report: `{old_path.name}`\n"
        f"New report: `{new_path.name}`\n\n"
        f"Extracted test results (auto-parsed from report tables):\n\n"
        f"{table}\n\n"
        f"--- Full old report (for context) ---\n{old_text[:8000]}\n\n"
        f"--- Full new report (for context) ---\n{new_text[:8000]}\n\n"
        "Now write the Regression Comparison Report."
    )

    messages = [
        {"role": "system", "content": _COMPARISON_SYSTEM_PROMPT},
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
            raise ValueError(f"Unknown provider: {provider}")

        if hasattr(mod, "chat_stream"):
            chunks = []
            async for chunk in mod.chat_stream(messages, max_tokens=4096):
                chunks.append(chunk)
            return "".join(chunks)
        elif hasattr(mod, "chat"):
            return await mod.chat(messages, max_tokens=4096)
        else:
            return "(Comparison failed: provider has no chat method)"
    except Exception as exc:
        return f"\n\n> ⚠ Comparison analysis failed: {exc}\n"
