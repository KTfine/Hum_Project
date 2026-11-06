#!/usr/bin/env bash

COMMON_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
SERVICE_ROOT="$(cd -- "${COMMON_DIR}/.." && pwd -P)"
VERSIONS_FILE="${SERVICE_ROOT}/config/versions.env"
UPSTREAM_DIR="${SERVICE_ROOT}/upstream"
VENV_DIR="${UPSTREAM_DIR}/.venv/base"
MODEL_DIR="${SERVICE_ROOT}/models/MiniCPM-o-4_5"
MODEL_MARKER="${MODEL_DIR}/.model_revision"
MODEL_MANIFEST="${MODEL_DIR}/.model_manifest.json"
HF_CACHE_DIR="${SERVICE_ROOT}/.cache/huggingface"
CERT_DIR="${SERVICE_ROOT}/certs"
LOG_ROOT="${SERVICE_ROOT}/logs"

if [[ ! -f "${VERSIONS_FILE}" ]]; then
    printf 'ERROR: missing version file: %s\n' "${VERSIONS_FILE}" >&2
    return 1 2>/dev/null || exit 1
fi

# shellcheck disable=SC1090
source "${VERSIONS_FILE}"

log() {
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

verify_pinned_demo_checkout() {
    local head_file="${UPSTREAM_DIR}/.git/HEAD" current_commit
    [[ -r "${head_file}" ]] || die "official Demo checkout metadata is missing: ${head_file}"
    IFS= read -r current_commit <"${head_file}" || die "cannot read official Demo checkout metadata: ${head_file}"
    [[ "${current_commit}" != ref:* ]] || die "official Demo checkout must be detached at pinned commit ${DEMO_COMMIT}"
    [[ "${current_commit}" == "${DEMO_COMMIT}" ]] || die "official Demo checkout is at ${current_commit}; expected ${DEMO_COMMIT}"
}

resolve_ffmpeg() {
    if command -v ffmpeg >/dev/null 2>&1; then
        command -v ffmpeg
        return 0
    fi
    [[ -x "${VENV_DIR}/bin/python" ]] || return 1
    "${VENV_DIR}/bin/python" -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())'
}

drop_unreachable_local_proxies() {
    local proxy_var proxy_value
    for proxy_var in HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy; do
        proxy_value="${!proxy_var-}"
        case "${proxy_value}" in
            *://127.0.0.1:*|*://localhost:*|*://\[::1\]:*|127.0.0.1:*|localhost:*|\[::1\]:*)
                unset "${proxy_var}"
                ;;
        esac
    done
}

configure_cpu_package_index() {
    export PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
    export PIP_DEFAULT_TIMEOUT="${PIP_DEFAULT_TIMEOUT:-120}"
    export PIP_RETRIES="${PIP_RETRIES:-5}"
    export PIP_USE_DEPRECATED="${PIP_USE_DEPRECATED:-legacy-resolver}"
    export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
}

require_slurm_job() {
    [[ -n "${SLURM_JOB_ID:-}" ]] || die "this script must run inside a Slurm allocation; do not run it on a login node"
    [[ -n "${SLURM_JOB_NODELIST:-}" ]] || die "Slurm allocation has no assigned node list; do not run this on a login node"
    local current_host allocated_host matched=0
    current_host="$(hostname -s)"
    if [[ -n "${SLURMD_NODENAME:-}" ]]; then
        [[ "${current_host}" == "${SLURMD_NODENAME%%.*}" ]] && matched=1
    else
        require_command scontrol
        while IFS= read -r allocated_host; do
            if [[ "${current_host}" == "${allocated_host%%.*}" ]]; then
                matched=1
                break
            fi
        done < <(scontrol show hostnames "${SLURM_JOB_NODELIST}")
    fi
    (( matched == 1 )) || die "current host ${current_host} is not a compute node in Slurm allocation ${SLURM_JOB_ID}"
    drop_unreachable_local_proxies
}

has_allocated_gpu() {
    local visible="${CUDA_VISIBLE_DEVICES:-}"
    if [[ -n "${SLURM_JOB_GPUS:-}" || -n "${SLURM_GPUS:-}" ]]; then
        return 0
    fi
    [[ -n "${visible}" && "${visible}" != "NoDevFiles" && "${visible}" != "none" && "${visible}" != "-1" ]]
}

require_cpu_job() {
    require_slurm_job
    if has_allocated_gpu; then
        die "this is a CPU-only preparation step; submit the matching CPU Slurm job"
    fi
    configure_cpu_package_index
}

require_gpu_job() {
    require_slurm_job
    has_allocated_gpu || die "this script requires a GPU Slurm allocation"
}

activate_conda_face() {
    local conda_sh="/hpc2ssd/softwares/anaconda3/etc/profile.d/conda.sh"
    [[ -f "${conda_sh}" ]] || die "Conda initialization script not found: ${conda_sh}"
    set +u
    # shellcheck disable=SC1090
    source "${conda_sh}"
    conda activate face
    set -u
}
