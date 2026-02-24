# IMPLEMENTATION: `qa-agent summarise`

> **Agent context document** — full detail for the `summarise` command.
> See [`CLAUDE.md`](../CLAUDE.md) for the project overview.

---

## Purpose

`qa-agent summarise` analyses one or more files or directories using an AI SDK
and prints a plain-English explanation.

- **No args** — analyses the current working directory (pwd)
- **Directory arg** — analyses that directory recursively
- **File arg(s)** — reads and explains exactly those files

The command is **provider-agnostic** — Claude is the default and the only current
provider, but the architecture allows adding OpenAI, Gemini, etc. with no changes to the
orchestrator.

---

## CLI

```bash
qa-agent summarise                         # summarise cwd (default)
qa-agent summarise .                       # same, explicit
qa-agent summarise src/                    # summarise a directory
qa-agent summarise main.py                 # summarise a single file
qa-agent summarise a.py b.py c.py         # summarise multiple files
qa-agent summarise -claude                 # explicit Claude flag (default)
qa-agent summarise -openai                 # use OpenAI (GPT-4o)
qa-agent summarise -gemini                 # use Google Gemini
```

---

## Module Responsibilities

| Module | Role |
|--------|------|
| `qa_agent/cli.py` | Registers `summarise` command + `paths` positional + provider flags; dispatches to `summarise.run()` |
| `qa_agent/summarise.py` | Orchestrator: path resolution, **prompt/tool construction**, provider routing, ANSI output, error handling |
| `qa_agent/providers.py` | Shared `ProviderRequest` dataclass — the contract between orchestrator and providers |
| `qa_agent/claude_provider.py` | Claude provider: auth + Claude SDK streaming. No prompt logic. |
| `qa_agent/openai_provider.py` | OpenAI provider: auth + streaming Chat Completions. No prompt logic. |
| `qa_agent/gemini_provider.py` | Gemini provider: auth + streaming generate_content. No prompt logic. |

### Provider Interface Contract

Every provider module **must** expose:

```python
from qa_agent.providers import ProviderRequest

PROVIDER_NAME: str                                          # e.g. "Claude (Anthropic)"
async def stream(request: ProviderRequest) -> AsyncIterator[str]:
    # Yield plain-text chunks from the AI
```

`summarise.py` builds the `ProviderRequest` (with prompts + tools), then calls
`provider.stream(request)`. Providers are pure AI-SDK drivers — they contain no
command-specific logic.

---

## ProviderRequest Fields

| Field | Type | Description |
|-------|------|-------------|
| `system_prompt` | `str` | Instruction text for the AI |
| `user_prompt` | `str` | Task/question to answer |
| `agent_cwd` | `str` | Working directory the agent operates in |
| `allowed_tools` | `list[str]` | Tools the agent may call |
| `max_turns` | `int` | Max agentic round-trips (default 10) |
| `extra` | `dict` | Provider-specific overrides (model, temperature, etc.) |

---

## Mode Selection (in `summarise.py → _build_request()`)

| Input | `agent_cwd` | `allowed_tools` | Mode |
|-------|-------------|-----------------|------|
| *(nothing)* → `[]` | cwd | `["Glob", "Read"]` | Directory |
| `[\"/abs/dir\"]` | that dir | `["Glob", "Read"]` | Directory |
| `[\"/f1\", ...]` | cwd | `["Read"]` | Files |

---

## Path Resolution (in `summarise.py → _resolve_paths()`)

| Input | Resolved to |
|-------|-------------|
| *(nothing)* | `[]` → cwd |
| `.` or `folder/` | `["/abs/dir"]` |
| `file.py` | `["/abs/file.py"]` |
| `a.py b.py` | `["/abs/a.py", "/abs/b.py"]` |

Path validation: each path is checked with `os.path.exists()` before being forwarded. Non-existent paths print an error and exit 1.

---

## Adding a New Provider

1. Create `qa_agent/<name>_provider.py` implementing `PROVIDER_NAME` + `stream(request: ProviderRequest)`.
2. In `summarise.py → _get_provider()`, add `if name == "<name>": ...`.
3. In `cli.py`, add the `-<name>` flag to the provider group.
4. Create `IMPLEMENTATION/<name>_sdk.md` with auth, deps, and error details.

The provider does **not** need to know about `summarise`-specific prompts — those
live in `summarise.py`. A provider can be reused by any other command.

---

## Security Constraints

| Constraint | Detail |
|------------|--------|
| `agent_cwd` locked | Set per mode in `_build_request()`; agent cannot leave the target directory |
| `allowed_tools` | Directory mode: `["Glob", "Read"]`; File mode: `["Read"]` — no Bash, Write, or Edit |
| Path validation | All user-supplied paths are resolved to absolute paths and existence-checked before use |

---

## Provider Auth Summary

| Provider | Flag | Auth Option 1 | Auth Option 2 |
|----------|------|---------------|---------------|
| Claude | `-claude` | `ANTHROPIC_API_KEY` | `claude login` (Claude Code CLI) |
| OpenAI | `-openai` | `OPENAI_API_KEY` | `codex login` (Codex CLI) |
| Gemini | `-gemini` | `GEMINI_API_KEY` | `gcloud auth application-default login` |

See the per-provider SDK docs for details:
- [`claude_sdk.md`](./claude_sdk.md)
- [`openai_sdk.md`](./openai_sdk.md)
- [`gemini_sdk.md`](./gemini_sdk.md)

---

## Error Handling (centralised in `summarise.py`)

| Error | Message |
|-------|---------|
| Path not found | "Path not found: '<path>'" |
| SDK not installed | `pip install claude-agent-sdk` |
| Auth failure | Instructions for both methods |
| `CLINotFoundError` | `npm install -g @anthropic-ai/claude-code` |
| `CLIConnectionError` | Connection detail |
| `ProcessError` | Exit code + detail |
| `CLIJSONDecodeError` | Parse failure detail |
| `KeyboardInterrupt` | "Interrupted" → exit 1 |
| Generic `Exception` | Message → exit 1 |

---

## Status

| Field | Value |
|-------|-------|
| Status | ✅ Implemented |
| Providers | `claude` (default) |
| Added in | `feat/summarise-cmd` |
