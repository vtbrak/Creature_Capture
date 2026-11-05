#!/bin/bash
# Creature Capture - install (or update) the conda environment on macOS.
# Double-click in Finder. First time: right-click > Open if macOS blocks it.
cd "$(dirname "$0")" || exit 1
ENV_NAME=creature_capture
source scripts/find_conda.sh

if conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
    echo "Updating existing environment '$ENV_NAME'..."
    conda env update -n "$ENV_NAME" -f environment.yml --prune || { read -r -p "FAILED. Press Return to close." _; exit 1; }
else
    echo "Creating environment '$ENV_NAME' (this can take several minutes)..."
    conda env create -n "$ENV_NAME" -f environment.yml || { read -r -p "FAILED. Press Return to close." _; exit 1; }
fi

conda activate "$ENV_NAME"
echo ""
echo "Running self-test..."
python run_creature_capture.py --self-test
echo ""
echo "Done. Start the program with run_mac.command"
read -r -p "Press Return to close." _
