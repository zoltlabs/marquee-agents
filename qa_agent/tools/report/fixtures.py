"""qa_agent/tools/report/fixtures.py

Test fixture generator — creates realistic mock simulation directories for
testing the report command without real Visualizer/Questa output.

Usage:
    from qa_agent.tools.report.fixtures import create_fixture
    create_fixture('/tmp/test_sim', 'assertion_failure')
    # Then: qa-agent report /tmp/test_sim --verbose
"""

from __future__ import annotations

import os
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Scenario content templates
# ─────────────────────────────────────────────────────────────────────────────

_METADATA = {
    "big_argv": (
        "questa_sim -do 'vsim -c -do sim.do work.tb_apci' -lib work\n"
        "+define+APCI_MAX_DATA_WIDTH=64\n"
        "+define+PIPE_BYTEWIDTH=4\n"
        "-sv_seed 1234\n"
        "-G TIMEOUT=100000\n"
    ),
    "history": "Run started: 2025-01-15 09:12:34\nPrevious run: 2025-01-14 22:01:00\n",
    "stats_log": (
        "Total tests: 1\n"
        "Passed: 0\n"
        "Failed: 1\n"
        "Compile time: 45.2s\n"
        "Simulation time wall-clock: 12.3s\n"
    ),
    "top_dus": "work.tb_apci\nwork.apci_top\nwork.pcie_core\n",
    "version": "Questa Sim-64 2024.1 Linux 64-Bit\nCompiler version: 2024.1\n",
}

_SCENARIOS: dict[str, dict[str, str]] = {
    "assertion_failure": {
        "logs/compile.log": (
            "# Starting compilation...\n"
            "# Compiling module apci_rx\n"
            "# Compiling module apci_tx\n"
            "# Compilation completed with 0 errors, 0 warnings.\n"
        ),
        "logs/sim.log": (
            "# Loading design...\n"
            "# Simulation started at time 0\n"
            "# @ 1000 ns: Initialization complete\n"
            "# @ 5000 ns: Starting test sequence\n"
            "** Error: (vsim-8684) /work/tb/apci_rx.sv(142): Assertion error: rx_data_valid_check\n"
            "  Time: 12345 ns  Scope: tb_apci.dut.apci_rx  File: apci_rx.sv  Line: 142\n"
            "** Error: Assertion 'rx_data_valid_check' Failed at time 12345\n"
            "  Expected: rx_data_valid == 1 when rx_ready is asserted\n"
            "  Actual:   rx_data_valid = 0\n"
            "** Fatal: Too many assertion failures (limit=5). Simulation aborted.\n"
            "# Simulation FAILED\n"
        ),
        "tracker.log": (
            "@ 1000 ns [APCI_RX] INIT: Receiver initialized\n"
            "@ 5000 ns [APCI_RX] START: Data reception started\n"
            "@ 12345 ns [APCI_RX] ERROR: Assertion failure in rx_data_valid_check\n"
            "@ 12345 ns [SYSTEM] FATAL: Aborting due to assertion failure\n"
        ),
        "signals.log": (
            "# 12000 ns apci_rx.state = IDLE\n"
            "# 12100 ns apci_rx.rx_ready = 1\n"
            "# 12200 ns apci_rx.rx_data_valid = 0\n"
            "# 12345 ns apci_rx.rx_data_valid = 0\n"
            "# 12400 ns apci_rx.state = ERROR\n"
        ),
    },
    "scoreboard_mismatch": {
        "logs/compile.log": (
            "# Starting compilation...\n"
            "# Compilation completed with 0 errors, 0 warnings.\n"
        ),
        "logs/sim.log": (
            "# Loading design...\n"
            "# Simulation started\n"
            "# @ 3000 ns: Test started — apcit_cpl_out_order\n"
            "UVM_ERROR @ 8500 ns [SCOREBOARD] Mismatch detected!\n"
            "  Component: apci_scoreboard\n"
            "  Expected: 8'hA5 (TLP completion data)\n"
            "  Actual:   8'h00 (received)\n"
            "UVM_ERROR @ 9100 ns [SCOREBOARD] Mismatch detected!\n"
            "  Component: apci_scoreboard\n"
            "  Expected: 8'hFF\n"
            "  Actual:   8'h0F\n"
            "UVM_FATAL @ 10000 ns [TIMEOUT] Simulation timeout after 10000 ns\n"
            "# Simulation FAILED\n"
        ),
        "tracker.log": (
            "@ 3000 ns [TEST] START: apcit_cpl_out_order\n"
            "@ 8500 ns [SCOREBOARD] mismatch: expected=0xA5 actual=0x00\n"
            "@ 9100 ns [SCOREBOARD] mismatch: expected=0xFF actual=0x0F\n"
            "@ 10000 ns [SYSTEM] TIMEOUT: simulation aborted\n"
        ),
    },
    "compile_error": {
        "logs/compile.log": (
            "# Starting compilation...\n"
            "** Error: /work/rtl/apci_pkg.sv(55): Syntax error near token 'endpackage'.\n"
            "** Error: /work/rtl/apci_rx.sv(12): Undefined variable 'APCI_WIDTH'.\n"
            "  Did you mean 'APCI_MAX_DATA_WIDTH'?\n"
            "** Error: 2 errors found. Compilation FAILED.\n"
        ),
        "logs/sim.log": "# Simulation did not run (compilation failed).\n",
    },
    "timeout": {
        "logs/compile.log": (
            "# Starting compilation...\n"
            "# Compilation completed with 0 errors, 0 warnings.\n"
        ),
        "logs/sim.log": (
            "# Loading design...\n"
            "# Simulation started\n"
            "# @ 0 ns: Reset asserted\n"
            "# @ 100 ns: Reset deasserted\n"
            "# @ 500 ns: Waiting for DUT to complete initialization...\n"
            "UVM_FATAL @ 100000 ns [TIMEOUT] Simulation timeout: DUT did not complete.\n"
            "  Possible causes: deadlock, missing interrupt, clock not running.\n"
            "# Simulation FAILED (timeout)\n"
        ),
        "tracker.log": (
            "@ 0 ns [SYSTEM] RESET: asserted\n"
            "@ 100 ns [SYSTEM] RESET: deasserted\n"
            "@ 100000 ns [SYSTEM] FATAL: timeout — simulation exceeded time limit\n"
        ),
    },
    "multi_failure": {
        "logs/compile.log": (
            "# Starting compilation...\n"
            "** Warning: /work/rtl/apci_rx.sv(30): Implicit net declaration.\n"
            "# Compilation completed with 0 errors, 1 warning.\n"
        ),
        "logs/sim.log": (
            "# Loading design...\n"
            "# Simulation started\n"
            "** Error: (vsim-8684) /work/tb/apci_rx.sv(142): Assertion error: rx_valid_check\n"
            "  Time: 5000 ns\n"
            "UVM_ERROR @ 7500 ns [SCOREBOARD] Mismatch: expected=0xAB actual=0xCD\n"
            "UVM_ERROR @ 8000 ns [SCOREBOARD] Mismatch: expected=0x12 actual=0x34\n"
            "UVM_FATAL @ 10000 ns [TIMEOUT] Simulation timeout.\n"
            "# Simulation FAILED\n"
        ),
        "tracker.log": (
            "@ 5000 ns [APCI_RX] ERROR: assertion failure rx_valid_check\n"
            "@ 7500 ns [SCOREBOARD] mismatch: expected=0xAB actual=0xCD\n"
            "@ 8000 ns [SCOREBOARD] mismatch: expected=0x12 actual=0x34\n"
            "@ 10000 ns [SYSTEM] FATAL: timeout\n"
        ),
        "signals.log": (
            "# 4900 ns apci_rx.rx_valid = 1\n"
            "# 5000 ns apci_rx.rx_valid = 0\n"
            "# 5100 ns apci_rx.state = ERROR\n"
        ),
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

SCENARIOS = list(_SCENARIOS.keys())


def create_fixture(target_dir: str | Path, scenario: str) -> Path:
    """Create a mock simulation output directory for testing.

    Args:
        target_dir: Directory to create (will be created if it does not exist).
        scenario:   One of: assertion_failure, scoreboard_mismatch,
                    compile_error, timeout, multi_failure.

    Returns:
        Path to the created simulation directory.

    Raises:
        ValueError: If the scenario name is not recognised.
    """
    if scenario not in _SCENARIOS:
        raise ValueError(
            f"Unknown scenario '{scenario}'. Available: {', '.join(SCENARIOS)}"
        )

    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)

    # Always create the qrun.out/ metadata directory
    qrun = target / "qrun.out"
    qrun.mkdir(exist_ok=True)
    for name, content in _METADATA.items():
        (qrun / name).write_text(content, encoding="utf-8")

    # Ensure logs/ directory exists
    (target / "logs").mkdir(exist_ok=True)

    # Write scenario-specific files
    for rel_path, content in _SCENARIOS[scenario].items():
        file_path = target / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")

    return target
