#!/bin/bash
# run_questa.sh — Slurm regression launcher
# Usage: ./run_questa.sh <filelist.txt> <config.txt> <slurm_script.py>

set -euo pipefail

FILELIST="${1:?Usage: $0 <filelist.txt> <config.txt> <slurm_script.py>}"
CONFIG="${2:?Usage: $0 <filelist.txt> <config.txt> <slurm_script.py>}"
SLURM_SCRIPT="${3:?Usage: $0 <filelist.txt> <config.txt> <slurm_script.py>}"

echo "Running Slurm regression..."
echo "  Filelist : $FILELIST"
echo "  Config   : $CONFIG"
echo "  Script   : $SLURM_SCRIPT"
echo ""

python3 "$SLURM_SCRIPT" "$FILELIST" "$CONFIG"
