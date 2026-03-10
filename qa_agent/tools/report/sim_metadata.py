"""qa_agent/tools/report/sim_metadata.py

Tools: list_sim_files, read_sim_metadata, get_sfi_data, get_coverage_report

Provides the AI with a directory listing and controlled access to Questa
qrun.out/ metadata, SFI interface data, and coverage reports.

The AI calls list_sim_files() first to discover what is available, then
uses specific tools to read data.  No design files, no source RTL, and
no binary files may be accessed.

Security:
  - list_sim_files: skips binary dirs (work/, design.bin, qwave.db) and
    renders only text files plus subdirectory names.
  - read_sim_metadata: hard-allowlisted to 5 known qrun.out/ metadata files.
  - get_sfi_data: filename must match sfi_*.txt pattern.
  - get_coverage_report: filename must contain 'coverage' and end in .txt.
  - All paths validated through security.validate_path().
"""

from __future__ import annotations

import re
from pathlib import Path

from qa_agent.tools.report.security import validate_path, truncate_output

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

# Allowlisted qrun.out/ metadata filenames the AI may read
_METADATA_ALLOWLIST = {"big_argv", "history", "stats_log", "top_dus", "version"}

# Binary/non-text items to skip from directory listings
_SKIP_NAMES = {"work", "design.bin", "qwave.db", "sessions", "snapshot", "__pycache__"}

# Text extensions shown in listings
_TEXT_EXTENSIONS = {".txt", ".log", ".doc", ".f", ".sv", ".v", ".vh", ".cmd", ".out", ".json"}

_METADATA_MAX_BYTES = 8_000
_SFI_MAX_LINES = 200
_COVERAGE_MAX_BYTES = 32_000


# ─────────────────────────────────────────────────────────────────────────────
# list_sim_files
# ─────────────────────────────────────────────────────────────────────────────

def _build_list_sim_files_handler(sim_dir: Path):
    def list_sim_files(subdir: str = "") -> str:
        """List readable files in the simulation output directory.

        Call this first to understand what data is available before
        requesting specific files.  Binary files (design.bin, qwave.db,
        work/) are automatically excluded.

        Args:
            subdir: Optional subdirectory relative to sim_dir
                    (e.g. 'qrun.out', 'qrun.out/big_argv').
                    Omit to list the top-level simulation directory.

        Returns:
            Formatted text list of files and directories with sizes.
        """
        if subdir:
            try:
                target = validate_path(subdir, sim_dir)
            except Exception as exc:
                return f"ERROR: {exc}"
        else:
            target = sim_dir.resolve()

        if not target.is_dir():
            return f"ERROR: '{subdir}' is not a directory inside sim_dir."

        try:
            entries = sorted(target.iterdir())
        except PermissionError as exc:
            return f"ERROR: Permission denied: {exc}"

        lines = [f"=== Contents of {'sim_dir' if not subdir else subdir}/ ==="]
        files_shown = 0
        dirs_shown = 0
        for entry in entries:
            name = entry.name
            if name in _SKIP_NAMES or name.startswith("."):
                continue
            if entry.is_dir():
                lines.append(f"  [DIR]  {name}/")
                dirs_shown += 1
            elif entry.is_file():
                suffix = entry.suffix.lower()
                # Always show text files; skip unknown binary extensions
                if not suffix or suffix in _TEXT_EXTENSIONS:
                    kb = entry.stat().st_size / 1024
                    lines.append(f"  [FILE] {name}  ({kb:.1f} KB)")
                    files_shown += 1
                # else: silently skip binary files

        lines.append(
            f"\n{files_shown} readable file(s), {dirs_shown} directory(s) shown."
        )
        if subdir == "" or subdir == ".":
            lines.append(
                "Tip: use subdir='qrun.out' to see metadata files, "
                "or read_sim_metadata(file='stats_log') to check build status."
            )
        return "\n".join(lines)

    return list_sim_files


# ─────────────────────────────────────────────────────────────────────────────
# read_sim_metadata
# ─────────────────────────────────────────────────────────────────────────────

def _build_read_sim_metadata_handler(sim_dir: Path):
    def read_sim_metadata(file: str) -> str:
        """Read a qrun.out/ metadata file.

        Available files:
          stats_log  — vlog/vopt/vsim/qrun error + warning counts (read FIRST)
          big_argv   — full vlog command line (plusargs, seed, defines, filelist)
          version    — Questa tool version
          top_dus    — compiled design units
          history    — run history

        Args:
            file: One of: stats_log, big_argv, version, top_dus, history.

        Returns:
            File content (plain text, up to 8 KB).
        """
        if file not in _METADATA_ALLOWLIST:
            return (
                f"ERROR: '{file}' is not an allowed metadata file. "
                f"Allowed: {', '.join(sorted(_METADATA_ALLOWLIST))}"
            )

        # big_argv may be a directory containing a .f file
        big_argv_dir = sim_dir / "qrun.out" / "big_argv"
        if file == "big_argv" and big_argv_dir.is_dir():
            try:
                f_files = sorted(big_argv_dir.glob("*.f"))
                if f_files:
                    try:
                        validated = validate_path(
                            str(f_files[0].relative_to(sim_dir)), sim_dir
                        )
                        raw = validated.read_bytes()[:_METADATA_MAX_BYTES]
                        text = raw.decode("utf-8", errors="replace")
                        excess = validated.stat().st_size - _METADATA_MAX_BYTES
                        if excess > 0:
                            text += f"\n... [truncated, {excess} more bytes] ..."
                        return f"=== qrun.out/big_argv/{f_files[0].name} ===\n{text}"
                    except Exception as exc:
                        return f"ERROR reading big_argv: {exc}"
            except Exception:
                pass

        try:
            meta_path = validate_path(f"qrun.out/{file}", sim_dir)
        except Exception as exc:
            return f"ERROR: {exc}"

        if not meta_path.exists():
            return f"INFO: qrun.out/{file} not found (may not exist for this Questa version)."

        try:
            raw = meta_path.read_bytes()
            excess = len(raw) - _METADATA_MAX_BYTES
            text = raw[:_METADATA_MAX_BYTES].decode("utf-8", errors="replace")
            if excess > 0:
                text += f"\n... [truncated, {excess} more bytes] ..."
            return f"=== qrun.out/{file} ===\n{text}"
        except OSError as exc:
            return f"ERROR: Cannot read qrun.out/{file}: {exc}"

    return read_sim_metadata


# ─────────────────────────────────────────────────────────────────────────────
# get_sfi_data
# ─────────────────────────────────────────────────────────────────────────────

def _build_get_sfi_data_handler(sim_dir: Path):
    def get_sfi_data(
        file_name: str,
        max_lines: int = 100,
        pattern: str = "",
    ) -> str:
        """Read an SFI (Scalable Fabric Interface) data file.

        SFI files capture fabric-level transactions:
          sfi_data_app_ep.txt  — data transactions
          sfi_glob_app_ep.txt  — global interface events
          sfi_hdr_app_ep.txt   — header transactions

        Use list_sim_files() first to see which sfi_*.txt files exist.

        IMPORTANT: Only sfi_*.txt files may be read. Do NOT request
        design files, source RTL, or any binary file.

        Args:
            file_name: SFI filename (must match sfi_*.txt).
            max_lines: Max lines to return (1–500, default 100).
            pattern:   Optional regex to filter lines.

        Returns:
            Plain text content from the SFI file.
        """
        basename = Path(file_name).name
        if not re.match(r"^sfi_[a-z0-9_.]+\.txt$", basename, re.IGNORECASE):
            return (
                f"ERROR: '{file_name}' is not a valid SFI filename. "
                "SFI files must match sfi_*.txt. "
                "Use list_sim_files() to see available files."
            )

        try:
            resolved = validate_path(basename, sim_dir)
        except Exception as exc:
            return f"ERROR: {exc}"

        if not resolved.is_file():
            return (
                f"ERROR: '{basename}' not found. "
                "Use list_sim_files() to check what files exist."
            )

        try:
            content = resolved.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"ERROR: Cannot read '{basename}': {exc}"

        max_lines = max(1, min(max_lines, 500))
        lines = content.splitlines()
        total = len(lines)

        if pattern:
            try:
                regex = re.compile(pattern, re.IGNORECASE)
            except re.error as exc:
                return f"ERROR: Invalid pattern '{pattern}': {exc}"
            matched = [f"[L{i+1}] {l}" for i, l in enumerate(lines) if regex.search(l)]
            result_lines = matched[:max_lines]
            header = (
                f"=== {basename} ({total} lines, pattern='{pattern}', "
                f"{len(result_lines)} matches) ==="
            )
        else:
            result_lines = [f"[L{i+1}] {l}" for i, l in enumerate(lines[:max_lines])]
            header = f"=== {basename} ({total} lines, showing first {len(result_lines)}) ==="

        suffix = ""
        if total > max_lines and not pattern:
            suffix = f"\n... [{total - max_lines} more lines — increase max_lines to see more] ..."

        return f"{header}\n" + "\n".join(result_lines) + suffix

    return get_sfi_data


# ─────────────────────────────────────────────────────────────────────────────
# get_coverage_report
# ─────────────────────────────────────────────────────────────────────────────

def _build_get_coverage_handler(sim_dir: Path):
    def get_coverage_report(file_name: str = "") -> str:
        """Read a functional coverage report file.

        Coverage files are named like apci_coverage_report.txt.
        Use list_sim_files() to discover the exact filename.

        If file_name is empty, returns the first coverage file found.

        Args:
            file_name: Coverage report filename (must contain 'coverage'
                       and end in .txt). Leave empty to auto-find.

        Returns:
            Plain text coverage report (up to 32 KB).
        """
        if file_name:
            basename = Path(file_name).name
            if "coverage" not in basename.lower() or not basename.endswith(".txt"):
                return (
                    f"ERROR: '{file_name}' does not look like a coverage file. "
                    "Coverage files contain 'coverage' in the name and end in .txt. "
                    "Use list_sim_files() to discover the correct name."
                )
            try:
                resolved = validate_path(basename, sim_dir)
            except Exception as exc:
                return f"ERROR: {exc}"
            if not resolved.is_file():
                return f"ERROR: '{basename}' not found."
        else:
            # Auto-discover
            resolved = None
            try:
                for entry in sorted(sim_dir.iterdir()):
                    if (
                        entry.is_file()
                        and "coverage" in entry.name.lower()
                        and entry.suffix == ".txt"
                    ):
                        try:
                            resolved = validate_path(
                                str(entry.relative_to(sim_dir)), sim_dir
                            )
                            break
                        except Exception:
                            continue
            except Exception:
                pass
            if resolved is None:
                return "INFO: No coverage report file found (looked for *coverage*.txt)."

        try:
            raw = resolved.read_bytes()
            text = raw[:_COVERAGE_MAX_BYTES].decode("utf-8", errors="replace")
            excess = len(raw) - _COVERAGE_MAX_BYTES
            header = f"=== {resolved.name} ({len(raw) / 1024:.1f} KB) ==="
            if excess > 0:
                text += f"\n... [truncated, {excess} more bytes] ..."
            return f"{header}\n{text}"
        except OSError as exc:
            return f"ERROR: Cannot read coverage file: {exc}"

    return get_coverage_report


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def build_sim_metadata_tools(sim_dir: Path) -> list[tuple]:
    """Return (name, description, parameters_schema, handler) tuples."""
    return [
        (
            "list_sim_files",
            (
                "List readable files in the simulation output directory. "
                "ALWAYS call this first to discover what data is available. "
                "Binary files (design.bin, qwave.db, work/) are excluded automatically. "
                "Use subdir='qrun.out' to see metadata files, "
                "or subdir='qrun.out/big_argv' for the filelist directory."
            ),
            {
                "type": "object",
                "properties": {
                    "subdir": {
                        "type": "string",
                        "description": (
                            "Optional subdirectory to list (e.g. 'qrun.out'). "
                            "Omit to list the top-level simulation directory."
                        ),
                    },
                },
                "required": [],
            },
            _build_list_sim_files_handler(sim_dir),
        ),
        (
            "read_sim_metadata",
            (
                "Read a qrun.out/ metadata file. "
                "Read stats_log FIRST — it shows vlog/vopt/vsim/qrun error counts at a glance. "
                "Then big_argv for the full command line (test name, seed, plusargs, defines). "
                "Allowed: stats_log, big_argv, version, top_dus, history."
            ),
            {
                "type": "object",
                "properties": {
                    "file": {
                        "type": "string",
                        "enum": sorted(_METADATA_ALLOWLIST),
                        "description": "Metadata file to read.",
                    },
                },
                "required": ["file"],
            },
            _build_read_sim_metadata_handler(sim_dir),
        ),
        (
            "get_sfi_data",
            (
                "Read a Questa SFI (Scalable Fabric Interface) data file. "
                "SFI files capture fabric-level transaction history: "
                "sfi_data_app_ep.txt, sfi_glob_app_ep.txt, sfi_hdr_app_ep.txt. "
                "Use list_sim_files() first to discover which exist. "
                "IMPORTANT: Only sfi_*.txt files are accessible."
            ),
            {
                "type": "object",
                "properties": {
                    "file_name": {
                        "type": "string",
                        "description": "SFI filename (must match sfi_*.txt).",
                    },
                    "max_lines": {
                        "type": "integer",
                        "description": "Max lines to return (1–500, default 100).",
                        "minimum": 1,
                        "maximum": 500,
                    },
                    "pattern": {
                        "type": "string",
                        "description": "Optional regex filter for lines.",
                    },
                },
                "required": ["file_name"],
            },
            _build_get_sfi_data_handler(sim_dir),
        ),
        (
            "get_coverage_report",
            (
                "Read a functional coverage report (e.g. apci_coverage_report.txt). "
                "Use list_sim_files() to find the filename. "
                "Leave file_name empty to auto-detect."
            ),
            {
                "type": "object",
                "properties": {
                    "file_name": {
                        "type": "string",
                        "description": (
                            "Coverage report filename (must contain 'coverage' + end in .txt). "
                            "Leave empty to auto-find."
                        ),
                    },
                },
                "required": [],
            },
            _build_get_coverage_handler(sim_dir),
        ),
    ]
