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
