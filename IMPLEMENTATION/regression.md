# `qa-agent regression` — Implementation Plan

> **Status:** Implemented
> **Module:** `qa_agent/regression.py`
> **CLI sub-command:** `qa-agent regression [source]`

---

## Overview

Automate the full regression run lifecycle for the `sig_pcie` workspace. The approach ensures the user runs tests within `sig_pcie/verif/AVERY/run/results/<source>/` rather than arbitrarily in the `cwd` using package-bundled scripts. It sources the environment, locates required input files (`filelist.txt`, `config.txt`, scripts) directly from the `sig_pcie` environment, executes the regression in either **basic** or **slurm** mode, streams stdout to the terminal, and verifies the expected results artefact.

---

## CLI Interface

```bash
qa-agent regression [source] [--slurm] [--verbose/-v]
```

| Flag | Short | Default | Effect |
|------|-------|---------|--------|
| `source` | — | None | The target directory name within `sig_pcie/verif/AVERY/run/results/`. If missing, the user is prompted interactively. |
| `--slurm` | — | off | Run in Slurm mode instead of basic regression |
| `--verbose` | `-v` | off | Print detailed progress (resolved paths, full commands) |

---

## Execution Pipeline

### Step 1 — Check Directory Path & Target Source

- Check for `sig_pcie/verif/AVERY/run/results` in `cwd`. If it doesn't exist, error out.
- If `source` is missing and `cwd` is directly inside `results/`, automatically use `cwd` name as source.
- Else, interactively ask for it.
- Resolve `target_dir` as `sig_pcie/verif/AVERY/run/results/<source>`. If it doesn't exist, create it.
- Locate the `.csh` environment source file: `sig_pcie/sourcefile_2025_3.csh`.

### Step 2 — Basic Regression (if `--slurm` omitted)

- Copy `regression_8B_16B_questa.py` from `sig_pcie/verif/AVERY/run/` to `target_dir`.
- Check if `target_dir` has `filelist.txt`.
  - If yes and in `cwd`, ask whether to use it or the bundled default from `qa-agent`.
  - Else if missing, ask the user to use the bundled default. If no, exit with a message.
- Execute `python3 regression_8B_16B_questa.py filelist.txt` inside `target_dir`.

### Step 3 — Slurm Regression (if `--slurm` passed)

- Copy `regression_slurm_questa_2025.py` and `run_questa.sh` from `sig_pcie/verif/AVERY/run/questa_slurm/` to `target_dir`.
- Check `filelist.txt` in `target_dir` (same as Basic mode).
- Check `config.txt` in `target_dir`.
  - If yes and in `cwd`, ask whether to use it, the one from `questa_slurm`, or the bundled default from `qa-agent`.
  - If missing, prompt to copy from `questa_slurm/config.txt`.
  - Alternatively, copy the bundled fallback from `qa-agent`.
- Execute `./run_questa.sh filelist.txt config.txt regression_slurm_questa_2025.py` inside `target_dir`.

### Step 4 — Log Capture & Verification

- Output is streamed live while being captured to `regression_<mode>_<timestamp>.log` inside the `target_dir`.
- After completion, verify if `results.doc` (Basic) or `results_new.doc` (Slurm) exists.
- The step log dump is skipped at the end unless running in `--debug` mode (dumped to `cwd` as `qa-agent_regression_<timestamp>.log`).
