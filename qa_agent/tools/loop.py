"""qa_agent/tools/loop.py

Provider-agnostic agentic tool-calling loop.

Entry point:
    final_report = await run_tool_loop(
        provider_name="claude",
        messages=[...],
        tools=registry,
        max_turns=15,
    )

The loop calls the active provider's chat_with_tools() in each iteration.
If the response contains tool_calls, each is dispatched through ToolRegistry.execute()
and the result is appended to messages before the next turn.
If the response is plain text (no tool_calls), that is the final report and
the loop returns it.
"""

from __future__ import annotations

import json
from typing import Callable

from qa_agent.tools.registry import ToolRegistry


# ─────────────────────────────────────────────────────────────────────────────
# Provider module loader
# ─────────────────────────────────────────────────────────────────────────────

def _load_provider(provider_name: str):
    """Import and return the provider module for *provider_name*.

    Returns the module object which must have a callable `chat_with_tools`.
    """
    if provider_name == "claude":
        from qa_agent import claude_provider as mod
    elif provider_name == "openai":
        from qa_agent import openai_provider as mod
    elif provider_name == "gemini":
        from qa_agent import gemini_provider as mod
    else:
        raise ValueError(
            f"Unknown provider '{provider_name}'. Choose: claude, openai, gemini."
        )
    if not hasattr(mod, "chat_with_tools"):
        raise AttributeError(
            f"Provider '{provider_name}' does not implement chat_with_tools()."
        )
    return mod


# ─────────────────────────────────────────────────────────────────────────────
# Message helpers
# ─────────────────────────────────────────────────────────────────────────────

def _append_assistant_turn(messages: list[dict], content: str | None, tool_calls: list[dict] | None) -> None:
    """Append the assistant's response to the message history.

    For providers that use a unified content list (Claude), tool_calls are
    embedded in the content blocks.  For OpenAI-style, they are separate.
    We normalise to a simple dict the loop can reason about; provider
    chat_with_tools() implementations handle their own serialisation.
    """
    msg: dict = {"role": "assistant"}
    if content:
        msg["content"] = content
    if tool_calls:
        msg["tool_calls"] = tool_calls
    messages.append(msg)


def _append_tool_results(messages: list[dict], results: list[dict]) -> None:
    """Append tool results to the message history in the format our loop expects.

    Each result dict: {tool_call_id, name, content, truncated, error}
    We store them as a "tool" role message (OpenAI style) that provider
    implementations may reformat before sending to the API.
    """
    for r in results:
        suffix = " [TRUNCATED]" if r.get("truncated") else ""
        messages.append({
            "role": "tool",
            "tool_call_id": r["tool_call_id"],
            "name": r["name"],
            "content": r["content"] + suffix,
        })


# ─────────────────────────────────────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────────────────────────────────────

async def run_tool_loop(
    provider_name: str,
    messages: list[dict],
    tools: ToolRegistry,
    *,
    max_turns: int = 15,
    model: str = "",
    max_tokens: int = 4096,
    verbose: bool = False,
    use_gvim: bool = False,
    on_tool_call: Callable[[str, dict], None] | None = None,
    on_tool_result: Callable[[str, str, bool], None] | None = None,
    on_text_chunk: Callable[[str], None] | None = None,
) -> str:
    """Run an agentic tool-calling loop until the AI produces a final report.

    Each iteration:
      1. Call provider.chat_with_tools() with the current message history.
      2. If the response has tool_calls → execute each via ToolRegistry,
         append results, continue.
      3. If the response is plain text (no tool_calls) → return it as the
         final report string.
      4. Stop after max_turns and request the AI to conclude.

    Args:
        provider_name:   "claude", "openai", or "gemini".
        messages:        Initial conversation history (mutable — loop appends to it).
        tools:           ToolRegistry with all available tools.
        max_turns:       Maximum total turns before forcing conclusion.
        model:           Optional model name override.
        max_tokens:      Max completion tokens per turn.
        verbose:         If True, print tool calls and results to stdout.
        on_tool_call:    Optional callback(tool_name, arguments) called before each tool.
        on_tool_result:  Optional callback(tool_name, content, truncated) after each tool.
        on_text_chunk:   Optional callback(chunk) for streaming text fragments.

    Returns:
        The AI's final text response (the debug report).

    Raises:
        RuntimeError: If the loop exhausts max_turns without a text response.
    """
    from qa_agent.providers import ToolCallRequest

    provider_mod = _load_provider(provider_name)

    for turn in range(1, max_turns + 1):

        # ── Warn AI as it approaches the limit ────────────────────────────────
        if turn == max_turns - 2:
            messages.append({
                "role": "user",
                "content": (
                    f"You have approximately {max_turns - turn} turns remaining. "
                    "Please start concluding your investigation and write the final report."
                ),
            })

        # ── Build the request ─────────────────────────────────────────────────
        request = ToolCallRequest(
            messages=messages,
            tools=tools,
            model=model,
            max_tokens=max_tokens,
        )

        # ── Call provider ────────────────────────────────────────────────────
        if use_gvim:
            import tempfile
            import subprocess
            import time
            from pathlib import Path
            dump_file = Path(tempfile.gettempdir()) / f"qa_agent_turn_{turn}.md"
            dump_text = f"# Turn {turn} Payload to AI\n\n"
            for m in messages:
                dump_text += f"## {m.get('role', 'unknown').upper()}\n"
                if m.get("content"):
                    dump_text += f"{m['content']}\n\n"
                if m.get("tool_calls"):
                    dump_text += "Tool Calls:\n"
                    for tc in m["tool_calls"]:
                        dump_text += f"  - {tc.get('name')}: {json.dumps(tc.get('arguments', {}))}\n"
                    dump_text += "\n"
            dump_file.write_text(dump_text, encoding="utf-8")
            try:
                # Open in foreground, suppressing output
                subprocess.run(["gvim", "-f", str(dump_file)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as e:
                print(f"Warning: Failed to open gvim: {e}")

            from qa_agent.output import bold, arrow_select
            import sys
            try:
                ans = arrow_select(
                    f"{bold('?')} Review complete. Send the payload to the AI? Proceed?",
                    [("Proceed", "send payload to AI"), ("Stop", "abort and exit")]
                )
                if ans != 0:
                    print("  AI request stopped by user. Exiting.")
                    sys.exit(0)
            except KeyboardInterrupt:
                print("\n  AI request stopped by user. Exiting.")
                sys.exit(0)

        response = await provider_mod.chat_with_tools(request)

        ai_content: str | None = response.get("content")
        ai_tool_calls: list[dict] | None = response.get("tool_calls")

        # ── Final report — no tool calls ─────────────────────────────────────
        if not ai_tool_calls:
            if ai_content:
                if on_text_chunk:
                    on_text_chunk(ai_content)
                return ai_content
            # Empty response — ask the AI to conclude
            messages.append({
                "role": "user",
                "content": "Please write your final debug report now.",
            })
            continue

        # ── Tool calls — execute each ─────────────────────────────────────────
        _append_assistant_turn(messages, ai_content, ai_tool_calls)

        tool_results = []
        for tc in ai_tool_calls:
            tc_id = tc.get("id", f"call_{turn}")
            tc_name = tc.get("name", "")
            tc_args = tc.get("arguments", {})

            if verbose or on_tool_call:
                if verbose:
                    print(f"  [tool] {tc_name}({json.dumps(tc_args, separators=(',', ':'))})")
                if on_tool_call:
                    on_tool_call(tc_name, tc_args)

            # Interactive tool execution user prompt
            from qa_agent.output import cyan, bold, arrow_select
            import sys
            try:
                ans = arrow_select(
                    f"{bold('?')} AI requested tool {cyan(tc_name)}. Proceed?",
                    [("Proceed", "allow execution"), ("Stop", "abort and exit")]
                )
                if ans != 0:
                    print(f"  Tool execution stopped by user. Exiting.")
                    sys.exit(0)
            except KeyboardInterrupt:
                print(f"\n  Tool execution stopped by user. Exiting.")
                sys.exit(0)

            result = tools.execute(tc_id, tc_name, tc_args)

            if verbose or on_tool_result:
                status = "ERROR" if result.error else ("TRUNCATED" if result.truncated else "OK")
                if verbose:
                    preview = result.content[:120].replace("\n", "↵")
                    print(f"  [tool result] {tc_name} [{status}]: {preview}")
                if on_tool_result:
                    on_tool_result(tc_name, result.content, result.truncated)

            tool_results.append({
                "tool_call_id": result.tool_call_id,
                "name": result.name,
                "content": result.content,
                "truncated": result.truncated,
                "error": result.error,
            })

        _append_tool_results(messages, tool_results)

    # ── Exhausted max_turns ───────────────────────────────────────────────────
    # Request a final summary from whatever the AI has gathered so far
    messages.append({
        "role": "user",
        "content": (
            "You have reached the maximum number of investigation turns. "
            "Write the final debug report now based on what you have found so far."
        ),
    })

    request = ToolCallRequest(messages=messages, tools=tools, model=model, max_tokens=max_tokens)
    final_response = await provider_mod.chat_with_tools(request)
    final_text = final_response.get("content") or ""
    return final_text or "[No report generated — max_turns exhausted without a text response]"
