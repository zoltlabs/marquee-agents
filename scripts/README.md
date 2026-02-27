# scripts/ — Bundled Default Files

This directory contains the **default/bundled resource files** that `qa-agent` ships with.
These are used as fallbacks when the user does not have the required files in their working directory.

---

## File Reference

| File | Used By | Purpose |
|------|---------|---------|
| `sourcefile_2025_3.csh` | `qa-agent regression`, `qa-agent analyse` | Environment setup — sources the correct shell env for the simulator. Auto-selected when no `.csh` file is found in the user's working directory. |
| `filelist.txt` | `qa-agent regression` | Default test filelist. Offered to the user if no `filelist.txt` is found in their working directory. |
| `config.txt` | `qa-agent regression --slurm` | Slurm configuration. Offered as a fallback when no `config.txt` is found in the working directory. |
| `run_questa.sh` | `qa-agent regression --slurm` | Slurm launcher script. Auto-selected when no `run_questa.sh` is found in the working directory. |
| `regression_8B_16B_questa.py` | `qa-agent regression` (basic mode) | Basic regression runner. Auto-selected when no matching `regression*.py` is found in the working directory. |
| `regression_slurm_questa_2025.py` | `qa-agent regression --slurm` | Slurm regression runner. Auto-selected when no matching `regression*slurm*.py` is found in the working directory. |
| `run_apci_2025.pl` | `qa-agent analyse` | Default debug Perl script embedded in generated debug commands. Offered when no `.pl` file is found. |

---

## How Fallback Selection Works

For each command, `qa-agent` follows this priority order:

1. **User's working directory** — files in the directory where the user runs `qa-agent`.
2. **`scripts/` directory** — bundled defaults shipped with `qa-agent` (this folder).

If both exist, the interactive arrow-key selector is shown so the user can pick.
If only the bundled default exists, it is auto-selected (or offered with `[Y/n]` for `.txt` files).

---

## Updating the Defaults

To update a bundled default file, simply replace the file in this directory and reinstall:

```bash
pip install -e .    # re-install in editable mode (dev)
# or
pip install .       # production install
```
