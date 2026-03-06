"""qa_agent/tools/report/security.py

Path validation and output sanitization for the report command's tool handlers.

All tool handlers call validate_path() before touching the filesystem so that
the AI agent cannot escape the simulation output directory.
"""

from __future__ import annotations

import os
from pathlib import Path

from qa_agent.errors import PathError


# ─────────────────────────────────────────────────────────────────────────────
# Path containment
# ─────────────────────────────────────────────────────────────────────────────

def validate_path(requested: str, sim_dir: Path) -> Path:
    """Resolve *requested* relative to *sim_dir* and assert containment.

    Rules:
      - Symlinks are fully resolved before comparison so traversal via symlinks
        is blocked.
      - raises PathError if the resolved path escapes sim_dir.
      - The returned Path is absolute and already resolved.

    Args:
        requested: A path string provided by the AI (may be relative or absolute).
        sim_dir:   The sandbox root — all access must stay inside here.

    Returns:
        Resolved absolute Path guaranteed to be within sim_dir.

    Raises:
        PathError: If the path traverses outside sim_dir.
    """
    sim_root = sim_dir.resolve()

    # Build an absolute candidate path — treat *requested* as relative to sim_dir
    # unless it is already absolute.
    candidate = Path(requested)
    if not candidate.is_absolute():
        candidate = sim_root / candidate

    try:
        resolved = candidate.resolve()
    except (OSError, ValueError) as exc:
        raise PathError(f"Cannot resolve path '{requested}': {exc}") from exc

    # Check containment
    try:
        resolved.relative_to(sim_root)
    except ValueError:
        raise PathError(
            f"Access denied: '{resolved}' is outside the simulation directory '{sim_root}'."
        )

    return resolved


# ─────────────────────────────────────────────────────────────────────────────
# Output sanitization
# ─────────────────────────────────────────────────────────────────────────────

def truncate_output(text: str, max_chars: int = 8_000) -> tuple[str, bool]:
    """Truncate *text* to at most *max_chars* characters.

    Returns:
        (truncated_text, was_truncated)
    """
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


def cap_lines(lines: list[str], max_lines: int) -> list[str]:
    """Return at most *max_lines* from *lines*."""
    return lines[:max_lines]
