"""qa_agent/tools/loop.py

Provider-agnostic agentic tool-calling loop.

Entry point:
    final_report = await run_tool_loop(
        provider_name="claude",
        messages=[...],
        tools=registry,
        system_prompt=AGENT_SYSTEM_PROMPT,
        max_turns=20,
        verbose=False,
        use_gvim=False,
        auto_accept=False,
    )

UI flow (agentic mode with interactive approval):
  1. AI requests tool call.
  2. Loop executes the tool immediately (collect result).
  3. render_tool_result_card() shows data preview to user.
     - Normal mode: first 15 lines of result, status badge, no tool internals.
     - Verbose mode: adds tool name + args above preview.
     - gvim mode:  opens full result in gvim, then shows Accept/Reject.
     - Auto-accept: skips card, feeds result directly.
  4. User chooses:
     - Accept → append tool result to AI conversation.
     - Reject + message → append user message instead (tool result discarded).
  5. Tab+Shift inside card toggles auto-accept for the rest of the session.
"""

from __future__ import annotations

import json
from typing import Callable

from qa_agent.tools.registry import ToolRegistry


# ─────────────────────────────────────────────────────────────────────────────
# Provider module loader
# ─────────────────────────────────────────────────────────────────────────────

def _load_provider(provider_name: str):
    """Import and return the provider module for *provider_name*."""
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

def _append_assistant_turn(
    messages: list[dict],
    content: str | None,
    tool_calls: list[dict] | None,
) -> None:
    """Append the assistant's response to the message history."""
    msg: dict = {"role": "assistant"}
    if content:
        msg["content"] = content
    if tool_calls:
        msg["tool_calls"] = tool_calls
    messages.append(msg)


def _append_tool_result(messages: list[dict], result_dict: dict) -> None:
    """Append a single tool result to the message history."""
    suffix = " [TRUNCATED]" if result_dict.get("truncated") else ""
    messages.append({
        "role": "tool",
        "tool_call_id": result_dict["tool_call_id"],
        "name": result_dict["name"],
        "content": result_dict["content"] + suffix,
    })


def _append_tool_results(messages: list[dict], results: list[dict]) -> None:
    """Append all tool results from a single turn at once."""
    for r in results:
        _append_tool_result(messages, r)


# ─────────────────────────────────────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────────────────────────────────────

async def run_tool_loop(
    provider_name: str,
    messages: list[dict],
    tools: ToolRegistry,
    *,
    system_prompt: str = "",
    max_turns: int = 20,
    model: str = "",
    max_tokens: int = 4096,
    verbose: bool = False,
    use_gvim: bool = False,
    auto_accept: bool = False,
    on_text_chunk: Callable[[str], None] | None = None,
) -> str:
    """Run an agentic tool-calling loop until the AI produces a final report.

    Each iteration:
      1. Call provider.chat_with_tools() with the current message history.
      2. If the response has tool_calls:
         a. Execute each tool immediately (collect result).
         b. Show render_tool_result_card() — user accepts or rejects.
         c. Append result (accepted) or user message (rejected) to history.
         d. Continue to next turn.
      3. If the response is plain text (no tool_calls) → return it as the
         final report string.
      4. Stop after max_turns and request the AI to conclude.

    Args:
        provider_name:  "claude", "openai", or "gemini".
        messages:       Initial conversation history (mutable — loop appends).
        tools:          ToolRegistry with all available tools.
        system_prompt:  System prompt injected as the first system message.
        max_turns:      Maximum total turns before forcing conclusion.
        model:          Optional model name override.
        max_tokens:     Max completion tokens per turn.
        verbose:        If True, show tool name/args in the data preview card.
        use_gvim:       If True, open tool results in gvim for review.
        auto_accept:    If True, start with auto-accept ON (skip all cards).
        on_text_chunk:  Optional callback(chunk) for streaming text fragments.

    Returns:
        The AI's final text response (the debug report).
    """
    from qa_agent.providers import ToolCallRequest
    from qa_agent.output import render_tool_result_card, console

    provider_mod = _load_provider(provider_name)

    # Mutable wrapper so render_tool_result_card can toggle it via lambda
    auto_accept_state: list[bool] = [auto_accept]

    # Inject system prompt as a system message if the provider supports it
    # (We prepend it rather than using a separate parameter so all providers
    #  receive it uniformly through the messages list.)
    if system_prompt:
        if not messages or messages[0].get("role") != "system":
            messages.insert(0, {"role": "system", "content": system_prompt})

    for turn in range(1, max_turns + 1):

        # ── Warn AI as it approaches the limit ────────────────────────────────
        if turn == max_turns - 2:
            messages.append({
                "role": "user",
                "content": (
                    f"You have approximately {max_turns - turn} turns remaining. "
                    "Please start concluding your investigation and write the "
                    "final structured Markdown debug report now."
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

        # ── Tool calls — execute each, then show card ─────────────────────────
        _append_assistant_turn(messages, ai_content, ai_tool_calls)

        for tc in ai_tool_calls:
            tc_id = tc.get("id", f"call_{turn}")
            tc_name = tc.get("name", "")
            tc_args = tc.get("arguments", {})

            # Step 1: Execute the tool immediately
            result = tools.execute(tc_id, tc_name, tc_args)

            # Step 2: Show data preview card and get user decision
            accepted, user_message = render_tool_result_card(
                tool_name=tc_name,
                args=tc_args,
                result_content=result.content,
                truncated=result.truncated,
                error=result.error,
                verbose=verbose,
                use_gvim=use_gvim,
                auto_accept_state=auto_accept_state,
            )

            if accepted:
                # Step 3a: User accepted — feed full result to AI
                _append_tool_result(messages, {
                    "tool_call_id": result.tool_call_id,
                    "name": result.name,
                    "content": result.content,
                    "truncated": result.truncated,
                    "error": result.error,
                })
            else:
                # Step 3b: User rejected — feed their message to AI instead
                # The tool result is discarded; AI gets the user's guidance.
                # We still need to close the tool call cleanly, so we send
                # a minimal placeholder tool result + the user note.
                _append_tool_result(messages, {
                    "tool_call_id": result.tool_call_id,
                    "name": result.name,
                    "content": "[User reviewed this data and provided feedback below.]",
                    "truncated": False,
                    "error": False,
                })
                # Then inject the user's message as the next turn input
                messages.append({
                    "role": "user",
                    "content": user_message or "Please try a different approach.",
                })
                # Break the inner loop — start a new AI turn with user input
                break

    # ── Exhausted max_turns ───────────────────────────────────────────────────
    messages.append({
        "role": "user",
        "content": (
            "You have reached the maximum number of investigation turns. "
            "Write the final debug report now based on what you have found so far."
        ),
    })

    request = ToolCallRequest(
        messages=messages,
        tools=tools,
        model=model,
        max_tokens=max_tokens,
    )
    final_response = await provider_mod.chat_with_tools(request)
    final_text = final_response.get("content") or ""
    return final_text or "[No report generated — max_turns exhausted without a text response]"
