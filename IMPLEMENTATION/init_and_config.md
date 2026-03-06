# `qa-agent init` and `qa-agent config` — Implementation Plan

> **Status:** Implemented
> **Module:** `qa_agent/init.py` and `qa_agent/config.py`
> **CLI sub-command:** `qa-agent init [root]` and `qa-agent config`

---

## Overview

The `init` and `config` commands introduce a robust configuration management system for `qa-agent`, replacing hard-coded scripts and environment variables. 
The system relies on a central `qa-agent.yaml` configuration file that resides at the root of a project.

- `qa-agent init`: An interactive wizard that scans the project directory, auto-detects required files (like `.csh` source files, regression scripts, debug perl scripts), and guides the user to confirm them. It generates the `qa-agent.yaml` file.
- `qa-agent config`: A simple utility that opens the discovered `qa-agent.yaml` in the user's `$EDITOR` (defaulting to `vim`) for quick manual edits.

This configuration is then consumed by the `regression` and `analyse` commands to dynamically locate files, allowing `qa-agent` to work seamlessly across different project structures.

---

## CLI Interface

### `init` Command

```bash
qa-agent init [root] [--force] [--use_defaults]
```

| Flag | Short | Default | Effect |
|------|-------|---------|--------|
| `root` | — | Auto-detected | Project root directory. If omitted, the tool searches upwards for an `RTL/` directory heuristic. |
| `--force` | `-f` | off | Overwrite existing `qa-agent.yaml` without prompting. |
| `--use_defaults` | — | off | Skip the interactive wizard; auto-detect paths and use all default values. |

### `config` Command

```bash
qa-agent config
```

Opens the `qa-agent.yaml` configuration file in the user's preferred editor (`$EDITOR`). If no configuration is found, prompts the user to run `qa-agent init`.

---

## Execution Pipeline

### Initialization Wizard (`init.py`)

1. **Step 1: Project Root Discovery**
   - Resolves the project root. If not provided, it walks up the directory tree looking for an `RTL/` subdirectory as a heuristic sign of the project root.
2. **Step 2: Results Directory**
   - Finds the regression results directory (e.g., `verif/AVERY/run/results`) under the root.
3. **Step 3: Source File Locator**
   - Searches for the environment setup script (default: `sourcefile_2025_3.csh`) under the root.
4. **Step 4: Basic Regression Script**
   - Searches for the standard regression Python script (default: `regression_8B_16B_questa.py`).
5. **Step 5: Slurm Files**
   - Identifies the Slurm regression script (`regression_slurm_questa_2025.py`), launcher script (`run_questa.sh`), and config file (`config.txt`).
6. **Step 6: Debug Script**
   - Finds the Perl debug script (`run_apci_2025.pl`) used by `qa-agent analyse`.
7. **Step 7: Output Filenames**
   - Configures the expected output filenames for Basic (`results.doc`) and Slurm (`results_new.doc`) regressions.
8. **Step 8: Fixed Simulator Flags**
   - Prompts the user to review and optionally edit the fixed simulator flags (e.g., `+define+PIPE_BYTEWIDTH_16`) appended during the `analyse` debug generation for both Endpoint (EP) and Root Complex (RC).
9. **Finalization**
   - Presents a configuration summary and saves the settings to `qa-agent.yaml` at the project root.

### Automated Mode (`--use_defaults`)
Bypasses interactive prompts, relying entirely on the auto-detection algorithms to locate the deepest/best-matching files and directories, failing gracefully if files are missing.

### Config Management (`config.py`)
- Provides the `QAConfig` dataclass and parsing logic.
- Implements `find_config()` which traverses upwards from the current working directory to locate `qa-agent.yaml`.
- Handles loading via PyYAML and provides absolute path resolutions for all discovered files.
- Throws meaningful `ConfigError`s if essential files/keys are missing or if PyYAML is not installed.
