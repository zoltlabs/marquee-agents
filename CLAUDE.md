# CLAUDE.md — AI Assistant Context for marquee-agents

This file provides context for AI coding assistants working inside this repository. It reflects **only the current implementation**.

---

## Project Overview

| Field | Value |
|-------|-------|
| **Project** | marquee-agents |
| **Purpose** | Automate post-regression triage for DV engineers |
| **Audience** | DV (Development / Validation) engineers on the server team |
| **Type** | Python CLI tool |
| **Entry-point** | `qa-agent` (registered via `pyproject.toml : project.scripts`) |
| **Language** | Python ≥ 3.8 |
| **Owner** | Zolt Labs |

---

## The Problem Being Solved

After every regression run, DV engineers currently must:

1. Manually go through results files to find failures
2. Reconstruct the exact **config and seed** for each failure
3. Re-invoke the **debug script** manually per failure
4. Dig through logs and piece together what went wrong

For a regression with **10+ failures**, this takes **hours**. Most of it is mechanical, deterministic work that does not require human judgment.

---

## Current Implementation

### File Structure

```
marquee-agents/
├── qa_agent/
│   ├── __init__.py     # Empty package marker
│   └── cli.py          # Sole entry-point; all CLI logic lives here
├── pyproject.toml      # Build config + registers `qa-agent` command
├── setup.py            # Editable install support
├── .gitignore
├── README.md
└── CLAUDE.md
```

### cli.py — What it does today

`main()` sets up an `argparse` parser with one registered sub-command:

| Sub-command | Behaviour |
|-------------|-----------|
| `hello` | Prints `"Hello 👋 I am QA Agent. How can I help you?"` |
| *(none)* | Prints help text |

```python
# qa_agent/cli.py (current full implementation)
import argparse

def main():
    parser = argparse.ArgumentParser(prog="qa-agent")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("hello")

    args = parser.parse_args()

    if args.command == "hello":
        print("Hello 👋 I am QA Agent. How can I help you?")
    else:
        parser.print_help()
```

### pyproject.toml — Entry-point registration

```toml
[project.scripts]
qa-agent = "qa_agent.cli:main"
```

This registers the `qa-agent` shell command pointing to `main()` in `cli.py`.

---

## Coding Conventions

- Follow **PEP 8**; max line length **100 characters**
- Use **type hints** on all public function signatures
- Prefer **f-strings** over `.format()` or `%`
- Keep `cli.py` thin — new logic goes in dedicated modules under `qa_agent/`
- Use `subprocess.run()` instead of `os.system()`

### Naming

| Kind | Convention | Example |
|------|-----------|---------|
| Modules | `snake_case` | `result_parser.py` |
| Functions | `snake_case` | `def parse_failures():` |
| Classes | `PascalCase` | `class TriageReport:` |
| Constants | `UPPER_SNAKE_CASE` | `DEFAULT_TIMEOUT = 30` |
| CLI sub-commands | `kebab-case` | `qa-agent run-triage` |

---

## Git Conventions

| Branch pattern | Purpose |
|----------------|---------|
| `main` | Stable, production-ready |
| `feat/<name>` | New features |
| `fix/<name>` | Bug fixes |
| `docs/<name>` | Documentation only |
| `chore/<name>` | Maintenance |

Commit format: `feat(cli): add hello command`

---

## Useful Commands

```bash
pip install -e .        # Install in editable/dev mode
qa-agent hello          # Run the only current command
qa-agent --help         # Show help
```
