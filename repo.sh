#!/usr/bin/env bash
set -euo pipefail

CONDA_HOME="${CONDA_HOME:-/tmp/conda}"
TEMP_DIR="${TEMP_DIR:-/tmp}"

function cdate() {
    date +"%Y-%m-%d %H:%M:%S"
}

function log() {
    >&2 echo -e "[$(cdate)] $*"
}


if ! [[ -e "${CONDA_HOME}/bin/mamba" ]]; then
    # new version you cen get from https://github.com/conda-forge/miniforge/releases/
    mamba_version="4.10.3-7"
    mamba_checksum="fc872522ec427fcab10167a93e802efaf251024b58cc27b084b915a9a73c4474"


    installer_path="${TEMP_DIR}/mambaforge.sh"
    base_url="https://github.com/conda-forge/miniforge/releases/download"
    file_name="Mambaforge-${mamba_version}-Linux-x86_64.sh"
    mamba_forge_url="${base_url}/${mamba_version}/${file_name}"

    log "Downloading mambaforge ${mamba_version}"
    curl -L "${mamba_forge_url}"                                                    \
        --output "${installer_path}"                                                \
        && echo "${mamba_checksum}  ${installer_path}"                              \
        | sha256sum --check                                                         \
        || {
            log "Can't download mambaforge from ${mamba_forge_url}"
            exit 2
        }

    log "Installing mambaforge ${mamba_version} to ${CONDA_HOME}"
    # mambaforge (or miniconda) is distruted as bash script with embedded binary
    # no another data are downloading during installation
    # For added security, you can run the process
    # without internet access using unshare --net --user
    # redirect HOME dir to CONDA_HOME due to creating some config files in HOME
    HOME="$CONDA_HOME" bash /tmp/mambaforge.sh -u -p "$CONDA_HOME" -b

    # remove installation script
    rm -f "${installer_path}"

fi

# manual initialize conda environment
export PATH="$CONDA_HOME/bin:$CONDA_HOME/condabin:$PATH"
export PYTHONPATH="$CONDA_HOME/lib/python3.9/site-packages"

if ! [[ -e "${CONDA_HOME}/bin/mamba" ]]; then
    export CONDA_PREFIX="$CONDA_HOME"
    export CONDA_EXE="$CONDA_HOME/bin/conda"
    export CONDA_PYTHON_EXE="$CONDA_HOME/bin/python"

    # install package for clonning conda repository
    # redirect HOME dir to CONDA_HOME due to creating some config files in HOME
    HOME="$CONDA_HOME" mamba install -y mamba=0.20 libmambapy=0.20 libmamba=0.20

fi

exec python "$(dirname "$0")/lib/clone.py" "$@"


