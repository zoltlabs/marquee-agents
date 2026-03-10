import argparse
import importlib.metadata
import sys
from pathlib import Path

from qa_agent.session_log import SessionLog


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="qa-agent",
        description="Post-regression triage automation for DV engineers.",
        epilog="Run  qa-agent guide <command>  for practical examples.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # ── Global flags ──────────────────────────────────────────────────────────
    try:
        _version = importlib.metadata.version("qa-agent")
    except importlib.metadata.PackageNotFoundError:
        _version = "dev"

    parser.add_argument(
        "--version", "-V",
        action="version",
        version=f"%(prog)s {_version}",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Show detailed progress, raw provider output, and full tracebacks.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Developer mode: --verbose + write a session log to disk.",
    )

    subparsers = parser.add_subparsers(dest="command")

    # ── hello ─────────────────────────────────────────────────────────────────
    subparsers.add_parser("hello", help="Welcome screen and quick start info.")

    # ── summarise ─────────────────────────────────────────────────────────────
    summarise_parser = subparsers.add_parser(
        "summarise",
        help="Summarise files or directories using AI.",
        description=(
            "Analyse and explain files using AI.\n\n"
            "  qa-agent summarise               # summarise current directory (pwd)\n"
            "  qa-agent summarise file.py       # summarise a single file\n"
            "  qa-agent summarise a.py b.py     # summarise multiple files\n"
            "  qa-agent summarise src/          # summarise an entire directory\n"
            "  qa-agent summarise .             # summarise current directory explicitly\n\n"
            "Defaults to Claude. Use -p / --provider to override."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    summarise_parser.add_argument(
        "paths",
        nargs="*",
        metavar="PATH",
        help="Files or directories to summarise. Omit to summarise the current directory.",
    )
    summarise_parser.add_argument(
        "--provider", "-p",
        choices=["claude", "openai", "gemini"],
        default="claude",
        metavar="PROVIDER",
        help="AI provider to use: claude (default), openai, gemini.",
    )

    # ── doctor ────────────────────────────────────────────────────────────────
    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Check environment health (SDKs, auth, log system).",
        description=(
            "Validates that all provider SDKs and credentials are correctly\n"
            "configured. Exit 0 = ready, Exit 1 = one or more errors found."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    doctor_parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show raw values and full paths for each check.",
    )

    # ── analyse ───────────────────────────────────────────────────────────────
    analyse_parser = subparsers.add_parser(
        "analyse",
        help="Parse a regression results file and generate a QA report.",
        description=(
            "Reads results.doc or results_new.doc from the working directory,\n"
            "identifies FAILED entries, and writes a Markdown QA report.\n\n"
            "  qa-agent analyse\n"
            "  qa-agent analyse --mode slurm --working-dir /path/to/run\n"
            "  qa-agent analyse --output my_report.md\n"
            "  qa-agent analyse --test apcit_cpl_out_order   # single test only\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    analyse_parser.add_argument(
        "--mode",
        choices=["basic", "slurm"],
        default=None,
        help="Explicit mode override (default: auto-detected from filename).",
    )
    analyse_parser.add_argument(
        "--working-dir",
        default=".",
        metavar="PATH",
        help="Directory containing results.doc / results_new.doc (default: CWD).",
    )
    analyse_parser.add_argument(
        "--output",
        default=None,
        metavar="PATH",
        help="Path for the output report (default: qa_report_<timestamp>.md in CWD).",
    )
    analyse_parser.add_argument(
        "--script", "-s",
        default="",
        metavar="SCRIPT",
        help="Path to the debug shell script (embedded in report debug commands).",
    )
    analyse_parser.add_argument(
        "--test", "-t",
        default=None,
        metavar="NAME",
        help="Focus on a single test case by name (skips all other failures).",
    )
    analyse_parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Print detailed progress to stdout (debug dirs, command text, etc.).",
    )
    analyse_parser.add_argument(
        "--cmd",
        action="store_true",
        default=False,
        help="Print the generated debug commands for each failure and exit (no runs, no report).",
    )

    # ── report ────────────────────────────────────────────────────────────────
    report_parser = subparsers.add_parser(
        "report",
        help="AI-driven debug report from Questa simulation output.",
        description=(
            "Generate a structured debug report from Questa/Visualizer simulation output.\n\n"
            "Stream mode (default): pre-fetches all data into a single AI prompt.\n"
            "Agentic mode (--agentic): AI uses tools to discover and fetch data;\n"
            "  each result is shown for preview before feeding to AI.\n\n"
            "  # Stream mode (default):\n"
            "  qa-agent report /path/to/debug_apcit_cpl_out_order_1234\n"
            "  qa-agent report . -p openai\n\n"
            "  # Agentic mode:\n"
            "  qa-agent report /path/to/debug_dir --agentic\n"
            "  qa-agent report /path/to/debug_dir --agentic --auto-accept\n"
            "  qa-agent report --agentic               # batch: all debug_* in cwd\n\n"
            "  # Regression comparison:\n"
            "  qa-agent report --compare OLD_SUMMARY.md NEW_SUMMARY.md\n\n"
            "  Output files:\n"
            "  DEBUG_CASE_REPORT_<ts>.md         individual debug case reports\n"
            "  QA-REGRESSION-SUMMARY_<ts>.md     batch aggregate report\n"
            "  QA-AGENT_TIMESTAMPS_<ts>.json     waveform timestamps (agentic)\n"
            "  QA-REGRESSION-COMPARISON_<ts>.md  comparison report (--compare)\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    report_parser.add_argument(
        "sim_dir",
        nargs="?",
        default=None,
        metavar="SIM_DIR",
        help=(
            "Simulation output directory (debug_*/qrun.out/logs/). "
            "If omitted (and --compare not set), runs on all debug_* subdirs in cwd."
        ),
    )
    report_parser.add_argument(
        "--provider", "-p",
        choices=["claude", "openai", "gemini"],
        default="claude",
        metavar="PROVIDER",
        help="AI provider: claude (default), openai, gemini.",
    )
    report_parser.add_argument(
        "--output", "-o",
        default=None,
        metavar="PATH",
        help="Output file path (single-dir mode only; auto-named otherwise).",
    )
    report_parser.add_argument(
        "--max-turns",
        type=int,
        default=20,
        metavar="N",
        help="Max AI investigation turns in agentic mode (default: 20).",
    )
    report_parser.add_argument(
        "--agentic",
        action="store_true",
        default=False,
        help=(
            "Agentic mode: AI uses tools to fetch data. Each result is previewed "
            "before feeding to AI. Includes confidence scoring, waveform timestamps, "
            "and cross-failure correlation in batch mode."
        ),
    )
    report_parser.add_argument(
        "--auto-accept",
        action="store_true",
        default=False,
        dest="auto_accept",
        help=(
            "(Agentic mode) Auto-accept all tool results without review. "
            "Equivalent to pressing Tab+Shift at the start of the session."
        ),
    )
    report_parser.add_argument(
        "--compare",
        nargs=2,
        metavar=("OLD_REPORT", "NEW_REPORT"),
        default=None,
        help=(
            "Compare two QA-REGRESSION-SUMMARY_*.md files and write a "
            "QA-REGRESSION-COMPARISON_*.md diff report (new failures, fixes, recurring)."
        ),
    )
    report_parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Show detailed progress. In agentic mode, adds tool name/args to data preview.",
    )
    report_parser.add_argument(
        "--gvim",
        action="store_true",
        default=False,
        help=(
            "Open data for AI review in gvim instead of terminal preview. "
            "In stream mode: shows assembled prompt. "
            "In agentic mode: each tool result opens in gvim."
        ),
    )


    # ── regression ────────────────────────────────────────────────────────────
    regression_parser = subparsers.add_parser(
        "regression",
        help="Run a regression (basic or slurm mode).",
        description=(
            "Source environment, locate inputs, execute regression,\n"
            "capture logs, and verify results.\n\n"
            "  qa-agent regression                # basic regression\n"
            "  qa-agent regression --slurm        # slurm mode\n"
            "  qa-agent regression --verbose      # print full resolved paths + commands\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    regression_parser.add_argument(
        "source",
        nargs="?",
        default=None,
        help="Target directory name in sig_pcie/verif/AVERY/run/results/",
    )
    regression_parser.add_argument(
        "--slurm",
        action="store_true",
        default=False,
        help="Run in Slurm mode (requires config.txt + run_questa.sh).",
    )
    regression_parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Print detailed progress (resolved paths, full commands).",
    )

    # ── init ──────────────────────────────────────────────────────────────────
    init_parser = subparsers.add_parser(
        "init",
        help="Interactive wizard: discover project files and write qa-agent.yaml.",
        description=(
            "Scans your project tree and guides you through selecting the right\n"
            "source file, regression scripts, debug script, and output names.\n"
            "Writes qa-agent.yaml to the project root.\n\n"
            "  qa-agent init                        # auto-detect project root\n"
            "  qa-agent init /path/to/my_project    # explicit root\n"
            "  qa-agent init --force                # overwrite existing config\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    init_parser.add_argument(
        "root",
        nargs="?",
        default=None,
        metavar="ROOT",
        help="Project root directory (default: auto-detect via RTL/ directory heuristic).",
    )
    init_parser.add_argument(
        "--force", "-f",
        action="store_true",
        default=False,
        help="Overwrite existing qa-agent.yaml without prompting.",
    )
    init_parser.add_argument(
        "--use_defaults",
        action="store_true",
        default=False,
        help="Skip interactive wizard; auto-detect paths and use all default values.",
    )

    # ── config ────────────────────────────────────────────────────────────────
    subparsers.add_parser(
        "config",
        help="Open qa-agent.yaml in your editor ($EDITOR, default: vim).",
        description="Opens the project qa-agent.yaml config file for manual editing.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # ── guide ─────────────────────────────────────────────────────────────────
    sp_guide = subparsers.add_parser(
        "guide",
        help="Short user guide for any command.",
        description="Show a practical guide with examples for a command.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sp_guide.add_argument(
        "topic",
        nargs="?",
        default="",
        choices=["regression", "analyse", "summarise", "doctor", "init", ""],
        metavar="COMMAND",
        help="Command to show guide for (omit for overview of all commands).",
    )

    # ── dispatch ──────────────────────────────────────────────────────────────
    args = parser.parse_args()

    # --debug implies --verbose
    if getattr(args, "debug", False):
        args.verbose = True

    log = SessionLog.open(debug=getattr(args, "debug", False))
    exit_code = 0

    def _require_config() -> bool:
        """Return True if a valid qa-agent.yaml is found; print a clear error and
        return False otherwise. Called before regression / analyse."""
        from qa_agent.config import find_config, load_config, ConfigError
        from qa_agent.output import bold, red, cyan, dim
        cfg_path = find_config(Path.cwd())
        if cfg_path is None:
            print()
            print(f"  {red('✖')}  No qa-agent.yaml found.")
            print(f"  {dim('Run')}  {bold('qa-agent init')}  {dim('to set up your project config first.')}")
            print()
            return False
        try:
            load_config(cfg_path)   # validates required keys
            return True
        except Exception as exc:
            print()
            print(f"  {red('✖')}  Config error: {exc}")
            print(f"  {dim('Fix it with')}  {bold('qa-agent config')}  {dim('or re-run')}  {bold('qa-agent init')}")
            print()
            return False

    try:
        if args.command == "hello":
            from qa_agent.output import print_welcome
            print_welcome()

        elif args.command == "summarise":
            from qa_agent.summarise import run
            run(
                provider=args.provider,
                paths=args.paths,
                verbose=args.verbose,
                log=log,
            )

        elif args.command == "doctor":
            from qa_agent.doctor import run as doctor_run
            doctor_run(verbose=args.verbose)

        elif args.command == "report":
            from qa_agent.report import run as do_report
            do_report(
                sim_dir=args.sim_dir,
                provider=args.provider,
                output=args.output,
                max_turns=args.max_turns,
                verbose=args.verbose,
                debug=args.debug,
                gvim=args.gvim,
                agentic=getattr(args, "agentic", False),
                auto_accept=getattr(args, "auto_accept", False),
                compare=tuple(args.compare) if getattr(args, "compare", None) else None,
                log=log,
            )

        elif args.command == "analyse":
            if not _require_config():
                sys.exit(1)
            from qa_agent.analyse import run as analyse_run
            analyse_run(
                mode=args.mode,
                working_dir=args.working_dir,
                output=args.output,
                script=args.script,
                test_filter=args.test,
                verbose=args.verbose,
                debug=args.debug,
                cmd_only=args.cmd,
                log=log,
            )

        elif args.command == "regression":
            if not _require_config():
                sys.exit(1)
            from qa_agent.regression import run as regression_run
            regression_run(
                source=getattr(args, "source", None),
                slurm=args.slurm,
                verbose=args.verbose,
                debug=args.debug,
                log=log,
            )

        elif args.command == "init":
            from qa_agent.init import run as init_run
            init_run(
                root=getattr(args, "root", None),
                force=getattr(args, "force", False),
                use_defaults=getattr(args, "use_defaults", False),
                verbose=args.verbose,
            )

        elif args.command == "config":
            from qa_agent.init import open_config
            open_config(verbose=args.verbose)

        elif args.command == "guide":
            from qa_agent.guide import run as guide_run
            guide_run(getattr(args, "topic", ""))

        else:
            parser.print_help()

    except SystemExit as exc:
        exit_code = int(exc.code) if exc.code is not None else 0
        raise
    except Exception as exc:
        from qa_agent.errors import handle_exception
        exit_code = handle_exception(exc, verbose=getattr(args, "verbose", False), log=log)
        sys.exit(exit_code)
    finally:
        log.close(exit_code)
