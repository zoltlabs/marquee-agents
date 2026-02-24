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
# Future:
# qa-agent summarise -openai
# qa-agent summarise -gemini
```

---

## Module Responsibilities

| Module | Role |
|--------|------|
| `qa_agent/cli.py` | Registers `summarise` command + `paths` positional + provider flags; dispatches to `summarise.run()` |
| `qa_agent/summarise.py` | Orchestrator: path resolution, provider routing, ANSI output formatting, error handling |
| `qa_agent/claude_summariser.py` | Claude provider: auth resolution, SDK streaming, mode selection (dir vs files) |

### Provider Interface Contract

Every provider module **must** expose:

```python
PROVIDER_NAME: str                                          # e.g. "Claude (Anthropic)"
async def stream(cwd: str, paths: list[str]) -> AsyncIterator[str]:
    # paths == []         → summarise cwd as a directory
    # paths == ["/dir"]   → summarise that directory
    # paths == ["/f1"...] → summarise exactly those files
```

`summarise.py` resolves CLI paths to absolute paths, then imports the provider
and calls `stream(cwd, paths)`. Output formatting and error handling are
entirely in `summarise.py`.

---

## Path Resolution (in `summarise.py`)

| Input | Resolved to | Agent mode |
|-------|-------------|------------|
| *(nothing)* | `[]` → cwd | Directory (Glob + Read) |
| `.` or `folder/` | `["/abs/dir"]` | Directory (Glob + Read) |
| `file.py` | `["/abs/file.py"]` | Files (Read only) |
| `a.py b.py` | `["/abs/a.py", "/abs/b.py"]` | Files (Read only) |

Path validation: each path is checked with `os.path.exists()` before being forwarded to the provider. Non-existent paths print an error and exit 1.

---

## Adding a New Provider

1. Create `qa_agent/<name>_summariser.py` implementing `PROVIDER_NAME` + `stream(cwd, paths)`.
2. In `summarise.py → _get_provider()`, add `elif name == "<name>": ...`.
3. In `cli.py`, uncomment (or add) the `-<name>` flag in the provider group.
4. Create `IMPLEMENTATION/<name>_summarise.md` with auth, deps, and error details.

---

## Security Constraints

| Constraint | Detail |
|------------|--------|
| `cwd` locked | `os.getcwd()` captured at call-time; agent cannot leave the target directory |
| `allowed_tools` | Directory mode: `["Glob", "Read"]`; File mode: `["Read"]` — no Bash, Write, or Edit |
| Path validation | All user-supplied paths are resolved to absolute paths and existence-checked before use |

---

## Claude Provider — Auth

See [`claude_summarise.md`](./claude_summarise.md) for full Claude auth detail.

Short version — checked in order:
1. `ANTHROPIC_API_KEY` env var (or `.env` in pwd)
2. `claude login` OAuth session (Claude Code CLI must be installed)
3. Error printed + exit 1

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
