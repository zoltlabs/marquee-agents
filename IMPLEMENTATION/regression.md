# `qa-agent regression` — Implementation Plan

> **Status:** Planned
> **Module:** `qa_agent/regression.py`
> **CLI sub-command:** `qa-agent regression`
> **Branch:** `feat/regression`

---

## Overview

Automate the full regression run lifecycle: source the environment, locate
required input files (filelist, config, scripts), execute the regression in
either **basic** or **slurm** mode, stream stdout to the terminal while
capturing it to a log file, and verify the expected results artefact was
produced.

---

## CLI Interface

```
qa-agent regression [--slurm] [--verbose/-v]
```

| Flag | Short | Default | Effect |
|------|-------|---------|--------|
| `--slurm` | — | off | Run in Slurm mode instead of basic regression |
| `--verbose` | `-v` | off | Print detailed progress (resolved paths, full commands) |

*(Global `--debug` flag also applies — enables session logging.)*

---

## Execution Pipeline

### Step 1 — Source the Environment (`.csh` file)

| # | Condition | Action |
|---|-----------|--------|
| 1a | No `.csh` files in **cwd** | Auto-select `sourcefile_2025_3.csh` bundled in the qa-agent package dir. Print: `ℹ  No .csh files found in cwd — using qa-agent default: sourcefile_2025_3.csh` |
| 1b | One or more `.csh` files in **cwd** | Present an interactive arrow-key selector listing **all** options: the qa-agent bundled `sourcefile_2025_3.csh` **plus** every `.csh` file found in cwd. The qa-agent default appears first, labelled `[qa-agent]`; cwd files are labelled `[cwd]`. |

**Selector appearance:**

```
🔧 Select source file to use:

  ❯  sourcefile_2025_3.csh                       [qa-agent]
     my_custom_source.csh                         [cwd]
     sourcefile_2025_4.csh                        [cwd]
```

**Implementation notes:**
- Reuse `_arrow_select()` pattern from `analyse.py`.
- "Source" the `.csh` file by converting it to env vars (parse `setenv` lines)
  or by wrapping the regression command inside `csh -c "source <file> && ..."`.
- The sourced environment must be available to the subprocess that runs the
  regression script.

---

### Step 2 — Locate `filelist.txt`

| # | Condition | Action |
|---|-----------|--------|
| 2a | `filelist.txt` exists in **cwd** | Use it. Print: `✔  Found filelist.txt in cwd` |
| 2b | `filelist.txt` **not** in cwd | Prompt the user: `⚠  No filelist.txt found in current directory. Use the one bundled with qa-agent? [Y/n]` |
| 2b-yes | User confirms | Use the qa-agent bundled `filelist.txt`. Print: `✔  Using qa-agent default filelist.txt` |
| 2b-no | User declines | Print: `ℹ  Please add a filelist.txt to the current directory and re-run.` then exit cleanly (exit code 0). |

---

### Step 3 — Mode Gate: Basic vs Slurm

If `--slurm` is **not** passed → continue to **Step 4 (Basic)**.
If `--slurm` is passed → continue to **Step 5 (Slurm)**.

---

### Step 4 — Basic Regression

#### 4a — Locate the regression Python script

| # | Condition | Action |
|---|-----------|--------|
| 4a-i | No regression `.py` files in **cwd** (excluding `__pycache__`, hidden dirs) | Auto-select the qa-agent bundled script (e.g. `regression_8B_16B_questa.py`). Print: `ℹ  No regression scripts found in cwd — using qa-agent default` |
| 4a-ii | One or more `.py` regression scripts in **cwd** | Arrow-key selector with qa-agent default(s) + cwd scripts, labelled `[qa-agent]` / `[cwd]`. |

**Heuristic for identifying regression scripts:** filename contains `regression`
and ends with `.py`, or user can select from all non-hidden `.py` files in cwd.

**Selector appearance:**

```
🐍 Select regression script:

  ❯  regression_8B_16B_questa.py                 [qa-agent]
     regression_custom.py                         [cwd]
```

#### 4b — Run the regression

```bash
python3 <selected_script.py> <selected_filelist.txt>
```

- Execute via `subprocess.Popen` (not `run`) to stream stdout **live** to the
  terminal while simultaneously writing to `regression_basic_<timestamp>.log`.
- Use a `Spinner` or live prefix while the process runs.
- Print the full command in `--verbose` mode.

#### 4c — Verify results

After the process exits:

| Exit code | `results.doc` exists? | Action |
|-----------|-----------------------|--------|
| 0 | Yes | `✔  Regression complete — results.doc created` |
| 0 | No | `⚠  Regression finished but results.doc was not generated. Check the log: <log_path>` |
| non-zero | — | `✖  Regression failed (exit code <N>). Log: <log_path>` |

---

### Step 5 — Slurm Regression

#### 5a — Locate `config.txt`

| # | Condition | Action |
|---|-----------|--------|
| 5a-i | `config.txt` exists in **cwd** | Use it. Print: `✔  Found config.txt in cwd` |
| 5a-ii | `config.txt` **not** in cwd | Prompt: `⚠  No config.txt found in current directory. Use the one bundled with qa-agent? [Y/n]` |
| 5a-yes | User confirms | Use qa-agent bundled `config.txt` |
| 5a-no | User declines | Print: `ℹ  Please add a config.txt to the current directory and re-run.` then exit cleanly. |

#### 5b — Locate `run_questa.sh`

| # | Condition | Action |
|---|-----------|--------|
| 5b-i | No `run_questa.sh` in **cwd** | Auto-select the qa-agent bundled `run_questa.sh`. Print: `ℹ  No run_questa.sh found in cwd — using qa-agent default` |
| 5b-ii | `run_questa.sh` exists in **cwd** | Arrow-key selector: qa-agent bundled `[qa-agent]` vs cwd copy `[cwd]`. |

#### 5c — Locate the Slurm regression Python script

Same pattern as Step 4a but looking for slurm-related scripts
(e.g. `regression_slurm_questa_2025.py`).

**Heuristic:** filename contains `regression` **and** `slurm` and ends `.py`.

| # | Condition | Action |
|---|-----------|--------|
| 5c-i | No matching `.py` in cwd | Auto-select qa-agent bundled script |
| 5c-ii | One or more in cwd | Arrow-key selector with `[qa-agent]` / `[cwd]` labels |

#### 5d — Run the Slurm regression

```bash
./run_questa.sh <filelist.txt> <config.txt> <slurm_script.py>
```

- Same live-streaming + log capture as Step 4b.
- Log file: `regression_slurm_<timestamp>.log`.
- Ensure `run_questa.sh` has execute permission (`chmod +x` if needed).

#### 5e — Verify results

| Exit code | `results_new.doc` exists? | Action |
|-----------|---------------------------|--------|
| 0 | Yes | `✔  Slurm regression complete — results_new.doc created` |
| 0 | No | `⚠  Slurm regression finished but results_new.doc was not generated. Check the log: <log_path>` |
| non-zero | — | `✖  Slurm regression failed (exit code <N>). Log: <log_path>` |

---

## UX Design

### Banner

```
╭──────────────────────────────────────────────────────╮
│  qa-agent regression                                 │
│  Mode: basic | slurm                                 │
╰──────────────────────────────────────────────────────╯
```

### Progress Indicators

| Phase | Indicator |
|-------|-----------|
| Sourcing environment | `⠋ Sourcing environment from <file>…` (Spinner) |
| File discovery | Instant — print status lines |
| Interactive selection | Arrow-key selector (no spinner) |
| Regression execution | Live stdout streaming with elapsed time |
| Results verification | Instant — print status line |

### Colour Scheme (from `output.py`)

| Element | Colour |
|---------|--------|
| Success messages | `green` (`✔`) |
| Warnings / prompts | `yellow` (`⚠`) |
| Errors | `red` (`✖`) |
| Info messages | `cyan` (`ℹ`) |
| File paths | `dim` |
| Selected option | `bold` + `cyan` with `❯` prefix |
| Tags `[qa-agent]` / `[cwd]` | `dim` |

### Summary Block (printed at end)

```
───────────────────────────────────────────────────────
  Mode        basic
  Script      regression_8B_16B_questa.py
  Filelist    filelist.txt
  Source      sourcefile_2025_3.csh
  Log         regression_basic_20260227_143022.log
  Result      ✔  results.doc created
───────────────────────────────────────────────────────
```

---

## File Discovery Logic

### Package Directory Resolution

The qa-agent bundled files live alongside the installed package. Resolve using:

```python
PACKAGE_DIR = Path(__file__).resolve().parent.parent  # repo root
```

Or use `importlib.resources` / `pkg_resources` for installed packages. For
editable installs (`pip install -e .`), the repo root approach is fine.

### `.csh` Discovery in cwd

```python
csh_files = sorted(Path.cwd().glob("*.csh"))
```

### Regression Script Discovery

```python
# Basic mode
py_files = sorted(
    p for p in Path.cwd().glob("*.py")
    if "regression" in p.name.lower()
    and not p.name.startswith(".")
)

# Slurm mode — narrower filter
slurm_py = sorted(
    p for p in Path.cwd().glob("*.py")
    if "regression" in p.name.lower()
    and "slurm" in p.name.lower()
)
```

---

## Log Capture

### Strategy

Use `subprocess.Popen` with `stdout=PIPE, stderr=STDOUT` and read line-by-line
in a loop:

```python
log_path = Path.cwd() / f"regression_{'slurm' if slurm else 'basic'}_{timestamp}.log"

with open(log_path, "w") as log_file:
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=str(Path.cwd()),
    )
    for line in proc.stdout:
        sys.stdout.write(line)      # live terminal output
        log_file.write(line)        # capture to file
    proc.wait()
```

### Log Filename Convention

| Mode | Pattern | Example |
|------|---------|---------|
| Basic | `regression_basic_<YYYYMMDD_HHMMSS>.log` | `regression_basic_20260227_143022.log` |
| Slurm | `regression_slurm_<YYYYMMDD_HHMMSS>.log` | `regression_slurm_20260227_143022.log` |

---

## Error Handling

| Scenario | Error class | Message |
|----------|-------------|---------|
| User declines filelist/config | Clean exit (code 0) | Info message + instruction |
| Regression script not found | `ConfigError` | `No regression script available` |
| `run_questa.sh` not executable | Auto-fix (`chmod +x`) | `ℹ  Made run_questa.sh executable` |
| Subprocess crash | `QAAgentError` | `Regression failed (exit code N)` |
| Results file missing | Warning (not error) | Yellow warning + log path |
| `.csh` source fails | `ConfigError` | `Failed to source <file>: <reason>` |

---

## Module Layout

### New file: `qa_agent/regression.py`

```
regression.py
├── PACKAGE_DIR               # constant — path to bundled files
├── _discover_csh_files()     # find .csh in cwd
├── _select_source_file()     # interactive or auto-select
├── _locate_filelist()        # cwd check + fallback prompt
├── _locate_config()          # cwd check + fallback prompt (slurm only)
├── _locate_run_questa()      # cwd check + selector (slurm only)
├── _discover_regression_py() # find regression .py scripts
├── _select_regression_py()   # interactive or auto-select
├── _build_command()          # assemble the final command list
├── _run_regression()         # Popen + live stream + log capture
├── _verify_results()         # check results.doc / results_new.doc
├── _print_summary()          # end-of-run summary block
└── run()                     # public entry-point (called from cli.py)
```

### Changes to `qa_agent/cli.py`

```python
# Add sub-parser
sp_regression = subparsers.add_parser(
    "regression",
    help="Run a regression (basic or slurm mode)",
    description="Source environment, locate inputs, execute regression, "
                "capture logs, and verify results.",
)
sp_regression.add_argument(
    "--slurm", action="store_true",
    help="Run in Slurm mode (requires config.txt + run_questa.sh)",
)

# Dispatch
if args.command == "regression":
    from qa_agent.regression import run
    run(
        slurm=args.slurm,
        verbose=args.verbose,
        log=log,
    )
```

### Changes to `qa_agent/output.py`

Add a new banner helper:

```python
def print_regression_banner(mode: str) -> None:
    """Print the regression command banner."""
    ...
```

---

## Bundled Files (qa-agent package)

These files ship with the package and act as defaults when the cwd has no
equivalent:

| File | Purpose |
|------|---------|
| `sourcefile_2025_3.csh` | Environment setup script |
| `filelist.txt` | Default test list |
| `config.txt` | Slurm configuration |
| `run_questa.sh` | Slurm launcher shell script |
| `regression_8B_16B_questa.py` | Basic regression runner |
| `regression_slurm_questa_2025.py` | Slurm regression runner |

---

## Full Flowchart

```
START
  │
  ▼
┌─────────────────────────┐
│ Print banner             │
└────────────┬────────────┘
             ▼
┌─────────────────────────┐     ┌──────────────────────────────┐
│ .csh files in cwd?      │─No─▶│ Auto-select qa-agent default │
└────────────┬────────────┘     └──────────────┬───────────────┘
           Yes                                  │
             ▼                                  │
┌─────────────────────────┐                     │
│ Arrow-key selector:     │                     │
│ qa-agent + cwd files    │                     │
└────────────┬────────────┘                     │
             ▼◀────────────────────────────────-┘
┌─────────────────────────┐
│ Source the .csh file     │
└────────────┬────────────┘
             ▼
┌─────────────────────────┐     ┌──────────────────────────────┐
│ filelist.txt in cwd?    │─No─▶│ Use qa-agent's? [Y/n]        │
└────────────┬────────────┘     └──────────┬───────┬───────────┘
           Yes                           Yes     No
             │                            │       ▼
             │                            │   EXIT with message
             ▼◀───────────────────────────┘
┌─────────────────────────┐
│ --slurm flag set?       │
└─────┬───────────┬───────┘
    No           Yes
     ▼             ▼
  BASIC          SLURM
  (Step 4)       (Step 5)
     │             │
     ▼             ▼
  Select .py     Locate config.txt
     │           Locate run_questa.sh
     │           Select slurm .py
     │             │
     ▼             ▼
  Run command    Run command
     │             │
     ▼             ▼
  Verify         Verify
  results.doc    results_new.doc
     │             │
     ▼◀────────────┘
┌─────────────────────────┐
│ Print summary block      │
└─────────────────────────┘
  END
```

---

## Testing Checklist

- [ ] No `.csh` in cwd → auto-selects qa-agent default
- [ ] `.csh` in cwd → selector shows both qa-agent + cwd options
- [ ] `filelist.txt` in cwd → used directly
- [ ] `filelist.txt` missing → prompt works (Y and N paths)
- [ ] Basic mode → correct command assembled and executed
- [ ] Basic mode → `results.doc` check passes/warns
- [ ] Slurm mode → `config.txt` discovery + prompt
- [ ] Slurm mode → `run_questa.sh` discovery + selector
- [ ] Slurm mode → correct command assembled and executed
- [ ] Slurm mode → `results_new.doc` check passes/warns
- [ ] Log file created with correct naming convention
- [ ] Stdout streams live to terminal
- [ ] Non-TTY fallback (no interactive selectors)
- [ ] `--verbose` prints full resolved paths and commands
- [ ] Session logging captures all steps when `--debug` is active
- [ ] Non-zero exit code handled gracefully
