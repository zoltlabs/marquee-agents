# IMPLEMENTATION: Claude Provider (`qa_agent/claude_provider.py`)

> Claude-specific SDK detail.
> See [`summarise.md`](./summarise.md) for the full command architecture.

---

## Module

`qa_agent/claude_provider.py`

Implements the standard provider interface (see `qa_agent/providers.py`):

```python
PROVIDER_NAME: str = "Claude (Anthropic)"
async def stream(request: ProviderRequest) -> AsyncIterator[str]
```

This module is a **generic Claude SDK driver** — it contains no
summarise-specific logic. Any command can use it by building a
`ProviderRequest` and calling `stream(request)`.

---

## Authentication

Checked in order by `_resolve_auth()`:

### 1. API Key
```bash
export ANTHROPIC_API_KEY=sk-ant-...
```
Passed via `ClaudeAgentOptions(env=...)` to the SDK subprocess.

### 2. OAuth (Claude Code CLI)
```bash
npm install -g @anthropic-ai/claude-code
claude login
```
If `claude` is on `$PATH` and no API key is set, the CLI's stored OAuth session is used.

### Auth failure message
```
✗ Authentication failed.

  Option 1 — API key:
    export ANTHROPIC_API_KEY=sk-ant-...

  Option 2 — Claude Code CLI OAuth:
    npm install -g @anthropic-ai/claude-code
    claude login
```

---

## SDK Options

```python
ClaudeAgentOptions(
    allowed_tools=request.allowed_tools,   # from ProviderRequest
    system_prompt=request.system_prompt,   # from ProviderRequest
    cwd=request.agent_cwd,                 # from ProviderRequest
    env=env_override,                      # {} or {"ANTHROPIC_API_KEY": "..."}
    max_turns=request.max_turns,           # default 10
)
```

---

## ProviderRequest.extra Keys

| Key | Default | Description |
|-----|---------|-------------|
| *(none currently)* | — | Claude model is set by the SDK |

---

## Error Types Raised

| Exception | Cause |
|-----------|-------|
| `RuntimeError` | Auth failure |
| `CLINotFoundError` | `claude` binary not found |
| `CLIConnectionError` | Claude Code process failed to start |
| `ProcessError` | Agent exited non-zero |
| `CLIJSONDecodeError` | Malformed SDK response |

---

## Status

| Field | Value |
|-------|-------|
| Status | ✅ Active |
| SDK | `claude-agent-sdk` |
| Install | `pip install claude-agent-sdk` |
