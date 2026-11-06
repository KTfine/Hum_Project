#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/common.sh"

GATEWAY_PATCH="${SERVICE_ROOT}/patches/gateway-internal-host.patch"

apply_gateway_patch() {
    local changed_files
    [[ -f "${GATEWAY_PATCH}" ]] || die "missing Gateway patch: ${GATEWAY_PATCH}"

    if git -C "${UPSTREAM_DIR}" apply --reverse --check "${GATEWAY_PATCH}" >/dev/null 2>&1; then
        log "Gateway split-listener patch is already applied"
    elif git -C "${UPSTREAM_DIR}" apply --check "${GATEWAY_PATCH}" >/dev/null 2>&1; then
        git -C "${UPSTREAM_DIR}" apply "${GATEWAY_PATCH}"
        log "applied Gateway split-listener patch"
    else
        die "Gateway checkout does not match the pinned patch"
    fi

    changed_files="$(git -C "${UPSTREAM_DIR}" diff --name-only)"
    [[ "${changed_files}" == "gateway.py" ]] || \
        die "unexpected tracked changes in official Demo checkout: ${changed_files:-none}"
}

require_cpu_job
require_command git
require_command openssl
activate_conda_face

face_python="$(command -v python)"
python_version="$(${face_python} -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
[[ "${python_version}" == "3.10" ]] || die "face must provide Python 3.10; found ${python_version} at ${face_python}"

mkdir -p "${LOG_ROOT}/slurm" "${CERT_DIR}"

if [[ -e "${UPSTREAM_DIR}" ]]; then
    [[ -d "${UPSTREAM_DIR}/.git" ]] || die "${UPSTREAM_DIR} exists but is not a Git checkout"
    current_commit="$(git -C "${UPSTREAM_DIR}" rev-parse HEAD)"
    [[ "${current_commit}" == "${DEMO_COMMIT}" ]] || die "upstream is at ${current_commit}; expected ${DEMO_COMMIT}"
    log "reusing official Demo checkout at ${DEMO_COMMIT}"
else
    log "cloning official Demo repository"
    git clone --filter=blob:none --no-checkout "${DEMO_REPO}" "${UPSTREAM_DIR}"
    git -C "${UPSTREAM_DIR}" fetch --depth 1 origin "${DEMO_COMMIT}"
    git -C "${UPSTREAM_DIR}" checkout --detach "${DEMO_COMMIT}"
fi

apply_gateway_patch

log "installing the official Demo environment with ${face_python}"
(
    cd "${UPSTREAM_DIR}"
    PYTHON="${face_python}" SKIP_FLASH_ATTN=1 bash install.sh
)

log "installing explicit Token2Wav runtime dependencies"
"${VENV_DIR}/bin/pip" install -r "${SERVICE_ROOT}/config/tts-requirements.txt"

"${VENV_DIR}/bin/python" - <<'PY'
import sys
import einops
import hyperpyyaml
import onnx
import onnxruntime
import stepaudio2
import torch
import transformers

assert sys.version_info[:2] == (3, 10), sys.version
assert torch.__version__.startswith("2.8.0"), torch.__version__
assert transformers.__version__ == "4.51.0", transformers.__version__
print(f"verified Python {sys.version.split()[0]}, torch {torch.__version__}, transformers {transformers.__version__}")
print("verified Token2Wav runtime imports: einops, hyperpyyaml, onnx, onnxruntime, stepaudio2")
PY

if [[ ! -s "${CERT_DIR}/cert.pem" || ! -s "${CERT_DIR}/key.pem" ]]; then
    log "generating a self-signed certificate for localhost"
    openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 365 \
        -keyout "${CERT_DIR}/key.pem" \
        -out "${CERT_DIR}/cert.pem" \
        -subj "/CN=localhost" \
        -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
    chmod 600 "${CERT_DIR}/key.pem"
fi

log "bootstrap complete; submit slurm/download_model_cpu.sbatch next"
