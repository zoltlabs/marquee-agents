# CLAUDE.md — AI Assistant Context for marquee-agents

High-level overview. For per-command implementation detail, see [`IMPLEMENTATION/`](./IMPLEMENTATION/).

---

## Project Overview

| Field | Value |
|-------|-------|
| **Project** | marquee-agents |
| **Purpose** | Automate post-regression triage for DV engineers |
| **Audience** | DV (Development / Validation) engineers on the server team |
| **Type** | Python CLI tool |
| **Entry-point** | `qa-agent` (registered via `pyproject.toml`) |
| **Language** | Python ≥ 3.10 |
| **Owner** | Zolt Labs |

---

## The Problem Being Solved

After every regression run, DV engineers must manually triage failures — finding
configs, seeds, re-running debug scripts, and correlating logs. For 10+ failures
this takes hours. `qa-agent` automates the mechanical parts.

---

## File Structure

```
marquee-agents/
├── IMPLEMENTATION/              # Per-command deep-dive docs (for agents + engineers)
│   ├── summarise.md             # `qa-agent summarise` — architecture + provider contract
│   └── claude_summarise.md     # Claude-specific auth, tools, error handling
├── qa_agent/
│   ├── __init__.py
│   ├── cli.py                   # Thin entry-point; registers all sub-commands
│   ├── summarise.py             # Orchestrator: output formatting, provider routing
│   └── claude_summariser.py    # Claude Agent SDK provider
├── pyproject.toml
├── setup.py
├── .gitignore
├── README.md
└── CLAUDE.md
```

---

## CLI Commands

| Sub-command | Args / Flags | Description | Detail |
|------------|-------|-------------|--------|
| `hello` | — | Prints a greeting | — |
| `summarise` | `[PATH …]` `-claude` *(default)* | Summarise files or directories using AI | [`IMPLEMENTATION/summarise.md`](./IMPLEMENTATION/summarise.md) |
| *(none)* | — | Prints help | — |

---

## Coding Conventions

- **PEP 8** · max line length 100 characters
- **Type hints** on all public function signatures
- **f-strings** over `.format()` or `%`
- `cli.py` stays thin — logic goes in dedicated modules under `qa_agent/`
- `subprocess.run()` over `os.system()`

### Naming

| Kind | Convention | Example |
|------|-----------|---------|
| Modules | `snake_case` | `claude_summariser.py` |
| Functions | `snake_case` | `def stream():` |
| Classes | `PascalCase` | `class TriageReport:` |
| Constants | `UPPER_SNAKE_CASE` | `DEFAULT_TIMEOUT = 30` |
| CLI sub-commands | `snake_case` | `qa-agent summarise` |
| CLI provider flags | `-<name>` | `qa-agent summarise -claude` |

---

## Git Conventions

| Branch pattern | Purpose |
|----------------|---------|
| `main` | Stable |
| `feat/<name>` | New features |
| `fix/<name>` | Bug fixes |
| `docs/<name>` | Docs only |
| `chore/<name>` | Maintenance |

Commit format: `feat(cli): add summarise command`

---

## Useful Commands

```bash
pip install -e .                           # Install in editable/dev mode
qa-agent hello                             # Greeting
qa-agent summarise                         # Summarise current dir (pwd)
qa-agent summarise .                       # Same, explicit
qa-agent summarise src/                    # Summarise a directory
qa-agent summarise main.py                 # Summarise a single file
qa-agent summarise a.py b.py c.py         # Summarise multiple files
qa-agent summarise -claude                 # Explicit Claude flag (default)
qa-agent --help                            # All commands
qa-agent summarise --help                  # Sub-command help

# Auth — Option 1 (API key)
export ANTHROPIC_API_KEY=sk-ant-...

# Auth — Option 2 (OAuth)
npm install -g @anthropic-ai/claude-code
claude login
```
