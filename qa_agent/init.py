"""qa_agent/init.py

Interactive `qa-agent init` wizard.

Walks the user through:
  1. Detecting / confirming the project root (via RTL directory heuristic)
  2. Confirming the results directory
  3. Locating each required file (source .csh, regression scripts, debug .pl, etc.)
  4. Reviewing EP / RC fixed flag templates
  5. Saving qa-agent.yaml to the project root
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from qa_agent.config import (
    QAConfig, CONFIG_FILENAME,
    DEFAULT_EP_FIXED_FLAGS, DEFAULT_RC_FIXED_FLAGS,
    save_config, find_config, load_config,
)
from qa_agent.output import (
    bold, cyan, dim, green, red, yellow, rule,
    print_header, arrow_select, confirm,
)

# ── Small UX helpers ──────────────────────────────────────────────────────────

def _section(title: str) -> None:
    print()
    print(rule())
    print(f"  {cyan(title)}")
    print(rule())
    print()


def _ok(label: str, value: str, note: str = "") -> None:
    note_str = f"  {dim(note)}" if note else ""
    print(f"  {green('✓')}  {dim(label+':')}  {bold(value)}{note_str}")


def _warn(label: str, value: str, note: str = "") -> None:
    note_str = f"  {dim(note)}" if note else ""
    print(f"  {yellow('⚠')}  {dim(label+':')}  {yellow(value)}{note_str}")


def _prompt(prompt: str, default: str = "") -> str:
    """Read a line of text; return default on empty input."""
    default_hint = f" [{dim(default)}]" if default else ""
    try:
        val = input(f"  {cyan('?')}  {prompt}{default_hint}: ").strip()
    except EOFError:
        val = ""
    return val if val else default


# ── Directory / file search helpers ──────────────────────────────────────────

def _find_rtl_parent(start: Path) -> Optional[Path]:
    """Walk up from start; if any directory named RTL (case-insensitive) is found,
    return its parent. Returns None if not found.
    """
    current = start.resolve()
    while True:
        # Check children of current for RTL dir
        try:
            for child in current.iterdir():
                if child.is_dir() and child.name.upper() == "RTL":
                    return current
        except PermissionError:
            pass
        parent = current.parent
        if parent == current:
            return None
        current = parent


def _walk_find(root: Path, name: str, max_depth: int = 8) -> list[Path]:
    """Find files/dirs matching `name` under `root`, up to max_depth levels deep."""
    matches: list[Path] = []
    _walk_collect(root, name.lower(), 0, max_depth, matches)
    return matches


def _walk_collect(path: Path, name_lower: str, depth: int, max_depth: int, out: list[Path]) -> None:
    if depth > max_depth:
        return
    try:
        for child in sorted(path.iterdir()):
            if child.name.lower() == name_lower:
                out.append(child)
            if child.is_dir() and not child.name.startswith("."):
                _walk_collect(child, name_lower, depth + 1, max_depth, out)
    except PermissionError:
        pass


def _walk_glob(root: Path, pattern: str, max_depth: int = 8) -> list[Path]:
    """Glob from root up to max_depth levels, returning sorted unique results."""
    results: list[Path] = []
    seen: set[Path] = set()
    _glob_collect(root, pattern, 0, max_depth, results, seen)
    return results


def _glob_collect(path: Path, pattern: str, depth: int, max_depth: int,
                   out: list[Path], seen: set[Path]) -> None:
    if depth > max_depth:
        return
    try:
        for child in sorted(path.glob(pattern)):
            if child not in seen:
                out.append(child)
                seen.add(child)
        for child in sorted(path.iterdir()):
            if child.is_dir() and not child.name.startswith("."):
                _glob_collect(child, pattern, depth + 1, max_depth, out, seen)
    except PermissionError:
        pass


def _parent_dirs(start: Path) -> list[Path]:
    """Return all parent directories from start upward, stopping at fs root."""
    dirs: list[Path] = []
    current = start.resolve()
    while True:
        parent = current.parent
        if parent == current:
            break
        dirs.append(parent)
        current = parent
    return dirs


# ── Step helpers ──────────────────────────────────────────────────────────────

def _select_directory(candidates: list[Path], prompt: str, allow_manual: bool = True) -> Optional[Path]:
    """Show arrow_select for a list of directory candidates.

    Returns the chosen Path, or None if user skips.
    Appends a [Enter manually] option when allow_manual=True.
    """
    options = [(str(p), str(p)) for p in candidates]
    if allow_manual:
        options.append(("[Enter path manually]", "__manual__"))

    idx = arrow_select(prompt, options)
    tag = options[idx][1]

    if tag == "__manual__":
        raw = _prompt("Enter full path")
        if not raw:
            return None
        p = Path(raw).expanduser().resolve()
        if not p.exists():
            print(f"  {yellow('⚠')}  Path does not exist: {p}")
        return p

    return candidates[idx]


def _select_file(
    candidates: list[Path],
    label: str,
    root: Path,
    allow_none: bool = False,
) -> Optional[Path]:
    """Arrow-select from file candidates; offer [Enter manually] and optionally [Skip]."""
    if not candidates and allow_none:
        print(f"  {yellow('⚠')}  No {label} found. Skipping.")
        return None

    options: list[tuple[str, str]] = []
    for p in candidates:
        try:
            rel = p.relative_to(root)
            label_str = str(rel)
        except ValueError:
            label_str = str(p)
        options.append((label_str, str(p)))

    options.append(("[Enter path manually]", "__manual__"))
    if allow_none:
        options.append(("[Skip this file]", "__skip__"))

    idx = arrow_select(f"Select {label}:", options)
    tag = options[idx][1]

    if tag == "__skip__":
        return None
    if tag == "__manual__":
        raw = _prompt(f"Enter full path to {label}")
        if not raw:
            return None
        return Path(raw).expanduser().resolve()

    return Path(tag)


# ── Step 1: Project Root ───────────────────────────────────────────────────────

def _step_root(explicit_root: Optional[str]) -> Path:
    _section("Step 1 of 8  —  Project Root")

    if explicit_root:
        root = Path(explicit_root).expanduser().resolve()
        print(f"  Using provided root: {bold(str(root))}")
        return root

    # Auto-detect via RTL dir heuristic
    rtl_parent = _find_rtl_parent(Path.cwd())
    candidate = rtl_parent or Path.cwd().resolve()

    print(f"  Scanning for project root{dim('  (looking for RTL/ directory)…')}")
    print()

    # Ask: is this it?
    answer = arrow_select(
        f"Is  {bold(str(candidate))}  the project root?",
        [("Yes, that's the project root", "yes"),
         ("No, let me choose from parent directories", "parents")],
    )

    if answer == 0:
        _ok("Project root", str(candidate))
        return candidate

    # Show all parent dirs
    parents = _parent_dirs(Path.cwd())
    if not parents:
        print(f"  {yellow('⚠')}  No parent directories available. Using CWD.")
        return Path.cwd().resolve()

    chosen = _select_directory(parents, "Select the project root directory:")
    if chosen is None:
        chosen = Path.cwd().resolve()
    _ok("Project root", str(chosen))
    return chosen


# ── Step 2: Results Directory ─────────────────────────────────────────────────

def _step_results_dir(root: Path) -> str:
    _section("Step 2 of 8  —  Results Directory")
    print(f"  {dim('Searching for results/ directory under project root…')}")
    print()

    # Find all dirs named "results" under root
    result_dirs = _walk_find(root, "results", max_depth=8)
    result_dirs = [p for p in result_dirs if p.is_dir()]

    # Prefer deepest match to a "run/results" pattern
    result_dirs.sort(key=lambda p: ("run/results" in p.as_posix().lower(), len(p.parts)), reverse=True)

    if result_dirs:
        chosen = _select_directory(result_dirs, "Select the regression results directory:")
    else:
        print(f"  {yellow('⚠')}  No results/ directory found under {root}.")
        chosen = None

    if chosen is None:
        raw = _prompt("Enter results directory path (relative to project root or absolute)",
                       default="verif/AVERY/run/results")
        chosen = Path(raw) if raw else Path("verif/AVERY/run/results")

    # Store relative to root if possible
    try:
        rel = chosen.resolve().relative_to(root)
        display = str(rel)
    except ValueError:
        display = str(chosen)

    _ok("Results dir", display)
    return display


# ── Step 3: Source File (.csh) ────────────────────────────────────────────────

def _step_source_file(root: Path) -> str:
    _section("Step 3 of 8  —  Environment Source File  (.csh)")
    print(f"  {dim('This is sourced to set up the simulator environment before running regressions.')}")
    print()

    default_name = "sourcefile_2025_3.csh"
    name = _prompt("Source file name (or leave blank to search all .csh files)", default=default_name)

    if name:
        candidates = _walk_find(root, name, max_depth=6)
        candidates = [p for p in candidates if p.is_file()]
    else:
        candidates = _walk_glob(root, "*.csh", max_depth=6)

    if not candidates:
        print(f"  {yellow('⚠')}  No .csh file matching '{name}' found under {root}.")

    chosen = _select_file(candidates, "source .csh file", root, allow_none=True)

    if chosen is None:
        _warn("source_file", "(none)", "source env will not be set — debug commands may fail")
        return ""

    try:
        rel = chosen.resolve().relative_to(root)
        display = str(rel)
    except ValueError:
        display = str(chosen)

    _ok("Source file", display)
    return display


# ── Step 4: Basic Regression Script (.py) ────────────────────────────────────

def _step_basic_script(root: Path) -> str:
    _section("Step 4 of 8  —  Basic Regression Script  (.py)")
    print(f"  {dim('Python script run for non-Slurm regressions.')}")
    print()

    default_name = "regression_8B_16B_questa.py"
    name = _prompt("Filename (or blank to search for regression_*.py)", default=default_name)

    if name:
        candidates = _walk_find(root, name, max_depth=6)
    else:
        candidates = _walk_glob(root, "regression_*.py", max_depth=6)
        # Exclude slurm scripts
        candidates = [p for p in candidates if "slurm" not in p.name.lower()]
    candidates = [p for p in candidates if p.is_file()]

    if not candidates:
        print(f"  {yellow('⚠')}  No matching file found under {root}.")

    chosen = _select_file(candidates, "basic regression script", root, allow_none=True)

    if chosen is None:
        _warn("basic_regression_script", "(none)")
        return ""

    try:
        rel = chosen.resolve().relative_to(root)
        display = str(rel)
    except ValueError:
        display = str(chosen)

    _ok("Basic regression script", display)
    return display


# ── Step 5: Slurm Files ───────────────────────────────────────────────────────

def _step_slurm_files(root: Path) -> tuple[str, str, str]:
    _section("Step 5 of 8  —  Slurm Files  (regression script + launcher + config)")
    print(f"  {dim('Required for: qa-agent regression --slurm')}")
    print()

    # Slurm regression script
    def _find_one(description: str, default_name: str, glob_pat: str,
                   extra_filter=None, allow_none: bool = True) -> str:
        print(f"  {bold(description)}")
        name = _prompt("Filename", default=default_name)
        cands = _walk_find(root, name, max_depth=6) if name else _walk_glob(root, glob_pat, max_depth=6)
        cands = [p for p in cands if p.is_file()]
        if extra_filter:
            cands = [p for p in cands if extra_filter(p)]
        if not cands:
            print(f"  {yellow('⚠')}  No matching file found.")
        c = _select_file(cands, description, root, allow_none=allow_none)
        if c is None:
            _warn(description, "(none)")
            return ""
        try:
            rel = c.resolve().relative_to(root)
            d = str(rel)
        except ValueError:
            d = str(c)
        _ok(description, d)
        print()
        return d

    slurm_script = _find_one(
        "Slurm regression script", "regression_slurm_questa_2025.py",
        "regression_slurm_*.py",
        extra_filter=lambda p: "slurm" in p.name.lower(),
    )
    slurm_run = _find_one(
        "Slurm launcher script", "run_questa.sh", "run_questa*.sh",
    )
    slurm_cfg = _find_one(
        "Slurm config file", "config.txt", "config.txt",
    )

    return slurm_script, slurm_run, slurm_cfg


# ── Step 6: Debug Script (.pl) ────────────────────────────────────────────────

def _step_debug_script(root: Path) -> str:
    _section("Step 6 of 8  —  Debug Script  (.pl)")
    print(f"  {dim('Perl script invoked per failure during: qa-agent analyse')}")
    print()

    default_name = "run_apci_2025.pl"
    name = _prompt("Filename (or blank to search all .pl files)", default=default_name)

    if name:
        candidates = _walk_find(root, name, max_depth=6)
    else:
        candidates = _walk_glob(root, "*.pl", max_depth=6)
    candidates = [p for p in candidates if p.is_file()]

    if not candidates:
        print(f"  {yellow('⚠')}  No .pl file found under {root}.")

    chosen = _select_file(candidates, "debug .pl script", root, allow_none=True)

    if chosen is None:
        _warn("debug_script", "(none)")
        return ""

    try:
        rel = chosen.resolve().relative_to(root)
        display = str(rel)
    except ValueError:
        display = str(chosen)

    _ok("Debug script", display)
    return display


# ── Step 7: Results filenames ─────────────────────────────────────────────────

def _step_result_filenames() -> tuple[str, str]:
    _section("Step 7 of 8  —  Regression Output Filenames")
    print(f"  {dim('Filenames that the regression scripts produce as output.')}")
    print()

    basic = _prompt("Basic regression output file", default="results.doc")
    slurm = _prompt("Slurm regression output file", default="results_new.doc")

    _ok("Basic output", basic or "results.doc")
    _ok("Slurm output", slurm or "results_new.doc")
    return basic or "results.doc", slurm or "results_new.doc"


# ── Step 8: EP / RC Flag Templates ───────────────────────────────────────────

def _step_flags() -> tuple[list[str], list[str]]:
    _section("Step 8 of 8  —  EP / RC Fixed Simulator Flag Templates")
    print(
        f"  {dim('These flags are appended to every debug command during qa-agent analyse.')}\n"
        f"  {dim('Variable parts (NUM_LANES, gen, flit_mode, PIPE_BYTEWIDTH) are computed')}\n"
        f"  {dim('automatically from the test result line.')}\n"
    )

    print(f"  {bold('Current EP fixed flags')} {dim('(non-variable extras):')}:")
    for f in DEFAULT_EP_FIXED_FLAGS:
        print(f"    {dim('•')} {f}")
    print()
    print(f"  {bold('Current RC fixed flags')} {dim('(non-variable extras):')}:")
    for f in DEFAULT_RC_FIXED_FLAGS:
        print(f"    {dim('•')} {f}")
    print()

    keep = arrow_select(
        "Keep these default flag templates?",
        [("Yes, keep defaults", "yes"), ("No, I want to edit them", "edit")],
    )

    if keep == 0:
        _ok("EP flags", "(defaults kept)")
        _ok("RC flags", "(defaults kept)")
        return list(DEFAULT_EP_FIXED_FLAGS), list(DEFAULT_RC_FIXED_FLAGS)

    def _edit_flags(label: str, current: list[str]) -> list[str]:
        print(f"\n  {bold(f'Editing {label} fixed flags')}")
        print(f"  {dim('Current flags (arrow-select to toggle remove, then confirm):')}")
        flags = list(current)

        while True:
            options = [(f"  {f}", f) for f in flags]
            options += [("[+ Add a flag]", "__add__"), ("[✓ Done]", "__done__")]
            idx = arrow_select(f"  {label} flags — select to remove or add:", options)
            chosen_tag = options[idx][1]
            if chosen_tag == "__done__":
                break
            elif chosen_tag == "__add__":
                new_flag = _prompt("Enter new flag (e.g. +define+MY_FLAG)")
                if new_flag:
                    flags.append(new_flag)
                    print(f"  {green('✓')}  Added: {new_flag}")
            else:
                # Toggle remove
                remove = confirm(f"Remove '{chosen_tag}'?", default=False)
                if remove:
                    flags.remove(chosen_tag)
                    print(f"  {yellow('⚠')}  Removed: {chosen_tag}")
        return flags

    ep_flags = _edit_flags("EP", DEFAULT_EP_FIXED_FLAGS)
    rc_flags = _edit_flags("RC", DEFAULT_RC_FIXED_FLAGS)
    return ep_flags, rc_flags


# ── Summary table ─────────────────────────────────────────────────────────────

def _print_summary(cfg: QAConfig) -> None:
    print()
    print(rule())
    print(f"  {cyan('Config Summary')}")
    print(rule())
    print()

    rows = [
        ("Project name",          cfg.project_name),
        ("Project root",          cfg.project_root),
        ("Results directory",     cfg.results_dir),
        ("Source file (.csh)",    cfg.source_file or dim("(none)")),
        ("Basic reg. script",     cfg.basic_regression_script or dim("(none)")),
        ("Slurm reg. script",     cfg.slurm_regression_script or dim("(none)")),
        ("Slurm launcher",        cfg.slurm_run_script or dim("(none)")),
        ("Slurm config",          cfg.slurm_config or dim("(none)")),
        ("Debug script (.pl)",    cfg.debug_script or dim("(none)")),
        ("Basic output file",     cfg.basic_output),
        ("Slurm output file",     cfg.slurm_output),
    ]

    max_lbl = max(len(r[0]) for r in rows)
    for label, value in rows:
        padding = " " * (max_lbl - len(label))
        root_p = Path(cfg.project_root) if cfg.project_root else None
        # Detect missing paths
        if value and not value.startswith("\x1b"):  # not already coloured
            try:
                p = cfg.resolve(value) if root_p else Path(value)
                status = green("✓") if p.exists() else yellow("?")
            except Exception:
                status = dim("·")
        else:
            status = dim("·")
        print(f"  {status}  {bold(label)}{padding}  {value}")

    print()
    print(f"  {dim('EP fixed flags:')}  {', '.join(cfg.ep_fixed_flags)}")
    print(f"  {dim('RC fixed flags:')}  {', '.join(cfg.rc_fixed_flags)}")
    print()


# ── Public entry-point ────────────────────────────────────────────────────────

def run(root: Optional[str] = None, force: bool = False, use_defaults: bool = False, verbose: bool = False) -> None:
    print_header("init", "Project Config Wizard")

    # ── --use_defaults: fully automated path ───────────────────────────────────
    if use_defaults:
        print(f"  {dim('--use-defaults mode: auto-detecting all paths, no prompts.')}\n")

        # 1. Project root
        rtl_parent = _find_rtl_parent(Path.cwd())
        project_root = Path(root).expanduser().resolve() if root else (rtl_parent or Path.cwd().resolve())
        _ok("Project root", str(project_root))

        # 2. Results dir — look for run/results pattern
        result_dirs = [p for p in _walk_find(project_root, "results", max_depth=8) if p.is_dir()]
        result_dirs.sort(key=lambda p: ("run/results" in p.as_posix().lower(), len(p.parts)), reverse=True)
        if result_dirs:
            try:
                results_dir = str(result_dirs[0].resolve().relative_to(project_root))
            except ValueError:
                results_dir = str(result_dirs[0])
        else:
            results_dir = "verif/AVERY/run/results"
        _ok("Results dir", results_dir)

        # 3. Source file
        src_cands = _walk_find(project_root, "sourcefile_2025_3.csh", max_depth=6)
        src_cands = [p for p in src_cands if p.is_file()]
        if src_cands:
            try:
                source_file = str(src_cands[0].resolve().relative_to(project_root))
            except ValueError:
                source_file = str(src_cands[0])
            _ok("Source file", source_file)
        else:
            source_file = ""
            _warn("Source file", "(not found)")

        # 4. Basic regression script
        basic_cands = _walk_find(project_root, "regression_8B_16B_questa.py", max_depth=6)
        basic_cands = [p for p in basic_cands if p.is_file()]
        if not basic_cands:
            basic_cands = [p for p in _walk_glob(project_root, "regression_*.py", max_depth=6)
                           if p.is_file() and "slurm" not in p.name.lower()]
        if basic_cands:
            try:
                basic_script = str(basic_cands[0].resolve().relative_to(project_root))
            except ValueError:
                basic_script = str(basic_cands[0])
            _ok("Basic regression script", basic_script)
        else:
            basic_script = ""
            _warn("Basic regression script", "(not found)")

        # 5. Slurm files
        def _auto_find(name: str, glob: str, extra_filter=None) -> str:
            cands = _walk_find(project_root, name, max_depth=6)
            if not cands:
                cands = _walk_glob(project_root, glob, max_depth=6)
            cands = [p for p in cands if p.is_file()]
            if extra_filter:
                cands = [p for p in cands if extra_filter(p)]
            if not cands:
                return ""
            try:
                return str(cands[0].resolve().relative_to(project_root))
            except ValueError:
                return str(cands[0])

        slurm_script = _auto_find("regression_slurm_questa_2025.py", "regression_slurm_*.py",
                                   lambda p: "slurm" in p.name.lower())
        slurm_run = _auto_find("run_questa.sh", "run_questa*.sh")
        slurm_cfg = _auto_find("config.txt", "config.txt")
        _ok("Slurm regression script", slurm_script or dim("(not found)"))
        _ok("Slurm run script",        slurm_run    or dim("(not found)"))
        _ok("Slurm config",            slurm_cfg    or dim("(not found)"))

        # 6. Debug script
        debug_cands = _walk_find(project_root, "run_apci_2025.pl", max_depth=6)
        debug_cands = [p for p in debug_cands if p.is_file()]
        if debug_cands:
            try:
                debug_script = str(debug_cands[0].resolve().relative_to(project_root))
            except ValueError:
                debug_script = str(debug_cands[0])
            _ok("Debug script", debug_script)
        else:
            debug_script = ""
            _warn("Debug script", "(not found)")

        cfg = QAConfig(
            project_name             = project_root.name,
            project_root             = str(project_root),
            results_dir              = results_dir,
            source_file              = source_file,
            basic_regression_script  = basic_script,
            slurm_regression_script  = slurm_script,
            slurm_run_script         = slurm_run,
            slurm_config             = slurm_cfg,
            debug_script             = debug_script,
            basic_output             = "results.doc",
            slurm_output             = "results_new.doc",
            ep_fixed_flags           = list(DEFAULT_EP_FIXED_FLAGS),
            rc_fixed_flags           = list(DEFAULT_RC_FIXED_FLAGS),
        )

        save_path = project_root / CONFIG_FILENAME
        if save_path.exists() and not force:
            print(f"\n  {yellow('⚠')}  Config already exists: {bold(str(save_path))}")
            print(f"  {dim('Use --force to overwrite.')}\n")
            return

        try:
            save_config(cfg, save_path)
        except Exception as exc:
            print(f"\n  {red('✖')}  Failed to save: {exc}\n")
            return

        print()
        print(f"  {green('✓')}  Config saved:  {bold(str(save_path))}")
        print(f"  {dim('Edit anytime with:')}  qa-agent config")
        print()
        return

    # Check for existing config
    existing = find_config(Path.cwd())
    if existing and not force:
        print(f"  {yellow('⚠')}  Config already exists: {bold(str(existing))}")
        print()
        overwrite = arrow_select(
            "What would you like to do?",
            [("Edit existing config  (opens vim)", "vim"),
             ("Recreate config from scratch", "recreate"),
             ("Cancel", "cancel")],
        )
        if overwrite == 2:  # cancel
            print(f"\n  {dim('Cancelled. Existing config unchanged.')}\n")
            return
        elif overwrite == 0:  # open vim
            _open_vim(existing)
            return
        # else: recreate (fall through)

    # ── Run wizard ────────────────────────────────────────────────────────────
    project_root   = _step_root(root)
    results_dir    = _step_results_dir(project_root)
    source_file    = _step_source_file(project_root)
    basic_script   = _step_basic_script(project_root)
    slurm_script, slurm_run, slurm_cfg = _step_slurm_files(project_root)
    debug_script   = _step_debug_script(project_root)
    basic_out, slurm_out = _step_result_filenames()
    ep_flags, rc_flags   = _step_flags()

    cfg = QAConfig(
        project_name             = project_root.name,
        project_root             = str(project_root),
        results_dir              = results_dir,
        source_file              = source_file,
        basic_regression_script  = basic_script,
        slurm_regression_script  = slurm_script,
        slurm_run_script         = slurm_run,
        slurm_config             = slurm_cfg,
        debug_script             = debug_script,
        basic_output             = basic_out,
        slurm_output             = slurm_out,
        ep_fixed_flags           = ep_flags,
        rc_fixed_flags           = rc_flags,
    )

    _print_summary(cfg)

    save_path = project_root / CONFIG_FILENAME
    save = confirm(f"Save config to  {bold(str(save_path))}?", default=True)

    if not save:
        print(f"\n  {yellow('⚠')}  Config not saved.\n")
        return

    try:
        save_config(cfg, save_path)
    except Exception as exc:
        print(f"\n  {red('✖')}  Failed to save config: {exc}\n")
        return

    print()
    print(f"  {green('✓')}  Config saved:  {bold(str(save_path))}")
    print(f"  {dim('Edit anytime with:')}  qa-agent config")
    print()


# ── Config command (open vim) ─────────────────────────────────────────────────

def _open_vim(path: Path) -> None:
    """Open the config file in vim."""
    import subprocess
    editor = os.environ.get("EDITOR", "vim")
    try:
        subprocess.run([editor, str(path)])
    except FileNotFoundError:
        print(f"  {red('✖')}  Editor not found: {editor}")
        print(f"  {dim('Tip:')}  Set the EDITOR environment variable to your preferred editor.")


def open_config(verbose: bool = False) -> None:
    """Entry-point for `qa-agent config` command — opens yaml in vim."""
    config_path = find_config(Path.cwd())
    if config_path is None:
        print()
        print(f"  {red('✖')}  No {CONFIG_FILENAME} found.")
        print(f"  {dim('Run')}  {bold('qa-agent init')}  {dim('to create one.')}")
        print()
        return
    print()
    print(f"  {cyan('ℹ')}  Opening: {bold(str(config_path))}")
    print()
    _open_vim(config_path)
