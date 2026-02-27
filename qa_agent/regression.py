"""qa_agent/regression.py

Automate the full regression run lifecycle:
  1. Source a .csh environment file
  2. Locate filelist.txt
  3. Mode gate: basic or slurm
  4. Basic: locate + run the regression Python script; verify results.doc
  5. Slurm: locate config.txt + run_questa.sh + slurm script; verify results_new.doc
  6. Print a summary block

Debug mode (--debug): wraps each step in a step_gate that pauses for user
confirmation between steps and writes a timestamped log file to cwd.
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
    print_header, print_summary_table, arrow_select, Spinner,
)
from qa_agent.step_gate import StepLog, step_gate, write_log

# ── Package / repo root ────────────────────────────────────────────────────────

PACKAGE_DIR: Path = Path(__file__).resolve().parent.parent  # repo root


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
    idx = arrow_select("🔧 Select source file to use:", options)
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
    idx = arrow_select("🐍 Select regression script:", options)
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
    idx = arrow_select("🚀 Select run_questa.sh to use:", options)
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
) -> tuple[int, Path, str]:
    """Execute the regression command, streaming stdout to terminal + log file.

    Returns (exit_code, log_path, captured_output).
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
    captured_lines: list[str] = []
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
                captured_lines.append(line.rstrip())
            proc.wait()
            exit_code = proc.returncode
    except Exception as exc:
        raise QAAgentError(f"Regression failed to start: {exc}") from exc

    return exit_code, log_path, "\n".join(captured_lines)


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
    debug: bool = False,
    log: object = None,
) -> None:
    """Main entry-point called from cli.py."""
    print_header("regression", f"Mode: {'slurm' if slurm else 'basic'}")

    mode = "slurm" if slurm else "basic"
    step_log = StepLog(command="regression", mode=mode)

    source_file: Optional[Path] = None
    filelist: Optional[Path] = None
    config: Optional[Path] = None
    run_questa: Optional[Path] = None
    regression_script: Optional[Path] = None
    exec_log_path: Optional[Path] = None
    result_status: str = ""

    # ── Step 1: source file ────────────────────────────────────────────────────
    with step_gate(1, "Source environment", debug, step_log) as ctx:
        source_file = _select_source_file()
        if source_file:
            ctx.detail = f"File: {source_file.name}"
        else:
            ctx.detail = "(none — environment will not be pre-configured)"
    if not ctx.ok:
        log_path = write_log(step_log, Path.cwd())
        print(f"\n  {cyan('ℹ')}  Log: {log_path}")
        return

    # ── Step 2: filelist.txt ───────────────────────────────────────────────────
    with step_gate(2, "Locate filelist", debug, step_log) as ctx:
        filelist = _locate_filelist()
        if filelist is None:
            ctx.fail("filelist.txt not found and user declined bundled default")
        else:
            ctx.detail = f"Found: {filelist.name}"
    if not ctx.ok:
        log_path = write_log(step_log, Path.cwd())
        print(f"\n  {cyan('ℹ')}  Log: {log_path}")
        return

    if slurm:
        # ── Step 3: config.txt (slurm) ─────────────────────────────────────────
        with step_gate(3, "Locate config.txt", debug, step_log) as ctx:
            config = _locate_config()
            if config is None:
                ctx.fail("config.txt not found and user declined bundled default")
            else:
                ctx.detail = f"Found: {config.name}"
        if not ctx.ok:
            log_path = write_log(step_log, Path.cwd())
            print(f"\n  {cyan('ℹ')}  Log: {log_path}")
            return

        # ── Step 4: run_questa.sh (slurm) ──────────────────────────────────────
        with step_gate(4, "Locate run_questa.sh", debug, step_log) as ctx:
            run_questa = _locate_run_questa()
            ctx.detail = f"Found: {run_questa.name}"
            # Ensure executable
            if not os.access(str(run_questa), os.X_OK):
                os.chmod(str(run_questa), os.stat(str(run_questa)).st_mode | 0o111)
                print(f"  {cyan('ℹ')}  Made {run_questa.name} executable")
        if not ctx.ok:
            log_path = write_log(step_log, Path.cwd())
            print(f"\n  {cyan('ℹ')}  Log: {log_path}")
            return

        # ── Step 5: slurm regression script ────────────────────────────────────
        with step_gate(5, "Select regression script", debug, step_log) as ctx:
            regression_script = _select_regression_py(slurm=True)
            ctx.detail = f"Selected: {regression_script.name}"
        if not ctx.ok:
            log_path = write_log(step_log, Path.cwd())
            print(f"\n  {cyan('ℹ')}  Log: {log_path}")
            return

        exec_step_num = 6
    else:
        # ── Step 3: basic regression script ────────────────────────────────────
        with step_gate(3, "Select regression script", debug, step_log) as ctx:
            regression_script = _select_regression_py(slurm=False)
            ctx.detail = f"Selected: {regression_script.name}"
        if not ctx.ok:
            log_path = write_log(step_log, Path.cwd())
            print(f"\n  {cyan('ℹ')}  Log: {log_path}")
            return

        exec_step_num = 4

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

    print()
    print(rule())
    mode_label = "Slurm" if slurm else "Basic"
    print(f"  {cyan(f'Running {mode_label} Regression')}")
    print(rule())
    print()

    # ── Step exec_step_num: Execute regression ─────────────────────────────────
    exec_exit_code = 0
    with step_gate(exec_step_num, "Execute regression", debug, step_log) as ctx:
        exec_exit_code, exec_log_path, captured = _run_regression(
            cmd, source_file, slurm=slurm, verbose=verbose
        )
        ctx.detail = f"Command: {' '.join(str(c) for c in cmd)}"
        ctx.output = captured
        if exec_exit_code != 0:
            ctx.fail(f"Exit code: {exec_exit_code}")
    if not ctx.ok and exec_exit_code != 0:
        has_failure = True
        if debug or True:  # always write on failure
            log_path = write_log(step_log, Path.cwd())
            print(f"\n  {cyan('ℹ')}  Step log: {log_path}")

    # ── Step exec_step_num+1: Verify results ───────────────────────────────────
    verify_step_num = exec_step_num + 1
    with step_gate(verify_step_num, "Verify results", debug, step_log) as ctx:
        result_status = _verify_results(exec_exit_code, exec_log_path, slurm=slurm)
        results_file = "results_new.doc" if slurm else "results.doc"
        results_path = Path.cwd() / results_file
        if not results_path.exists() and exec_exit_code == 0:
            ctx.detail = f"{results_file} not generated"
        elif results_path.exists():
            ctx.detail = f"{results_file} present"
        # verify step is non-fatal — never fail ctx here

    # Print original result status line
    print()
    print(f"  {result_status}")

    # ── Summary ────────────────────────────────────────────────────────────────
    _print_summary(
        slurm=slurm,
        regression_script=regression_script,
        filelist=filelist,
        source_file=source_file,
        log_path=exec_log_path,
        result_status=result_status,
        config=config,
        run_questa=run_questa,
    )

    # ── Write step log in debug mode or on failure ─────────────────────────────
    has_failure = any(s.status == "FAILED" for s in step_log.steps)
    if debug or has_failure:
        step_log_path = write_log(step_log, Path.cwd())
        print(f"  {cyan('ℹ')}  Step log: {step_log_path}\n")
