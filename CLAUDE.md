# CLAUDE.md — AI Assistant Context for marquee-agents

High-level overview. For per-command implementation detail, see [`IMPLEMENTATION/`](./IMPLEMENTATION/).

---

## Project Overview

| Field | Value |
|-------|-------|
| **Project** | marquee-agents |
| **Purpose** | Automate DV regression runs and post-regression failure triage for DV engineers |
| **Audience** | DV (Design Verification) engineers on the server team |
| **Type** | Python CLI tool |
| **Entry-point** | `qa-agent` (registered via `pyproject.toml`) |
| **Language** | Python ≥ 3.10 |
| **Owner** | Zolt Labs |

---

## The Problem Being Solved

`qa-agent` automates the full mechanical DV regression workflow:

1. **Regression** (`qa-agent regression`) — sources the shell environment, locates filelist/config files, runs basic or Slurm regressions with live output, and captures a timestamped log.
2. **Triage** (`qa-agent analyse`) — parses results files, reconstructs configs + seeds for every failure, re-runs debug scripts in isolated subdirs, and writes a grouped Markdown QA report.
3. **AI summarisation** (`qa-agent summarise`) — sends source files to Claude, OpenAI, or Gemini for structured explanation. *Available now.*
4. **AI-driven triage** — automated root-cause correlation and natural-language report generation. *On the roadmap.*

For 10+ failures this turns hours of mechanical work into a single command.

---

## File Structure

```
marquee-agents/
├── IMPLEMENTATION/              # Per-command deep-dive docs (for agents + engineers)
│   ├── summarise.md             # `qa-agent summarise` — architecture + provider contract
│   ├── analyse.md               # `qa-agent analyse` — results parser + QA report writer
│   ├── doctor.md                # `qa-agent doctor` — env health checker
│   ├── regression.md            # `qa-agent regression` — regression run lifecycle
│   ├── help_and_hello.md        # `qa-agent hello` / `qa-agent guide` — welcome screen + user guides
│   ├── logging.md               # Session logging — format, rotation, crash capture
│   ├── cli_consistency.md       # CLI flag + output consistency plan (tasks + conventions)
│   ├── debug_mode.md            # step-through debug mode — step_gate, StepLog, log files
│   ├── claude_sdk.md            # Claude provider — auth, SDK options, error types
│   ├── openai_sdk.md            # OpenAI provider — auth, API details, error types
│   └── gemini_sdk.md            # Gemini provider — auth, API details, error types
├── qa_agent/
│   ├── __init__.py
│   ├── cli.py                   # Thin entry-point; registers all sub-commands
│   ├── providers.py             # Shared ProviderRequest dataclass (provider interface)
│   ├── output.py                # Shared ANSI rendering: colour helpers, banner, Spinner, print_welcome
│   ├── errors.py                # Error taxonomy (QAAgentError hierarchy) + central handler
│   ├── session_log.py           # Structured session logging (JSON Lines, gzip, rotation)
│   ├── step_gate.py             # Step-through debug gate: StepLog, StepRecord, step_gate()
│   ├── guide.py                 # Short per-command user guides + overview renderer
│   ├── summarise.py             # Orchestrator: prompt building, output formatting, provider routing
│   ├── analyse.py               # Regression results parser + Markdown QA report writer
│   ├── doctor.py                # Environment health checker: SDKs, auth, log dir
│   ├── regression.py            # Regression run lifecycle: source env, locate files, run, verify
│   ├── claude_provider.py       # Claude Agent SDK provider (generic; reusable across commands)
│   ├── openai_provider.py       # OpenAI Chat Completions provider
│   └── gemini_provider.py       # Google Gemini provider
├── run_apci_2025.pl             # Default debug Perl script (used in generated commands)
├── run_questa.sh                # Bundled Slurm launcher script
├── sourcefile_2025_3.csh        # Bundled environment source file
├── filelist.txt                 # Bundled default test filelist
├── config.txt                   # Bundled Slurm configuration
├── regression_8B_16B_questa.py  # Bundled basic regression runner
├── regression_slurm_questa_2025.py  # Bundled Slurm regression runner
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
| `hello` | — | ASCII logo welcome screen + quick start | [`IMPLEMENTATION/help_and_hello.md`](./IMPLEMENTATION/help_and_hello.md) |
| `guide` | `[COMMAND]` | Short practical user guide for any command; no arg = overview of all | [`IMPLEMENTATION/help_and_hello.md`](./IMPLEMENTATION/help_and_hello.md) |
| `summarise` | `[PATH …]` `--provider`/`-p {claude,openai,gemini}` | Summarise files or directories using AI | [`IMPLEMENTATION/summarise.md`](./IMPLEMENTATION/summarise.md) |
| `doctor` | `--verbose`/`-v` | Check SDKs, auth, and log system | [`IMPLEMENTATION/doctor.md`](./IMPLEMENTATION/doctor.md) |
| `analyse` | `[--mode basic\|slurm]` `[--working-dir PATH]` `[--output PATH]` `[--script/-s SCRIPT]` `[--test NAME]` `[--verbose/-v]` | Parse regression results, interactively select source/script files, re-run each failure in a debug subdir, capture logs, and write a grouped Markdown QA report | [`IMPLEMENTATION/analyse.md`](./IMPLEMENTATION/analyse.md) |
| `regression` | `[--slurm]` `[--verbose/-v]` | Source environment, locate inputs, execute regression (basic or slurm), stream output, capture log, verify results | [`IMPLEMENTATION/regression.md`](./IMPLEMENTATION/regression.md) |
| *(none)* | — | Prints help | — |

### Global Flags (available on ALL commands)

| Flag | Short | Default | Effect |
|------|-------|---------|--------|
| `--verbose` | `-v` | off | Detailed progress, raw provider output, full tracebacks |
| `--debug` | — | off | `--verbose` + write session log to disk + step-through gate on `regression`/`analyse` |
| `--version` | `-V` | — | Print `qa-agent <version>` and exit |

---

## Migration Notes

> **Breaking change — provider flags renamed** (previous single-dash flags removed)
>
> | Old | New |
> |-----|-----|
> | `qa-agent summarise -claude` | `qa-agent summarise` *(claude is still the default)* |
> | `qa-agent summarise -openai` | `qa-agent summarise -p openai` |
> | `qa-agent summarise -gemini` | `qa-agent summarise -p gemini` |

---

## Coding Conventions

- **PEP 8** · max line length 100 characters
- **Type hints** on all public function signatures
- **f-strings** over `.format()` or `%`
- `cli.py` stays thin — logic goes in dedicated modules under `qa_agent/`
- `subprocess.run()` over `os.system()`
- ANSI output — import from `qa_agent.output`, never define colour helpers locally
- Error handling — raise `QAAgentError` subclasses, never call `sys.exit()` inside modules

### Naming

| Kind | Convention | Example |
|------|-----------|---------| 
| Modules | `snake_case` | `claude_provider.py` |
| Functions | `snake_case` | `def stream():` |
| Classes | `PascalCase` | `class TriageReport:` |
| Constants | `UPPER_SNAKE_CASE` | `DEFAULT_TIMEOUT = 30` |
| CLI sub-commands | `snake_case` | `qa-agent summarise` |
| CLI provider flag | `--provider / -p` | `qa-agent summarise -p gemini` |

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
qa-agent hello                             # Welcome screen: ASCII logo + quick start
qa-agent guide                             # Overview of all commands
qa-agent guide regression                  # Guide for regression command
qa-agent guide analyse                     # Guide for analyse command
qa-agent guide summarise                   # Guide for summarise command
qa-agent guide doctor                      # Guide for doctor command
qa-agent doctor                            # Check environment health
qa-agent doctor --verbose                  # Show raw values/paths
qa-agent summarise                         # Summarise current dir (pwd) — Claude by default
qa-agent summarise .                       # Same, explicit
qa-agent summarise src/                    # Summarise a directory
qa-agent summarise main.py                 # Summarise a single file
qa-agent summarise a.py b.py c.py         # Summarise multiple files
qa-agent summarise -p openai               # Use OpenAI (GPT-4o)
qa-agent summarise -p gemini               # Use Google Gemini
qa-agent --verbose summarise .             # Verbose output + full tracebacks
qa-agent --debug summarise .              # Debug mode: verbose + session log written
qa-agent --version                         # Print version
qa-agent --help                            # All commands
qa-agent summarise --help                  # Sub-command help
qa-agent analyse                              # Auto-detect file, interactive script/source selection, run debug
qa-agent analyse --working-dir /path/to/run   # Specify regression dir
qa-agent analyse --mode slurm                 # Force slurm mode
qa-agent analyse --output report.md           # Custom report path
qa-agent analyse -s /tools/run_debug.pl       # Skip script selection prompt
qa-agent analyse --test apcit_cpl_out_order   # Focus on a single test case
qa-agent analyse --verbose                    # Print detailed progress (full cmd, abs paths)
qa-agent regression                           # Run basic regression (auto-selects scripts)
qa-agent regression --slurm                   # Run in Slurm mode
qa-agent regression --verbose                 # Print full resolved paths + commands

# Claude auth — Option 1 (API key)
export ANTHROPIC_API_KEY=sk-ant-...
# Claude auth — Option 2 (OAuth)
npm install -g @anthropic-ai/claude-code
claude login

# OpenAI auth — Option 1 (API key)
export OPENAI_API_KEY=sk-...
# OpenAI auth — Option 2 (Codex CLI OAuth)
npm install -g @openai/codex
codex login

# Gemini auth — Option 1 (API key)
export GEMINI_API_KEY=AIza...
# Gemini auth — Option 2 (Vertex AI gcloud ADC)
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT=your-project
```

---

## Session Logs

```bash
# View last session log (macOS: use gzcat instead of zcat)
zcat ~/.local/share/qa-agent/logs/last-session.log
gzcat ~/Library/Application\ Support/ZoltLabs/qa-agent/logs/last-session.log

# Pretty-print JSON
zcat ... | python -m json.tool

# List all session logs
ls -lh ~/.local/share/qa-agent/logs/

# Delete all logs (reset)
rm -rf ~/.local/share/qa-agent/logs/

# Force a debug session
qa-agent --debug summarise .
```

Log directory (platform-specific):
- **macOS**: `~/Library/Application Support/ZoltLabs/qa-agent/logs/`
- **Linux**: `~/.local/share/qa-agent/logs/`
