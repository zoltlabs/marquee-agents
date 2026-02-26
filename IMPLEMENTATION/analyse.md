# `qa-agent analyse` — Implementation Plan

Parse a regression results file, identify failed test cases, re-run each
failure in a dedicated debug subdirectory, capture logs, and write a single
Markdown QA report to disk. **No AI — pure Python.**

---

## Command

```bash
qa-agent analyse [--mode basic|slurm] [--working-dir <path>] [--output <path>] [--script/-s <script>]
```

### Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--mode basic\|slurm` | auto-detected from filename | Explicit mode override |
| `--working-dir <path>` | CWD | Where the regression ran (contains config subdirs + logs) |
| `--output <path>` | `qa_report_<timestamp>.md` | Where to write the report |
| `--script / -s <path>` | *(interactive selection)* | Path to the debug Perl/shell script used in generated commands |

> `<timestamp>` format: `YYYYMMDD_HHMMSS` (e.g. `qa_report_20260226_102900.md`)

---

## Execution Steps

### Step 1 — Read the results file

1. Look for `results.doc` or `results_new.doc` inside `--working-dir` (in that
   order).
2. Open the located file.
3. **If neither file is found** → print a clear error message and **stop**:

   ```
   ✗  No results file found in <working-dir>.
      Expected: results.doc  or  results_new.doc
   ```

4. On success → print a confirmation line:

   ```
   ✓  Reading results from: <absolute-path-to-file>
   ```

### Step 2 — Detect failed cases

Parse every line of the results file against the regex patterns below:

- Lines matching `passed for` → **pass** (counted only).
- Lines matching `FAILED for` (case-insensitive) → **fail** (collected for
  report).
- All other lines → silently skipped.

If **zero** recognisable lines are found, stop with:

```
✗  No recognisable test result lines found in '<file>'.
   Check that the file follows the expected format.
```

Print a summary after parsing:

```
  Found N failed test(s) across M unique test names.
```

### Step 3 — Source file selection (interactive)

Before running any debug commands, the user must select a `.csh` environment
source file. This step runs once, before the debug loop.

**Discovery order:**

1. Look for `.csh` files in the **`qa-agent` package directory** (the directory
   that contains `analyse.py`, i.e. `qa_agent/`). This is the "first option".
2. Look for `.csh` files in the **working directory** (`--working-dir`).
3. If `sourcefile_2025_3.csh` exists at the **project root** (i.e. the parent
   of `qa_agent/`), always include it — this is the fallback provided by the
   project.

All discovered `.csh` files are presented in an interactive arrow-key selector
(up/down to move, Enter to confirm). The `qa-agent` package option(s) are
listed **first**; working-directory files follow.

```
  Select a source file to use (↑/↓ arrow keys, Enter to confirm):

  ❯  sourcefile_2025_3.csh   [qa-agent]
     env_setup.csh            [working-dir]
     sim_env.csh              [working-dir]
```

**If only one file is found** → no prompt; use it automatically and print:

```
  ✓  Auto-selected source: <path>
```

**If no `.csh` file is found** → warn and continue without sourcing:

```
  ⚠  No .csh source file found. The debug shell will not be pre-configured.
```

The selected file path is stored as `source_file: Path | None` for use in the
debug commands.

> **Implementation note**: Use `sys.stdin.isatty()` to detect interactive mode.
> If not a TTY (e.g. piped/CI), skip the prompt and use the first found file
> (or none), printing which file was chosen.

### Step 4 — Script file selection (interactive)

Determine which Perl/shell script to use when building debug commands.

**If `--script / -s` was explicitly passed** → use it, skip the prompt.

**Otherwise**, discover candidate script files:

1. Look for `.pl` files in the **current working directory** (CWD).
2. Look for `.pl` files in the **`qa-agent` package directory**.
3. Always include `run_apci_2025.pl` from the `qa-agent` package directory as
   a fallback.

**Selection UX (same arrow-key pattern as Step 3):**

```
  Select a debug script (↑/↓ arrow keys, Enter to confirm):

  ❯  run_apci_2025.pl   [qa-agent]
     my_debug.pl        [cwd]
```

- If **no `.pl` file** is found anywhere → warn and set `script = ""` (commands
  will still be written in the report but cannot be executed).
- If **only one file** is found → auto-select, no prompt.

> **Implementation note**: Non-TTY fallback — use the first discovered `.pl`
> file (qa-agent package preferred), print which script was selected.

### Step 5 — Create per-failure debug subdirectories

For every `TestResult` in the `failed` list, create a dedicated subdirectory
under **`--working-dir`**:

```
<working-dir>/debug_<testcase>_<config_hash>_<seed>/
```

- `<testcase>` — the `test` field from the parsed result line.
- `<config_hash>` — a 6-character lowercase hex hash of `result.configuration`
  (use `hashlib.md5(config.encode()).hexdigest()[:6]`).
- `<seed>` — the seed value parsed from the results file.

Example:

```
debug_apcit_cpl_out_order_a3f9c1_1234567890/
```

Create the directory with `mkdir(parents=True, exist_ok=True)`. Print one
confirmation line per subdirectory:

```
  ✓  Created debug dir: debug_apcit_cpl_out_order_a3f9c1_1234567890/
```

### Step 6 — Run the debug command per failure

For each `TestResult` in `failed`:

1. Construct the full debug command (see **Config Flag Builder** below).
2. If `source_file` was selected in Step 3, prepend `source <source_file> &&`
   to the command so the environment is loaded before execution.
3. Execute via `subprocess.run()` with:
   - `shell=True` (so `source` works in the subshell)
   - `stdout` and `stderr` both captured to a file named `debug.log` inside the
     failure's debug subdirectory.
   - A timeout of **2 hours** (`timeout=7200`).

   ```python
   log_file = debug_dir / "debug.log"
   with log_file.open("w") as fh:
       result = subprocess.run(
           full_cmd,
           shell=True,
           stdout=fh,
           stderr=subprocess.STDOUT,
           timeout=7200,
       )
   ```

4. Record the outcome for each failure using a `DebugOutcome` dataclass:

   ```python
   @dataclass
   class DebugOutcome:
       result: TestResult
       debug_dir: Path
       log_file: Path
       exit_code: int | None      # None = timed out
       timed_out: bool
       error_note: str            # "" on success, message on failure/timeout
   ```

5. **On timeout** (`subprocess.TimeoutExpired`) → set `timed_out=True`,
   `exit_code=None`, and `error_note = "Timed out after 2h"`. **Do not abort**;
   continue with the next failure.

6. **On any other exception** → catch, set `error_note` to the exception
   message, and continue.

7. Print a status line after each run:

   ```
     ✓  [1/N] apcit_cpl_out_order  seed=1234567890  exit=0
     ✗  [2/N] apcit_cpl_out_order  seed=5678  TIMEOUT
     ✗  [3/N] pcie_bar_test        seed=9999  exit=1
   ```

### Step 7 — Generate the Markdown report

1. Determine the output path:
   - Use `--output` if supplied.
   - Otherwise generate: `qa_report_<YYYYMMDD_HHMMSS>.md` in CWD.
2. Write the report file (see **Report Format** below).
3. Print a confirmation line:

   ```
   ✓  Report written to: <absolute-path-to-report>
   ```

---

## Input File Format

Each line follows one of two patterns:

```
{test} for {sys_ele}_{gen}_lane{num_lane}_{flit_mode}_{typ}_iter{iteration} passed for {seed}
{test} for {sys_ele}_{gen}_lane{num_lane}_{flit_mode}_{typ}_iter{iteration} FAILED for {seed}
```

### Parsed Fields

| Field | Example |
|-------|---------|
| `test` | `pcie_tlp_test` |
| `sys_ele` | `ep1` |
| `gen` | `gen4` |
| `num_lane` | `16` |
| `flit_mode` | `flit` |
| `typ` | `nominal` |
| `iteration` | `3` |
| `seed` | `1234567890` |

---

## Regex

```python
_SHARED = (
    r"^(?P<test>\S+)\s+for\s+"
    r"(?P<sys_ele>[^_]+)_(?P<gen>[^_]+)_lane(?P<num_lane>\d+)_"
    r"(?P<flit_mode>.+?)_(?P<typ>[^_]+)_iter(?P<iteration>\d+)"
    r"\s+{verb}\s+(?P<seed>\d+)"
)
PASS_RE = re.compile(_SHARED.format(verb="passed for"), re.IGNORECASE)
FAIL_RE = re.compile(_SHARED.format(verb="failed for"), re.IGNORECASE)
```

> **Note**: `flit_mode` uses `.+?` (non-greedy) to correctly capture values that contain
> underscores (e.g. `NON_FLIT`). `typ` is anchored by `[^_]+` before `_iter`.

---

## Mode Detection

| Mode | When active |
|------|-------------|
| `basic` | Filename is `results.doc` |
| `slurm` | Filename is `results_new.doc` |

`--mode` overrides automatic detection. Mode is recorded in the report header
for traceability but does not affect parsing logic.

---

## Config Flag Builder

`_build_config_flags(sys_ele, gen, num_lane, flit_mode, typ)` in `analyse.py`
maps parsed fields to the `-R` simulator flag string required by the debug
script. EP and RC modes produce different flag sets.

### EP Mapping rules

| Parsed field | Value example | Emitted flags |
|---|---|---|
| `num_lane` | `4` | `+define+APCI_NUM_LANES=4` |
| `gen` | `GEN5` | `+apci_gen5  +define+SIPC_GEN5` |
| `flit_mode` | `NON_FLIT` | `+define+SIPC_USE_NON_FLIT_MODE` |
| `flit_mode` | `FLIT` | *(no extra define)* |
| *(always)* | — | `+define+SIPC_FASTER_MS_TICK` |
| `num_lane` | `4` | `+define+GEN3_MAX_WIDTH_4` `+define+GEN4_MAX_WIDTH_4` `+define+GEN5_MAX_WIDTH_4` |
| *(always)* | — | `+define+GEN6_MAX_WIDTH_8` |
| `typ` | `4B` → bus_bytes=4 | `+define+PIPE_BYTEWIDTH_16` `+define+APCI_MAX_DATA_WIDTH=16` |
| `typ` | `8B` → bus_bytes=8 | `+define+PIPE_BYTEWIDTH_32` `+define+APCI_MAX_DATA_WIDTH=32` |
| `num_lane` | `4` | `+define+GEN1_2_MAX_WIDTH_4` |
| *(always)* | — | `+licq` |

### RC Mapping rules

| Parsed field | Value example | Emitted flags |
|---|---|---|
| `num_lane` | `4` | `+define+SIPC_NUM_LANES=4` `+define+APCI_NUM_LANES=4` |
| `gen` | `GEN5` | `+apci_gen5  +define+SIPC_GEN5` |
| `flit_mode` | `NON_FLIT` | `+define+SIPC_USE_NON_FLIT_MODE` |
| *(always)* | — | `+define+SIPC_FASTER_MS_TICK` `+define+ROUTINE_RC` |
| `num_lane` | `4` | `+define+GEN1_2_MAX_WIDTH_4` |
| `typ` | `4B` | `+define+PIPE_BYTEWIDTH_16` `+define+APCI_MAX_DATA_WIDTH=16` |
| *(always)* | — | `+licq` `+define+RC_INITIATING_SPEED_CHANGE` |

> `PIPE_BYTEWIDTH` and `APCI_MAX_DATA_WIDTH` = `bus_bytes × 4`  
> e.g. `4B` → `16`, `8B` → `32`, `16B` → `64`

### Debug command format

```
<script> -t <test> -s mti64 -visualizer -debug \
  -T $SIG_PCIE_AVERY_TOP/sipc_top_<sys_ele>.sv \
  -file $SIG_PCIE_HOME/RTL/PCIeCore/sig_pcie_core_16B.f \
  -R " <config_flags>" -n <seed>
```

- **EP**: `-T $SIG_PCIE_AVERY_TOP/sipc_top_ep1.sv`
- **RC**: `-T $SIG_PCIE_AVERY_TOP/sipc_top_rc1.sv`

The script used in the command comes from **Step 4** (user selection or
`--script` flag). If `--script` is passed by the user, it replaces whichever
script would have been shown/selected.

#### Full example (GEN5 / 4-lane / NON_FLIT / 4B / seed 1234 / EP)

```bash
source /path/to/sourcefile_2025_3.csh && \
../../run_apci_2025.pl -t apcit_basic.sv -s mti64 -visualizer -debug \
  -T $SIG_PCIE_AVERY_TOP/sipc_top_ep1.sv \
  -file $SIG_PCIE_HOME/RTL/PCIeCore/sig_pcie_core_16B.f \
  -R " +define+APCI_NUM_LANES=4 +apci_gen5 +define+SIPC_GEN5 +define+SIPC_USE_NON_FLIT_MODE +define+SIPC_FASTER_MS_TICK +define+GEN3_MAX_WIDTH_4 +define+GEN4_MAX_WIDTH_4 +define+GEN5_MAX_WIDTH_4 +define+GEN6_MAX_WIDTH_8 +define+PIPE_BYTEWIDTH_16 +define+APCI_MAX_DATA_WIDTH=16 +define+GEN1_2_MAX_WIDTH_4 +licq" \
  -n 1234
```

---

## Debug Subdirectory Layout

After Step 5 and Step 6, the working directory will contain:

```
<working-dir>/
├── results.doc
├── debug_apcit_cpl_out_order_a3f9c1_1234567890/
│   └── debug.log          ← stdout + stderr from the debug run
├── debug_apcit_cpl_out_order_b7d2e4_5678/
│   └── debug.log
└── debug_pcie_bar_test_c1f3a9_9999/
    └── debug.log
```

---

## Report Format (`qa_report_<timestamp>.md`)

The report uses the new structured format specified below. The "Key Log
Evidence" section is populated from the last 30 lines of `debug.log` (or the
entire file if shorter).

```markdown
# QA Regression Analysis Report

Generated: <timestamp>
Results File: <path>
Mode: Basic | Slurm

## Summary

- Total: N | Passed: N (X%) | Failed: N (X%)
- Unique failing tests: N

---

## [1] apcit_cpl_out_order

| Config | Seed | Exit Code | Error |
|--------|------|-----------|-------|
| GEN5, 4-lane, NON_FLIT, 8B | 1234 | 1 | Timeout at 2000000000 |
| GEN6, 4-lane, NON_FLIT, 8B | 5678 | 0 | — |

**Debug Dir:** `debug_apcit_cpl_out_order_a3f9c1_1234/`
**Log:** `debug_apcit_cpl_out_order_a3f9c1_1234/debug.log`

**Debug Command:**
```bash
<full debug command here>
```

**Key Log Evidence:**
```
<last 30 lines of debug.log, or note if timed out / missing>
```

> ⚠ Rerun timed out after 2h — log may be incomplete.

---

## [2] pcie_bar_test

...

---

## Passed Tests

*N test(s) passed — details omitted.*
```

### Report generation rules

- Group failures **by test name** (`result.test`). Each test gets one numbered
  section (`## [N] <test_name>`).
- Within each section, list every config+seed combination as a table row.
- Populate "Error" column from:
  - `"Timed out after 2h"` if `timed_out=True`
  - `"exit <code>"` if exit code is non-zero
  - `"—"` if the run succeeded cleanly
- Append `**Key Log Evidence**` block with the tail of `debug.log`. If the log
  file is empty or missing, write `*(log not available)*`.
- If the run timed out, add the blockquote warning line.
- Do **not** include a Classification or Pattern field — those are reserved for
  future AI-enhanced analysis.

---

## New / Updated Files

### `qa_agent/analyse.py` — updated

New responsibilities added on top of the existing parser + report writer:

```python
# New imports
import hashlib
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Optional

# ── Interactive selector ──────────────────────────────────────────────────────

def _arrow_select(prompt: str, options: list[tuple[str, str]]) -> int:
    """
    Arrow-key interactive selector (TTY only).
    options: list of (label, tag) tuples — tag shown in brackets.
    Returns the chosen index.
    Falls back to index 0 if not a TTY.
    """
    # Uses ANSI escape sequences + raw terminal mode (tty / termios).
    # On non-TTY, returns 0 immediately.
    ...

# ── Source file discovery ─────────────────────────────────────────────────────

def _find_source_files(working_dir: Path, package_dir: Path) -> list[tuple[Path, str]]:
    """
    Return (path, tag) pairs for all .csh files, package-dir files first.
    tag is one of: 'qa-agent', 'working-dir'.
    """
    ...

def _select_source_file(working_dir: Path, package_dir: Path) -> Optional[Path]:
    """
    Interactive (or auto) source file selection. Returns selected Path or None.
    """
    ...

# ── Script file discovery ─────────────────────────────────────────────────────

def _find_script_files(working_dir: Path, package_dir: Path) -> list[tuple[Path, str]]:
    """
    Return (path, tag) pairs for all .pl files.
    """
    ...

def _select_script(
    script_flag: str, working_dir: Path, package_dir: Path
) -> str:
    """
    If --script was passed, use it. Otherwise run interactive selection.
    Returns the chosen script path as string, or '' if none found.
    """
    ...

# ── Debug subdirectory helpers ────────────────────────────────────────────────

def _debug_dir_name(result: TestResult) -> str:
    config_hash = hashlib.md5(result.configuration.encode()).hexdigest()[:6]
    return f"debug_{result.test}_{config_hash}_{result.seed}"

def _create_debug_dirs(
    failed: list[TestResult], working_dir: Path
) -> dict[TestResult, Path]:
    """Create debug_<test>_<hash>_<seed>/ for each failure. Return mapping."""
    ...

# ── Debug runner ──────────────────────────────────────────────────────────────

@dataclass
class DebugOutcome:
    result: TestResult
    debug_dir: Path
    log_file: Path
    exit_code: Optional[int]      # None = timed out
    timed_out: bool
    error_note: str               # "" on success

def _run_debug(
    result: TestResult,
    debug_dir: Path,
    script: str,
    source_file: Optional[Path],
    index: int,
    total: int,
) -> DebugOutcome:
    """
    Build and execute the full debug command for one failure.
    Captures stdout+stderr to debug_dir/debug.log.
    Returns DebugOutcome regardless of success/failure/timeout.
    """
    ...

# ── Report writer — updated ───────────────────────────────────────────────────

def _write_report(
    *,
    path: Path,
    results_path: Path,
    mode: str,
    working_dir: Path,
    passed: list[TestResult],
    outcomes: list[DebugOutcome],
    script: str,
    now: datetime,
) -> None:
    """
    Write the new grouped-by-test report format.
    outcomes replaces the old 'failed' list — it carries the debug dir + log.
    """
    ...

# ── Public entry-point — updated ─────────────────────────────────────────────

def run(
    mode: str | None = None,
    working_dir: str = ".",
    output: str | None = None,
    script: str = "",
    verbose: bool = False,
) -> None:
    wd = Path(working_dir).resolve()
    package_dir = Path(__file__).parent  # qa_agent/

    # Step 1: find results file
    results_path = _find_results(wd)

    # Step 2: parse
    passed, failed = _parse(results_path)

    # Step 3: source file selection
    source_file = _select_source_file(wd, package_dir)

    # Step 4: script selection
    effective_script = _select_script(script, wd, package_dir)

    # Step 5: create debug dirs
    debug_dirs = _create_debug_dirs(failed, wd)

    # Step 6: run debug commands + capture logs
    outcomes: list[DebugOutcome] = []
    for i, result in enumerate(failed, 1):
        outcome = _run_debug(
            result, debug_dirs[result], effective_script, source_file, i, len(failed)
        )
        outcomes.append(outcome)

    # Step 7: write report
    now = datetime.now()
    report_path = (
        Path(output) if output
        else Path.cwd() / f"qa_report_{now.strftime('%Y%m%d_%H%M%S')}.md"
    )
    _write_report(
        path=report_path,
        results_path=results_path,
        mode=effective_mode,
        working_dir=wd,
        passed=passed,
        outcomes=outcomes,
        script=effective_script,
        now=now,
    )
    print(f"\n  {green('✓')}  Report written to: {report_path.resolve()}\n")
```

---

## CLI Changes

### `qa_agent/cli.py`

The `analyse` sub-parser is unchanged. No new flags are needed — script and
source file selection happen interactively inside `analyse.py`.

> The existing dispatch block calls `analyse_run(mode, working_dir, output, script, verbose)`
> and that signature stays the same.

---

## Documentation Changes

### `CLAUDE.md`

- Update `analyse` row in the **CLI Commands** table to mention the new
  post-regression debug execution step.
- Update **Useful Commands** with:

  ```bash
  qa-agent analyse                              # Auto-detect file, interactive script/source selection, run debug
  qa-agent analyse --working-dir /path/to/run   # Specify regression dir
  qa-agent analyse --mode slurm                 # Force slurm mode
  qa-agent analyse --output report.md           # Custom report path
  qa-agent analyse -s /tools/run_debug.pl       # Skip script selection prompt
  ```

---

## Verification

Create `results.doc` in a test directory with at least one FAILED line.

```
pcie_tlp_test for ep1_gen4_lane16_flit_nominal_iter3 passed for 1234567890
apcit_cpl_out_order for ep1_gen5_lane4_NON_FLIT_8B_iter1 FAILED for 1234
apcit_cpl_out_order for ep1_gen6_lane4_NON_FLIT_8B_iter2 FAILED for 5678
pcie_bar_test for ep1_gen4_lane16_flit_nominal_iter2 FAILED for 9999
```

Run:

```bash
pip install -e .
qa-agent analyse                                    # interactive prompts appear
qa-agent analyse -s ../../run_apci_2025.pl          # skip script prompt
qa-agent analyse --output /tmp/test_report.md       # custom output path
qa-agent analyse --working-dir /nonexistent         # expect PathError
```

Expected:

- Arrow-key source-file prompt appears (if multiple `.csh` files present).
- Arrow-key script-selection prompt appears (unless `-s` passed).
- `debug_<test>_<hash>_<seed>/` directories created under working dir.
- `debug.log` written in each subdir.
- Timed-out or errored runs noted in the report without aborting.
- `qa_report_<timestamp>.md` written with new grouped-by-test format.
- Missing results dir → `PathError` with clear message + stop.
- Zero-match file → `QAAgentError` with format hint.
