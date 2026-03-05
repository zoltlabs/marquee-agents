"""qa_agent/regression.py

Automate the full regression run lifecycle.
Now driven by qa-agent.yaml (loaded via qa_agent.config).
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

from qa_agent.config import find_config, load_config, CONFIG_FILENAME
from qa_agent.errors import ConfigError, QAAgentError
from qa_agent.output import (
    bold, cyan, dim, green, red, rule, yellow,
    print_header, confirm, stream_with_esc_monitor, arrow_select
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
    use_shell = True
    if source_file and source_file.exists():
        pcie_dir = source_file.parent.resolve()
        tgt_dir = target_dir.resolve()
        if source_file.suffix in {'.csh', '.tcsh'}:
            exec_shell = '/bin/csh' if os.path.exists('/bin/csh') else 'csh'
            csh_cmd = f"cd {pcie_dir} ; source {source_file.name} ; cd {tgt_dir} ; {' '.join(cmd)}"
            shell_cmd = [f"./{source_file.name}", "-c", csh_cmd]
            use_shell = False
        else:
            shell_cmd = f"cd {pcie_dir} && source {source_file.name} && cd {tgt_dir} && {' '.join(cmd)}"
    else:
        shell_cmd = " ".join(cmd)

    if verbose:
        printable = shell_cmd[2] if not use_shell else shell_cmd
        print(f"  {dim('cmd:')} {printable}")
        print()

    print(f"  {cyan('ℹ')}  Log: {dim(str(log_path))}")
    print()

    exit_code = 0
    captured_text = ""
    try:
        with open(log_path, "w", encoding="utf-8") as log_file:
            proc = subprocess.Popen(
                shell_cmd,
                shell=use_shell,
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


def _verify_results(exit_code: int, log_path: Path, results_file: str, target_dir: Path) -> str:
    results_path = target_dir / results_file

    if exit_code != 0:
        return red(f"✖  Regression failed (exit code {exit_code}). Log: {log_path}")

    if results_path.exists():
        return green(f"✔  Regression complete — {results_file} created")
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

    # ── Load config ────────────────────────────────────────────────────────────
    cfg_path = find_config(cwd)
    if cfg_path is None:
        raise ConfigError(
            f"No {CONFIG_FILENAME} found. Run  qa-agent init  to create one."
        )
    cfg = load_config(cfg_path)
    print(f"  {dim('Using config:')} {dim(str(cfg_path))}")
    print()

    project_root = cfg.root_path
    results_dir  = cfg.results_dir_path
    results_file = cfg.slurm_output if slurm else cfg.basic_output
    source_file: Optional[Path] = cfg.source_file_path

    # ── Step 1: Check Directory & Target ──────────────────────────────────────
    with step_gate(1, "Check directory path & target", debug, step_log) as ctx:
        if not results_dir.exists():
            ctx.fail(f"Results directory from config not found: {results_dir}")

        if ctx.ok:
            if not source:
                # If CWD is directly inside results_dir, use its name
                if cwd.parent.resolve() == results_dir.resolve():
                    source = cwd.name
                    print(f"  {cyan('ℹ')}  Using current directory '{source}' as target.")
                else:
                    try:
                        source = input("  Enter directory name for regression: ").strip()
                    except EOFError:
                        source = ""
                    if not source:
                        ctx.fail("Directory name cannot be empty.")

        if ctx.ok:
            target_dir = results_dir / source
            target_dir.mkdir(parents=True, exist_ok=True)
            ctx.detail = f"Target dir: {target_dir.name}"

    if not ctx.ok:
        log_path = write_log(step_log, cwd)
        print(f"\n  {cyan('ℹ')}  Log: {log_path}")
        return

    # ── Step 2: Preparations ──────────────────────────────────────────────────
    filelist: Optional[Path] = None
    config_txt: Optional[Path] = None
    run_questa: Optional[Path] = None
    regression_script: Optional[Path] = None

    if not slurm:
        with step_gate(2, "Basic regression setup", debug, step_log) as ctx:
            # Locate basic regression script from config
            src_script = cfg.basic_regression_script_path
            if src_script is None or not src_script.exists():
                ctx.fail(f"Basic regression script not found: {cfg.basic_regression_script}")

            if ctx.ok:
                target_script = target_dir / src_script.name
                shutil.copy2(src_script, target_script)
                regression_script = target_script

                # Filelist — always check CWD/target first, then bundled
                filelist_target = target_dir / "filelist.txt"
                bundled_filelist = PACKAGE_DIR / "scripts" / "filelist.txt"

                if filelist_target.exists():
                    if bundled_filelist.exists():
                        ans = arrow_select(
                            "Found filelist.txt in target directory. Which one to use?",
                            [("The one in target directory", "cwd"),
                             ("The bundled qa-agent default", "bundled")]
                        )
                        if ans == 1:
                            shutil.copy2(bundled_filelist, filelist_target)
                    filelist = filelist_target
                else:
                    print(f"  {yellow('⚠')}  No filelist.txt in target directory.")
                    if bundled_filelist.exists() and confirm("Use bundled filelist.txt?", default=True):
                        shutil.copy2(bundled_filelist, filelist_target)
                        filelist = filelist_target
                    else:
                        ctx.fail("Please create filelist.txt in the target directory and try again.")

            if ctx.ok:
                cmd = ["python3", str(regression_script.name), str(filelist.name)]
                ctx.detail = f"Script: {regression_script.name}, Filelist: {filelist.name}"

        if not ctx.ok:
            log_path = write_log(step_log, cwd)
            print(f"\n  {cyan('ℹ')}  Log: {log_path}")
            return

    else:  # slurm
        with step_gate(2, "Slurm regression setup", debug, step_log) as ctx:
            src_script  = cfg.slurm_regression_script_path
            src_run_sh  = cfg.slurm_run_script_path
            src_config  = cfg.slurm_config_path

            if src_script is None or not src_script.exists():
                ctx.fail(f"Slurm regression script not found: {cfg.slurm_regression_script}")
            if src_run_sh is None or not src_run_sh.exists():
                ctx.fail(f"Slurm run script not found: {cfg.slurm_run_script}")

            if ctx.ok:
                target_script   = target_dir / src_script.name
                target_run_sh   = target_dir / src_run_sh.name
                shutil.copy2(src_script, target_script)
                shutil.copy2(src_run_sh, target_run_sh)
                os.chmod(str(target_run_sh), os.stat(str(target_run_sh)).st_mode | 0o111)
                regression_script = target_script
                run_questa = target_run_sh

                # Filelist
                filelist_target  = target_dir / "filelist.txt"
                bundled_filelist = PACKAGE_DIR / "scripts" / "filelist.txt"

                if filelist_target.exists():
                    if bundled_filelist.exists():
                        ans = arrow_select(
                            "Found filelist.txt in target directory. Which one to use?",
                            [("The one in target directory", "cwd"),
                             ("The bundled qa-agent default", "bundled")]
                        )
                        if ans == 1:
                            shutil.copy2(bundled_filelist, filelist_target)
                    filelist = filelist_target
                else:
                    print(f"\n  {yellow('⚠')}  No filelist.txt in target directory.")
                    if bundled_filelist.exists() and confirm("Use bundled filelist.txt?", default=True):
                        shutil.copy2(bundled_filelist, filelist_target)
                        filelist = filelist_target
                    else:
                        ctx.fail("Please create filelist.txt in the target directory and try again.")

            if ctx.ok:
                # Config.txt
                target_config = target_dir / "config.txt"
                if target_config.exists():
                    options = [("The one in target directory", "cwd")]
                    if src_config and src_config.exists():
                        options.append(("The config from project (config.txt)", "project"))
                    ans = arrow_select("Found config.txt in target directory. Which one to use?", options)
                    if ans == 1 and src_config and src_config.exists():
                        shutil.copy2(src_config, target_config)
                    config_txt = target_config
                else:
                    print(f"\n  {yellow('⚠')}  No config.txt in target directory.")
                    if src_config and src_config.exists() and confirm(
                        f"Use config.txt from project ({src_config.name})?", default=True
                    ):
                        shutil.copy2(src_config, target_config)
                        config_txt = target_config
                    else:
                        ctx.fail("Please provide config.txt in the target directory.")

            if ctx.ok:
                cmd = [
                    "./" + run_questa.name,
                    str(filelist.name),
                    str(config_txt.name),
                    str(regression_script.name),
                ]
                ctx.detail = f"Config: {config_txt.name}"

        if not ctx.ok:
            log_path = write_log(step_log, cwd)
            print(f"\n  {cyan('ℹ')}  Log: {log_path}")
            return

    # ── Step 3: Run regression ─────────────────────────────────────────────────
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
        if debug:
            log_path = write_log(step_log, cwd)
            print(f"\n  {cyan('ℹ')}  Step log: {log_path}")

    # ── Step 4: Verify results ─────────────────────────────────────────────────
    with step_gate(4, "Verify results", debug, step_log) as ctx:
        result_status = _verify_results(exec_exit_code, exec_log_path, results_file, target_dir)
        results_path = target_dir / results_file
        if not results_path.exists() and exec_exit_code == 0:
            ctx.detail = f"{results_file} not generated"
        elif results_path.exists():
            ctx.detail = f"{results_file} present"

    print()
    print(f"  {result_status}")
    print()

    if debug:
        step_log_path = write_log(step_log, cwd)
        print(f"  {cyan('ℹ')}  Step log: {step_log_path}\n")
