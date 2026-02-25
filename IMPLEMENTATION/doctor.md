# `qa-agent doctor` — Implementation Plan

Environment health checker for DV engineers. Validates that every dependency
and auth credential needed by `qa-agent` is correctly set up before a real
command is attempted.

---

## Purpose

Engineers hitting `qa-agent summarise` with a missing `ANTHROPIC_API_KEY` see
a cryptic traceback. `doctor` surfaces every problem at once, in plain English,
with actionable fix instructions.

```
$ qa-agent doctor

  ──────────────────────────────────────────────────
   qa-agent doctor  ·  environment health check
  ──────────────────────────────────────────────────

  Runtime
    ✓  Python 3.12.2  (≥ 3.10 required)

  Providers
    ✓  Claude    SDK installed (claude-agent-sdk 0.3.1)
                ANTHROPIC_API_KEY  ✓ set
    ✗  OpenAI   SDK installed (openai 1.14.0)
                OPENAI_API_KEY     ✗ not set
                  → export OPENAI_API_KEY=sk-...
    ⚠  Gemini   SDK installed (google-generativeai 0.5.0)
                GEMINI_API_KEY     ✗ not set
                GOOGLE_CLOUD_PROJECT  ✗ not set
                  → export GEMINI_API_KEY=AIza...
                  → OR: gcloud auth application-default login

  Log system
    ✓  Log directory ~/.local/share/qa-agent/logs/  (12 KB used)

  ──────────────────────────────────────────────────
    1 error · 1 warning
  ──────────────────────────────────────────────────
```

Exit codes
- `0` — all checks passed (or only warnings)
- `1` — one or more errors found

---

## File Layout

```
qa_agent/
└── doctor.py          # New module  — all check logic + rendering
IMPLEMENTATION/
└── doctor.md          # This file
```

`cli.py` receives one new sub-command registration (see §CLI Registration).

---

## Module: `qa_agent/doctor.py`

### Public API

```python
def run(verbose: bool = False) -> None:
    """Entry point called from cli.py."""
```

`verbose=True` prints raw detail (e.g. full SDK path, env var prefix) instead
of summarised one-liners.

---

### Check Architecture

Each check is a plain function that returns a `CheckResult`:

```python
from dataclasses import dataclass
from enum import Enum

class Status(Enum):
    OK      = "ok"
    WARN    = "warn"
    ERROR   = "error"

@dataclass
class CheckResult:
    label:  str          # Short display label, e.g. "ANTHROPIC_API_KEY"
    status: Status
    detail: str          # One-line human message, e.g. "set"  /  "not set"
    fix:    str = ""     # Optional fix instruction printed indented below detail
```

All checks are collected into sections:

```python
SECTIONS: list[tuple[str, list[Callable[[], CheckResult]]]] = [
    ("Runtime",   [check_python_version]),
    ("Providers", [check_claude, check_openai, check_gemini]),
    ("Log system",[check_log_dir]),
]
```

Adding a new provider later = add one `check_<name>()` function + append to
`SECTIONS`. No other changes needed.

---

### Check Implementations

#### `check_python_version() -> CheckResult`
- `sys.version_info >= (3, 10)` → OK; else ERROR with fix `Upgrade to Python ≥ 3.10`

#### `check_claude() -> list[CheckResult]`
Returns two results: SDK presence + auth.

```
SDK check:
  importlib.metadata.version("claude-agent-sdk")
  → OK with version string   |   ERROR + pip install fix

Auth check (only if SDK OK):
  os.environ.get("ANTHROPIC_API_KEY")  → OK
  subprocess.run(["claude", "--version"], capture_output=True)  → WARN "CLI login detected"
  neither → ERROR
```

#### `check_openai() -> list[CheckResult]`
```
SDK:  importlib.metadata.version("openai")
Auth: OPENAI_API_KEY  or  codex --version reachable  → WARN
```

#### `check_gemini() -> list[CheckResult]`
```
SDK:  importlib.metadata.version("google-generativeai")
Auth: GEMINI_API_KEY  or  (GOOGLE_CLOUD_PROJECT + gcloud reachable)
```

#### `check_log_dir() -> CheckResult`
```
path = platformdirs.user_data_dir("qa-agent", "ZoltLabs")
exists?   → OK + show disk usage (du -sh)
missing?  → WARN (will be created on first run)
```

---

### Renderer

Reuses `qa_agent.output` (see `ux_improvements.md`) for ANSI helpers.

```python
def _print_section(title: str, results: list[CheckResult]) -> None:
    ...

def _print_summary(errors: int, warnings: int) -> None:
    ...
```

Rules:
- OK rows: green `✓`
- WARN rows: yellow `⚠`
- ERROR rows: red `✗`  + indented cyan fix line
- `--verbose` additionally prints the raw value / path for each check

---

## CLI Registration

`cli.py` addition:

```python
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

# In the dispatch section:
elif args.command == "doctor":
    from qa_agent.doctor import run as doctor_run
    doctor_run(verbose=args.verbose)
```

---

## Dependencies

| Package | Usage | Already a dep? |
|---------|-------|----------------|
| `importlib.metadata` | SDK version lookup | stdlib ✓ |
| `platformdirs` | Cross-platform data dir | Add to `pyproject.toml` |
| `subprocess` | CLI reachability probe | stdlib ✓ |

`platformdirs` is the only new runtime dependency. It is small (~20 KB) and
widely used (pip itself uses it).

---

## CLAUDE.md Update Required

Add to the CLI commands table:

```
| `doctor` | `--verbose` | Check SDKs, auth, and log system | `IMPLEMENTATION/doctor.md` |
```

---

## Verification Plan

```bash
# Happy path — all set
ANTHROPIC_API_KEY=sk-ant-... qa-agent doctor   # exit 0

# Missing key
unset ANTHROPIC_API_KEY
qa-agent doctor                                 # exit 1, shows fix

# Verbose
qa-agent doctor --verbose

# Piped (no colour)
qa-agent doctor | cat

# Integration: doctor passes before summarise
qa-agent doctor && qa-agent summarise .
```

All checks must be read-only and complete in < 2 seconds on a normal laptop.
