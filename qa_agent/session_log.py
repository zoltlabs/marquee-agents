"""qa_agent/session_log.py

Thin, thread-safe session log writer.

Usage (in cli.py):

    log = SessionLog.open(debug=args.debug)
    try:
        run_command(...)
    except Exception as exc:
        log.error(exc)     # writes error + traceback
        raise
    finally:
        log.close(exit_code)  # writes footer + compresses

In normal (non-debug) mode SessionLog.open() returns a _NullLog sentinel
so callers never need to guard against None.
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

try:
    import platformdirs
    _HAS_PLATFORMDIRS = True
except ImportError:
    _HAS_PLATFORMDIRS = False


# ─────────────────────────────────────────────────────────────────────────────
# Log directory
# ─────────────────────────────────────────────────────────────────────────────

def _log_dir() -> Path:
    if _HAS_PLATFORMDIRS:
        base = platformdirs.user_data_dir("qa-agent", "ZoltLabs")
    else:
        base = os.path.join(os.path.expanduser("~"), ".local", "share", "qa-agent")
    return Path(base) / "logs"


# ─────────────────────────────────────────────────────────────────────────────
# Pruning
# ─────────────────────────────────────────────────────────────────────────────

def _prune_old_logs(log_dir: Path, *, max_files: int = 50, max_days: int = 14) -> None:
    """Delete oldest compressed logs when retention limits are exceeded."""
    files = sorted(log_dir.glob("session-*.jsonl.gz"), key=lambda p: p.stat().st_mtime)
    cutoff = time.time() - max_days * 86400
    to_delete = {f for f in files if f.stat().st_mtime < cutoff}
    over = len(files) - max_files
    if over > 0:
        to_delete |= set(files[:over])
    for f in to_delete:
        f.unlink(missing_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# Compression helper
# ─────────────────────────────────────────────────────────────────────────────

def _compress(path: Path) -> Path:
    """Gzip-compress *path* in-place; return the .jsonl.gz path."""
    gz_path = path.with_suffix(".jsonl.gz")
    with path.open("rb") as f_in, gzip.open(gz_path, "wb", compresslevel=6) as f_out:
        shutil.copyfileobj(f_in, f_out)
    path.unlink()
    return gz_path


# ─────────────────────────────────────────────────────────────────────────────
# Null sentinel (no-op for all write methods)
# ─────────────────────────────────────────────────────────────────────────────

class _NullLog:
    """Drop-in replacement when logging is disabled. All methods are no-ops."""

    path: str | None = None

    def event(self, msg: str, **kwargs) -> None:  # noqa: D102
        pass

    def chunk(self, text: str) -> None:  # noqa: D102
        pass

    def error(self, exc: BaseException) -> None:  # noqa: D102
        pass

    def close(self, exit_code: int = 0) -> None:  # noqa: D102
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Real session log
# ─────────────────────────────────────────────────────────────────────────────

class SessionLog:
    """Thin, thread-safe session log writer.

    Open via :meth:`open` — never instantiate directly.
    In normal (non-debug) mode ``open()`` returns a :class:`_NullLog`
    so callers never need to guard.
    """

    def __init__(self, file_path: Path, *, debug: bool) -> None:
        self._path = file_path
        self._debug = debug
        self._lock = threading.Lock()
        self._start = time.monotonic()
        self._fh = file_path.open("w", encoding="utf-8")
        self._write_header()

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def path(self) -> str:
        """Path to the (possibly still-uncompressed) log file."""
        return str(self._path)

    @classmethod
    def open(cls, *, debug: bool = False) -> "SessionLog | _NullLog":
        """Return a SessionLog (or _NullLog if logging is disabled).

        A real log is opened when ``debug=True``.  Crash-triggered logs are
        opened lazily by :func:`qa_agent.errors.handle_exception`.
        """
        if not debug:
            return _NullLog()

        log_dir = _log_dir()
        log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            _prune_old_logs(log_dir)
        except OSError:
            pass

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
        file_path = log_dir / f"session-{ts}.jsonl"
        return cls(file_path, debug=debug)

    def event(self, msg: str, **kwargs) -> None:
        """Write a progress/event record."""
        self._emit({"k": "event", "msg": msg, **kwargs})

    def chunk(self, text: str) -> None:
        """Write a streamed AI chunk (debug mode only)."""
        if self._debug:
            self._emit({"k": "chunk", "text": text})

    def error(self, exc: BaseException) -> None:
        """Write an error record with full traceback. Always flushes."""
        record = {
            "k": "error",
            "exc_type": type(exc).__name__,
            "msg": str(exc),
            "traceback": traceback.format_exc(),
        }
        self._emit(record, flush=True)

    def close(self, exit_code: int = 0) -> None:
        """Write footer, flush, gzip-compress the file, update symlink."""
        elapsed = time.monotonic() - self._start
        self._emit({"k": "session_end", "exit_code": exit_code, "elapsed_s": round(elapsed, 3)},
                   flush=True)
        try:
            self._fh.close()
        except OSError:
            pass

        uncompressed = self._path
        try:
            gz = _compress(uncompressed)
            self._path = gz
            self._update_symlink(gz)
        except OSError:
            pass

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _write_header(self) -> None:
        try:
            import importlib.metadata as _meta
            version = _meta.version("qa-agent")
        except Exception:
            version = "unknown"

        record = {
            "k": "session_start",
            "v": version,
            "cmd": sys.argv[1:],
            "cwd": os.getcwd(),
            "pid": os.getpid(),
            "python": ".".join(str(x) for x in sys.version_info[:3]),
        }
        self._emit(record)

    def _emit(self, record: dict, *, flush: bool = False) -> None:
        record["t"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with self._lock:
            try:
                self._fh.write(line)
                if flush:
                    self._fh.flush()
            except OSError:
                pass

    @staticmethod
    def _update_symlink(gz: Path) -> None:
        link = gz.parent / "last-session.log"
        try:
            if link.exists() or link.is_symlink():
                link.unlink()
            link.symlink_to(gz.name)
        except OSError:
            pass
