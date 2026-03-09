# `qa-agent report` — AI-Driven Debug Report from Simulation Output

## Purpose

Generate a structured debug report from Questa/Visualizer simulation output. All simulation data is pre-collected from the output directory and fed to the AI in a single prompt — the AI analyses it and produces a Markdown report in one streaming pass. No agentic tool-calling loop is used in the default flow.

---

## Architecture

### Current: Stream-Based (Prefetch Model)

```
Questa/Visualizer output directory
  (debug.log, mti.log, tracker_*.txt, sfi_*.txt, qrun.out/)
        │
  [report_prefetch.py]   ── discovers + reads all files, filters, sanitizes, smart windows
        │
  [agents/dv_debug_agent.py]  ── builds system + user prompt (sim data embedded)
        │
  [provider.stream()]    ── claude/openai/gemini streaming API
        │
  [report.py]            ── orchestrator: CLI args → (batch discover) → prefetch → AI → write report + aggregate
```

### Data Flow

```
report.py
  │
  ├─► report_prefetch.collect_sim_data(sim_dir)
  │         │
  │         ├─ _discover_files()          discovers debug.log, mti.log, tracker_*.txt, sfi_*.txt
  │         ├─ _collect_stats_summary()   reads qrun.out/stats_log
  │         ├─ _collect_test_config()     reads qrun.out/big_argv (dir or file), version, top_dus
  │         ├─ _collect_debug_log()       reads debug.log → errors + UVM summary + tail
  │         ├─ _collect_mti_log()         reads mti.log → errors only
  │         ├─ _collect_tracker_data()    reads tracker_*.txt → 5 failure categories only
  │         ├─ _collect_sfi_data()        reads sfi_*.txt → first 50 lines each
  │         ├─ _collect_coverage()        reads *coverage*.txt
  │         └─ _sanitize()               strips sim_dir path, home dirs, hostname, API keys
  │
  ├─► agents/dv_debug_agent.build_prompt(sim_data)
  │         └─ wraps sim data in system prompt + user message → ProviderRequest
  │
  └─► provider.stream(request)
            └─ streams AI response → assembled → written to .md file
```

### Preserved: Agentic (Tool-Calling) Infrastructure

The original agentic approach (AI calls tools interactively) is preserved but **not used by default**. It lives at:

```
qa_agent/tools/loop.py                   ── agentic tool dispatch loop
qa_agent/tools/registry.py              ── ToolDef, ToolResult, ToolRegistry
qa_agent/tools/report/                  ── tool handlers (log_errors, assertions, etc.)
qa_agent/agents/dv_debug_agent_agentic.py  ── agentic agent persona (if exists)
```

---

## Package Layout

```
qa_agent/
├── report_prefetch.py                  # Data collection: discovers + reads sim output files
├── report.py                           # Thin orchestrator: CLI args → prefetch → AI → write
│
├── agents/
│   ├── __init__.py
│   └── dv_debug_agent.py              # Stream-based: system prompt + build_prompt() + runner
│
└── tools/                              # Agentic tool infrastructure (preserved, not default)
    ├── __init__.py
    ├── registry.py                     # ToolDef, ToolResult, ToolRegistry
    ├── loop.py                         # Agentic loop
    └── report/
        ├── __init__.py                 # build_report_tools(sim_dir) → ToolRegistry
        ├── security.py                 # validate_path(), truncate_output()
        ├── sim_metadata.py             # list_sim_files, read_sim_metadata
        ├── log_errors.py               # extract_log_errors
        ├── assertions.py               # get_assertion_failures
        ├── scoreboard.py               # get_scoreboard_mismatches
        ├── tracker.py                  # extract_tracker_failures
        ├── signals.py                  # read_signal_values
        └── fixtures.py                 # Test fixture generator (mock sim data)
```

---

## Real Questa/Visualizer Output Directory Structure

The prefetch is designed around the actual Questa qrun output layout:

```
<sim_dir>/
├── debug.log                      # Main simulation log (vsim output)
├── mti.log                        # Questa/MTI internal diagnostics
├── mti.cmd                        # MTI command file
├── design.bin                     # Compiled design binary (skipped — binary)
├── qwave.db                       # Waveform database (skipped — binary)
├── apci_coverage_report.txt       # Functional coverage report
├── sfi_data_app_ep.txt            # SFI data transactions
├── sfi_glob_app_ep.txt            # SFI global interface
├── sfi_hdr_app_ep.txt             # SFI header transactions
├── tracker_cfg_ep_app_bfm.txt     # Config layer tracker (EP side)
├── tracker_cfg_rc.txt             # Config layer tracker (RC side)
├── tracker_dll_flit_rc.txt        # DLL flit tracker
├── tracker_dll_rc.txt             # DLL tracker
├── tracker_phy_flit_rc.txt        # PHY flit tracker
├── tracker_phy_rc.txt             # PHY tracker
├── tracker_tl_ep_app_bfm.txt      # TL tracker (EP side)
├── tracker_tl_rc.txt              # TL tracker (RC side)
├── work/                          # Compiled library (skipped — binary dir)
└── qrun.out/
    ├── big_argv/                  # Directory containing vlog_work_*.f filelist
    │   └── vlog_work_<hash>.f    # Full vlog command line + filelist
    ├── history
    ├── history.cnt
    ├── sessions/
    ├── snapshot/
    ├── stats_log                  # vlog/vopt/vsim/qrun error+warning counts
    ├── top_dus                    # Compiled design units
    └── version                   # Questa tool version
```

> **Note on `big_argv`**: In recent Questa versions, `qrun.out/big_argv` is a **directory** containing a single `.f` file (e.g. `vlog_work_b402oC34PUd0F1NA1.f`). The prefetch handles both the directory form and the legacy plain-file form.

---

## Security Model

The AI receives **pre-collected, sanitized data** — it never accesses the filesystem directly.

### Path Containment (`tools/report/security.py`)
- All file reads go through `validate_path()` which resolves symlinks and asserts the path is within `sim_dir`
- Raises `PathError` on any traversal attempt

### Content Sanitization (`report_prefetch._sanitize()`)
The entire context block is sanitized before being embedded in the prompt:

| What is stripped | Replaced with |
|-----------------|---------------|
| `sim_dir` absolute path | `<SIM_DIR>` |
| Home directory paths (`/home/<user>/`, `/Users/<user>/`) | `<HOME>/` |
| Machine hostname | `<HOST>` |
| API key patterns (`sk-ant-`, `sk-...`, `AIza...`) | `<REDACTED>` |

### Tracker Data Filtering (Smart Windowing)
Tracker files (`tracker_*.txt`) are evaluated to extract failures while avoiding context limit overflows:
- The prefetch searches for 5 failure categories: ASSERT failures, SCOREBOARD mismatches, TIMEOUT events, FATAL errors, and Transaction mismatches.
- **Smart Sizing**: If extracting 500 lines of context per error exceeds 20,000 tracker lines total, the extract logic automatically falls back to 100 lines per error.
- **Windowed Context**: The AI receives the top 50 lines (for configuration context), the N lines preceding the error (either 500 or 100), the error line itself, and the 20 lines succeeding the error. Non-relevant transaction stretches are skipped and replaced with a `... [Lines skipped] ...` marker to save tokens.
- Files with no matching events are **silently skipped** — no noise.

### Output Size Caps
- **32,000 characters** per section
- **150,000 characters** total context (prevents context window overflow)
- Truncated sections flagged with `*[Section truncated at size limit]*`

### Read-Only
- No file writes in the prefetch layer
- Binary files (`design.bin`, `qwave.db`, `work/`) are automatically skipped

---

## Data Sections Fed to AI

Sections are collected in debugging priority order:

| # | Section | Source | What is collected |
|---|---------|--------|-------------------|
| 1 | Build & Simulation Status | `qrun.out/stats_log` | vlog/vopt/vsim/qrun error+warning counts |
| 2 | Test Configuration & Metadata | `qrun.out/big_argv/`, `version`, `stats_log`, `top_dus` | Full command line, tool version, design units |
| 3 | Simulation Log (debug.log) | `debug.log` | All error blocks (5 lines before, 8 after), UVM Report Summary, last 150 lines |
| 4 | Questa Diagnostics (mti.log) | `mti.log` | Error blocks only |
| 5 | Tracker Data | `tracker_*.txt` | Only: ASSERT / SCOREBOARD / TIMEOUT / FATAL / transaction mismatch lines |
| 6 | SFI Interface Data | `sfi_*.txt` | First 50 lines per file |
| 7 | Coverage Report | `*coverage*.txt` | Full content (capped at 32KB) |

---

## Agent: DV Debug Expert (`agents/dv_debug_agent.py`)

### Persona
Senior DV engineer specialising in Siemens EDA Questa/Visualizer and PCIe/APCI silicon verification. Deep knowledge of UVM methodology, SVA assertions, Questa error codes, PCIe protocol, per-component tracker files, and SFI fabric.

### Analysis Methodology (step-by-step, enforced in system prompt)

1. **Build Status Check** — inspect `stats_log` error counts per stage (vlog, vopt, vsim, qrun). If compile errors: classify and stop.
2. **Simulation Log Analysis** — UVM Report Summary counts + log tail (test verdict/exit status).
3. **First Error Identification** — find the chronologically first error by timestamp. First error = root cause; subsequent = cascading.
4. **Failure Classification** — one of: Assertion Failure | Scoreboard Mismatch | Compile Error | Timeout | Protocol Violation | Sequence Error | Phase Error | Link Training Failure.
5. **Root Cause Analysis** — cross-reference error with tracker events, SFI data, test configuration (plusargs, seed).
6. **Evidence Chain** — time-ordered sequence of events across all data sources.

### Output Format (enforced by system prompt)

```markdown
## Executive Summary
## Failure Classification
## Root Cause Analysis
  ### Evidence Chain
  ### Analysis
## Failure Timeline
## Debugging Recommendations
```

Recommendations include: Visualizer waveform timestamps + signal names, specific tracker files to examine, re-run plusarg suggestions.

---

## CLI Interface

```
qa-agent report [SIM_DIR] [--provider/-p {claude,openai,gemini}]
                          [--output/-o PATH]
                          [--verbose/-v]
                          [--gvim]
```

| Flag | Default | Description |
|------|---------|-------------|
| `SIM_DIR` | (optional) | Questa/Visualizer output directory. If omitted, runs in Batch Mode (iterates over all `debug_*` subdirectories, or the current directory if prefixed with `debug_`). |
| `--provider/-p` | `claude` | AI provider: claude, openai, gemini |
| `--output/-o` | `debug_report_<timestamp>.md` | Output Markdown path (only used if a single directory is processed) |
| `--verbose/-v` | off | Stream AI output to stdout while generating |
| `--gvim` | off | Open assembled prompt in gvim for review before sending |

## Report Generation Output

When running `qa-agent report`, two levels of output are generated:

### 1. Individual Directory Report
Written inside the simulation directory (e.g., `debug_apcit_cpl_out_order_1234/QA-AGENT_REPORT_<timestamp>.md`).
- Contains the exact AI Analysis (Executive Summary, Root Cause Analysis).
- Contains the **Raw Simulation Data** and **Metadata** passed to the AI.
- **Note:** The instructional prompt itself is stripped out to keep the report clean for end-users.

### 2. Summary Aggregate Report
Written in the parent directory (from where `qa-agent report` was called) as `QA-AGENT_REPORT_<timestamp>.md`.
- Aggregates the `Executive Summary` and `Failure Classification` for every failing testcase directory discovered.
- Contains direct links to the full individual reports.

> `--max-turns` is accepted for CLI compatibility but unused in stream mode.

---

## Testing

### Fixture System (`tools/report/fixtures.py`)

Creates mock simulation directories for testing (uses the `logs/` layout, not real Questa layout).

| Scenario | What it plants |
|----------|---------------|
| `assertion_failure` | SVA assertion failure in `logs/sim.log` |
| `scoreboard_mismatch` | Expected vs actual mismatch entries |
| `compile_error` | Compilation errors in `logs/compile.log` |
| `timeout` | Simulation timeout |
| `multi_failure` | Multiple failure types combined |

```bash
# Generate a fixture and run report against it
python3 -c "from qa_agent.tools.report.fixtures import create_fixture; \
            create_fixture('/tmp/test_sim', 'assertion_failure')"
qa-agent report /tmp/test_sim --verbose
```

> **Note**: Fixtures use the `logs/sim.log` layout. Against a real Questa output directory, the prefetch discovers `debug.log` and `tracker_*.txt` instead.

---

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `anthropic` / `claude-agent-sdk` | latest | Claude streaming (stream-based flow) |
| `openai` | existing | OpenAI streaming |
| `google-genai` | existing | Gemini streaming |
