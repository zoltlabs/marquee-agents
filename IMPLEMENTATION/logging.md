# Session Logging — Implementation Plan

Structured, disk-efficient session logs for `qa-agent`.

---

## Goals

| Goal | Detail |
|------|--------|
| **Crash capture** | Full traceback + context written on any unexpected exit |
| **Debug mode** | `--debug` flag writes a complete session transcript |
| **Disk efficiency** | Rotated, compressed, bounded — safe for many concurrent users |
| **Zero in normal mode** | No I/O cost unless something fails or `--debug` is set |
| **Developer-readable** | Structured JSON Lines (`.jsonl.gz`) + plain last-session link |

---

## Log Directory Layout

```
~/.local/share/qa-agent/logs/         ← Linux / macOS XDG default via platformdirs
    session-2026-02-25T10-04-21.jsonl.gz
    session-2026-02-25T11-17-03.jsonl.gz
    ...
    last-session.log                  ← symlink to most recent uncompressed draft
```

On macOS `platformdirs.user_data_dir("qa-agent", "ZoltLabs")` resolves to
`~/Library/Application Support/ZoltLabs/qa-agent/logs`.

### Size Budget per User

| Item | Size |
|------|------|
| One compressed session | ~2–8 KB |
| Retention window | 14 days **or** 50 files, whichever is smaller |
| Max total on disk | ~400 KB per user |

Rotation is enforced by `_prune_old_logs()` called at the start of every
session that writes a log (crash or `--debug`).

---

## Log Record Format — JSON Lines

Each log entry is one JSON object on one line, newline-delimited (`.jsonl`).
After the session the file is gzip-compressed in-place (`.jsonl.gz`).

### Schema

```jsonc
// Header record — always first
{
  "t": "2026-02-25T10:04:21.123Z",   // ISO-8601 UTC timestamp
  "k": "session_start",
  "v": "0.1.0",                       // qa-agent version
  "cmd": ["summarise", ".", "-p", "gemini"],
  "cwd": "/home/eng/project",
  "pid": 91234,
  "python": "3.12.2"
}

// Progress event
{
  "t": "2026-02-25T10:04:22.001Z",
  "k": "event",
  "msg": "provider_stream_started",
  "provider": "gemini"
}

// Chunk received (debug mode only — verbose=True)
{
  "t": "...",
  "k": "chunk",
  "text": "## Directory Structure\n"
}

// Error record — written on any exception
{
  "t": "...",
  "k": "error",
  "exc_type": "ProviderAuthError",
  "msg": "GEMINI_API_KEY not set.",
  "traceback": "Traceback (most recent call last):\n  ..."
}

// Footer — written on clean exit or after error record
{
  "t": "...",
  "k": "session_end",
  "exit_code": 1,
  "elapsed_s": 3.14
}
```

Key design choices:
- Short key names (`t`, `k`, `msg`) save bytes at scale
- `chunk` records are **only** written in `--debug` mode
- All timestamps are UTC to avoid DST confusion on shared CI machines

---

## Module: `qa_agent/session_log.py`

### Public API

```python
class SessionLog:
    """
    Thin, thread-safe session log writer.

    Usage (in cli.py):

        log = SessionLog.open(debug=args.debug)   # None if not writing
        try:
            run_command(...)
        except Exception as exc:
            log.error(exc)          # writes error + traceback
            raise
        finally:
            log.close(exit_code)    # writes footer + compresses
    """

    @classmethod
    def open(cls, *, debug: bool = False) -> "SessionLog | None":
        """
        Returns a SessionLog instance when debug=True or on crash.
        Returns None in normal (non-debug) mode — all methods become no-ops
        through the NullLog sentinel so callers never need to guard.
        """

    def event(self, msg: str, **kwargs) -> None:
        """Write a progress/event record. No-op on NullLog."""

    def chunk(self, text: str) -> None:
        """Write a streamed AI chunk. Only active in debug mode."""

    def error(self, exc: BaseException) -> None:
        """Write an error record with full traceback. Always flushes."""

    def close(self, exit_code: int = 0) -> None:
        """Write footer, flush, gzip-compress the file, update symlink."""
```

### Crash-triggered logging (unexpected exit)

For unexpected crashes the log is opened lazily in `errors.py::handle_exception`
even outside of `--debug` mode:

```python
# errors.py
def handle_exception(exc, provider=None, *, verbose=False, log_path=None):
    ...
    if log_path is None and not isinstance(exc, (KeyboardInterrupt, SystemExit)):
        # Unexpected crash — open a crash log automatically
        from qa_agent.session_log import SessionLog
        crash_log = SessionLog.open(debug=False)
        crash_log.error(exc)
        crash_log.close(exit_code=2)
        log_path = crash_log.path
        print_error(f"Session log written to: {log_path}")
```

So engineers always get a log file path to share with the team after a crash,
without needing to know about `--debug`.

### Rotation / Pruning

```python
def _prune_old_logs(log_dir: Path, *, max_files: int = 50, max_days: int = 14) -> None:
    """
    Delete the oldest compressed logs when limits are exceeded.
    Called once at the start of open() before creating a new file.
    """
    files = sorted(log_dir.glob("session-*.jsonl.gz"), key=lambda p: p.stat().st_mtime)
    cutoff = time.time() - max_days * 86400
    to_delete = [f for f in files if f.stat().st_mtime < cutoff]
    # Also delete oldest if over max_files
    over = len(files) - max_files
    if over > 0:
        to_delete = list(set(to_delete) | set(files[:over]))
    for f in to_delete:
        f.unlink(missing_ok=True)
```

### Compression

After `close()` is called:

```python
import gzip, shutil

def _compress(path: Path) -> Path:
    gz_path = path.with_suffix(".jsonl.gz")
    with path.open("rb") as f_in, gzip.open(gz_path, "wb", compresslevel=6) as f_out:
        shutil.copyfileobj(f_in, f_out)
    path.unlink()   # remove uncompressed draft
    return gz_path
```

`compresslevel=6` is the stdlib default — good compression/speed balance.
A typical 5s session compresses from ~20 KB → ~3 KB.

---

## `last-session.log` Symlink

After compression, `last-session.log` is updated to point at the newest
`.jsonl.gz` file. This gives engineers a stable path to share:

```bash
# Developer-friendly commands documented in CLAUDE.md:
zcat ~/.local/share/qa-agent/logs/last-session.log | python -m json.tool | head -50
```

On macOS, `zcat` is aliased from `gzcat` — document both.

---

## CLI Integration Points

### `cli.py` change

```python
from qa_agent.session_log import SessionLog

def main() -> None:
    args = parser.parse_args()
    log  = SessionLog.open(debug=getattr(args, "debug", False))

    exit_code = 0
    try:
        if args.command == "summarise":
            from qa_agent.summarise import run
            run(provider=args.provider, paths=args.paths,
                verbose=args.verbose, log=log)
        elif args.command == "doctor":
            ...
        else:
            parser.print_help()
    except Exception as exc:
        from qa_agent.errors import handle_exception
        exit_code = handle_exception(exc, verbose=args.verbose, log=log)
    finally:
        log.close(exit_code)
        sys.exit(exit_code)
```

Every command receives `log` as an optional parameter and calls `log.event()`
at key milestones (provider selected, first chunk received, etc.).

---

## Developer Commands (to add to CLAUDE.md)

```bash
# View last session log
zcat ~/.local/share/qa-agent/logs/last-session.log   # macOS: gzcat

# Pretty-print JSON
zcat ... | python -m json.tool

# List all session logs
ls -lh ~/.local/share/qa-agent/logs/

# Delete all logs (reset)
rm -rf ~/.local/share/qa-agent/logs/

# Force a debug session
qa-agent --debug summarise .
```

---

## Dependencies

| Package | Usage | New? |
|---------|-------|------|
| `platformdirs` | Cross-platform log dir | Shared with doctor.md |
| `gzip` | Compression | stdlib ✓ |
| `json` | Record serialisation | stdlib ✓ |
| `threading` | Thread-safe writes | stdlib ✓ |

No new runtime dependencies beyond `platformdirs` (already added for `doctor`).

---

## Security & Privacy

- Logs are written to the **user's own home directory only** — never shared
- If files in a directory are summarised, only file *paths* are logged — never
  file *contents* (even in `--debug` mode, chunk records contain AI output only)
- Log directory is created with `mode=0o700` (user-only permissions)

---

## Verification Plan

```bash
# Normal run — no log created
qa-agent summarise .
ls ~/.local/share/qa-agent/logs/       # empty

# Debug run — log created + compressed
qa-agent --debug summarise .
ls -lh ~/.local/share/qa-agent/logs/  # session-*.jsonl.gz

# Crash log — created automatically on unexpected error
ANTHROPIC_API_KEY=bad qa-agent summarise .   # exits 1 with log path printed

# Rotation — create 51 dummy logs, run, verify oldest deleted
# (integration test)

# doctor shows log dir size
qa-agent doctor
# → Log system  ✓  ...  (X KB used)
```
