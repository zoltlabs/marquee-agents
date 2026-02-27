# CLI Consistency — Feature Plan

> **Status:** In Progress  
> **Branch:** `feat/cli-consistency`  
> **Owner:** AI Agent / Engineer  
> **Scope:** CLI flag naming, command behaviour, output format, and UX conventions across all `qa-agent` sub-commands

---

## Objective

Ensure that every `qa-agent` sub-command follows identical conventions for flags, output structure, interactive selectors, and error handling — so the CLI feels like a single coherent product rather than a collection of independent scripts.

---

## Design Principles

| Principle | Rule |
|-----------|------|
| **Consistent flags** | Same flag name, same short alias, same behaviour on every command that exposes the concept |
| **Consistent headers** | Every command starts with a branded `print_header()` panel — same look, same version line |
| **Consistent footers** | Success → `print_footer("message")`. Error → rich red panel via `print_rich_error()` |
| **Consistent selectors** | All interactive arrow-key pickers go through the single `arrow_select()` in `output.py` |
| **Progressive detail** | Default is clean. `--verbose` adds raw paths/commands. `--debug` adds step gates + logs |
| **Non-TTY safe** | Every interactive element degrades gracefully when stdout is not a TTY |

---

## Current State Assessment

### ✅ Already consistent (as of current implementation)

| Feature | Status |
|---------|--------|
| Branded `print_header()` on all commands | ✅ implemented |
| Shared `arrow_select()` in `output.py` | ✅ implemented (was duplicated in analyse + regression) |
| `print_footer()` for success/failure | ✅ implemented |
| Rich panels for errors (`print_rich_error`) | ✅ implemented |
| `--verbose / -v` on all applicable commands | ✅ consistent |
| `--debug` global flag | ✅ consistent |
| `--version / -V` global flag | ✅ consistent |

### ⚠️ Inconsistencies to fix

| Area | Issue | Priority |
|------|-------|----------|
| **`--verbose` scope** | `doctor` and `analyse` each define their own local `--verbose`; it shadows the global flag | High |
| **`--test` short alias** | `analyse --test` uses `-t`; should audit all flags for alias collisions | Medium |
| **Output line format** | Some commands use `print()` directly for status lines; others use `console.print()` | Medium |
| **Banner after filter** | `analyse` re-prints a second banner after the `--test` filter step; should be single header | Medium |
| **Summary tables** | `regression._print_summary()` still uses raw `print()` calls, not `print_summary_table()` | High |
| **`confirm()` helper** | `regression` and `analyse` both have inline `input()` prompts; should use `confirm()` | Medium |
| **Exit codes** | `doctor` calls `sys.exit(1)` internally; should raise `QAAgentError` and let cli.py handle | Low |

---

## Flag Conventions (canonical reference)

All flags below are **the standard**. Any deviation in a command module is a bug.

### Global flags (registered on the root parser in `cli.py`)

| Flag | Short | Type | Description |
|------|-------|------|-------------|
| `--verbose` | `-v` | `store_true` | Detailed progress, raw paths, full tracebacks |
| `--debug` | — | `store_true` | `--verbose` + session log + step gates on `regression`/`analyse` |
| `--version` | `-V` | `version` | Print `qa-agent <version>` and exit |

> **Rule:** Sub-command parsers MUST NOT re-define `--verbose` or `--debug`. They receive it from `args.verbose` / `args.debug` passed down from `cli.py`.

### Per-command flags

#### `analyse`

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--mode basic\|slurm` | — | auto | Override mode detection |
| `--working-dir PATH` | — | CWD | Directory with results file |
| `--output PATH` | — | `qa_report_<ts>.md` | Report output path |
| `--script PATH` | `-s` | *(interactive)* | Debug script; skips picker |
| `--test NAME` | `-t` | *(all)* | Filter to a single test case |

#### `regression`

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--slurm` | — | off | Run in Slurm mode |

#### `summarise`

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--provider {claude,openai,gemini}` | `-p` | `claude` | AI provider |

#### `doctor`

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| *(none beyond globals)* | — | — | — |

---

## Output Conventions (canonical reference)

### Header
Every command calls `print_header(command_name, subtitle)` **once**, at the very start of `run()`.

```python
# ✅ Correct
print_header("analyse", f"Mode: {mode or 'auto-detect'}")

# ❌ Wrong — multiple headers, or banner printed after input steps
```

### Status lines (body)
Use the legacy ANSI helpers for inline status lines:

```python
print(f"  {green('✓')}  Source: {bold(path.name)}  {dim('[qa-agent]')}")
print(f"  {yellow('⚠')}  No .csh files found — skipping source step")
print(f"  {red('✗')}  [{i}/{total}] {bold(test)}  seed={seed}  TIMEOUT")
```

### Footer
```python
print_footer("Report written.")          # green ✓
print_footer("Debug run failed.", success=False)  # red ✗
```

### Error display
Never call `sys.exit()` from inside a module. Always raise:

```python
raise QAAgentError("No results file found.")
# cli.py catches it → print_rich_error() → sys.exit(1)
```

### Interactive selector
```python
from qa_agent.output import arrow_select

idx = arrow_select("🔧 Select source file:", options)  # options = [(label, tag), ...]
```

### Y/n confirmation
```python
from qa_agent.output import confirm

if confirm("Use bundled filelist.txt?", default=True):
    ...
```

---

## Implementation Tasks

### Task 1 — Remove sub-command `--verbose` re-definitions

**Files:** `qa_agent/cli.py`, `qa_agent/analyse.py`  
**Problem:** `analyse` sub-parser re-defines `--verbose / -v`, which shadows the global flag and creates confusion.  
**Fix:**
1. Remove `--verbose` from the `analyse` sub-parser in `cli.py`.
2. `verbose` is already passed down from `args.verbose` in the dispatch block — no change needed in `analyse.run()`.
3. Apply same check to `doctor` sub-parser (`--verbose` there is intentional for showing raw values — keep but document clearly).

```python
# cli.py — BEFORE (analyse sub-parser):
analyse_parser.add_argument("--verbose", "-v", ...)  # ← remove this

# cli.py — AFTER:
# Nothing. args.verbose comes from the global flag.
```

**Acceptance:** `qa-agent --verbose analyse` and `qa-agent analyse --verbose` both work identically.

---

### Task 2 — Migrate `regression._print_summary()` to `print_summary_table()`

**File:** `qa_agent/regression.py`  
**Problem:** `_print_summary()` still uses raw `print()` with f-strings and manual padding.  
**Fix:** Replace with `print_summary_table(rows)`.

```python
# Before:
def _print_summary(...):
    print()
    print(rule())
    print(f"  {'Mode':<12}{bold('slurm' if slurm else 'basic')}")
    ...

# After:
from qa_agent.output import print_summary_table

def _print_summary(...):
    rows = [
        ("Mode",     "slurm" if slurm else "basic"),
        ("Script",   regression_script.name),
        ("Filelist", filelist.name),
        ("Source",   source_file.name if source_file else "(none)"),
        ("Log",      log_path.name),
        ("Result",   result_status),
    ]
    if slurm and config:
        rows.insert(2, ("Config", config.name))
    if slurm and run_questa:
        rows.insert(3, ("Launcher", run_questa.name))
    print_summary_table(rows)
```

---

### Task 3 — Migrate inline `input()` prompts to `confirm()`

**Files:** `qa_agent/regression.py`, `qa_agent/analyse.py`  
**Problem:** Several places call `input()` directly (e.g. filelist prompt, config prompt).  
**Fix:** Replace all `input()` Y/n prompts with `confirm()` from `output.py`.

```python
# Before:
answer = input("Use bundled filelist? [Y/n] ").strip().lower()
if answer in ("", "y", "yes"):
    ...

# After:
from qa_agent.output import confirm
if confirm("Use bundled filelist?", default=True):
    ...
```

---

### Task 4 — Remove duplicate banner in `analyse.run()`

**File:** `qa_agent/analyse.py`  
**Problem:** After the `--test` filter step, `analyse.run()` prints a second rule + banner block (lines ~635–645 in original). Now that `print_header()` is called at the top, this is redundant.  
**Fix:** Remove the manual rule + banner block that appears after parsing; keep only the top-level `print_header()` call.

---

### Task 5 — Standardise `exit()` calls

**File:** `qa_agent/doctor.py`  
**Problem:** `doctor.run()` calls `sys.exit(1)` directly instead of raising `QAAgentError`.  
**Fix:** Raise `QAAgentError` and let `cli.py` handle it.

```python
# Before:
if total_errors:
    sys.exit(1)

# After:
if total_errors:
    raise QAAgentError(f"doctor: {total_errors} check(s) failed.")
```

---

## Testing Checklist

After each task is complete, verify:

- [ ] `qa-agent hello` — full ASCII logo renders without clipping; correct tagline
- [ ] `qa-agent doctor` — two sections (Runtime + Providers); no Log System section
- [ ] `qa-agent guide` — overview shows correct feature list
- [ ] `qa-agent guide regression` — correct guide panel header
- [ ] `qa-agent regression` — branded header; summary table rendered with `print_summary_table()`
- [ ] `qa-agent analyse` — single header at top; no duplicate banner mid-run
- [ ] `qa-agent summarise` — branded header; spinner; AI output; footer
- [ ] `qa-agent --verbose analyse` — verbose works from global flag
- [ ] `qa-agent analyse --verbose` — same behaviour (if sub-parser flag is kept)
- [ ] Non-TTY piped output — no ANSI codes, no box-drawing glitches
- [ ] Error path — exception renders in red rich panel, exits with code 1

---

## File Change Summary

| File | Tasks |
|------|-------|
| `qa_agent/cli.py` | Task 1 — remove `--verbose` re-def from analyse sub-parser |
| `qa_agent/regression.py` | Task 2 — `print_summary_table()`; Task 3 — `confirm()` |
| `qa_agent/analyse.py` | Task 3 — `confirm()`; Task 4 — remove duplicate banner |
| `qa_agent/doctor.py` | Task 5 — raise `QAAgentError` instead of `sys.exit()` |
| `qa_agent/output.py` | Any new shared helpers needed |
