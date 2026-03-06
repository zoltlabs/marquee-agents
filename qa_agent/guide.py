"""qa_agent/guide.py — Short user guides for each command."""

from __future__ import annotations

from qa_agent.output import bold, cyan, dim, print_header


# ── Guide body content ───────────────────────────────────────────────────────

_REGRESSION_BODY = """\
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
"""

_ANALYSE_BODY = """\
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
"""

_SUMMARISE_BODY = """\
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
"""

_DOCTOR_BODY = """\
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
"""

_REPORT_BODY = """\
  What it does:
    • Generates a structured debug report from Questa/Visualizer simulation output
    • Uses an AI agent (acting as a DV expert) to investigate the failure
    • The AI makes targeted tool calls to extract logs, assertions, scoreboard, and signals
    • Writes a final Markdown report summarizing the root cause, evidence, and next steps

  When to use:
    • You have a failing simulation directory (e.g., from `qa-agent analyse` debug run)
    • You want an AI-generated explanation of the failure without reading logs manually

  Quick examples:
    $ qa-agent report /path/to/sim/dir         # Standard run
    $ qa-agent report . -p openai              # Use OpenAI instead of Claude
    $ qa-agent report . --verbose              # See every tool call the AI makes

  Flags:
    --provider, -p {claude,openai,gemini}   AI provider (default: claude)
    --output, -o PATH                       Custom report path
    --max-turns N                           Max investigation turns (default: 15)
    --verbose, -v                           Print detailed progress and tool calls

  See also:  qa-agent analyse   (generates the debug directories this command reads)
"""

_OVERVIEW_BODY = """\
  qa-agent automates the mechanical work in a DV regression workflow:

    1. Run a regression      →  qa-agent regression
    2. Triage the failures   →  qa-agent analyse
    3. Generate debug report →  qa-agent report      (Claude / OpenAI / Gemini)
    4. AI code summaries     →  qa-agent summarise   (Claude / OpenAI / Gemini)

  Commands:

    regression   Source env, run regression (basic or slurm), capture log
    analyse      Parse results file, re-run failed tests, generate QA report
    report       Generate an AI-driven debug report from simulation output
    summarise    Summarise files / directories using an AI provider
    doctor       Check environment: SDKs, API keys, Python version
    hello        Welcome screen and quick start
    guide        This command — short practical guides

  Global flags (work with any command):

    --verbose, -v    Detailed output + full tracebacks
    --debug          Verbose + session log + step-through on regression/analyse
    --version, -V    Print version and exit

  Usage:  qa-agent guide <command>   for a detailed guide.
"""

# ── Guide registry ────────────────────────────────────────────────────────────

GUIDES: dict[str, tuple[str, str, str]] = {
    "regression": (
        "qa-agent regression",
        "Run a full regression — source env, execute, verify",
        _REGRESSION_BODY,
    ),
    "analyse": (
        "qa-agent analyse",
        "Parse failures, re-run debug, generate QA report",
        _ANALYSE_BODY,
    ),
    "summarise": (
        "qa-agent summarise",
        "Summarise files or directories using AI",
        _SUMMARISE_BODY,
    ),
    "doctor": (
        "qa-agent doctor",
        "Check that your environment is correctly set up",
        _DOCTOR_BODY,
    ),
    "report": (
        "qa-agent report",
        "Generate an AI-driven debug report from sim output",
        _REPORT_BODY,
    ),
}


# ── Rendering ─────────────────────────────────────────────────────────────────

def _print_guide_panel(title: str, one_liner: str) -> None:
    """Print the header panel for a guide using the shared print_header."""
    print_header(title.replace("qa-agent ", ""), one_liner)


def _print_body(body: str) -> None:
    """Print the guide body with consistent formatting."""
    for line in body.strip().splitlines():
        stripped = line.strip()
        if stripped.startswith("$"):
            # Command example — highlight the $ and bold the command
            parts = line.split("$", 1)
            indent = parts[0]
            cmd = parts[1].strip()
            print(f"{indent}{cyan('$')} {bold(cmd)}")
        elif stripped.endswith(":") and not stripped.startswith("--"):
            # Section header (e.g. "  What it does:")
            print(f"\n  {bold(stripped)}")
        elif stripped.startswith("--"):
            # Flag definition line
            flag_parts = stripped.split(None, 1)
            if len(flag_parts) == 2:
                print(f"    {cyan(flag_parts[0])}  {dim(flag_parts[1])}")
            else:
                print(f"    {cyan(stripped)}")
        elif stripped.startswith("See also:"):
            print(f"\n  {dim(stripped)}")
        else:
            print(line)


# ── Entry point ───────────────────────────────────────────────────────────────

def run(command: str = "") -> None:
    """Print the guide for *command*, or the overview if command is empty."""
    if not command:
        _print_guide_panel("qa-agent guide", "Quick reference for all commands")
        _print_body(_OVERVIEW_BODY)
        return

    if command not in GUIDES:
        available = ", ".join(GUIDES.keys())
        print(f"\n  No guide for '{command}'. Available: {available}\n")
        return

    title, one_liner, body = GUIDES[command]
    _print_guide_panel(title, one_liner)
    _print_body(body)
