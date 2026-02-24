import argparse


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="qa-agent",
        description="QA Agent — automate post-regression triage for DV engineers.",
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
            "Defaults to Claude. Pass a provider flag to override."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    summarise_parser.add_argument(
        "paths",
        nargs="*",
        metavar="PATH",
        help=(
            "Files or directories to summarise. "
            "Omit to summarise the current directory."
        ),
    )
    provider_group = summarise_parser.add_mutually_exclusive_group()
    provider_group.add_argument(
        "-claude",
        dest="provider",
        action="store_const",
        const="claude",
        help="Use Claude Agent SDK (default).",
    )
    provider_group.add_argument(
        "-openai",
        dest="provider",
        action="store_const",
        const="openai",
        help="Use OpenAI Chat Completions API (GPT-4o).",
    )
    provider_group.add_argument(
        "-gemini",
        dest="provider",
        action="store_const",
        const="gemini",
        help="Use Google Gemini API.",
    )
    summarise_parser.set_defaults(provider="claude")

    # ── dispatch ──────────────────────────────────────────────────────────────
    args = parser.parse_args()

    if args.command == "hello":
        print("Hello 👋 I am QA Agent. How can I help you?")

    elif args.command == "summarise":
        from qa_agent.summarise import run
        run(provider=args.provider, paths=args.paths)

    else:
        parser.print_help()
