#!/bin/bash
# Locate Anaconda/Miniconda/Miniforge and load conda into this shell by
# sourcing <conda base>/etc/profile.d/conda.sh. Sourced by the .command files in the folder above app/.
# Override by setting CONDA_BASE before running, e.g. CONDA_BASE=~/miniforge3

find_conda_sh() {
    local candidates=()
    [ -n "$CONDA_BASE" ] && candidates+=("$CONDA_BASE")
    if command -v conda >/dev/null 2>&1; then
        candidates+=("$(conda info --base 2>/dev/null)")
    fi
    [ -n "$CONDA_EXE" ] && candidates+=("$(dirname "$(dirname "$CONDA_EXE")")")
    candidates+=(
        "$HOME/anaconda3" "$HOME/miniconda3" "$HOME/miniforge3" "$HOME/mambaforge"
        "$HOME/opt/anaconda3" "$HOME/opt/miniconda3"
        "/opt/anaconda3" "/opt/miniconda3" "/opt/miniforge3"
        "/opt/homebrew/anaconda3" "/opt/homebrew/Caskroom/miniconda/base"
        "/opt/homebrew/Caskroom/miniforge/base" "/usr/local/anaconda3"
        "/usr/local/Caskroom/miniconda/base" "/usr/local/miniconda3"
        "/Applications/anaconda3"
    )
    local base
    for base in "${candidates[@]}"; do
        if [ -n "$base" ] && [ -f "$base/etc/profile.d/conda.sh" ]; then
            echo "$base/etc/profile.d/conda.sh"
            return 0
        fi
    done
    # Last resort: search the home folder (slow, but only if nothing else worked)
    local found
    found=$(find "$HOME" -maxdepth 4 -path "*/etc/profile.d/conda.sh" 2>/dev/null | head -n 1)
    if [ -n "$found" ]; then
        echo "$found"
        return 0
    fi
    return 1
}

CONDA_SH="$(find_conda_sh)"
if [ -z "$CONDA_SH" ]; then
    echo ""
    echo "ERROR: Could not find Anaconda / Miniconda (no etc/profile.d/conda.sh found)."
    echo "Install Anaconda or Miniconda, or run again with CONDA_BASE set, e.g.:"
    echo "    CONDA_BASE=/path/to/anaconda3 bash \"$0\""
    echo ""
    read -r -p "Press Return to close." _
    exit 1
fi
echo "Using conda from: $CONDA_SH"
# shellcheck disable=SC1090
source "$CONDA_SH"
