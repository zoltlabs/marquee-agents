"""qa_agent/tools/report/sim_metadata.py

Tools: list_sim_files, read_sim_metadata

Provides the AI agent with a map of available simulation output files and
controlled access to known metadata files in qrun.out/.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from qa_agent.tools.report.security import validate_path, truncate_output

# Allowlisted metadata files the agent may read from qrun.out/
_METADATA_ALLOWLIST = {"big_argv", "history", "stats_log", "top_dus", "version"}

# Max bytes for a single metadata file read
_METADATA_MAX_BYTES = 4_096

# Known file extensions to include in directory listings
_KNOWN_EXTENSIONS = {
    ".log", ".out", ".doc", ".txt", ".xml", ".json", ".sv", ".v", ".vh", ".vhd"
}


def _build_list_sim_files_handler(sim_dir: Path):
    """Return a handler for list_sim_files bound to *sim_dir*."""

    def list_sim_files(subdir: str = "") -> str:
        """List files available in the simulation output directory.

        Args:
            subdir: Optional subdirectory relative to sim_dir (e.g. "qrun.out", "logs").

        Returns:
            JSON string: list of {name, size_bytes, type} objects.
        """
        if subdir:
            target = validate_path(subdir, sim_dir)
        else:
            target = sim_dir.resolve()

        if not target.is_dir():
            return json.dumps({"error": f"'{subdir}' is not a directory."})

        entries = []
        try:
            for entry in sorted(target.iterdir()):
                if entry.is_file() and (entry.suffix.lower() in _KNOWN_EXTENSIONS or not entry.suffix):
                    entries.append({
                        "name": str(entry.relative_to(sim_dir.resolve())),
                        "size_bytes": entry.stat().st_size,
                        "type": "file",
                    })
                elif entry.is_dir():
                    entries.append({
                        "name": str(entry.relative_to(sim_dir.resolve())) + "/",
                        "size_bytes": None,
                        "type": "directory",
                    })
        except PermissionError as exc:
            return json.dumps({"error": str(exc)})

        return json.dumps(entries, indent=2)

    return list_sim_files


def _build_read_sim_metadata_handler(sim_dir: Path):
    """Return a handler for read_sim_metadata bound to *sim_dir*."""

    def read_sim_metadata(file: str) -> str:
        """Read a metadata file from qrun.out/.

        Args:
            file: One of: big_argv, history, stats_log, top_dus, version.

        Returns:
            File content truncated at 4KB.
        """
        if file not in _METADATA_ALLOWLIST:
            return (
                f"Access denied: '{file}' is not in the metadata allowlist. "
                f"Allowed: {', '.join(sorted(_METADATA_ALLOWLIST))}"
            )

        metadata_path = validate_path(f"qrun.out/{file}", sim_dir)

        if not metadata_path.exists():
            return f"File not found: qrun.out/{file}"

        try:
            raw = metadata_path.read_bytes()[:_METADATA_MAX_BYTES]
            text = raw.decode("utf-8", errors="replace")
            truncated = len(metadata_path.read_bytes()) > _METADATA_MAX_BYTES
            if truncated:
                text += "\n... [output truncated at 4KB]"
            return text
        except OSError as exc:
            return f"Read error: {exc}"

    return read_sim_metadata


def build_sim_metadata_tools(sim_dir: Path) -> list[tuple]:
    """Return (name, description, parameters_schema, handler) tuples for sim metadata tools."""
    return [
        (
            "list_sim_files",
            (
                "List files available in the simulation output directory. "
                "Use this first to understand what data is available. "
                "Pass a subdir like 'qrun.out' or 'logs' to drill down."
            ),
            {
                "type": "object",
                "properties": {
                    "subdir": {
                        "type": "string",
                        "description": "Optional subdirectory to list (e.g. 'qrun.out', 'logs'). Omit to list the top level.",
                    }
                },
                "required": [],
            },
            _build_list_sim_files_handler(sim_dir),
        ),
        (
            "read_sim_metadata",
            (
                "Read a metadata file from qrun.out/. Provides test configuration context. "
                "Allowed files: big_argv (full command line), history (run history), "
                "stats_log (run statistics), top_dus (design units), version (tool versions)."
            ),
            {
                "type": "object",
                "properties": {
                    "file": {
                        "type": "string",
                        "enum": list(_METADATA_ALLOWLIST),
                        "description": "Metadata file to read.",
                    }
                },
                "required": ["file"],
            },
            _build_read_sim_metadata_handler(sim_dir),
        ),
    ]
