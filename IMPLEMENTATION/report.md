# `qa-agent report` — AI-Driven Debug Report from Simulation Output

## Purpose

Generate a structured debug report from Questa/Visualizer simulation output using an agentic AI loop. The AI acts as a specialized expert DV engineer that investigates failures by requesting targeted data through sanitized tool calls — it **never** sees raw files or full logs directly.

---

## Architecture

```
Visualizer output (qrun.out/, logs/, tracker, waveforms)
        │
  [tools/report/]        ── tool handlers: extract, filter, sanitize
        │
  [tools/registry.py]    ── ToolRegistry: validate, execute, cap output
        │
  [tools/loop.py]        ── agentic loop: AI → tool call → result → AI → ...
        │
  [provider.chat_with_tools()]  ── claude/openai/gemini API transport
        │
  [agents/dv_debug_agent.py]    ── expert DV engineer persona + investigation strategy
        │
  [report.py]            ── orchestrator: CLI args → agent → write report
```

### Data Flow

```
AI sends tool_call request
       │
       ▼
tool_loop.py intercepts ──► tools/registry.py validates + dispatches
                                    │
                                    ▼
                            tools/report/<handler>.py
                            ┌─ validate_path() (no traversal)
                            ├─ read/grep target file
                            ├─ filter to relevant lines only
                            ├─ cap output size (8KB max)
                            └─ return sanitized result
                                    │
                                    ▼
                            tool_loop.py appends result to messages
                                    │
                                    ▼
                            AI receives filtered data, reasons, asks next tool
                                    │
                                    ▼
                            (repeat until AI produces final report)
```

---

## Package Layout

```
qa_agent/
├── tools/                              # Reusable agentic tool infrastructure
│   ├── __init__.py                     # Re-exports: ToolDef, ToolResult, ToolRegistry
│   ├── registry.py                     # Core: ToolDef, ToolResult, ToolRegistry
│   ├── loop.py                         # Provider-agnostic agentic tool-calling loop
│   └── report/                         # Tools specific to the report command
│       ├── __init__.py                 # build_report_tools(sim_dir) → ToolRegistry
│       ├── security.py                 # Path validation, output sanitization, allowlists
│       ├── sim_metadata.py             # list_sim_files, read_sim_metadata
│       ├── log_errors.py               # extract_log_errors
│       ├── assertions.py               # get_assertion_failures
│       ├── scoreboard.py               # get_scoreboard_mismatches
│       ├── tracker.py                  # extract_tracker_failures
│       ├── signals.py                  # read_signal_values
│       └── fixtures.py                 # Test fixture generator (mock sim data)
│
├── agents/                             # AI agent definitions (persona + orchestration)
│   ├── __init__.py
│   └── dv_debug_agent.py              # DV debug expert: system prompt, investigation loop
│
├── report.py                           # Thin orchestrator: CLI args → agent → write report
└── ...
```

---

## Security Model

The AI agent operates in a **sandboxed data environment**. It has zero direct filesystem access. Additionally, the execution layer of the agent itself (`claude_provider.py`, `openai_provider.py`, `gemini_provider.py`) is forcefully jailed to an empty generated `/tmp/.qa-agent` workspace while executing. Every piece of data it receives passes through a tool handler that enforces:

### Path Containment (`tools/report/security.py`)
- All requested paths are resolved and validated to be **within** `sim_dir`
- Symlinks are resolved before validation — no symlink traversal
- Raises `PathError` on any traversal attempt

### Content Filtering
- **Never** return full log files — only matching error/warning lines with limited context
- Metadata files restricted to a hardcoded **allowlist** (`big_argv`, `history`, `stats_log`, `top_dus`, `version`)
- Tracker/signal data filtered by time window and failure markers only

### Output Size Caps
- Per-tool output capped at **8,000 characters** (configurable via `ToolRegistry.max_output_chars`)
- Metadata reads capped at **4KB**
- Error extraction limited to **50 matches** per call
- Truncated results flagged with `truncated=True` so the AI knows data was cut

### Read-Only
- No tool modifies the filesystem
- All handlers are pure read + filter operations

---

## Tool Reference

### `list_sim_files`
| Field | Value |
|-------|-------|
| **Module** | `tools/report/sim_metadata.py` |
| **Purpose** | List files available in the simulation output directory |
| **Parameters** | `subdir: str` (optional — e.g. `"qrun.out"`, `"logs"`) |
| **Returns** | JSON list of `{name, size_bytes, type}` |
| **Security** | Lists only, never reads content. Filters to known file types. |

### `read_sim_metadata`
| Field | Value |
|-------|-------|
| **Module** | `tools/report/sim_metadata.py` |
| **Purpose** | Read metadata from `qrun.out/` |
| **Parameters** | `file: str` (one of: `big_argv`, `history`, `stats_log`, `top_dus`, `version`) |
| **Returns** | File content (truncated at 4KB) |
| **Security** | Allowlisted files only. Size-capped. |

### `extract_log_errors`
| Field | Value |
|-------|-------|
| **Module** | `tools/report/log_errors.py` |
| **Purpose** | Grep error/warning lines from simulation logs |
| **Parameters** | `log_file: str` (`sim.log`, `compile.log`, `run.log`), `pattern: str` (optional regex), `context_lines: int` (default 3) |
| **Returns** | Matched error lines with surrounding context |
| **Security** | Only returns lines matching error/warning/fatal patterns. Max 50 matches. Log file must be from allowlist. |

### `get_assertion_failures`
| Field | Value |
|-------|-------|
| **Module** | `tools/report/assertions.py` |
| **Purpose** | Extract SystemVerilog assertion failures |
| **Parameters** | `log_file: str` (optional, defaults to `sim.log`) |
| **Returns** | JSON array of `{assertion, time, module, message}` |
| **Security** | Filters to assertion failure lines only. |

### `get_scoreboard_mismatches`
| Field | Value |
|-------|-------|
| **Module** | `tools/report/scoreboard.py` |
| **Purpose** | Extract scoreboard mismatch summary |
| **Parameters** | `log_file: str` (optional, defaults to `sim.log`) |
| **Returns** | JSON `{total_mismatches, first_time, last_time, components: [{name, expected, actual, count}]}` |
| **Security** | Aggregated summary only, not raw comparison data. |

### `extract_tracker_failures`
| Field | Value |
|-------|-------|
| **Module** | `tools/report/tracker.py` |
| **Purpose** | Get tracker entries around failure time |
| **Parameters** | `time_start: int` (optional), `time_end: int` (optional), `component: str` (optional filter) |
| **Returns** | JSON array of `{time, component, signal, event, message}` |
| **Security** | Time-windowed. Failure/mismatch entries only. |

### `read_signal_values`
| Field | Value |
|-------|-------|
| **Module** | `tools/report/signals.py` |
| **Purpose** | Read specific signal values at specific simulation times |
| **Parameters** | `signals: list[str]`, `time: int`, `window: int` (default 100 time units) |
| **Returns** | JSON table of `{signal, time, value}` rows |
| **Security** | Only requested signals. Short time window enforced. |

---

## Core Framework

### `ToolDef` (dataclass)
```python
name: str              # Unique identifier used by AI (e.g. "extract_log_errors")
description: str       # Shown to AI in tool schema
parameters: dict       # JSON Schema for input validation
handler: Callable      # Sync function(**kwargs) → str
```

### `ToolResult` (dataclass)
```python
tool_call_id: str      # Correlates with AI's request
name: str              # Tool that was called
content: str           # Sanitized, size-capped result
truncated: bool        # True if output was cut
```

### `ToolRegistry`
```python
register(tool: ToolDef) → None
get(name: str) → ToolDef | None
all_defs() → list[ToolDef]
to_openai_schema() → list[dict]     # OpenAI function-calling format
to_claude_schema() → list[dict]     # Anthropic tool format
to_gemini_schema() → list[dict]     # Google function declaration format
execute(tool_call_id, name, arguments) → ToolResult
```

`execute()` is the security enforcement point:
1. Validates tool name exists
2. Calls the handler
3. Truncates output to `max_output_chars`
4. Catches handler exceptions → returns error result (never crashes the loop)

### `run_tool_loop()` (async)
```python
async def run_tool_loop(
    provider_name: str,
    messages: list[dict],
    tools: ToolRegistry,
    *,
    max_turns: int = 15,
    verbose: bool = False,
    on_tool_call: Callable | None = None,
    on_tool_result: Callable | None = None,
    on_text_chunk: Callable | None = None,
) -> str:
```

Each iteration:
1. Send messages + tool schemas to `provider.chat_with_tools()`
2. If response contains `tool_calls` → execute each via `ToolRegistry.execute()`, append results
3. If response is text → return as final report
4. Stop at `max_turns` and request the AI to conclude

---

## Agent: DV Debug Expert (`agents/dv_debug_agent.py`)

### System Prompt (summary)

The agent is instructed to:
1. **First**, list available files to understand what data exists
2. **Then**, read simulation metadata for test configuration context
3. **Then**, extract errors from logs (compile.log first, then sim.log)
4. **Then**, check assertion failures and scoreboard mismatches
5. **Only if needed**, examine tracker data and signal values around failure time
6. **Stop** investigating when enough evidence exists for a conclusion

### Efficiency Rules (in system prompt)
- Request only what you need — do not dump entire logs
- Use specific patterns when searching logs
- Request signal values only for signals mentioned in error messages
- Stop investigating when you have enough evidence

### Output Format (enforced by system prompt)
```markdown
## Root Cause Summary
## Failure Classification
## Affected Component/Module
## Evidence
## Suggested Debugging Direction
```

---

## Provider Integration

Each provider module gains a new function alongside the existing `stream()`:

```python
async def chat_with_tools(request: ToolCallRequest) -> dict
```

Returns:
```python
{
    "role": "assistant",
    "content": str | None,        # text response (final turn)
    "tool_calls": list[dict] | None  # tool call requests (intermediate turns)
}
```

| Provider | SDK Used | Notes |
|----------|----------|-------|
| Claude | `anthropic` (direct API) | Uses Anthropic Messages API, **not** `claude-agent-sdk`, to intercept tool calls locally |
| OpenAI | `openai` | `chat.completions.create(tools=..., tool_choice="auto")` |
| Gemini | `google-genai` | `models.generate_content(tools=...)` with function-calling |

**Why not `claude-agent-sdk` for tool calling?** The Agent SDK executes tools internally (it wraps Claude Code CLI). We need to intercept tool calls at the API level so that our local tool handlers run — this is the security boundary.

---

## Token Optimization

| Strategy | Mechanism |
|----------|-----------|
| Incremental investigation | System prompt guides AI to ask for data progressively |
| Output caps | 8KB per tool result; 4KB for metadata; 50 max error matches |
| Structured output | Tools return compact JSON, not verbose text |
| Filter parameters | Time windows, signal names, regex patterns narrow data at extraction |
| Turn limit | Default 15 turns; AI prompted to conclude when turns are running low |
| Aggregation tools | `get_scoreboard_mismatches` returns stats, not raw data |

---

## CLI Interface

```
qa-agent report SIM_DIR [--provider/-p {claude,openai,gemini}]
                        [--output/-o PATH]
                        [--max-turns N]
                        [--verbose/-v]
```

| Flag | Default | Description |
|------|---------|-------------|
| `SIM_DIR` | (required) | Simulation output directory (contains `qrun.out/`, `logs/`, etc.) |
| `--provider/-p` | `claude` | AI provider |
| `--output/-o` | `debug_report_<timestamp>.md` | Output report path |
| `--max-turns` | `15` | Max AI investigation turns |
| `--verbose/-v` | off | Show tool calls, raw AI reasoning |

---

## Testing

### Fixture System (`tools/report/fixtures.py`)

Creates realistic mock simulation directories for testing without real Visualizer data.

| Scenario | What it plants |
|----------|---------------|
| `assertion_failure` | SVA assertion failure in sim.log, clean compile |
| `scoreboard_mismatch` | Expected vs actual mismatch entries |
| `compile_error` | Compilation errors in compile.log |
| `timeout` | Simulation timeout in sim.log |
| `multi_failure` | Multiple failure types combined |

Each creates: `qrun.out/` with metadata, `logs/` with planted errors, tracker data, mock signal data.

### Test Files

| File | Scope |
|------|-------|
| `tests/test_tools_registry.py` | ToolRegistry: register, execute, schema conversion, truncation |
| `tests/test_tools_report.py` | Each tool handler with fixture data; path traversal rejection |
| `tests/test_tools_loop.py` | Agentic loop with mocked provider; max_turns; error handling |
| `tests/test_report.py` | End-to-end: fixture → mocked provider → report output |

### Manual Testing

```bash
# Generate a fixture
python -c "from qa_agent.tools.report.fixtures import create_fixture; \
           create_fixture('/tmp/test_sim', 'assertion_failure')"

# Run report
qa-agent report /tmp/test_sim --verbose
qa-agent report /tmp/test_sim -p openai
qa-agent report /tmp/test_sim -p gemini -o my_report.md
```

---

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `anthropic` | ≥ 0.30 | Claude tool-calling via Messages API (new) |
| `openai` | (existing) | OpenAI function calling |
| `google-genai` | (existing) | Gemini function calling |

---

## Implementation Order

1. `qa_agent/errors.py` — add `ToolExecutionError`
2. `qa_agent/tools/__init__.py` + `registry.py` — tool registry
3. `qa_agent/tools/report/security.py` — path validation + sanitization
4. `qa_agent/tools/report/fixtures.py` — fixture generator
5. `qa_agent/tools/report/*.py` — all tool handler modules
6. `qa_agent/tools/report/__init__.py` — `build_report_tools()`
7. `qa_agent/providers.py` — add `ToolCallRequest`
8. Provider extensions — `chat_with_tools()` in all three providers
9. `qa_agent/tools/loop.py` — agentic loop
10. `qa_agent/agents/dv_debug_agent.py` — agent persona
11. `qa_agent/report.py` — orchestrator
12. `qa_agent/cli.py` — add subparser + dispatch
13. `qa_agent/guide.py` — add report guide
14. Tests
15. Update `CLAUDE.md` file structure + command table
