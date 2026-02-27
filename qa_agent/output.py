"""qa_agent/output.py

Central terminal rendering for all qa-agent commands.

Usage:
    from qa_agent.output import (
        bold, cyan, red, green, yellow, dim, magenta, rule,
        print_banner, print_success, print_error, render_line,
        Spinner,
    )

Never import ANSI helpers directly from summarise.py.
"""

from __future__ import annotations

import itertools
import sys
import threading
import time

# ─────────────────────────────────────────────────────────────────────────────
# TTY detection
# ─────────────────────────────────────────────────────────────────────────────
USE_COLOR: bool = sys.stdout.isatty()


# ─────────────────────────────────────────────────────────────────────────────
# ANSI colour helpers
# ─────────────────────────────────────────────────────────────────────────────

def _c(code: str, text: str) -> str:
    """Wrap *text* in an ANSI escape sequence (no-op when not a TTY)."""
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text


def bold(t: str) -> str:    return _c("1", t)
def cyan(t: str) -> str:    return _c("1;36", t)
def green(t: str) -> str:   return _c("1;32", t)
def yellow(t: str) -> str:  return _c("1;33", t)
def red(t: str) -> str:     return _c("1;31", t)
def dim(t: str) -> str:     return _c("2", t)
def magenta(t: str) -> str: return _c("1;35", t)


def rule(char: str = "─", width: int = 60) -> str:
    return dim(char * width)


# ─────────────────────────────────────────────────────────────────────────────
# Banner / footer helpers
# ─────────────────────────────────────────────────────────────────────────────

def print_banner(target_label: str, provider_name: str) -> None:
    """Print the opening banner for a command."""
    print()
    print(rule())
    print(f"  {cyan('qa-agent summarise')}  {dim('·')}  {magenta(provider_name)}")
    print(f"  {dim('Target:')} {bold(target_label)}")
    print(rule())
    print()


def print_doctor_banner() -> None:
    """Print the opening banner for `qa-agent doctor`."""
    print()
    print(rule())
    print(f"  {cyan('qa-agent doctor')}  {dim('·')}  environment health check")
    print(rule())
    print()


def print_regression_banner(mode: str) -> None:
    """Print the opening banner for `qa-agent regression`."""
    print()
    print(rule())
    print(f"  {cyan('qa-agent regression')}  {dim('·')}  Mode: {bold(mode)}")
    print(rule())
    print()


def print_success(msg: str = "Summary complete.") -> None:
    """Print a green success footer."""
    print()
    print(rule())
    print(f"  {green('✓')} {bold(msg)}")
    print(rule())
    print()


def print_error(msg: str) -> None:
    """Print a red error box (multi-line safe)."""
    print()
    print(rule())
    for line in msg.strip().splitlines():
        print(f"  {red('✗')} {line}")
    print(rule())
    print()


# ─────────────────────────────────────────────────────────────────────────────
# Markdown-aware line renderer
# ─────────────────────────────────────────────────────────────────────────────

def render_line(line: str) -> None:
    """Apply ANSI colour to markdown headings; pass the rest through."""
    if line.startswith("## "):
        print(f"\n{cyan(bold(line))}")
    elif line.startswith("### "):
        print(f"\n{bold(line)}")
    elif line.startswith("#### "):
        print(f"{yellow(line)}")
    else:
        print(line)


# ─────────────────────────────────────────────────────────────────────────────
# Live progress spinner
# ─────────────────────────────────────────────────────────────────────────────

class Spinner:
    """Context manager that animates a Braille spinner while the block runs.

    Usage::

        with Spinner("Analysing"):
            ...  # long-running work

    The spinner is silently suppressed when stdout is not a TTY so that piped
    output stays clean.
    """

    _FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

    def __init__(self, label: str, *, stream=sys.stderr) -> None:
        self._label = label
        self._stream = stream
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "Spinner":
        if not USE_COLOR:
            return self
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join()
        if USE_COLOR:
            # Erase the spinner line completely before returning to the caller.
            self._stream.write("\r\033[K")
            self._stream.flush()

    def _spin(self) -> None:
        frames = itertools.cycle(self._FRAMES)
        start = time.monotonic()
        while not self._stop.wait(0.1):
            elapsed = time.monotonic() - start
            frame = next(frames)
            line = f"  {dim(frame)}  {self._label}  {dim(f'{elapsed:.0f}s')}"
            self._stream.write(f"\r{line}")
            self._stream.flush()
