import argparse

def main():
    parser = argparse.ArgumentParser(prog="qa-agent")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("hello")

    args = parser.parse_args()

    if args.command == "hello":
        print("Hello ? I am QA Agent. How can I help you?")
    else:
        parser.print_help()
