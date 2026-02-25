# UX Improvements — Implementation Plan

Covers five related changes that must land together to avoid duplication:

1. `output.py` — Shared terminal rendering module
2. `errors.py` — Centralised error taxonomy & handler
3. Better `--help` output (provider flag rename + examples + `--version`)
4. Global `--verbose` / `--debug` flag
5. Live progress spinner

---

## 1. `qa_agent/output.py` — Shared Rendering Layer

### Problem
ANSI helpers, banners, rule lines, and `_render_line` are all defined inside
`summarise.py`. Every new command (triage, doctor, etc.) would duplicate them.

### New Module

```python
"""qa_agent/output.py

Central terminal rendering for all qa-agent commands.

Usage:
    from qa_agent.output import bold, cyan, red, print_banner,
                                print_success, print_error, render_line

Never import ANSI helpers directly from summarise.py.
"""
```

#### Colour helpers (identical to current summarise.py, moved here)

```python
USE_COLOR: bool = sys.stdout.isatty()

def _c(code: str, text: str) -> str: ...
def bold(t)    -> str: ...
def cyan(t)    -> str: ...
def green(t)   -> str: ...
def yellow(t)  -> str: ...
def red(t)     -> str: ...
def dim(t)     -> str: ...
def magenta(t) -> str: ...
def rule(char="─", width=60) -> str: ...
```

#### Banner / footer

```python
def print_banner(target_label: str, provider_name: str) -> None: ...
def print_success(msg: str = "Summary complete.") -> None: ...
def print_error(msg: str) -> None: ...
```

#### Markdown-aware line renderer

```python
def render_line(line: str) -> None:
    """Apply ANSI colour to markdown headings; pass rest through."""
    # ## → cyan bold   ### → bold   #### → yellow   else → plain
```

#### Migration

`summarise.py` replaces all its local colour functions with imports from
`output.py`. It keeps only orchestration logic internally.

---

## 2. `qa_agent/errors.py` — Error Taxonomy

### Problem
`summarise.py:run()` (lines 254–299) handles Claude SDK errors inline. As
more commands and providers are added every command would re-implement this.

### Approach

```python
"""qa_agent/errors.py

qa-agent error hierarchy and centralised handler.

Raise QAAgentError subclasses from anywhere in the codebase.
Call handle_exception(exc, provider) at the top-level dispatch layer.
"""

class QAAgentError(Exception):
    """Base for all qa-agent errors. Always has a user-readable message."""
    exit_code: int = 1

class ProviderAuthError(QAAgentError):
    """Missing or invalid credentials for a provider."""

class ProviderConnectionError(QAAgentError):
    """Network or process-level failure reaching a provider."""

class ProviderResponseError(QAAgentError):
    """Provider returned an unexpected / malformed response."""

class PathError(QAAgentError):
    """File or directory argument does not exist / is not accessible."""

class ConfigError(QAAgentError):
    """Invalid or missing configuration."""
```

#### Central handler

```python
def handle_exception(
    exc: BaseException,
    provider: str | None = None,
    *,
    verbose: bool = False,
    log_path: str | None = None,
) -> int:
    """
    Map any exception to a user-friendly error message + exit code.
    Always returns an exit code (caller does sys.exit).
    Writes full traceback to log_path when provided (see logging.md).
    """
```

Mapping table (evaluated in order):

| Exception type | Message shown | Exit |
|---|---|---|
| `KeyboardInterrupt` | `⚠ Interrupted.` | 1 |
| `ProviderAuthError` | message + provider-specific setup tip | 1 |
| `ProviderConnectionError` | connection message | 1 |
| `QAAgentError` (any other) | `.args[0]` | `.exit_code` |
| Claude `CLINotFoundError` | install tip | 1 |
| Claude `CLIConnectionError` | connection message | 1 |
| Claude `ProcessError` | exit code message | 1 |
| Claude `CLIJSONDecodeError` | unexpected response | 1 |
| `RuntimeError` | str(exc) | 1 |
| `Exception` (catch-all) | `Unexpected error` + see-log tip | 2 |

When `verbose=True` the full Python traceback is also printed to stderr.
When `log_path` is given the traceback is always written there silently.

#### Provider-specific error wrappers

Each provider module wraps its SDK exceptions into the common hierarchy:

```python
# claude_provider.py  (inside stream())
except CLINotFoundError as exc:
    raise ProviderAuthError(
        "Claude Code CLI not found.\n"
        "  Install: npm install -g @anthropic-ai/claude-code\n"
        "  Or set:  ANTHROPIC_API_KEY=sk-ant-..."
    ) from exc
```

This way `summarise.py` and future commands need zero provider-specific
`isinstance` checks.

---

## 3. Better `--help` Output

### Provider Flag Rename

**Current** (non-standard single-dash):
```
-claude  -openai  -gemini
```

**New** (standard POSIX double-dash with positional shorthand):
```
--provider {claude,openai,gemini}   (default: claude)
```

Keeps a short alias for power users:
```
-p claude   -p openai   -p gemini
```

`cli.py` diff:

```python
# Before
provider_group.add_argument("-claude", dest="provider", ...)

# After
summarise_parser.add_argument(
    "--provider", "-p",
    choices=["claude", "openai", "gemini"],
    default="claude",
    metavar="PROVIDER",
    help="AI provider to use: claude (default), openai, gemini.",
)
```

**Breaking change**: document in CLAUDE.md under a `## Migration Notes`
section. Old single-dash flags will be removed.

### `--version` Flag

```python
# pyproject.toml  (already has version = "0.1.0")
# cli.py root parser:
parser.add_argument(
    "--version", "-V",
    action="version",
    version=f"%(prog)s {importlib.metadata.version('marquee-agents')}",
)
```

### Root Help Examples

```python
parser = argparse.ArgumentParser(
    ...
    epilog=(
        "Examples:\n"
        "  qa-agent doctor                  # check environment\n"
        "  qa-agent summarise               # summarise cwd\n"
        "  qa-agent summarise src/ -p gemini\n"
        "  qa-agent --version\n"
    ),
    formatter_class=argparse.RawDescriptionHelpFormatter,
)
```

---

## 4. Global `--verbose` / `--debug` Flag

### Design

Verbosity lives on the root parser so it is available to every sub-command.

```python
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
    help="Developer mode: --verbose + write session log (see logging.md).",
)
```

`--debug` implies `--verbose`.

### Propagation

`args.verbose` and `args.debug` are passed to every command's `run()` function
and forwarded into `ProviderRequest.extra`:

```python
request = _build_request(cwd, abs_paths, verbose=args.verbose)
# ProviderRequest.extra["verbose"] = True
```

Providers use `extra.get("verbose", False)` to decide whether to surface
internal SDK events.

### Effect Table

| Output | Normal | `--verbose` | `--debug` |
|--------|--------|-------------|-----------|
| Banner + spinner | ✓ | ✓ | ✓ |
| AI streamed text | ✓ | ✓ | ✓ |
| SDK tool-call events | — | ✓ | ✓ |
| Full tracebacks on error | — | ✓ | ✓ |
| Session log written | — | — | ✓ |

---

## 5. Live Progress Spinner

### Requirements

- Zero new dependencies (use stdlib only)
- Stops cleanly on `KeyboardInterrupt` and on error
- Disabled automatically when stdout is not a TTY (piped output)
- Shows elapsed time

### Implementation

```python
# qa_agent/output.py  (added section)

import itertools, threading, time

class Spinner:
    """
    Context manager that animates a spinner on the current line
    while the block executes.

        with Spinner("Analysing"):
            ...  # long-running work

    The spinner is silently suppressed when stdout is not a TTY.
    """
    _FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

    def __init__(self, label: str, *, stream=sys.stderr) -> None:
        self._label  = label
        self._stream = stream
        self._stop   = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "Spinner":
        if not USE_COLOR:            # not a TTY → silent
            return self
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join()
        if USE_COLOR:
            # Erase the spinner line
            self._stream.write("\r\033[K")
            self._stream.flush()

    def _spin(self) -> None:
        frames = itertools.cycle(self._FRAMES)
        start  = time.monotonic()
        while not self._stop.wait(0.1):
            elapsed = time.monotonic() - start
            frame   = next(frames)
            line    = f"  {dim(frame)}  {self._label}  {dim(f'{elapsed:.0f}s')}"
            self._stream.write(f"\r{line}")
            self._stream.flush()
```

### Usage in `summarise.py`

```python
from qa_agent.output import Spinner

# Before:
print(f"  {dim('Analysing …')}\n")
await _render_stream(provider.stream(request))

# After:
with Spinner(f"Analysing with {provider.PROVIDER_NAME}"):
    first_chunk = await _get_first_chunk(provider.stream(request))

# Spinner exits → print first chunk → stream the rest normally
```

The spinner stops as soon as the first token arrives, giving the engineer
immediate visual feedback that the AI is responding.

---

## Migration Checklist

- [ ] Create `qa_agent/output.py` with all helpers
- [ ] Create `qa_agent/errors.py` with hierarchy + handler
- [ ] Update `qa_agent/summarise.py`: import from `output`, use `errors`
- [ ] Update `qa_agent/claude_provider.py`: wrap SDK exceptions
- [ ] Update `qa_agent/openai_provider.py`: wrap SDK exceptions
- [ ] Update `qa_agent/gemini_provider.py`: wrap SDK exceptions
- [ ] Update `qa_agent/cli.py`: `--provider`, `--version`, `--verbose`, `--debug`
- [ ] Update `CLAUDE.md`: flag rename, new flags, migration note
- [ ] Update `IMPLEMENTATION/summarise.md`: reflect provider flag change

---

## Verification Plan

```bash
# Spinner visible
qa-agent summarise .

# No spinner (piped)
qa-agent summarise . | cat

# Verbose mode
qa-agent --verbose summarise .

# Debug mode (creates log)
qa-agent --debug summarise .

# New provider flag
qa-agent summarise . --provider openai
qa-agent summarise . -p gemini

# Version
qa-agent --version        # e.g. qa-agent 0.1.0

# Error with verbose traceback
unset ANTHROPIC_API_KEY
qa-agent --verbose summarise .

# Interrupt
qa-agent summarise . &  sleep 1  kill -INT $!   # → ⚠ Interrupted.
```
