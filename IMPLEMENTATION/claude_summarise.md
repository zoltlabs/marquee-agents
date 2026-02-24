# IMPLEMENTATION: Claude Provider for `qa-agent summarise`

> Claude-specific detail for the `summarise` command.
> See [`summarise.md`](./summarise.md) for the full command architecture.

---

## Module

`qa_agent/claude_summariser.py`

Implements the standard provider interface:

```python
PROVIDER_NAME: str                                          # "Claude (Anthropic)"
async def stream(cwd: str, paths: list[str]) -> AsyncIterator[str]:
    # paths == []          → summarise cwd (Glob + Read)
    # paths == ["/dir"]    → summarise that directory (Glob + Read)
    # paths == ["/f", ...] → summarise those exact files (Read only)
```

---

## Modes

### Directory mode

Triggered when `paths` is empty or contains a single directory.

```python
allowed_tools = ["Glob", "Read"]
agent_cwd     = target_dir   # cwd when paths=[]; else paths[0]
```

The agent globs all files recursively, reads each one, and produces an ASCII
directory tree followed by per-file explanations.

### File mode

Triggered when `paths` contains one or more file paths.

```python
allowed_tools = ["Read"]
agent_cwd     = cwd          # original working directory
```

The agent reads only the explicitly listed files and produces per-file
explanations (no directory tree).

---

## Authentication

Checked in order:

### 1. API Key
```bash
export ANTHROPIC_API_KEY=sk-ant-...
qa-agent summarise
```
If `ANTHROPIC_API_KEY` is in the environment (or a `.env` file in the current directory),
it is passed via `ClaudeAgentOptions(env=...)` to the SDK subprocess.

### 2. OAuth (Claude Code CLI)
```bash
npm install -g @anthropic-ai/claude-code
claude login
qa-agent summarise        # no env var needed
```
If no API key is set but `claude` is on `$PATH`, the CLI's stored OAuth session is used.
No env override is passed — the SDK subprocess reads credentials from the CLI.

### Auth failure
```
✗ Authentication failed.

  Option 1 — API key:
    export ANTHROPIC_API_KEY=sk-ant-...

  Option 2 — Claude Code CLI OAuth:
    npm install -g @anthropic-ai/claude-code
    claude login
```
Exits with code 1.

---

## SDK Options

```python
# Directory mode
ClaudeAgentOptions(
    allowed_tools=["Glob", "Read"],
    system_prompt=_SYSTEM_PROMPT_DIRECTORY,
    cwd=target_dir,
    env=env_override,
    max_turns=10,
)

# File mode
ClaudeAgentOptions(
    allowed_tools=["Read"],
    system_prompt=_SYSTEM_PROMPT_FILES,
    cwd=cwd,
    env=env_override,
    max_turns=10,
)
```

---

## Prompts

| Prompt | Mode | Purpose |
|--------|------|---------|
| `_SYSTEM_PROMPT_DIRECTORY` | Directory | Constrains to ASCII tree + `### file` headings |
| `_SYSTEM_PROMPT_FILES` | File(s) | Constrains to `### file` headings, no tree |
| `_USER_PROMPT_DIRECTORY` | Directory | Instructs agent to glob → read → summarise |
| `_user_prompt_files(paths)` | File(s) | Lists explicit files for the agent to read |

---

## Error Types Raised

All caught by `summarise.py`:

| Exception | Cause |
|-----------|-------|
| `RuntimeError` | Auth failure (from `_resolve_auth()`) |
| `CLINotFoundError` | `claude` CLI binary not found |
| `CLIConnectionError` | Claude Code process failed to start |
| `ProcessError` | Agent process exited non-zero |
| `CLIJSONDecodeError` | Malformed SDK response |

---

## Status

| Field | Value |
|-------|-------|
| Status | ✅ Active |
| SDK | `claude-agent-sdk` |
| Model | Default (set by SDK) |
