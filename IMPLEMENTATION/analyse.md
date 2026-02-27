# `qa-agent analyse` — Implementation Plan

Parse a regression results file, identify failed test cases, create an isolated debug directory for each failed case inside the `sig_pcie` workspace, re-run the debug commands, capture logs, and write a single Markdown QA report to disk.

---

## Command

```bash
qa-agent analyse [--mode basic|slurm] [--working-dir <path>] [--output <path>] [--script/-s <script>]
```

---

## Execution Steps

### Step 1 — Check Path for `sig_pcie`

Ensure `sig_pcie/verif/AVERY/run/results` is in the `cwd`'s absolute path. The tool parses `cwd` (or `--working-dir`) to verify it is located inside the `sig_pcie/verif/AVERY/run/results/` target regression directory.

### Step 2 — Read the Results File

Look for `results.doc` or `results_new.doc` inside `--working-dir` (`cwd`). Open and parse the failed tests natively via Python regex without AI. It checks specific configs, seed values, and exact test names.

### Step 3 — Locate Environment Source and Scripts

- Instead of interactively choosing scripts, implicitly retrieve `sourcefile_2025_3.csh` from the `sig_pcie` relative parent.
- Retrieve the debug Perl script `run_apci_2025.pl` from `sig_pcie/verif/AVERY/run/run_apci_2025.pl`. 

### Step 4 — Create Debug Subdirectories & Run Commands

For every failed entry:
1. Create a `debug_<testcase_name>` directory inside `--working-dir`.
2. Generate the debug command using the dynamically extracted script: `<script> -t <test> -s mti64 -visualizer -debug -T ... -file ... -R " <config_flags>" -n <seed>`.
3. Wrap it in a subshell sourcing `sourcefile_2025_3.csh` and execute with a 2-hour timeout.
4. Capture logs directly to the test case's `debug_.../debug.log` file.

### Step 5 — Markdown QA Report

Generate `qa_report_<YYYYMMDD_HHMMSS>.md` summarizing metrics, failures, commands used, and embedding `debug.log` excerpts (key log evidence).
