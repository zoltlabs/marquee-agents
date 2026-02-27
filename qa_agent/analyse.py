"""qa_agent/analyse.py

Parse a regression results .doc file, detect failures, run debug commands
per failure, capture logs, and write a grouped Markdown QA report.
No AI — pure Python.

Debug mode (--debug): wraps each pipeline step in a step_gate that pauses
for user confirmation and writes a timestamped log file to cwd.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from qa_agent.errors import PathError, QAAgentError
from qa_agent.output import bold, cyan, dim, green, red, rule, yellow, print_header, arrow_select, confirm, stream_with_esc_monitor
from qa_agent.step_gate import StepLog, step_gate, write_log

# ── Default script ────────────────────────────────────────────────────────────

DEFAULT_SCRIPT = "../../scripts/run_apci_2025.pl"

# ── Regexes ───────────────────────────────────────────────────────────────────

_SHARED = (
    r"^(?P<test>\S+)\s+for\s+"
    r"(?P<sys_ele>[^_]+)_(?P<gen>[^_]+)_lane(?P<num_lane>\d+)_"
    r"(?P<flit_mode>.+?)_(?P<typ>[^_]+)_iter(?P<iteration>\d+)"
    r"\s+{verb}\s+(?P<seed>\d+)"
)
PASS_RE = re.compile(_SHARED.format(verb="passed for"), re.IGNORECASE)
FAIL_RE = re.compile(_SHARED.format(verb="failed for"), re.IGNORECASE)

# ── Mode detection ────────────────────────────────────────────────────────────

_MODE_MAP = {
    "results.doc": "basic",
    "results_new.doc": "slurm",
}


def _detect_mode(filename: str) -> str:
    return _MODE_MAP.get(filename, "basic")


# ── File discovery ────────────────────────────────────────────────────────────

_RESULT_CANDIDATES = ["results.doc", "results_new.doc"]


def _find_results(working_dir: Path) -> Path:
    """Return the first candidate file found; raise PathError otherwise."""
    for name in _RESULT_CANDIDATES:
        p = working_dir / name
        if p.exists():
            return p
    candidates = "  or  ".join(_RESULT_CANDIDATES)
    raise PathError(
        f"No results file found in {working_dir}.\n"
        f"  Expected: {candidates}"
    )


# ── Config flag builder ───────────────────────────────────────────────────────

def _is_rc(sys_ele: str) -> bool:
    """Return True when the sys_ele represents an RC (Root Complex) endpoint."""
    return sys_ele.lower().startswith("rc")


def _data_width_flags(typ: str) -> tuple[str, str]:
    """Return (PIPE_BYTEWIDTH, APCI_MAX_DATA_WIDTH) defines derived from typ (e.g. '4B')."""
    m = re.search(r"(\d+)B", typ.upper())
    if m:
        bus_bytes = int(m.group(1))       # 4B → 4
        width = bus_bytes * 4             # 4 → 16, 8 → 32
        return f"+define+PIPE_BYTEWIDTH_{width}", f"+define+APCI_MAX_DATA_WIDTH={width}"
    return "+define+PIPE_BYTEWIDTH_16", "+define+APCI_MAX_DATA_WIDTH=16"


def _build_config_flags(sys_ele: str, gen: str, num_lane: str, flit_mode: str, typ: str) -> str:
    """Expand parsed config fields into the +define+ simulator flag string for -R.

    EP example (sys_ele=ep1, gen=GEN5, num_lane=4, flit_mode=NON_FLIT, typ=4B):
        +define+APCI_NUM_LANES=4 +apci_gen5 +define+SIPC_GEN5
        +define+SIPC_USE_NON_FLIT_MODE +define+SIPC_FASTER_MS_TICK
        +define+GEN3_MAX_WIDTH_4 +define+GEN4_MAX_WIDTH_4
        +define+GEN5_MAX_WIDTH_4 +define+GEN6_MAX_WIDTH_8
        +define+PIPE_BYTEWIDTH_16 +define+APCI_MAX_DATA_WIDTH=16
        +define+GEN1_2_MAX_WIDTH_4 +licq

    RC example (sys_ele=rc1, gen=GEN5, num_lane=4, flit_mode=NON_FLIT, typ=4B):
        +define+SIPC_NUM_LANES=4 +define+APCI_NUM_LANES=4 +apci_gen5 +define+SIPC_GEN5
        +define+SIPC_USE_NON_FLIT_MODE +define+SIPC_FASTER_MS_TICK +define+ROUTINE_RC
        +define+GEN1_2_MAX_WIDTH_4 +define+PIPE_BYTEWIDTH_16 +define+APCI_MAX_DATA_WIDTH=16
        +licq +define+RC_INITIATING_SPEED_CHANGE
    """
    rc = _is_rc(sys_ele)
    gen_upper = gen.upper()   # e.g. GEN5
    gen_lower = gen.lower()   # e.g. gen5
    fm_upper  = flit_mode.upper()
    pb, adw   = _data_width_flags(typ)

    flags: list[str] = []

    if rc:
        # ── RC flag order ──────────────────────────────────────────────────────
        flags.append(f"+define+SIPC_NUM_LANES={num_lane}")
        flags.append(f"+define+APCI_NUM_LANES={num_lane}")
        flags.append(f"+apci_{gen_lower}")
        flags.append(f"+define+SIPC_{gen_upper}")
        if "NON" in fm_upper:
            flags.append("+define+SIPC_USE_NON_FLIT_MODE")
        flags.append("+define+SIPC_FASTER_MS_TICK")
        flags.append("+define+ROUTINE_RC")
        flags.append(f"+define+GEN1_2_MAX_WIDTH_{num_lane}")
        flags.append(pb)
        flags.append(adw)
        flags.append("+licq")
        flags.append("+define+RC_INITIATING_SPEED_CHANGE")
    else:
        # ── EP flag order ──────────────────────────────────────────────────────
        flags.append(f"+define+APCI_NUM_LANES={num_lane}")
        flags.append(f"+apci_{gen_lower}")
        flags.append(f"+define+SIPC_{gen_upper}")
        if "NON" in fm_upper:
            flags.append("+define+SIPC_USE_NON_FLIT_MODE")
        flags.append("+define+SIPC_FASTER_MS_TICK")
        flags.append(f"+define+GEN3_MAX_WIDTH_{num_lane}")
        flags.append(f"+define+GEN4_MAX_WIDTH_{num_lane}")
        flags.append(f"+define+GEN5_MAX_WIDTH_{num_lane}")
        flags.append("+define+GEN6_MAX_WIDTH_8")
        flags.append(pb)
        flags.append(adw)
        flags.append(f"+define+GEN1_2_MAX_WIDTH_{num_lane}")
        flags.append("+licq")

    return " ".join(flags)


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TestResult:
    test: str
    sys_ele: str
    gen: str
    num_lane: str
    flit_mode: str
    typ: str
    iteration: str
    seed: str

    @property
    def configuration(self) -> str:
        return (
            f"{self.sys_ele}_{self.gen}_lane{self.num_lane}"
            f"_{self.flit_mode}_{self.typ}"
        )

    @property
    def is_rc(self) -> bool:
        """True when this result is from an RC (Root Complex) sys_ele."""
        return _is_rc(self.sys_ele)

    @property
    def config_flags(self) -> str:
        """Return the expanded +define+ simulator flags for -R (EP or RC flavour)."""
        return _build_config_flags(self.sys_ele, self.gen, self.num_lane, self.flit_mode, self.typ)

    def debug_command(self, script: str) -> str:
        """Return the full debug invocation command for this test result.

        EP format:  -T $SIG_PCIE_AVERY_TOP/sipc_top_ep1.sv
        RC format:  -T $SIG_PCIE_AVERY_TOP/sipc_top_rc1.sv  (sys_ele in filename)
        """
        effective_script = script or DEFAULT_SCRIPT
        test_file = self.test if self.test.endswith(".sv") else f"{self.test}.sv"
        top_sv = f"$SIG_PCIE_AVERY_TOP/sipc_top_{self.sys_ele}.sv"
        return (
            f"{effective_script} -t {test_file} -s mti64 -visualizer -debug"
            f" -T {top_sv}"
            f" -file $SIG_PCIE_HOME/RTL/PCIeCore/sig_pcie_core_16B.f"
            f' -R " {self.config_flags}" -n {self.seed}'
        )


# ── Parser ────────────────────────────────────────────────────────────────────

def _parse(path: Path) -> tuple[list[TestResult], list[TestResult]]:
    """Return (passed, failed) lists."""
    passed: list[TestResult] = []
    failed: list[TestResult] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        for rex, bucket in ((PASS_RE, passed), (FAIL_RE, failed)):
            m = rex.match(line.strip())
            if m:
                bucket.append(TestResult(**{k: m.group(k) for k in TestResult.__dataclass_fields__}))
                break
    return passed, failed



# ── Source file discovery & selection (Step 3) ────────────────────────────────

def _find_source_files(working_dir: Path, package_dir: Path) -> list[tuple[Path, str]]:
    """Return (path, tag) pairs for all .csh files, package-dir files first.
    tag is one of: 'qa-agent', 'working-dir'.
    """
    results: list[tuple[Path, str]] = []
    seen: set[Path] = set()

    # 1. .csh files in the qa_agent/ package directory
    for p in sorted(package_dir.glob("*.csh")):
        if p not in seen:
            results.append((p, "qa-agent"))
            seen.add(p)

    # 2. Project root fallback: sourcefile_2025_3.csh (parent of qa_agent/)
    root_csh = package_dir.parent / "scripts" / "sourcefile_2025_3.csh"
    if root_csh.exists() and root_csh not in seen:
        results.append((root_csh, "qa-agent"))
        seen.add(root_csh)

    # 3. .csh files in the working directory
    for p in sorted(working_dir.glob("*.csh")):
        if p not in seen:
            results.append((p, "working-dir"))
            seen.add(p)

    return results


def _select_source_file(working_dir: Path, package_dir: Path) -> Optional[Path]:
    """Interactive (or auto) source file selection. Returns selected Path or None."""
    candidates = _find_source_files(working_dir, package_dir)

    if not candidates:
        print(f"\n  {yellow('⚠')}  No .csh source file found. The debug shell will not be pre-configured.")
        return None

    if len(candidates) == 1:
        path, tag = candidates[0]
        print(f"\n  {green('✓')}  Auto-selected source: {path}  {dim(f'[{tag}]')}")
        return path

    options = [(p.name, tag) for p, tag in candidates]
    idx = arrow_select("Select a source file to use (↑/↓ arrow keys, Enter to confirm):", options)
    chosen_path = candidates[idx][0]
    print(f"  {green('✓')}  Using source file: {chosen_path}")
    return chosen_path


# ── Script file discovery & selection (Step 4) ────────────────────────────────

def _find_script_files(working_dir: Path, package_dir: Path) -> list[tuple[Path, str]]:
    """Return (path, tag) pairs for all .pl files."""
    results: list[tuple[Path, str]] = []
    seen: set[Path] = set()

    # 1. .pl files in the qa_agent/ package directory
    for p in sorted(package_dir.glob("*.pl")):
        if p not in seen:
            results.append((p, "qa-agent"))
            seen.add(p)

    # 2. Project root: run_apci_2025.pl fallback
    root_pl = package_dir.parent / "scripts" / "run_apci_2025.pl"
    if root_pl.exists() and root_pl not in seen:
        results.append((root_pl, "qa-agent"))
        seen.add(root_pl)

    # 3. .pl files in the current working directory (CWD)
    cwd = Path.cwd()
    for p in sorted(cwd.glob("*.pl")):
        if p not in seen:
            results.append((p, "cwd"))
            seen.add(p)

    # 4. .pl files in the working dir (if different from CWD)
    if working_dir != cwd:
        for p in sorted(working_dir.glob("*.pl")):
            if p not in seen:
                results.append((p, "working-dir"))
                seen.add(p)

    return results


def _check_and_chmod(script_path: Path) -> None:
    if script_path.exists() and not os.access(str(script_path), os.X_OK):
        print(f"\n  {yellow('⚠')}  The script '{script_path.name}' is not executable.")
        if confirm("Grant execute permission to run it?", default=True):
            try:
                os.chmod(str(script_path), os.stat(str(script_path)).st_mode | 0o111)
                print(f"  {cyan('ℹ')}  Made {script_path.name} executable")
            except Exception as e:
                print(f"  {yellow('⚠')}  Could not grant execute permission: {e}")
        else:
            print(f"  {yellow('⚠')}  Did not grant execute permission. Debug runs may fail.")


def _select_script(script_flag: str, working_dir: Path, package_dir: Path) -> str:
    """If --script was passed, use it. Otherwise run interactive selection.
    Returns the chosen script path as string, or '' if none found.
    """
    if script_flag:
        print(f"  {green('✓')}  Using script: {script_flag}  {dim('[--script flag]')}")
        _check_and_chmod(Path(script_flag))
        return script_flag

    candidates = _find_script_files(working_dir, package_dir)

    if not candidates:
        print(f"\n  {yellow('⚠')}  No .pl script file found. Debug commands will be written to the report "
              "but cannot be executed.")
        _check_and_chmod(package_dir.parent / "scripts" / "run_apci_2025.pl")
        return ""

    if len(candidates) == 1:
        path, tag = candidates[0]
        print(f"\n  {green('✓')}  Auto-selected script: {path}  {dim(f'[{tag}]')}")
        _check_and_chmod(path)
        return str(path)

    options = [(p.name, tag) for p, tag in candidates]
    idx = arrow_select("Select a debug script (↑/↓ arrow keys, Enter to confirm):", options)
    chosen_path = candidates[idx][0]
    print(f"  {green('✓')}  Using script: {chosen_path}")
    _check_and_chmod(chosen_path)
    return str(chosen_path)


# ── Debug subdirectory helpers (Step 5) ───────────────────────────────────────

def _debug_dir_name(result: TestResult) -> str:
    return f"debug_{result.test}"


def _create_debug_dirs(
    failed: list[TestResult], working_dir: Path, verbose: bool = False
) -> dict[TestResult, Path]:
    """Create debug_<test>_<hash>_<seed>/ for each failure. Return mapping."""
    mapping: dict[TestResult, Path] = {}
    for result in failed:
        dir_name = _debug_dir_name(result)
        debug_dir = working_dir / dir_name
        debug_dir.mkdir(parents=True, exist_ok=True)
        if verbose:
            print(f"  {green('✓')}  Created debug dir: {debug_dir}/")
        else:
            print(f"  {green('✓')}  Created debug dir: {dir_name}/")
        mapping[result] = debug_dir
    return mapping


# ── Debug runner (Step 6) ─────────────────────────────────────────────────────

@dataclass
class DebugOutcome:
    result: TestResult
    debug_dir: Path
    log_file: Path
    exit_code: Optional[int]      # None = timed out
    timed_out: bool
    error_note: str               # "" on success


def _run_debug(
    result: TestResult,
    debug_dir: Path,
    script: str,
    source_file: Optional[Path],
    index: int,
    total: int,
    verbose: bool = False,
) -> DebugOutcome:
    """Build and execute the full debug command for one failure.

    Captures stdout+stderr to debug_dir/debug.log.
    Returns DebugOutcome regardless of success/failure/timeout.
    """
    log_file = debug_dir / "debug.log"
    cmd = result.debug_command(script)

    if source_file:
        full_cmd = f"source {source_file} && \\\n{cmd}"
    else:
        full_cmd = cmd

    print(f"\n  {cyan('▶')}  Running: {bold(result.test)} (seed={result.seed})")
    print(f"  {dim('Command:')} {full_cmd}\n")

    exit_code: Optional[int] = None
    timed_out = False
    error_note = ""

    try:
        with log_file.open("w", encoding="utf-8") as fh:
            proc = subprocess.Popen(
                full_cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=str(debug_dir),
                start_new_session=True,
            )
            stream_with_esc_monitor(proc, fh, print_output=True)
            proc.wait(timeout=7200)
        exit_code = proc.returncode
        if exit_code != 0:
            error_note = f"exit {exit_code}"
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        timed_out = True
        exit_code = None
        error_note = "Timed out after 2h"
    except Exception as exc:
        error_note = str(exc)

    # Status line
    tag = f"[{index}/{total}]"
    label = f"{bold(result.test)}  seed={result.seed}"
    if timed_out:
        print(f"  {red('✗')}  {tag} {label}  {red('TIMEOUT')}")
    elif exit_code is not None and exit_code != 0:
        print(f"  {red('✗')}  {tag} {label}  exit={exit_code}")
    elif error_note:
        print(f"  {red('✗')}  {tag} {label}  {red(error_note)}")
    else:
        print(f"  {green('✓')}  {tag} {label}  exit=0")

    return DebugOutcome(
        result=result,
        debug_dir=debug_dir,
        log_file=log_file,
        exit_code=exit_code,
        timed_out=timed_out,
        error_note=error_note,
    )


# ── Report writer (Step 7) ────────────────────────────────────────────────────

def _tail_log(log_file: Path, n: int = 30) -> str:
    """Return the last n lines of log_file, or a note if missing/empty."""
    if not log_file.exists():
        return "*(log not available)*"
    text = log_file.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        return "*(log is empty)*"
    lines = text.splitlines()
    return "\n".join(lines[-n:])


def _write_report(
    *,
    path: Path,
    results_path: Path,
    mode: str,
    working_dir: Path,
    passed: list[TestResult],
    outcomes: list[DebugOutcome],
    script: str,
    now: datetime,
) -> None:
    """Write the new grouped-by-test report format."""
    total = len(passed) + len(outcomes)
    n_failed = len(outcomes)
    n_passed = len(passed)
    pct_passed = round(n_passed / total * 100) if total else 0
    pct_failed = round(n_failed / total * 100) if total else 0

    # Unique failing test names
    unique_failing = len({o.result.test for o in outcomes})

    lines: list[str] = []

    # ── Header ────────────────────────────────────────────────────────────────
    lines += [
        "# QA Regression Analysis Report",
        "",
        f"Generated: {now.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Results File: {results_path.resolve()}",
        f"Mode: {'Basic' if mode == 'basic' else 'Slurm'}",
        "",
        "## Summary",
        "",
        f"- Total: {total} | Passed: {n_passed} ({pct_passed}%) | Failed: {n_failed} ({pct_failed}%)",
        f"- Unique failing tests: {unique_failing}",
        "",
        "---",
        "",
    ]

    # ── Group failures by test name ───────────────────────────────────────────
    grouped: dict[str, list[DebugOutcome]] = defaultdict(list)
    for outcome in outcomes:
        grouped[outcome.result.test].append(outcome)

    for section_num, (test_name, test_outcomes) in enumerate(grouped.items(), 1):
        lines += [
            f"## [{section_num}] {test_name}",
            "",
            "| Config | Seed | Exit Code | Error |",
            "|--------|------|-----------|-------|",
        ]

        for o in test_outcomes:
            r = o.result
            config_label = f"{r.gen.upper()}, {r.num_lane}-lane, {r.flit_mode.upper()}, {r.typ}"
            exit_col = str(o.exit_code) if o.exit_code is not None else "—"
            error_col = o.error_note if o.error_note else "—"
            lines.append(f"| {config_label} | {r.seed} | {exit_col} | {error_col} |")

        lines.append("")

        # For each outcome in this group, add debug dir / log / command / evidence
        for o in test_outcomes:
            r = o.result
            dir_name = o.debug_dir.name
            log_name = o.log_file.relative_to(working_dir) if o.log_file.is_relative_to(working_dir) else o.log_file

            lines += [
                f"**Debug Dir:** `{dir_name}/`",
                f"**Log:** `{log_name}`",
                "",
                "**Debug Command:**",
                "```bash",
            ]
            if o.result.debug_command(script):
                lines.append(r.debug_command(script))
            lines += [
                "```",
                "",
                "**Key Log Evidence:**",
                "```",
                _tail_log(o.log_file),
                "```",
                "",
            ]

            if o.timed_out:
                lines.append("> ⚠ Rerun timed out after 2h — log may be incomplete.")
                lines.append("")

        lines += ["---", ""]

    # ── Passed summary ────────────────────────────────────────────────────────
    lines += [
        "## Passed Tests",
        "",
        f"*{n_passed} test(s) passed — details omitted.*",
        "",
    ]

    path.write_text("\n".join(lines), encoding="utf-8")


# ── Public entry-point ────────────────────────────────────────────────────────

def run(
    mode: str | None = None,
    working_dir: str = ".",
    output: str | None = None,
    script: str = "",
    test_filter: str | None = None,
    verbose: bool = False,
    debug: bool = False,
    log: object = None,
) -> None:
    wd = Path(working_dir).resolve()
    package_dir = Path(__file__).parent  # qa_agent/

    print_header("analyse", f"Mode: {mode or 'auto-detect'}")

    effective_mode = "basic"  # will be set during parsing
    step_log = StepLog(command="analyse", mode="basic")

    results_path: Optional[Path] = None
    passed: list[TestResult] = []
    failed: list[TestResult] = []
    source_file: Optional[Path] = None
    effective_script: str = ""
    debug_dirs: dict[TestResult, Path] = {}
    outcomes: list[DebugOutcome] = []
    report_path: Optional[Path] = None

    # ── Step 1: find and read results file ────────────────────────────────────
    with step_gate(1, "Read results file", debug, step_log) as ctx:
        results_path = _find_results(wd)
        
        # Check for sig_pcie in the path
        sig_pcie_dir = None
        for parent in wd.parents:
            if parent.name == "sig_pcie":
                sig_pcie_dir = parent
                break
        if wd.name == "sig_pcie":
            sig_pcie_dir = wd
            
        if not sig_pcie_dir:
            ctx.fail("sig_pcie not found in the current working directory path.")
            
        if sig_pcie_dir and "sig_pcie/verif/AVERY/run/results" not in wd.as_posix():
             ctx.fail("cwd must be within sig_pcie/verif/AVERY/run/results.")
             
        ctx.detail = f"Path: {results_path}"
    if not ctx.ok:
        log_path = write_log(step_log, wd)
        print(f"\n  {cyan('ℹ')}  Log: {log_path}")
        return

    print(f"\n  {green('✓')}  Reading results from: {results_path}")

    # ── Step 2: detect mode & parse ───────────────────────────────────────────
    with step_gate(2, "Parse results", debug, step_log) as ctx:
        effective_mode = mode or _detect_mode(results_path.name)
        step_log.mode = effective_mode
        passed, failed = _parse(results_path)
        total = len(passed) + len(failed)

        if total == 0:
            ctx.fail(
                f"No recognisable test result lines found in '{results_path}'.\n"
                "Check that the file follows the expected format."
            )
        else:
            ctx.detail = f"Passed: {len(passed)} | Failed: {len(failed)}"
    if not ctx.ok:
        log_path = write_log(step_log, wd)
        print(f"\n  {cyan('ℹ')}  Log: {log_path}")
        raise QAAgentError(ctx.error)

    # ── Step 3: --test filter (optional) ─────────────────────────────────────
    if test_filter:
        with step_gate(3, f"Filter by test '{test_filter}'", debug, step_log) as ctx:
            filtered = [r for r in failed if r.test == test_filter]
            if not filtered:
                available = ", ".join(sorted({r.test for r in failed})) or "(none)"
                ctx.fail(
                    f"No failed test named '{test_filter}' found.\n"
                    f"  Failing tests: {available}"
                )
            else:
                skipped = len(failed) - len(filtered)
                failed = filtered
                ctx.detail = f"Matched: {len(filtered)}, skipped: {skipped}"
        if not ctx.ok:
            log_path = write_log(step_log, wd)
            print(f"\n  {cyan('ℹ')}  Log: {log_path}")
            raise QAAgentError(ctx.error)

        print(f"  {yellow('⚑')}  --test filter active: "
              f"focusing on '{bold(test_filter)}' "
              f"{dim(f'({len(failed)} match(es))')}")

    # Banner
    print()
    print(rule())
    print(f"  {cyan('qa-agent analyse')}  {dim('·')}  {bold(results_path.name)}  {dim(f'[{effective_mode}]')}")
    print(
        f"  {green(f'Passed: {len(passed)}')}   "
        f"{(red if failed else dim)(f'Failed: {len(failed)}')}"
        + (f"  {dim(f'(filtered to: {test_filter})')}" if test_filter else "")
    )
    print(rule())

    unique_failing = len({r.test for r in failed})
    print(f"\n  Found {bold(str(len(failed)))} failed test(s) across {bold(str(unique_failing))} unique test name(s).\n")

    # ── Step 4: Find sig_pcie source and script ───────────────────────────────
    step_offset = 1 if test_filter else 0
    with step_gate(3 + step_offset, "Locate source file and script", debug, step_log) as ctx:
        if sig_pcie_dir:
            source_file = sig_pcie_dir / "sourcefile_2025_3.csh"
            if not source_file.exists():
                source_file = None
            
            pl_script = sig_pcie_dir / "verif/AVERY/run/run_apci_2025.pl"
            if pl_script.exists():
                effective_script = str(pl_script)
            else:
                effective_script = ""
                
            ctx.detail = f"source: {source_file.name if source_file else 'None'}, script: {Path(effective_script).name if effective_script else 'None'}"
        else:
            ctx.fail("sig_pcie_dir is somehow missing.")
            
    if not ctx.ok:
        log_path = write_log(step_log, wd)
        print(f"\n  {cyan('ℹ')}  Log: {log_path}")
        return
        
    print(f"  {green('✓')}  Using source file: {source_file if source_file else 'None'}")
    print(f"  {green('✓')}  Using script: {effective_script if effective_script else 'None'}")

    # ── Step 5: create debug directories ──────────────────────────────────────
    if failed:
        with step_gate(4 + step_offset, "Create debug directories", debug, step_log) as ctx:
            print()
            debug_dirs = _create_debug_dirs(failed, wd, verbose=verbose)
            ctx.detail = f"Created: {len(debug_dirs)} directories"
        if not ctx.ok:
            log_path = write_log(step_log, wd)
            print(f"\n  {cyan('ℹ')}  Log: {log_path}")
            return
    else:
        debug_dirs = {}

    # ── Step 6: run debug commands ─────────────────────────────────────────────
    if failed:
        print()
        print(rule())
        print(f"  {cyan('Running debug commands')}  {dim(f'({len(failed)} failure(s))')}")
        print(rule())
        print()

        for i, result in enumerate(failed, 1):
            step_title = f"Debug [{i}/{len(failed)}] {result.test} seed={result.seed}"
            with step_gate(5 + step_offset + (i - 1), step_title, debug, step_log) as ctx:
                outcome = _run_debug(
                    result, debug_dirs[result], effective_script, source_file, i, len(failed),
                    verbose=verbose,
                )
                ctx.detail = f"exit={outcome.exit_code}"
                if outcome.timed_out:
                    ctx.fail("Timed out after 2h")
                elif outcome.exit_code is not None and outcome.exit_code != 0:
                    ctx.detail += " (non-zero, captured in report)"
                    # NOT fatal — debug run errors are expected and captured in report
            outcomes.append(outcome)

        print()
        print(rule())
        print(
            f"  {bold(str(len(failed)))} debug run(s) complete."
            f"  Success: {sum(1 for o in outcomes if not o.timed_out and o.exit_code == 0)}"
            f"  Timeout: {sum(1 for o in outcomes if o.timed_out)}"
            f"  Error: {sum(1 for o in outcomes if not o.timed_out and o.exit_code not in (None, 0))}"
        )
        print(rule())
    else:
        print(f"\n  {green('✓')} All {len(passed)} test(s) passed.\n")

    # ── Step 7: write report ───────────────────────────────────────────────────
    report_step_num = 5 + step_offset + len(failed) if failed else 5 + step_offset
    now = datetime.now()
    report_path = (
        Path(output) if output
        else Path.cwd() / f"qa_report_{now.strftime('%Y%m%d_%H%M%S')}.md"
    )

    with step_gate(report_step_num, "Write report", debug, step_log) as ctx:
        _write_report(
            path=report_path,
            results_path=results_path,
            mode=effective_mode,
            working_dir=wd,
            passed=passed,
            outcomes=outcomes,
            script=effective_script,
            now=now,
        )
        ctx.detail = f"Path: {report_path.resolve()}"
    if not ctx.ok:
        log_path = write_log(step_log, wd)
        print(f"\n  {cyan('ℹ')}  Log: {log_path}")
        return

    print(f"\n  {green('✓')}  Report written to: {report_path.resolve()}\n")

    # ── Write step log in debug mode or on failure ─────────────────────────────
    has_failure = any(s.status == "FAILED" for s in step_log.steps)
    if debug or has_failure:
        step_log_path = write_log(step_log, wd)
        print(f"  {cyan('ℹ')}  Step log: {step_log_path}\n")
