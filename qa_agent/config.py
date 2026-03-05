"""qa_agent/config.py

QAConfig — project config loader, validator, saver.

Config file: qa-agent.yaml  (placed at the project workspace root)
Find it by walking up from CWD.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from qa_agent.errors import ConfigError

# ── YAML import (stdlib tomllib not available; use PyYAML if present) ──────────

try:
    import yaml as _yaml  # type: ignore
    _HAS_YAML = True
except ImportError:  # pragma: no cover
    _HAS_YAML = False

CONFIG_FILENAME = "qa-agent.yaml"

# ── Default fixed flag extras ──────────────────────────────────────────────────

DEFAULT_EP_FIXED_FLAGS: list[str] = [
    "+define+SIPC_FASTER_MS_TICK",
    "+define+GEN6_MAX_WIDTH_8",
    "+define+PIPE_BYTEWIDTH_16",
    "+define+APCI_MAX_DATA_WIDTH=16",
    "+licq",
]

DEFAULT_RC_FIXED_FLAGS: list[str] = [
    "+define+SIPC_FASTER_MS_TICK",
    "+define+ROUTINE_RC",
    "+define+PIPE_BYTEWIDTH_16",
    "+define+APCI_MAX_DATA_WIDTH=16",
    "+licq",
    "+define+RC_INITIATING_SPEED_CHANGE",
]

# ── Data model ─────────────────────────────────────────────────────────────────

@dataclass
class QAConfig:
    # Project
    project_name: str = ""
    project_root: str = ""          # absolute path

    # Workspace layout (relative to project_root)
    results_dir: str = ""           # e.g. verif/AVERY/run/results

    # Files (relative to project_root or absolute)
    source_file: str = ""
    basic_regression_script: str = ""
    slurm_regression_script: str = ""
    slurm_run_script: str = ""
    slurm_config: str = ""
    debug_script: str = ""

    # Results output filenames
    basic_output: str = "results.doc"
    slurm_output: str = "results_new.doc"

    # EP / RC fixed flags (merged with dynamic flags at runtime)
    ep_fixed_flags: list[str] = field(default_factory=lambda: list(DEFAULT_EP_FIXED_FLAGS))
    rc_fixed_flags: list[str] = field(default_factory=lambda: list(DEFAULT_RC_FIXED_FLAGS))

    # Path where this config was loaded from (not serialised)
    _config_path: Optional[Path] = field(default=None, repr=False, compare=False)

    @property
    def root_path(self) -> Path:
        return Path(self.project_root)

    def resolve(self, rel_or_abs: str) -> Path:
        """Return an absolute Path, resolving relative paths against project_root."""
        p = Path(rel_or_abs)
        if p.is_absolute():
            return p
        return self.root_path / p

    @property
    def source_file_path(self) -> Optional[Path]:
        if not self.source_file:
            return None
        p = self.resolve(self.source_file)
        return p if p.exists() else None

    @property
    def basic_regression_script_path(self) -> Optional[Path]:
        if not self.basic_regression_script:
            return None
        return self.resolve(self.basic_regression_script)

    @property
    def slurm_regression_script_path(self) -> Optional[Path]:
        if not self.slurm_regression_script:
            return None
        return self.resolve(self.slurm_regression_script)

    @property
    def slurm_run_script_path(self) -> Optional[Path]:
        if not self.slurm_run_script:
            return None
        return self.resolve(self.slurm_run_script)

    @property
    def slurm_config_path(self) -> Optional[Path]:
        if not self.slurm_config:
            return None
        return self.resolve(self.slurm_config)

    @property
    def debug_script_path(self) -> Optional[Path]:
        if not self.debug_script:
            return None
        return self.resolve(self.debug_script)

    @property
    def results_dir_path(self) -> Path:
        return self.resolve(self.results_dir)


# ── Discovery ──────────────────────────────────────────────────────────────────

def find_config(start: Path = None) -> Optional[Path]:
    """Walk up from `start` (default: CWD) searching for qa-agent.yaml.

    Returns the Path if found, or None.
    """
    if start is None:
        start = Path.cwd()
    current = start.resolve()
    while True:
        candidate = current / CONFIG_FILENAME
        if candidate.exists():
            return candidate
        parent = current.parent
        if parent == current:   # reached filesystem root
            return None
        current = parent


# ── Load ───────────────────────────────────────────────────────────────────────

def _require_yaml() -> None:
    if not _HAS_YAML:
        raise ConfigError(
            "PyYAML is required for config support.  Install it with:  pip install pyyaml"
        )


def load_config(path: Path) -> QAConfig:
    """Parse qa-agent.yaml and return QAConfig. Raises ConfigError on invalid data."""
    _require_yaml()
    try:
        text = path.read_text(encoding="utf-8")
        data = _yaml.safe_load(text) or {}
    except Exception as exc:
        raise ConfigError(f"Could not read {path}: {exc}") from exc

    # ── Extract fields ─────────────────────────────────────────────────────────
    proj = data.get("project", {}) or {}
    ws   = data.get("workspace", {}) or {}
    f    = data.get("files", {}) or {}
    res  = data.get("results", {}) or {}
    ep   = data.get("ep_flags", {}) or {}
    rc   = data.get("rc_flags", {}) or {}

    def _must(section: dict, key: str, label: str) -> str:
        val = section.get(key, "")
        if not val:
            raise ConfigError(
                f"Missing required config key: '{label}'. Run  qa-agent init  to create a valid config."
            )
        return str(val)

    cfg = QAConfig(
        project_name             = proj.get("name", ""),
        project_root             = _must(proj, "root", "project.root"),
        results_dir              = _must(ws, "results_dir", "workspace.results_dir"),
        source_file              = f.get("source_file", ""),
        basic_regression_script  = f.get("basic_regression_script", ""),
        slurm_regression_script  = f.get("slurm_regression_script", ""),
        slurm_run_script         = f.get("slurm_run_script", ""),
        slurm_config             = f.get("slurm_config", ""),
        debug_script             = f.get("debug_script", ""),
        basic_output             = res.get("basic_output", "results.doc"),
        slurm_output             = res.get("slurm_output", "results_new.doc"),
        ep_fixed_flags           = ep.get("fixed", list(DEFAULT_EP_FIXED_FLAGS)),
        rc_fixed_flags           = rc.get("fixed", list(DEFAULT_RC_FIXED_FLAGS)),
    )
    cfg._config_path = path
    return cfg


# ── Validate ───────────────────────────────────────────────────────────────────

def validate_config(cfg: QAConfig) -> list[str]:
    """Return a list of human-readable error strings for missing/invalid paths.

    Empty list = all paths valid.
    """
    errors: list[str] = []

    root = Path(cfg.project_root)
    if not root.exists():
        errors.append(f"project.root not found: {root}")
        return errors   # no point checking sub-paths

    checks = [
        ("workspace.results_dir",            cfg.results_dir_path),
        ("files.source_file",                cfg.source_file_path),
        ("files.basic_regression_script",    cfg.basic_regression_script_path),
        ("files.slurm_regression_script",    cfg.slurm_regression_script_path),
        ("files.slurm_run_script",           cfg.slurm_run_script_path),
        ("files.slurm_config",              cfg.slurm_config_path),
        ("files.debug_script",              cfg.debug_script_path),
    ]
    for label, path in checks:
        if path is not None and not path.exists():
            errors.append(f"{label} not found: {path}")
    return errors


# ── Save ───────────────────────────────────────────────────────────────────────

_YAML_HEADER = """\
# qa-agent project config
# Generated by `qa-agent init`  |  Edit with `qa-agent config`
#
"""

def save_config(cfg: QAConfig, path: Path) -> None:
    """Serialise QAConfig to YAML at the given path."""
    _require_yaml()

    data = {
        "project": {
            "name": cfg.project_name,
            "root": cfg.project_root,
        },
        "workspace": {
            "results_dir": cfg.results_dir,
        },
        "files": {
            "source_file":               cfg.source_file,
            "basic_regression_script":   cfg.basic_regression_script,
            "slurm_regression_script":   cfg.slurm_regression_script,
            "slurm_run_script":          cfg.slurm_run_script,
            "slurm_config":              cfg.slurm_config,
            "debug_script":              cfg.debug_script,
        },
        "results": {
            "basic_output": cfg.basic_output,
            "slurm_output": cfg.slurm_output,
        },
        "ep_flags": {
            "fixed": cfg.ep_fixed_flags,
        },
        "rc_flags": {
            "fixed": cfg.rc_fixed_flags,
        },
    }

    yaml_body = _yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
    path.write_text(_YAML_HEADER + yaml_body, encoding="utf-8")
