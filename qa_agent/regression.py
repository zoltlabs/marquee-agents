"""qa_agent/regression.py

Automate the full regression run lifecycle for sig_pcie workspace.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import signal
from datetime import datetime
from pathlib import Path
from typing import Optional

from qa_agent.errors import ConfigError, QAAgentError
from qa_agent.output import (
    bold, cyan, dim, green, red, rule, yellow,
    print_header, confirm, stream_with_esc_monitor
)
from qa_agent.step_gate import StepLog, write_log, step_gate

PACKAGE_DIR: Path = Path(__file__).resolve().parent.parent

def _run_regression(
    cmd: list[str],
    source_file: Optional[Path],
    slurm: bool,
    target_dir: Path,
    verbose: bool = False,
) -> tuple[int, Path, str]:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    mode_label = "slurm" if slurm else "basic"
    log_path = target_dir / f"regression_{mode_label}_{timestamp}.log"

    exec_shell = None
    if source_file and source_file.exists():
        shell_cmd = f"source {source_file.resolve()} && {' '.join(cmd)}"
        if source_file.suffix in {'.csh', '.tcsh'}:
            import shutil
            exec_shell = shutil.which("csh") or shutil.which("tcsh")
    else:
        shell_cmd = " ".join(cmd)

    if verbose:
        print(f"  {dim('cmd:')} {shell_cmd}")
        print()

    print(f"  {cyan('ℹ')}  Log: {dim(str(log_path))}")
    print()

    exit_code = 0
    captured_text = ""
    try:
        with open(log_path, "w", encoding="utf-8") as log_file:
            proc = subprocess.Popen(
                shell_cmd,
                shell=True,
                executable=exec_shell,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=str(target_dir),
                start_new_session=True,
            )
            try:
                captured_text = stream_with_esc_monitor(proc, log_file, print_output=True)
                proc.wait(timeout=7200)
            except BaseException:
                if proc.poll() is None:
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                raise
            exit_code = proc.returncode
    except Exception as exc:
        raise QAAgentError(f"Regression failed to start: {exc}") from exc

    return exit_code, log_path, captured_text

def _verify_results(exit_code: int, log_path: Path, slurm: bool, target_dir: Path) -> str:
    results_file = "results_new.doc" if slurm else "results.doc"
    results_path = target_dir / results_file

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

def run(
    source: str | None = None,
    slurm: bool = False,
    verbose: bool = False,
    debug: bool = False,
    log: object = None,
) -> None:
    print_header("regression", f"Mode: {'slurm' if slurm else 'basic'}")

    mode = "slurm" if slurm else "basic"
    step_log = StepLog(command="regression", mode=mode)
    cwd = Path.cwd()

    # Step 1: Check Directory Path & Target Source
    with step_gate(1, "Check Directory Path & Target Source", debug, step_log) as ctx:
        if "sig_pcie/verif/AVERY/run/results" not in cwd.as_posix():
            ctx.fail("cwd must be within and contain 'sig_pcie/verif/AVERY/run/results'")
        
        # Locate sig_pcie
        sig_pcie_dir = None
        for parent in cwd.parents:
            if parent.name == "sig_pcie":
                sig_pcie_dir = parent
                break
        if cwd.name == "sig_pcie":
            sig_pcie_dir = cwd
            
        if not sig_pcie_dir:
            ctx.fail("sig_pcie not found in cwd path")
        elif ctx.ok:
            results_dir = sig_pcie_dir / "verif/AVERY/run/results"
            run_dir = sig_pcie_dir / "verif/AVERY/run"

            if not source:
                try:
                    source = input("  Enter directory name for regression: ").strip()
                except EOFError:
                    source = ""
                if not source:
                    ctx.fail("Directory name cannot be empty.")
            
            if ctx.ok:
                target_dir = results_dir / source
                target_dir.mkdir(parents=True, exist_ok=True)
                ctx.detail = f"Target Dir: {target_dir.name}"
                
                source_file = sig_pcie_dir / "sourcefile_2025_3.csh"
                if not source_file.exists():
                    source_file = None
                    
    if not ctx.ok:
        log_path = write_log(step_log, Path.cwd())
        print(f"\n  {cyan('ℹ')}  Log: {log_path}")
        return

    # Step 2: Preparations
    filelist: Optional[Path] = None
    config: Optional[Path] = None
    run_questa: Optional[Path] = None
    regression_script: Optional[Path] = None

    if not slurm:
        with step_gate(2, "Basic Regression Setup", debug, step_log) as ctx:
            src_script = run_dir / "regression_8B_16B_questa.py"
            target_script = target_dir / "regression_8B_16B_questa.py"
            if src_script.exists():
                shutil.copy2(src_script, target_script)
                regression_script = target_script
            else:
                ctx.fail(f"Missing basic regression script in {run_dir}")
                
            if ctx.ok:
                filelist_target = target_dir / "filelist.txt"
                if filelist_target.exists():
                    filelist = filelist_target
                else:
                    bundled_filelist = PACKAGE_DIR / "scripts" / "filelist.txt"
                    print(f"  {yellow('⚠')}  No filelist.txt found in target directory.")
                    if bundled_filelist.exists() and confirm("Use the one in qa-agent script?", default=True):
                        shutil.copy2(bundled_filelist, filelist_target)
                        filelist = filelist_target
                    else:
                        ctx.fail("Please make filelist.txt and try again.")
            
            if ctx.ok:
                cmd = ["python3", str(regression_script.name), str(filelist.name)]
                ctx.detail = f"Script: {regression_script.name}, Filelist: {filelist.name}"

        if not ctx.ok:
            log_path = write_log(step_log, Path.cwd())
            print(f"\n  {cyan('ℹ')}  Log: {log_path}")
            return
            
    else:
        with step_gate(2, "Slurm Regression Setup", debug, step_log) as ctx:
            src_script = run_dir / "questa_slurm" / "regression_slurm_questa_2025.py"
            src_run_questa = run_dir / "questa_slurm" / "run_questa.sh"
            src_config = run_dir / "questa_slurm" / "config.txt"

            target_script = target_dir / "regression_slurm_questa_2025.py"
            target_run_questa = target_dir / "run_questa.sh"
            target_config = target_dir / "config.txt"

            if src_script.exists() and src_run_questa.exists():
                shutil.copy2(src_script, target_script)
                shutil.copy2(src_run_questa, target_run_questa)
                regression_script = target_script
                run_questa = target_run_questa
                os.chmod(str(run_questa), os.stat(str(run_questa)).st_mode | 0o111)
            else:
                ctx.fail(f"Missing slurm scripts in {run_dir / 'questa_slurm'}")

            if ctx.ok:
                filelist_target = target_dir / "filelist.txt"
                if filelist_target.exists():
                    filelist = filelist_target
                else:
                    bundled_filelist = PACKAGE_DIR / "scripts" / "filelist.txt"
                    print(f"\n  {yellow('⚠')}  No filelist.txt found in target directory.")
                    if bundled_filelist.exists() and confirm("Use the one in qa-agent script?", default=True):
                        shutil.copy2(bundled_filelist, filelist_target)
                        filelist = filelist_target
                    else:
                        ctx.fail("Please make filelist.txt and try again.")

            if ctx.ok:
                if target_config.exists():
                    config = target_config
                else:
                    print(f"\n  {yellow('⚠')}  No config.txt found in target directory.")
                    bundled_config = PACKAGE_DIR / "scripts" / "config.txt"
                    if src_config.exists() and confirm("Use the config.txt from questa_slurm?", default=True):
                        shutil.copy2(src_config, target_config)
                        config = target_config
                    elif bundled_config.exists() and confirm("Use the one in qa-agent script?", default=True):
                        shutil.copy2(bundled_config, target_config)
                        config = target_config
                    else:
                        ctx.fail("Please provide config.txt")

            if ctx.ok:
                cmd = ["./" + run_questa.name, str(filelist.name), str(config.name), str(regression_script.name)]
                ctx.detail = f"Config: {config.name}"

        if not ctx.ok:
            log_path = write_log(step_log, Path.cwd())
            print(f"\n  {cyan('ℹ')}  Log: {log_path}")
            return

    # Step 3: Run regression
    print()
    print(rule())
    mode_str = "Slurm" if slurm else "Basic"
    print(f"  {cyan(f'Running {mode_str} Regression')}")
    print(rule())
    print()

    exec_exit_code = 0
    with step_gate(3, "Execute regression", debug, step_log) as ctx:
        exec_exit_code, exec_log_path, captured = _run_regression(
            cmd, source_file, slurm=slurm, target_dir=target_dir, verbose=verbose
        )
        ctx.detail = f"Command: {' '.join(str(c) for c in cmd)}"
        ctx.output = captured
        if exec_exit_code != 0:
            ctx.fail(f"Exit code: {exec_exit_code}")
            
    if not ctx.ok and exec_exit_code != 0:
        if debug or True:  # always write on failure
            log_path = write_log(step_log, Path.cwd())
            print(f"\n  {cyan('ℹ')}  Step log: {log_path}")

    # Step 4: Verify results
    with step_gate(4, "Verify results", debug, step_log) as ctx:
        result_status = _verify_results(exec_exit_code, exec_log_path, slurm=slurm, target_dir=target_dir)
        results_file = "results_new.doc" if slurm else "results.doc"
        results_path = target_dir / results_file
        if not results_path.exists() and exec_exit_code == 0:
            ctx.detail = f"{results_file} not generated"
        elif results_path.exists():
            ctx.detail = f"{results_file} present"

    print()
    print(f"  {result_status}")
    print()

    has_failure = any(s.status == "FAILED" for s in step_log.steps)
    if debug or has_failure:
        step_log_path = write_log(step_log, Path.cwd())
        print(f"  {cyan('ℹ')}  Step log: {step_log_path}\n")
