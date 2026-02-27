import argparse
import importlib.metadata
import sys

from qa_agent.session_log import SessionLog


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="qa-agent",
        description="QA Agent — automate post-regression triage for DV engineers.",
        epilog=(
            "Examples:\n"
            "  qa-agent doctor                   # check environment\n"
            "  qa-agent summarise                # summarise cwd\n"
            "  qa-agent summarise src/ -p gemini\n"
            "  qa-agent analyse                  # parse results and generate QA report\n"
            "  qa-agent --version\n"
        ),
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
    subparsers.add_parser("hello", help="Print a greeting message.")

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

    # ── dispatch ──────────────────────────────────────────────────────────────
    args = parser.parse_args()

    # --debug implies --verbose
    if getattr(args, "debug", False):
        args.verbose = True

    log = SessionLog.open(debug=getattr(args, "debug", False))
    exit_code = 0

    try:
        if args.command == "hello":
            print("Hello 👋 I am QA Agent. How can I help you?")

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

        elif args.command == "analyse":
            from qa_agent.analyse import run as analyse_run
            analyse_run(
                mode=args.mode,
                working_dir=args.working_dir,
                output=args.output,
                script=args.script,
                test_filter=args.test,
                verbose=args.verbose,
            )

        elif args.command == "regression":
            from qa_agent.regression import run as regression_run
            regression_run(
                slurm=args.slurm,
                verbose=args.verbose,
                log=log,
            )

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
