# Help Command & Hello Improvements — Implementation Plan

> **Status:** Planned
> **Branch:** `feat/help-hello`
> **New module:** `qa_agent/guide.py`
> **Updated modules:** `qa_agent/cli.py`, `qa_agent/output.py`

---

## Overview

Better discoverability, concise capability descriptions, and an improved first
impression. Three changes:

1. **Revamped `hello` command** — purposeful welcome with ASCII art and quick start.
2. **New `guide` command** — short, practical per-command user guides.
3. **Improved `--help` output** — cleaner argparse formatting.

---

## 1. Improved `hello` Command

The current `hello` command prints a generic greeting. Replace it with a
purposeful welcome message that communicates what the tool does and how to get
started.

### New output

```
╭──────────────────────────────────────────────────────╮
│                                                      │
│    ██████╗  █████╗        █████╗  ██████╗ ███████╗   │
│   ██╔═══██╗██╔══██╗      ██╔══██╗██╔════╝ ██╔════╝  │
│   ██║   ██║███████║█████╗███████║██║  ███╗█████╗     │
│   ██║▄▄ ██║██╔══██║╚════╝██╔══██║██║   ██║██╔══╝    │
│   ╚██████╔╝██║  ██║      ██║  ██║╚██████╔╝███████╗  │
│    ╚══▀▀═╝ ╚═╝  ╚═╝      ╚═╝  ╚═╝ ╚═════╝ ╚══════╝ │
│                                                      │
│   Post-regression triage, automated.                 │
│   Built for DV & Design engineers.                   │
│                                                      │
│   Version: 0.1.0                                     │
│                                                      │
╰──────────────────────────────────────────────────────╯

  Quick start:

    qa-agent doctor              Check your environment is set up
    qa-agent regression          Run a regression (basic or slurm)
    qa-agent analyse             Parse failures, run debug, generate report
    qa-agent summarise .         Summarise code with AI (Claude/OpenAI/Gemini)

  Run  qa-agent <command> --help  for details on any command.
  Run  qa-agent guide <command>   for a short user guide.
```

### Implementation

- Read version dynamically from `importlib.metadata.version("qa-agent")`.
- ASCII art stored as `QA_AGENT_LOGO` constant in `output.py`.
- New `print_welcome()` function in `output.py` renders the full welcome screen.
- `hello` subcommand in `cli.py` calls `print_welcome()` instead of the
  current simple print.

### `output.py` additions

```python
import importlib.metadata

QA_AGENT_LOGO = r"""
    ██████╗  █████╗        █████╗  ██████╗ ███████╗
   ██╔═══██╗██╔══██╗      ██╔══██╗██╔════╝ ██╔════╝
   ██║   ██║███████║█████╗███████║██║  ███╗█████╗
   ██║▄▄ ██║██╔══██║╚════╝██╔══██║██║   ██║██╔══╝
   ╚██████╔╝██║  ██║      ██║  ██║╚██████╔╝███████╗
    ╚══▀▀═╝ ╚═╝  ╚═╝      ╚═╝  ╚═╝ ╚═════╝ ╚══════╝
"""


def _get_version() -> str:
    """Read version from package metadata, fallback to 'dev'."""
    try:
        return importlib.metadata.version("qa-agent")
    except importlib.metadata.PackageNotFoundError:
        return "dev"


def print_welcome() -> None:
    """Print the full welcome screen with ASCII art and quick start."""
    version = _get_version()

    # Logo box
    print()
    print(cyan("╭" + "─" * 54 + "╮"))
    for line in QA_AGENT_LOGO.splitlines():
        padded = f"│  {line:<52}│"
        print(cyan(padded))
    print(cyan("│" + " " * 54 + "│"))
    print(cyan("│") + f"   {bold('Post-regression triage, automated.'):<52}" + cyan("│"))
    print(cyan("│") + f"   Built for DV & Design engineers.{' ' * 19}" + cyan("│"))
    print(cyan("│") + " " * 54 + cyan("│"))
    print(cyan("│") + f"   Version: {version}{' ' * (42 - len(version))}" + cyan("│"))
    print(cyan("│") + " " * 54 + cyan("│"))
    print(cyan("╰" + "─" * 54 + "╯"))
    print()

    # Quick start
    print(f"  {bold('Quick start:')}")
    print()
    cmds = [
        ("qa-agent doctor", "Check your environment is set up"),
        ("qa-agent regression", "Run a regression (basic or slurm)"),
        ("qa-agent analyse", "Parse failures, run debug, generate report"),
        ("qa-agent summarise .", "Summarise code with AI (Claude/OpenAI/Gemini)"),
    ]
    for cmd, desc in cmds:
        print(f"    {cyan(f'{cmd:<25}')} {dim(desc)}")
    print()
    print(f"  Run  {bold('qa-agent <command> --help')}  for details on any command.")
    print(f"  Run  {bold('qa-agent guide <command>')}   for a short user guide.")
    print()
```

### `cli.py` change

```python
# Current:
if args.command == "hello":
    print("Hello from qa-agent!")

# New:
if args.command == "hello":
    from qa_agent.output import print_welcome
    print_welcome()
```

---

## 2. New `guide` Command

A dedicated command that gives a short, practical user guide for each
subcommand. Different from `--help` which shows flags/args only — `guide`
explains **what** the command does, **when** to use it, and shows realistic
examples. Assumes the user has basic DV/AI knowledge.

### CLI interface

```bash
qa-agent guide                    # overview of all commands
qa-agent guide regression         # guide for regression command
qa-agent guide analyse            # guide for analyse command
qa-agent guide summarise          # guide for summarise command
qa-agent guide doctor             # guide for doctor command
```

### Guide content structure

Each guide follows a fixed template:

```
╭─ qa-agent <command> ────────────────────────────────╮
│  <one-line purpose>                                  │
╰──────────────────────────────────────────────────────╯

  What it does:
    <2-3 bullet points>

  When to use:
    <1-2 bullet points>

  Quick examples:
    $ qa-agent <command> <example-1>
    $ qa-agent <command> <example-2>

  Flags:
    --flag, -f    <what it does>

  See also:  qa-agent <related-command>
```

---

### Guide content: `guide regression`

```
╭─ qa-agent regression ───────────────────────────────╮
│  Run a full regression — source env, execute, verify │
╰──────────────────────────────────────────────────────╯

  What it does:
    • Sources your .csh environment file (auto-selects or lets you pick)
    • Locates filelist.txt, config, and regression scripts
    • Runs basic (python) or slurm (sbatch) regression with live output
    • Captures full output to a timestamped log file
    • Verifies results.doc / results_new.doc was generated

  When to use:
    • Starting a new regression run from your working directory
    • Need slurm dispatch with auto config.txt + run_questa.sh discovery

  Quick examples:
    $ qa-agent regression                    # basic mode, auto-detect files
    $ qa-agent regression --slurm            # slurm mode
    $ qa-agent --debug regression            # step-by-step with pause gates

  Flags:
    --slurm           Run in Slurm mode (needs config.txt + run_questa.sh)
    --verbose, -v     Show resolved paths and full commands
    --debug           Step-through mode — pause after each step

  See also:  qa-agent analyse   (triage failures after regression)
```

### Guide content: `guide analyse`

```
╭─ qa-agent analyse ──────────────────────────────────╮
│  Parse failures, re-run debug, generate QA report    │
╰──────────────────────────────────────────────────────╯

  What it does:
    • Reads results.doc / results_new.doc from a regression run
    • Identifies all FAILED test cases with config + seed
    • Lets you pick a source file (.csh) and debug script (.pl)
    • Creates a debug_<test>_<hash>_<seed>/ subdir per failure
    • Runs the debug command in each subdir, captures debug.log
    • Writes a grouped Markdown QA report with log evidence

  When to use:
    • After a regression completes with failures
    • You want automated debug re-runs instead of manual copy-paste

  Quick examples:
    $ qa-agent analyse                               # auto-detect everything
    $ qa-agent analyse --working-dir /path/to/run    # specify regression dir
    $ qa-agent analyse -s ./run_apci_2025.pl         # skip script prompt
    $ qa-agent analyse --test apcit_cpl_out_order    # single test only
    $ qa-agent --debug analyse                       # step-through mode

  Flags:
    --mode basic|slurm       Override auto-detection (results.doc vs results_new.doc)
    --working-dir PATH       Regression output directory (default: cwd)
    --output PATH            Custom report path (default: qa_report_<ts>.md)
    --script, -s PATH        Debug script path (skips interactive picker)
    --test NAME              Filter to a single test case
    --verbose, -v            Show full commands and absolute paths
    --debug                  Step-through mode — pause after each step

  See also:  qa-agent regression   (run the regression first)
```

### Guide content: `guide summarise`

```
╭─ qa-agent summarise ────────────────────────────────╮
│  Summarise files or directories using AI             │
╰──────────────────────────────────────────────────────╯

  What it does:
    • Reads file contents and sends to an AI provider (Claude, OpenAI, Gemini)
    • Returns a structured summary with key sections highlighted
    • Supports single files, multiple files, or entire directories

  When to use:
    • Quick overview of unfamiliar code or config files
    • Generating documentation snippets from source

  Quick examples:
    $ qa-agent summarise                    # summarise current directory
    $ qa-agent summarise src/main.py        # single file
    $ qa-agent summarise a.py b.py          # multiple files
    $ qa-agent summarise -p openai .        # use OpenAI instead of Claude

  Flags:
    --provider, -p {claude,openai,gemini}   AI provider (default: claude)
    --verbose, -v                           Show raw provider output

  See also:  qa-agent doctor   (check provider auth is set up)
```

### Guide content: `guide doctor`

```
╭─ qa-agent doctor ───────────────────────────────────╮
│  Check that your environment is correctly set up     │
╰──────────────────────────────────────────────────────╯

  What it does:
    • Validates Python version (≥ 3.10 required)
    • Checks Claude, OpenAI, and Gemini SDK installations
    • Verifies API keys or CLI OAuth login for each provider
    • Reports session log directory status and disk usage

  When to use:
    • First time setting up qa-agent
    • Provider commands failing with auth errors

  Quick examples:
    $ qa-agent doctor                   # standard check
    $ qa-agent doctor --verbose         # show raw env values + paths

  Flags:
    --verbose, -v     Show raw API key prefixes and resolved paths

  See also:  qa-agent guide   (overview of all commands)
```

### Guide content: `guide` (no argument — overview)

```
╭─ qa-agent guide ────────────────────────────────────╮
│  Quick reference for all commands                    │
╰──────────────────────────────────────────────────────╯

  Commands:

    regression   Run a full regression (basic or slurm)
    analyse      Parse failures, re-run debug, generate QA report
    summarise    Summarise files or directories using AI
    doctor       Check environment setup (SDKs, API keys, logs)
    hello        Welcome screen and quick start info
    guide        This command — short user guides

  Global flags (work with any command):

    --verbose, -v    Detailed output + full tracebacks
    --debug          Verbose + session log + step-through for regression/analyse
    --version, -V    Print version and exit

  Usage:  qa-agent guide <command>   for a detailed guide.
```

---

### Implementation: `qa_agent/guide.py`

```python
"""qa_agent/guide.py — Short user guides for each command."""

from __future__ import annotations

from qa_agent.output import bold, cyan, dim, rule


# ── Guide content ────────────────────────────────────────────────────────────

GUIDES: dict[str, tuple[str, str, str]] = {
    # key: (header_title, one_liner, body)
    "regression": (
        "qa-agent regression",
        "Run a full regression — source env, execute, verify",
        # body is the full guide text (What it does / When to use / etc.)
        "..."
    ),
    "analyse": (
        "qa-agent analyse",
        "Parse failures, re-run debug, generate QA report",
        "..."
    ),
    "summarise": (
        "qa-agent summarise",
        "Summarise files or directories using AI",
        "..."
    ),
    "doctor": (
        "qa-agent doctor",
        "Check that your environment is correctly set up",
        "..."
    ),
}

OVERVIEW_BODY = "..."  # the overview text shown when no command given


# ── Rendering ────────────────────────────────────────────────────────────────

def _print_guide_panel(title: str, one_liner: str) -> None:
    """Print the header panel for a guide."""
    width = 54
    inner = f"  {title}"
    print()
    print(cyan(f"╭─ {title} " + "─" * max(1, width - len(title) - 4) + "╮"))
    print(cyan("│") + f"  {one_liner:<{width}}" + cyan("│"))
    print(cyan("╰" + "─" * (width + 2) + "╯"))
    print()


def _print_body(body: str) -> None:
    """Print the guide body with consistent indentation."""
    for line in body.strip().splitlines():
        if line.strip().startswith("$"):
            # Command example — highlight
            parts = line.split("$", 1)
            indent = parts[0]
            cmd = parts[1].strip()
            print(f"{indent}{cyan('$')} {bold(cmd)}")
        elif line.strip().endswith(":"):
            # Section header
            print(f"  {bold(line.strip())}")
        elif line.strip().startswith("--"):
            # Flag line
            flag_parts = line.strip().split(None, 1)
            if len(flag_parts) == 2:
                print(f"    {cyan(flag_parts[0])}  {dim(flag_parts[1])}")
            else:
                print(f"    {cyan(line.strip())}")
        elif line.strip().startswith("See also:"):
            print(f"\n  {dim(line.strip())}")
        else:
            print(line)


# ── Entry point ──────────────────────────────────────────────────────────────

def run(command: str = "") -> None:
    """Print the guide for a command, or the overview if empty."""
    if not command:
        _print_guide_panel("qa-agent guide", "Quick reference for all commands")
        _print_body(OVERVIEW_BODY)
        return

    if command not in GUIDES:
        print(f"  No guide for '{command}'. Available: {', '.join(GUIDES.keys())}")
        return

    title, one_liner, body = GUIDES[command]
    _print_guide_panel(title, one_liner)
    _print_body(body)
```

---

### `cli.py` changes

```python
# Add guide sub-parser
sp_guide = subparsers.add_parser(
    "guide",
    help="Short user guide for any command",
    description="Show a practical guide with examples for a command.",
)
sp_guide.add_argument(
    "topic", nargs="?", default="",
    choices=["regression", "analyse", "summarise", "doctor"],
    help="Command to show guide for (omit for overview)",
)

# Dispatch (add to the command dispatch block)
if args.command == "guide":
    from qa_agent.guide import run as guide_run
    guide_run(getattr(args, "topic", ""))
```

---

## 3. Improved `--help` Output

Override the default argparse help formatter to produce cleaner, more scannable
output that points users toward `guide` for practical examples.

### Main help (`qa-agent --help`)

```
usage: qa-agent [-v] [--debug] [-V] <command> ...

  Post-regression triage automation for DV engineers.

commands:
  regression   Run a full regression (basic or slurm)
  analyse      Parse failures, run debug, generate QA report
  summarise    Summarise files/dirs with AI
  doctor       Check environment setup
  hello        Welcome screen
  guide        Short user guides with examples

global flags:
  -v, --verbose   Detailed output
  --debug         Verbose + session log + step-through
  -V, --version   Print version

Run  qa-agent guide <command>  for practical examples.
```

### Implementation

Use `argparse.RawDescriptionHelpFormatter` and set:

```python
parser = argparse.ArgumentParser(
    prog="qa-agent",
    description="Post-regression triage automation for DV engineers.",
    epilog="Run  qa-agent guide <command>  for practical examples.",
    formatter_class=argparse.RawDescriptionHelpFormatter,
)
```

Update each sub-parser's `help=` string to match the concise style above.

---

## New / Updated Files

| File | Action | Description |
|------|--------|-------------|
| `qa_agent/guide.py` | **New** | Guide content for all commands + renderer |
| `qa_agent/output.py` | **Update** | Add `QA_AGENT_LOGO`, `_get_version()`, `print_welcome()` |
| `qa_agent/cli.py` | **Update** | Add `guide` sub-parser, update `hello` dispatch, improve formatter |

---

## Testing Checklist

- [ ] `qa-agent hello` — shows ASCII logo, version, quick start table
- [ ] `qa-agent guide` — shows overview of all commands
- [ ] `qa-agent guide regression` — shows regression guide with examples
- [ ] `qa-agent guide analyse` — shows analyse guide with examples
- [ ] `qa-agent guide summarise` — shows summarise guide
- [ ] `qa-agent guide doctor` — shows doctor guide
- [ ] `qa-agent guide nonexistent` — prints "no guide" message
- [ ] `qa-agent --help` — shows clean formatted help with guide pointer
- [ ] `qa-agent regression --help` — shows sub-command help
- [ ] Non-TTY — guide output works without colour codes
