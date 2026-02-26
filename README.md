# marquee-agents — QA Agent CLI

> **Automated post-regression triage for DV engineers.**
> After every regression run, `qa-agent` automatically reconstructs failing configs, re-invokes debug scripts, and collates logs — turning hours of mechanical work into a single command.

---

## Table of Contents

- [The Problem](#the-problem)
- [What qa-agent Does](#what-qa-agent-does)
- [Requirements](#requirements)
- [Installation — Development](#installation--development)
- [Installation — Production (Server / Sysadmin)](#installation--production-server--sysadmin)
- [Usage](#usage)
- [Authentication](#authentication)
- [Project Structure](#project-structure)
- [Adding New Sub-commands](#adding-new-sub-commands)
- [Running Tests](#running-tests)
- [Contributing](#contributing)
- [License](#license)

---

## The Problem

After every regression run, DV engineers manually:

1. Go through results files to find failures
2. Reconstruct the exact **config and seed** for each failure
3. Re-invoke the **debug script** manually
4. Dig through logs to piece together root causes

For a regression with **10+ failures**, this takes **hours** — and most of it is mechanical work that doesn't require human judgment.

---

## What qa-agent Does

`qa-agent` automates the mechanical parts of this pipeline:

- **Parses** regression result files to extract all failures
- **Reconstructs** the exact config + seed combination for each failure
- **Re-invokes** the debug script automatically for each failed test
- **Aggregates** logs into a single, readable triage report

DV engineers can focus on the failures themselves rather than the process of finding them.

---

## Requirements

| Tool | Version |
|------|---------|
| Python | ≥ 3.10 |
| pip | latest |

---

## Installation — Development

For DV engineers or contributors running the tool locally.

```bash
# 1. Clone the repository
git clone https://github.com/zoltlabs/marquee-agents.git
cd marquee-agents

# 2. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate        # macOS / Linux
# venv\Scripts\activate         # Windows

# 3. Install in editable mode (installs all dependencies)
pip install -e .

# 4. Verify
qa-agent hello
qa-agent doctor      # check your environment
```

---

## Installation — Production (Server / Sysadmin)

> **This section is for system administrators** deploying `qa-agent` on a shared server so that all DV engineers can use it as a system-level command.

### Prerequisites

- Python 3.10+ installed system-wide (`python3 --version`)
- `pip` available (`pip3 --version`)
- Sufficient permissions to install into the target Python environment

### Option A — System-wide install via pip (recommended)

```bash
# 1. Clone the repo to a stable server path
sudo git clone https://github.com/zoltlabs/marquee-agents.git /opt/marquee-agents
cd /opt/marquee-agents

# 2. Install globally so all users get the `qa-agent` command
sudo pip3 install .

# 3. Verify the command is available system-wide
qa-agent hello
qa-agent doctor
```

All users on the server can now run `qa-agent` without any virtual environment setup.

### Option B — Shared virtual environment

Use this approach if you want to isolate the install from the system Python.

```bash
# 1. Clone to a shared location
sudo git clone https://github.com/zoltlabs/marquee-agents.git /opt/marquee-agents
cd /opt/marquee-agents

# 2. Create a shared venv
sudo python3 -m venv /opt/marquee-agents/venv

# 3. Install into the shared venv
sudo /opt/marquee-agents/venv/bin/pip install .

# 4. Create a system-wide symlink so everyone can use it
sudo ln -s /opt/marquee-agents/venv/bin/qa-agent /usr/local/bin/qa-agent

# 5. Verify
qa-agent hello
```

### Upgrading (Production)

```bash
cd /opt/marquee-agents
sudo git pull origin main

# Option A (system-wide):
sudo pip3 install --upgrade .

# Option B (shared venv):
sudo /opt/marquee-agents/venv/bin/pip install --upgrade .
```

### Uninstalling

```bash
# Option A:
sudo pip3 uninstall qa-agent

# Option B:
sudo rm /usr/local/bin/qa-agent
sudo rm -rf /opt/marquee-agents/venv
```

---

## Usage

```bash
qa-agent <command> [options]
```

### Available Commands

| Command | Description |
|---------|-------------|
| `hello` | Verify the agent is installed and responsive |
| `doctor` | Check that all SDKs and credentials are correctly configured |
| `summarise [PATH …]` | Summarise files or directories using AI |
| `analyse` | Parse a regression results file, run debug commands per failure, and write a grouped Markdown QA report |

### Global Flags

| Flag | Short | Description |
|------|-------|-------------|
| `--verbose` | `-v` | Show detailed progress, raw provider output, and full tracebacks |
| `--debug` | — | `--verbose` + write a session log to disk for debugging |
| `--version` | `-V` | Print version and exit |

---

### `qa-agent doctor`

Run this **before your first `summarise`** to confirm all dependencies are installed
and credentials are set.

```bash
qa-agent doctor            # basic check — exit 0 = ready
qa-agent doctor --verbose  # show raw values and full paths
```

Exit codes: `0` = all checks passed (or warnings only) · `1` = one or more errors found.

---

### `qa-agent summarise`

Analyse and explain files using an AI provider (Claude by default).

```bash
# Summarise the current directory (pwd)
qa-agent summarise

# Summarise explicitly with .
qa-agent summarise .

# Summarise a specific directory
qa-agent summarise src/

# Summarise a single file
qa-agent summarise main.py

# Summarise multiple files
qa-agent summarise a.py b.py c.py

# Use a specific provider
qa-agent summarise -p openai      # OpenAI GPT-4o
qa-agent summarise -p gemini      # Google Gemini
qa-agent summarise -p claude      # Claude (default)

# Long form
qa-agent summarise --provider openai src/

# Show sub-command help
qa-agent summarise --help
```

> **Migration note** — the old single-dash provider flags (`-claude`, `-openai`, `-gemini`)
> have been replaced by `--provider / -p`.

#### Provider choices

| Flag | Provider | Model |
|------|----------|-------|
| *(default)* | Claude (Anthropic) | claude-agent-sdk |
| `-p openai` | OpenAI | GPT-4o |
| `-p gemini` | Google Gemini | gemini-2.5-flash |

---

### `qa-agent analyse`

The primary post-regression triage command. **No AI required — pure Python.**

`qa-agent analyse` runs a **7-step pipeline**:

1. **Finds** `results.doc` or `results_new.doc` in the working directory.
2. **Parses** every result line to extract passed/failed tests with their configs and seeds.
3. **Interactively selects** a `.csh` environment source file (arrow-key prompt; auto-skipped on non-TTY).
4. **Interactively selects** a `.pl` debug script (arrow-key prompt; skipped when `--script` is passed).
5. **Creates** a dedicated `debug_<test>_<hash>_<seed>/` subdirectory for each failure.
6. **Runs** the debug command for each failure, writing `stdout` + `stderr` to `debug.log` (2h timeout).
7. **Writes** a grouped-by-test Markdown report including config tables, debug commands, and the last 30 lines of each log.

```bash
# Auto-detect results.doc / results_new.doc in the current directory
qa-agent analyse

# Specify the regression run directory
qa-agent analyse --working-dir /path/to/regression/run

# Force slurm mode (auto-detected from filename by default)
qa-agent analyse --mode slurm

# Write the report to a custom path
qa-agent analyse --output /tmp/report.md

# Skip the interactive script prompt — embed this path in debug commands
qa-agent analyse -s /tools/run_debug.pl

# Focus on a single failing test (all others are skipped)
qa-agent analyse --test apcit_cpl_out_order

# Print detailed progress: full debug commands + absolute paths
qa-agent analyse --verbose

# Combine options
qa-agent analyse --working-dir /path/to/run --output report.md -s /tools/run_debug.pl
```

#### Flags

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--mode basic\|slurm` | — | auto-detected from filename | Override mode detection |
| `--working-dir PATH` | — | CWD | Directory containing the results file |
| `--output PATH` | — | `qa_report_<timestamp>.md` | Output report path |
| `--script PATH` | `-s` | *(interactive selection)* | Debug script path; skips the arrow-key prompt |
| `--test NAME` | `-t` | *(all failures)* | Focus on a single test case by name; skips all others |
| `--verbose` | `-v` | off | Print detailed progress: full commands, absolute debug dir paths |

#### Mode detection

| Filename | Mode |
|----------|------|
| `results.doc` | `basic` |
| `results_new.doc` | `slurm` |

#### Debug directory layout

For every failure, a subdirectory is created under `--working-dir`:

```
<working-dir>/
├── results.doc
├── debug_apcit_cpl_out_order_a3f9c1_1234/
│   └── debug.log    ← stdout + stderr from the debug run
└── debug_pcie_bar_test_c1f3a9_9999/
    └── debug.log
```

## Authentication

Run `qa-agent doctor` to verify your credentials are correctly configured.

### Claude

```bash
# Option 1 — API key
export ANTHROPIC_API_KEY=sk-ant-...

# Option 2 — Claude Code CLI OAuth
npm install -g @anthropic-ai/claude-code
claude login
```

### OpenAI

```bash
# Option 1 — API key
export OPENAI_API_KEY=sk-...

# Option 2 — Codex CLI OAuth
npm install -g @openai/codex
codex login
```

### Gemini

```bash
# Option 1 — Gemini API key (Google AI Studio)
export GEMINI_API_KEY=AIza...

# Option 2 — Vertex AI + gcloud Application Default Credentials
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT=your-project
```

---

## Project Structure

```
marquee-agents/
├── IMPLEMENTATION/
│   ├── summarise.md         # summarise command — architecture + provider contract
│   ├── analyse.md           # analyse command — results parser + QA report writer
│   ├── doctor.md            # doctor command — env health checker design
│   ├── logging.md           # session logging — format, rotation, crash capture
│   ├── ux_improvements.md   # output.py, errors.py, spinner, global flags
│   └── claude_sdk.md        # Claude-specific auth, tools, error handling
├── qa_agent/
│   ├── __init__.py          # Package init
│   ├── cli.py               # CLI entry-point and sub-command definitions
│   ├── output.py            # Shared ANSI rendering (colour helpers, banner, Spinner)
│   ├── errors.py            # Error taxonomy (QAAgentError hierarchy) + central handler
│   ├── session_log.py       # Structured session logging (JSON Lines, gzip, rotation)
│   ├── providers.py         # Shared ProviderRequest dataclass
│   ├── summarise.py         # Orchestrator: path resolution, output formatting
│   ├── analyse.py           # Regression results parser + Markdown QA report writer
│   ├── doctor.py            # Environment health checker
│   ├── claude_provider.py   # Claude Agent SDK provider
│   ├── openai_provider.py   # OpenAI Chat Completions provider
│   └── gemini_provider.py   # Google Gemini provider
├── pyproject.toml           # Build system & project metadata (PEP 517/518)
├── setup.py                 # Legacy setuptools config (for editable installs)
├── .gitignore               # Git ignore rules
├── CLAUDE.md                # AI assistant context & coding conventions
└── README.md                # This file
```

---

## Adding New Sub-commands

1. Open `qa_agent/cli.py` and register the new sub-parser inside `main()`.
2. Add the handler logic in a new module (`qa_agent/my_command.py`) — keep `cli.py` thin.
3. Call the module from the `if/elif` dispatch block in `main()`.
4. Import from `qa_agent.output` for rendering; raise `QAAgentError` subclasses for errors.

See [`CLAUDE.md`](./CLAUDE.md) for full conventions.

---

## Running Tests

> Tests are not yet implemented. The recommended framework is **pytest**.

```bash
pip install pytest
pytest tests/
```

---

## Contributing

1. Fork and create a feature branch: `git checkout -b feat/my-feature`
2. Follow the conventions in [`CLAUDE.md`](./CLAUDE.md)
3. Use [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`, `chore:`
4. Open a Pull Request against `main`

---

## License

This project is private and maintained by **Zolt Labs**. All rights reserved.
