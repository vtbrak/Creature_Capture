#!/bin/bash
# Creature Capture - start the program on macOS (run "Install Creature Capture.command" first).
cd "$(dirname "$0")/app" || exit 1  # the program files
ENV_NAME=creature_capture
source scripts/find_conda.sh
if ! conda activate "$ENV_NAME" 2>/dev/null; then
    echo "The '$ENV_NAME' environment is not installed. Run \"Install Creature Capture.command\" first."
    read -r -p "Press Return to close." _
    exit 1
fi
python run_creature_capture.py "$@"
status=$?
if [ $status -ne 0 ]; then
    echo ""
    echo "Creature Capture exited with an error (code $status)."
    read -r -p "Press Return to close." _
fi
