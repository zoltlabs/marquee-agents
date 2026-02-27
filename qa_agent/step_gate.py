"""qa_agent/step_gate.py

Step-through execution gate for debug mode.

Wraps each pipeline step in regression.py and analyse.py with a gate that:
  - Prints step result (✓ / ✗) to stdout
  - In debug mode: waits for Enter (continue) or Esc (abort)
  - Appends StepRecord to StepLog for the final log file
  - On failure: records error without re-raising (caller checks ctx.ok)
"""

from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from qa_agent.output import bold, dim, green, red


@dataclass
class StepRecord:
    """One completed step's record for the log file."""
    number: int
    title: str
    status: str                      # "OK", "FAILED", "SKIPPED"
    detail: str = ""
    duration_s: float = 0.0
    output: str = ""                 # captured subprocess output (if any)
    error: str = ""                  # error message on failure


@dataclass
class StepLog:
    """Accumulates step results for the final log file."""
    command: str                     # "regression" or "analyse"
    mode: str                        # "basic", "slurm", etc.
    started: datetime = field(default_factory=datetime.now)
    steps: list[StepRecord] = field(default_factory=list)

    def add(self, step: StepRecord) -> None:
        """Append a completed step record."""
        self.steps.append(step)

    def write(self, path: Path) -> None:
        """Write the full log to disk in the human-readable format."""
        with open(path, "w") as f:
            f.write("═" * 55 + "\n")
            f.write(f"  qa-agent {self.command} — run log\n")
            f.write(f"  Started: {self.started.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"  Mode: {self.mode}\n")
            f.write("═" * 55 + "\n\n")

            for step in self.steps:
                f.write(f"── Step {step.number}: {step.title} ")
                f.write("─" * max(1, 50 - len(step.title)) + "\n")
                if step.detail:
                    f.write(f"  {step.detail}\n")
                dur = f" ({step.duration_s:.1f}s)" if step.duration_s else ""
                f.write(f"  Status: {step.status}{dur}\n")
                if step.output:
                    f.write("  Output:\n")
                    for line in step.output.splitlines()[:200]:
                        f.write(f"    | {line}\n")
                if step.error:
                    f.write(f"  Error: {step.error}\n")
                f.write("\n")

            # Summary
            failed = [s for s in self.steps if s.status == "FAILED"]
            elapsed = sum(s.duration_s for s in self.steps)
            f.write("── Result " + "─" * 45 + "\n")
            if failed:
                f.write(f"  Outcome: FAILED at Step {failed[0].number}\n")
            else:
                f.write("  Outcome: OK\n")
            f.write(f"  Duration: {_fmt_duration(elapsed)}\n")
            f.write(f"  Log: {path.name}\n")
            f.write("═" * 55 + "\n")


class StepContext:
    """Yielded by step_gate(); lets the step body record detail and errors."""

    def __init__(self) -> None:
        self.ok: bool = True
        self.detail: str = ""
        self.output: str = ""
        self.error: str = ""

    def fail(self, msg: str) -> None:
        """Mark this step as failed. The gate will NOT re-raise."""
        self.ok = False
        self.error = msg


@contextmanager
def step_gate(
    step_num: int,
    title: str,
    debug: bool,
    step_log: StepLog,
):
    """Context manager that wraps one pipeline step.

    Usage::

        with step_gate(1, "Source environment", debug, log) as ctx:
            # ... do work ...
            ctx.detail = "sourcefile_2025_3.csh"

    On exit:
      - Prints step result (✓ / ✗) to stdout
      - In debug mode: waits for Enter (continue) or Esc (abort)
      - Appends StepRecord to step_log
      - On failure: records error; does NOT re-raise
      - Caller checks ctx.ok to decide whether to continue
    """
    ctx = StepContext()
    if debug:
        print(f"\n  {dim('──')} Step {step_num}: {bold(title)} {dim('──')}")

    t0 = time.monotonic()
    try:
        yield ctx
    except Exception as exc:
        ctx.fail(str(exc))

    elapsed = time.monotonic() - t0

    # Print result
    if debug:
        if ctx.ok:
            print(f"  {green('✓')}  {title}  {dim(f'({elapsed:.1f}s)')}")
        else:
            print(f"  {red('✗')}  {title}  {dim(f'({elapsed:.1f}s)')}")
            if ctx.error:
                print(f"      {red(ctx.error)}")

    # Record
    step_log.add(StepRecord(
        number=step_num,
        title=title,
        status="OK" if ctx.ok else "FAILED",
        detail=ctx.detail,
        duration_s=elapsed,
        output=ctx.output,
        error=ctx.error,
    ))

    # Debug gate — wait for user
    if debug and sys.stdout.isatty():
        if ctx.ok:
            cont = _wait_for_keypress("Press Enter to continue · Esc to abort")
        else:
            cont = _wait_for_keypress("Press Enter to continue · Esc to exit")
        if not cont:
            ctx.ok = False
            ctx.error = "Aborted by user"


def _wait_for_keypress(prompt: str) -> bool:
    """Block until user presses Enter (returns True) or Esc (returns False).

    Falls back to input() if not a TTY.
    Uses termios on Unix for raw key reading.
    """
    if not sys.stdin.isatty():
        return True  # auto-continue in non-TTY
    print(f"  {dim(prompt)}", end="", flush=True)
    try:
        import termios
        import tty
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        print()  # newline after keypress
        return ch != "\x1b"  # Esc = abort, anything else = continue
    except (ImportError, Exception):
        # Fallback: simple input
        try:
            input()
            return True
        except (EOFError, KeyboardInterrupt):
            return False


def write_log(step_log: StepLog, cwd: Path) -> Path:
    """Write the accumulated log to cwd. Returns the log file path."""
    ts = step_log.started.strftime("%Y%m%d_%H%M%S")
    path = cwd / f"{step_log.command}_{ts}.log"
    step_log.write(path)
    return path


def _fmt_duration(seconds: float) -> str:
    """Format seconds as 'Xh Ym Zs' or 'Xm Zs' or 'Zs'."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"
