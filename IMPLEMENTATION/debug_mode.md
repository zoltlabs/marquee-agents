# `qa-agent` Debug Mode — Implementation Plan

> **Status:** Implemented
> **Branch:** `main`
> **Module:** `qa_agent/step_gate.py` (new), `qa_agent/regression.py`, `qa_agent/analyse.py`, `qa_agent/cli.py`

---

## Overview

Add a step-through debug mode to `regression` and `analyse` commands. Each
pipeline step executes, shows its result on stdout, and waits for user
confirmation before proceeding. On failure — in both normal and debug mode —
a timestamped log file is written to the working directory.

---

## Concept

Both `regression` and `analyse` already execute multi-step pipelines. Debug mode
wraps each step in a **gate**:

```
┌─────────────────────────────────────────────────────┐
│  Step N: <description>                              │
│                                                     │
│  <step executes, output streams to stdout>          │
│                                                     │
│  ✓  Step N complete                                 │
│  Press Enter to continue · Esc to abort             │
└─────────────────────────────────────────────────────┘
```

- On **Enter** → proceed to next step.
- On **Esc** → write log, print log path, exit cleanly.
- On **failure** at any step → write log, show error, pause with
  `Press Enter to view log / Esc to exit`.

---

## Activation

Debug mode is activated via the existing `--debug` global flag, which already
sets `verbose=True` and enables session logging. The step-through gate is
layered on top.

```bash
qa-agent --debug regression          # step-through basic regression
qa-agent --debug regression --slurm  # step-through slurm regression
qa-agent --debug analyse             # step-through analyse pipeline
```

Normal mode (no `--debug`) runs the full pipeline without pauses but still
writes a log file **on failure**.

---

## Log Files

### When logs are written

| Mode | On success | On failure |
|------|------------|------------|
| Normal (no `--debug`) | No log | Write log |
| Debug (`--debug`) | Write log | Write log |

### Filename convention

| Command | Log filename | Location |
|---------|-------------|----------|
| `regression` | `regression_<YYYYMMDD_HHMMSS>.log` | Current working directory |
| `analyse` | `analyse_<YYYYMMDD_HHMMSS>.log` | Current working directory |

### Log format (plain text, human-readable)

```
═══════════════════════════════════════════════════════
  qa-agent regression — run log
  Started: 2026-02-27 14:30:22
  Mode: basic
═══════════════════════════════════════════════════════

── Step 1: Source environment ─────────────────────────
  File: sourcefile_2025_3.csh
  Status: OK
  Duration: 1.2s

── Step 2: Locate filelist.txt ────────────────────────
  Found: /path/to/filelist.txt (cwd)
  Status: OK

── Step 3: Select regression script ───────────────────
  Selected: regression_8B_16B_questa.py [qa-agent]
  Status: OK

── Step 4: Execute regression ─────────────────────────
  Command: python3 regression_8B_16B_questa.py filelist.txt
  Exit code: 1
  Status: FAILED
  Captured output:
    | <first 200 lines of subprocess output>
    | ...

── Summary ────────────────────────────────────────────
  Result: FAILED at Step 4
  Duration: 4m 12s
  Log: /path/to/regression_20260227_143022.log
═══════════════════════════════════════════════════════
```

---

## Step Gate Implementation

### New file: `qa_agent/step_gate.py`

```python
"""Step-through execution gate for debug mode."""

from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from qa_agent.output import bold, cyan, dim, green, red, yellow, rule


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
    ok: bool = True
    detail: str = ""
    output: str = ""
    error: str = ""

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
    """
    Context manager that wraps one pipeline step.

    Usage:
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
    print(f"\n  {dim('──')} Step {step_num}: {bold(title)} {dim('──')}")

    t0 = time.monotonic()
    try:
        yield ctx
    except Exception as exc:
        ctx.fail(str(exc))

    elapsed = time.monotonic() - t0

    # Print result
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
            ctx.fail("Aborted by user")


def _wait_for_keypress(prompt: str) -> bool:
    """
    Block until user presses Enter (returns True) or Esc (returns False).
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
    except (ImportError, termios.error):
        # Fallback: simple input
        try:
            input()
            return True
        except (EOFError, KeyboardInterrupt):
            return False


def write_log(step_log: StepLog, cwd: Path) -> Path:
    """
    Write the accumulated log to cwd.
    Returns the log file path.
    """
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
```

---

## `regression.py` — Debug Mode Changes

### Updated `run()` signature

```python
def run(
    slurm: bool = False,
    verbose: bool = False,
    debug: bool = False,        # NEW
    log: SessionLog | None = None,
) -> None:
```

### Step mapping

| Step | Title | Action | On failure |
|------|-------|--------|------------|
| 1 | Source environment | Select + validate `.csh` file | `ConfigError` → log, show fix hint |
| 2 | Locate filelist | Find `filelist.txt` in cwd or bundled | Log "not found" + user declined |
| 3 | Locate config *(slurm only)* | Find `config.txt` | Same as step 2 |
| 4 | Locate run_questa.sh *(slurm only)* | Find launcher script | Log "not found" |
| 5 | Select regression script | Interactive or auto-select `.py` | `ConfigError` |
| 6 | Execute regression | `Popen` with live streaming | Non-zero exit → log captured output |
| 7 | Verify results | Check `results.doc` / `results_new.doc` | Warning (not fatal) |

### Integration pattern

```python
from qa_agent.step_gate import StepLog, step_gate, write_log

def run(slurm=False, verbose=False, debug=False, log=None):
    mode = "slurm" if slurm else "basic"
    step_log = StepLog(command="regression", mode=mode)

    # Step 1
    with step_gate(1, "Source environment", debug, step_log) as ctx:
        source_file = _select_source_file()
        ctx.detail = f"File: {source_file.name}"
    if not ctx.ok:
        log_path = write_log(step_log, Path.cwd())
        print(f"  Log: {log_path}")
        return

    # Step 2
    with step_gate(2, "Locate filelist", debug, step_log) as ctx:
        filelist = _locate_filelist()
        ctx.detail = f"Found: {filelist.name}"
    if not ctx.ok:
        log_path = write_log(step_log, Path.cwd())
        print(f"  Log: {log_path}")
        return

    # ... steps 3-7 follow same pattern ...

    # Always write log in debug mode; on failure in normal mode
    has_failure = any(s.status == "FAILED" for s in step_log.steps)
    if debug or has_failure:
        log_path = write_log(step_log, Path.cwd())
        print(f"\n  Log: {log_path}")
```

### Normal mode (no `--debug`) behaviour

- Steps run without pause (no keypress gates).
- On **any failure** at steps 1–6: write `regression_<timestamp>.log` to cwd,
  print log path, exit with error.
- On step 7 warning: print warning, still write log if debug.

### Debug mode (`--debug`) behaviour

- After each step: print result, wait for Enter/Esc.
- On failure: pause, show error, offer to continue or abort.
- Log file is **always** written at the end (success or failure).

---

## `analyse.py` — Debug Mode Changes

### Updated `run()` signature

```python
def run(
    mode: str | None = None,
    working_dir: str = ".",
    output: str | None = None,
    script: str = "",
    test: str = "",
    verbose: bool = False,
    debug: bool = False,        # NEW
    log: SessionLog | None = None,
) -> None:
```

### Step mapping

| Step | Title | Action | On failure |
|------|-------|--------|------------|
| 1 | Read results file | Find `results.doc` / `results_new.doc` | `PathError` → log |
| 2 | Parse results | Regex parse, count pass/fail | Zero lines → log |
| 3 | Filter by test *(if `--test`)* | Filter failed list | No matches → log |
| 4 | Select source file | Interactive `.csh` selection | Warning only (non-fatal) |
| 5 | Select debug script | Interactive `.pl` selection | Warning only (non-fatal) |
| 6 | Create debug dirs | `mkdir` per failure | Permission error → log |
| 7 | Run debug commands | `subprocess.run` per failure | Per-failure error capture |
| 8 | Write report | Generate Markdown report | IO error → log |

### Integration pattern

Same as regression — wrap each step in `step_gate`, check `ctx.ok`, write log
on failure or when debug is active.

**Step 7 special handling:** In debug mode, the gate pauses after **each
individual debug run** (not just after the whole batch), showing exit code and
offering continue/abort:

```python
for i, result in enumerate(failed, 1):
    with step_gate(
        7, f"Debug [{i}/{len(failed)}] {result.test} seed={result.seed}",
        debug, step_log,
    ) as ctx:
        outcome = _run_debug(result, debug_dirs[result], ...)
        ctx.detail = f"exit={outcome.exit_code}"
        if outcome.timed_out:
            ctx.fail("Timed out after 2h")
        elif outcome.exit_code != 0:
            ctx.detail += " (non-zero, captured in report)"
            # NOT a fatal failure — debug run errors are expected
    outcomes.append(outcome)
```

### Normal mode behaviour

- Steps run without pause.
- On fatal failure (steps 1–3, 6, 8): write `analyse_<timestamp>.log`, print
  log path, exit.
- Individual debug command failures (step 7) are non-fatal — captured in report.

### Debug mode behaviour

- After each step: print result, wait for Enter/Esc.
- Step 7 pauses after **each failure run**, showing the exit code.
- Log file always written.

---

## `cli.py` Changes

Pass the `debug` flag down to both commands:

```python
# regression dispatch
if args.command == "regression":
    from qa_agent.regression import run
    run(
        slurm=args.slurm,
        verbose=args.verbose,
        debug=args.debug,          # NEW
        log=log,
    )

# analyse dispatch
if args.command == "analyse":
    from qa_agent.analyse import run as analyse_run
    analyse_run(
        mode=args.mode,
        working_dir=args.working_dir,
        output=args.output,
        script=args.script,
        test=args.test,
        verbose=args.verbose,
        debug=args.debug,          # NEW
        log=log,
    )
```

---

## Log File Examples

### `regression_20260227_143022.log` (failure case)

```
═══════════════════════════════════════════════════════
  qa-agent regression — run log
  Started: 2026-02-27 14:30:22
  Mode: basic
═══════════════════════════════════════════════════════

── Step 1: Source environment ─────────────────────────
  File: sourcefile_2025_3.csh [qa-agent]
  Status: OK (0.8s)

── Step 2: Locate filelist.txt ────────────────────────
  Found: filelist.txt [cwd]
  Status: OK

── Step 3: Select regression script ───────────────────
  Selected: regression_8B_16B_questa.py [qa-agent]
  Status: OK

── Step 4: Execute regression ─────────────────────────
  Command: python3 /path/to/regression_8B_16B_questa.py filelist.txt
  Exit code: 1
  Status: FAILED
  Output (last 50 lines):
    | Error: Unable to find test bench file
    | Traceback: ...

── Result ─────────────────────────────────────────────
  Outcome: FAILED at Step 4
  Log: regression_20260227_143022.log
═══════════════════════════════════════════════════════
```

### `analyse_20260227_151200.log` (partial success with timeout)

```
═══════════════════════════════════════════════════════
  qa-agent analyse — run log
  Started: 2026-02-27 15:12:00
  Mode: basic (auto-detected from results.doc)
═══════════════════════════════════════════════════════

── Step 1: Read results file ──────────────────────────
  Path: /work/regression/results.doc
  Status: OK

── Step 2: Parse results ──────────────────────────────
  Passed: 42 | Failed: 3
  Status: OK

── Step 3: Select source file ─────────────────────────
  Selected: sourcefile_2025_3.csh [qa-agent]
  Status: OK

── Step 4: Select debug script ────────────────────────
  Selected: run_apci_2025.pl [qa-agent]
  Status: OK

── Step 5: Create debug directories ───────────────────
  Created: 3 directories
  Status: OK

── Step 6: Run debug commands ─────────────────────────
  [1/3] apcit_cpl_out_order  seed=1234  exit=0  OK (12m 3s)
  [2/3] apcit_cpl_out_order  seed=5678  TIMEOUT (2h 0m 0s)
  [3/3] pcie_bar_test         seed=9999  exit=1  FAILED (8m 22s)
  Status: PARTIAL (1 ok, 1 timeout, 1 failed)

── Step 7: Write report ───────────────────────────────
  Path: /work/qa_report_20260227_151200.md
  Status: OK

── Result ─────────────────────────────────────────────
  Outcome: COMPLETED WITH WARNINGS
  Duration: 2h 20m 25s
  Log: analyse_20260227_151200.log
═══════════════════════════════════════════════════════
```

---

## Error Handling

| Scenario | Log behaviour | User sees |
|----------|--------------|-----------|
| Step fails in normal mode | Log written immediately | `✗ <step>` + log path |
| Step fails in debug mode | Log written, pause for user | `✗ <step>` + error + Enter/Esc prompt |
| User presses Esc | Log written with "Aborted" | `ℹ Aborted at Step N` + log path |
| All steps pass (normal) | No log written | Normal output |
| All steps pass (debug) | Log written | Normal output + log path |
| Non-TTY + debug | No pauses, log written | Same as debug but auto-continue |

---

## New / Updated Files

| File | Action | Description |
|------|--------|-------------|
| `qa_agent/step_gate.py` | **New** | `StepLog`, `StepRecord`, `StepContext`, `step_gate()`, `write_log()` |
| `qa_agent/regression.py` | **Update** | Add `debug` param, wrap steps in `step_gate` |
| `qa_agent/analyse.py` | **Update** | Add `debug` param, wrap steps in `step_gate` |
| `qa_agent/cli.py` | **Update** | Pass `debug=args.debug` to regression and analyse |

---

## Testing Checklist

- [ ] `qa-agent regression` (no debug) — runs without pauses
- [ ] `qa-agent regression` failure — writes `regression_<ts>.log`
- [ ] `qa-agent --debug regression` — pauses after each step
- [ ] `qa-agent --debug regression` + Esc — aborts, writes log
- [ ] `qa-agent --debug regression` success — writes log
- [ ] `qa-agent analyse` (no debug) — runs without pauses
- [ ] `qa-agent analyse` failure — writes `analyse_<ts>.log`
- [ ] `qa-agent --debug analyse` — pauses after each step
- [ ] `qa-agent --debug analyse` step 7 — pauses per debug run
- [ ] Non-TTY (piped) — no pauses, auto-continue
- [ ] Log file format matches spec
- [ ] Log captures subprocess output (first 200 lines)
