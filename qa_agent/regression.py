"""qa_agent/regression.py

Automate the full regression run lifecycle:
  1. Source a .csh environment file
  2. Locate filelist.txt
  3. Mode gate: basic or slurm
  4. Basic: locate + run the regression Python script; verify results.doc
  5. Slurm: locate config.txt + run_questa.sh + slurm script; verify results_new.doc
  6. Print a summary block
"""

from __future__ import annotations

import os
import subprocess
import sys
import termios
import tty
from datetime import datetime
from pathlib import Path
from typing import Optional

from qa_agent.errors import ConfigError, QAAgentError
from qa_agent.output import (
    bold, cyan, dim, green, red, rule, yellow,
    print_regression_banner, Spinner,
)

# ── Package / repo root ────────────────────────────────────────────────────────

PACKAGE_DIR: Path = Path(__file__).resolve().parent.parent  # repo root


# ── Interactive arrow-key selector ────────────────────────────────────────────

def _arrow_select(prompt: str, options: list[tuple[str, str]]) -> int:
    """Arrow-key interactive selector (TTY only).

    options: list of (label, tag) tuples — tag shown in brackets.
    Returns the chosen index.
    Falls back to index 0 if not a TTY.
    """
    if not sys.stdin.isatty() or not options:
        return 0

    selected = 0
    n = len(options)

    print(f"\n  {prompt}\n")

    def _render(sel: int) -> None:
        sys.stdout.write(f"\033[{n}A")
        for i, (label, tag) in enumerate(options):
            prefix = f"  {cyan('❯')}  " if i == sel else "     "
            tag_str = dim(f"[{tag}]")
            sys.stdout.write(f"\r{prefix}{bold(label) if i == sel else label}  {tag_str}\n")
        sys.stdout.flush()

    # Initial render
    for i, (label, tag) in enumerate(options):
        prefix = f"  {cyan('❯')}  " if i == 0 else "     "
        tag_str = dim(f"[{tag}]")
        print(f"{prefix}{bold(label) if i == 0 else label}  {tag_str}")

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while True:
            ch = sys.stdin.read(1)
            if ch in ("\r", "\n"):
                break
            elif ch == "\x1b":
                seq = sys.stdin.read(2)
                if seq == "[A":    # up
                    selected = (selected - 1) % n
                elif seq == "[B":  # down
                    selected = (selected + 1) % n
                _render(selected)
            elif ch == "\x03":     # Ctrl-C
                raise KeyboardInterrupt
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    print()
    return selected


# ── Step 1: .csh file discovery & selection ───────────────────────────────────

def _discover_csh_files() -> list[tuple[Path, str]]:
    """Return (path, tag) pairs: qa-agent bundled first, then cwd."""
    results: list[tuple[Path, str]] = []
    seen: set[Path] = set()

    # Bundled default
    bundled = PACKAGE_DIR / "sourcefile_2025_3.csh"
    if bundled.exists() and bundled not in seen:
        results.append((bundled, "qa-agent"))
        seen.add(bundled)

    # Any other .csh in the package dir itself
    for p in sorted(PACKAGE_DIR.glob("*.csh")):
        if p not in seen:
            results.append((p, "qa-agent"))
            seen.add(p)

    # .csh files in cwd
    for p in sorted(Path.cwd().glob("*.csh")):
        if p not in seen:
            results.append((p, "cwd"))
            seen.add(p)

    return results


def _select_source_file() -> Optional[Path]:
    """Present selector or auto-select. Returns chosen Path or None."""
    cwd_csh = sorted(Path.cwd().glob("*.csh"))
    candidates = _discover_csh_files()

    if not candidates:
        print(f"\n  {yellow('⚠')}  No .csh source files found — environment will not be pre-configured.")
        return None

    if not cwd_csh:
        # No cwd files — auto-select qa-agent default
        path, tag = candidates[0]
        print(f"  {cyan('ℹ')}  No .csh files found in cwd — using qa-agent default: {bold(path.name)}")
        return path

    # Interactive selector
    options = [(p.name, tag) for p, tag in candidates]
    idx = _arrow_select("🔧 Select source file to use:", options)
    chosen_path = candidates[idx][0]
    print(f"  {green('✓')}  Using source file: {bold(chosen_path.name)}")
    return chosen_path


# ── Step 2: filelist.txt ──────────────────────────────────────────────────────

def _locate_filelist() -> Optional[Path]:
    """Return path to filelist.txt; prompt if not in cwd. Returns None on decline."""
    cwd_file = Path.cwd() / "filelist.txt"
    if cwd_file.exists():
        print(f"  {green('✓')}  Found filelist.txt in cwd")
        return cwd_file

    # Not in cwd — prompt
    bundled = PACKAGE_DIR / "filelist.txt"
    if bundled.exists():
        sys.stdout.write(
            f"  {yellow('⚠')}  No filelist.txt found in current directory."
            f" Use the one bundled with qa-agent? [Y/n] "
        )
        sys.stdout.flush()
        answer = input().strip().lower()
        if answer in ("", "y", "yes"):
            print(f"  {green('✓')}  Using qa-agent default filelist.txt")
            return bundled
        else:
            print(f"  {cyan('ℹ')}  Please add a filelist.txt to the current directory and re-run.")
            return None
    else:
        print(
            f"  {red('✖')}  No filelist.txt found in cwd and no bundled default available.\n"
            f"  Please add a filelist.txt to the current directory and re-run."
        )
        return None


# ── Step 4a: Basic regression script discovery & selection ────────────────────

def _discover_regression_py(slurm: bool = False) -> list[tuple[Path, str]]:
    """Find regression .py scripts. Returns (path, tag) pairs."""
    results: list[tuple[Path, str]] = []
    seen: set[Path] = set()

    if slurm:
        # Bundled slurm script
        bundled = PACKAGE_DIR / "regression_slurm_questa_2025.py"
        if bundled.exists() and bundled not in seen:
            results.append((bundled, "qa-agent"))
            seen.add(bundled)
        # cwd slurm scripts
        for p in sorted(Path.cwd().glob("*.py")):
            if (
                "regression" in p.name.lower()
                and "slurm" in p.name.lower()
                and not p.name.startswith(".")
                and p not in seen
            ):
                results.append((p, "cwd"))
                seen.add(p)
    else:
        # Bundled basic script
        bundled = PACKAGE_DIR / "regression_8B_16B_questa.py"
        if bundled.exists() and bundled not in seen:
            results.append((bundled, "qa-agent"))
            seen.add(bundled)
        # cwd regression scripts
        for p in sorted(Path.cwd().glob("*.py")):
            if (
                "regression" in p.name.lower()
                and not p.name.startswith(".")
                and p not in seen
            ):
                results.append((p, "cwd"))
                seen.add(p)

    return results


def _select_regression_py(slurm: bool = False) -> Optional[Path]:
    """Interactive or auto-select regression script. Returns chosen Path."""
    candidates = _discover_regression_py(slurm=slurm)
    cwd_scripts = [p for p, tag in candidates if tag == "cwd"]

    if not candidates:
        raise ConfigError(
            "No regression script available.\n"
            "  Add a regression*.py script to the current directory or ensure the\n"
            "  qa-agent bundled script is present."
        )

    if not cwd_scripts:
        # No cwd scripts — auto-select bundled default
        path, _ = candidates[0]
        label = "slurm" if slurm else "basic"
        print(f"  {cyan('ℹ')}  No regression scripts found in cwd — using qa-agent default: {bold(path.name)}")
        return path

    # Interactive selector
    options = [(p.name, tag) for p, tag in candidates]
    idx = _arrow_select("🐍 Select regression script:", options)
    chosen_path = candidates[idx][0]
    print(f"  {green('✓')}  Using regression script: {bold(chosen_path.name)}")
    return chosen_path


# ── Step 5a: config.txt (slurm only) ─────────────────────────────────────────

def _locate_config() -> Optional[Path]:
    """Return path to config.txt for slurm mode; prompt if not in cwd."""
    cwd_file = Path.cwd() / "config.txt"
    if cwd_file.exists():
        print(f"  {green('✓')}  Found config.txt in cwd")
        return cwd_file

    bundled = PACKAGE_DIR / "config.txt"
    if bundled.exists():
        sys.stdout.write(
            f"  {yellow('⚠')}  No config.txt found in current directory."
            f" Use the one bundled with qa-agent? [Y/n] "
        )
        sys.stdout.flush()
        answer = input().strip().lower()
        if answer in ("", "y", "yes"):
            print(f"  {green('✓')}  Using qa-agent default config.txt")
            return bundled
        else:
            print(f"  {cyan('ℹ')}  Please add a config.txt to the current directory and re-run.")
            return None
    else:
        print(
            f"  {red('✖')}  No config.txt found in cwd and no bundled default available.\n"
            f"  Please add a config.txt to the current directory and re-run."
        )
        return None


# ── Step 5b: run_questa.sh (slurm only) ───────────────────────────────────────

def _locate_run_questa() -> Optional[Path]:
    """Return path to run_questa.sh; interactive selector if cwd copy exists."""
    cwd_file = Path.cwd() / "run_questa.sh"
    bundled = PACKAGE_DIR / "run_questa.sh"

    candidates: list[tuple[Path, str]] = []

    if bundled.exists():
        candidates.append((bundled, "qa-agent"))
    if cwd_file.exists():
        candidates.append((cwd_file, "cwd"))

    if not candidates:
        raise ConfigError(
            "No run_questa.sh found.\n"
            "  Add run_questa.sh to the current directory or ensure the\n"
            "  qa-agent bundled script is present."
        )

    if not cwd_file.exists():
        # No cwd copy — auto-select bundled
        path, _ = candidates[0]
        print(f"  {cyan('ℹ')}  No run_questa.sh found in cwd — using qa-agent default: {bold(path.name)}")
        return path

    # Both exist — interactive selector
    options = [(p.name, tag) for p, tag in candidates]
    idx = _arrow_select("🚀 Select run_questa.sh to use:", options)
    chosen_path = candidates[idx][0]
    print(f"  {green('✓')}  Using: {bold(chosen_path.name)}")
    return chosen_path


# ── Build command ──────────────────────────────────────────────────────────────

def _build_command(
    *,
    slurm: bool,
    regression_script: Path,
    filelist: Path,
    config: Optional[Path] = None,
    run_questa: Optional[Path] = None,
) -> list[str]:
    """Assemble the final command list."""
    if slurm:
        return [str(run_questa), str(filelist), str(config), str(regression_script)]
    else:
        return ["python3", str(regression_script), str(filelist)]


# ── Run regression with live streaming ────────────────────────────────────────

def _run_regression(
    cmd: list[str],
    source_file: Optional[Path],
    slurm: bool,
    verbose: bool = False,
) -> tuple[int, Path]:
    """Execute the regression command, streaming stdout to terminal + log file.

    Returns (exit_code, log_path).
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    mode_label = "slurm" if slurm else "basic"
    log_path = Path.cwd() / f"regression_{mode_label}_{timestamp}.log"

    # Build the full shell command (wrapping with source if needed)
    if source_file:
        shell_cmd = f"source {source_file} && {' '.join(cmd)}"
    else:
        shell_cmd = " ".join(cmd)

    if verbose:
        print(f"  {dim('cmd:')} {shell_cmd}")
        print()

    print(f"  {cyan('ℹ')}  Log: {dim(str(log_path))}")
    print()

    exit_code = 0
    try:
        with open(log_path, "w", encoding="utf-8") as log_file:
            proc = subprocess.Popen(
                shell_cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=str(Path.cwd()),
            )
            for line in proc.stdout:
                sys.stdout.write(line)
                log_file.write(line)
            proc.wait()
            exit_code = proc.returncode
    except Exception as exc:
        raise QAAgentError(f"Regression failed to start: {exc}") from exc

    return exit_code, log_path


# ── Verify results ─────────────────────────────────────────────────────────────

def _verify_results(exit_code: int, log_path: Path, slurm: bool) -> str:
    """Check exit code and results file. Returns a human-readable status string."""
    results_file = "results_new.doc" if slurm else "results.doc"
    results_path = Path.cwd() / results_file

    if exit_code != 0:
        return red(f"✖  Regression failed (exit code {exit_code}). Log: {log_path}")

    if results_path.exists():
        label = "Slurm " if slurm else ""
        return green(f"✔  {label}Regression complete — {results_file} created")
    else:
        return yellow(
            f"⚠  Regression finished but {results_file} was not generated."
            f" Check the log: {log_path}"
        )


# ── Summary block ──────────────────────────────────────────────────────────────

def _print_summary(
    *,
    slurm: bool,
    regression_script: Path,
    filelist: Path,
    source_file: Optional[Path],
    log_path: Path,
    result_status: str,
    config: Optional[Path] = None,
    run_questa: Optional[Path] = None,
) -> None:
    """Print the end-of-run summary table."""
    print()
    print(rule())
    print(f"  {'Mode':<12}{bold('slurm' if slurm else 'basic')}")
    print(f"  {'Script':<12}{dim(str(regression_script.name))}")
    print(f"  {'Filelist':<12}{dim(str(filelist.name))}")
    if slurm and config:
        print(f"  {'Config':<12}{dim(str(config.name))}")
    if slurm and run_questa:
        print(f"  {'Launcher':<12}{dim(str(run_questa.name))}")
    print(f"  {'Source':<12}{dim(str(source_file.name) if source_file else '(none)')}")
    print(f"  {'Log':<12}{dim(str(log_path.name))}")
    print(f"  {'Result':<12}{result_status}")
    print(rule())
    print()


# ── Public entry-point ─────────────────────────────────────────────────────────

def run(
    slurm: bool = False,
    verbose: bool = False,
    log: object = None,
) -> None:
    """Main entry-point called from cli.py."""
    print_regression_banner("slurm" if slurm else "basic")

    # ── Step 1: source file ────────────────────────────────────────────────────
    source_file = _select_source_file()

    # ── Step 2: filelist.txt ───────────────────────────────────────────────────
    filelist = _locate_filelist()
    if filelist is None:
        return  # user declined — clean exit

    # ── Step 3: mode gate ──────────────────────────────────────────────────────
    config: Optional[Path] = None
    run_questa: Optional[Path] = None

    if slurm:
        # ── Step 5a: config.txt ────────────────────────────────────────────────
        config = _locate_config()
        if config is None:
            return  # user declined

        # ── Step 5b: run_questa.sh ─────────────────────────────────────────────
        run_questa = _locate_run_questa()

        # Ensure run_questa.sh is executable
        if not os.access(str(run_questa), os.X_OK):
            os.chmod(str(run_questa), os.stat(str(run_questa)).st_mode | 0o111)
            print(f"  {cyan('ℹ')}  Made {run_questa.name} executable")

        # ── Step 5c: slurm regression script ──────────────────────────────────
        regression_script = _select_regression_py(slurm=True)
    else:
        # ── Step 4a: basic regression script ──────────────────────────────────
        regression_script = _select_regression_py(slurm=False)

    # ── Build command ──────────────────────────────────────────────────────────
    cmd = _build_command(
        slurm=slurm,
        regression_script=regression_script,
        filelist=filelist,
        config=config,
        run_questa=run_questa,
    )

    if verbose:
        print(f"\n  {dim('Full command:')} {' '.join(str(c) for c in cmd)}")

    # ── Run ────────────────────────────────────────────────────────────────────
    print()
    print(rule())
    mode_label = "Slurm" if slurm else "Basic"
    print(f"  {cyan(f'Running {mode_label} Regression')}")
    print(rule())
    print()

    exit_code, log_path = _run_regression(cmd, source_file, slurm=slurm, verbose=verbose)

    # ── Verify ─────────────────────────────────────────────────────────────────
    result_status = _verify_results(exit_code, log_path, slurm=slurm)
    print()
    print(f"  {result_status}")

    # ── Summary ────────────────────────────────────────────────────────────────
    _print_summary(
        slurm=slurm,
        regression_script=regression_script,
        filelist=filelist,
        source_file=source_file,
        log_path=log_path,
        result_status=result_status,
        config=config,
        run_questa=run_questa,
    )
