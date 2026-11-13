#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/common.sh"

require_cpu_job
[[ -x "${VENV_DIR}/bin/python" ]] || die "upstream environment is missing; run bootstrap_cpu.sbatch first"

if [[ -f "${MODEL_MARKER}" ]] && [[ "$(<"${MODEL_MARKER}")" == "${MODEL_REVISION}" ]] \
    && "${VENV_DIR}/bin/python" "${SCRIPT_DIR}/model_manifest.py" verify \
        "${MODEL_DIR}" "${MODEL_REPO}" "${MODEL_REVISION}"; then
    log "model revision ${MODEL_REVISION} is already complete"
    exit 0
fi

mkdir -p "${MODEL_DIR}" "${HF_CACHE_DIR}" "${LOG_ROOT}/slurm"
rm -f "${MODEL_MARKER}" "${MODEL_MANIFEST}"
export HF_HOME="${HF_CACHE_DIR}"
export HF_HUB_CACHE="${HF_CACHE_DIR}/hub"
export HF_HUB_DISABLE_TELEMETRY=1

log "downloading ${MODEL_REPO} at revision ${MODEL_REVISION} on CPU node $(hostname)"
"${VENV_DIR}/bin/python" - "${MODEL_REPO}" "${MODEL_REVISION}" "${MODEL_DIR}" <<'PY'
import sys
from huggingface_hub import snapshot_download

repo_id, revision, local_dir = sys.argv[1:]
path = snapshot_download(
    repo_id=repo_id,
    revision=revision,
    local_dir=local_dir,
    resume_download=True,
)
print(f"snapshot available at {path}")
PY

"${VENV_DIR}/bin/python" "${SCRIPT_DIR}/model_manifest.py" write \
    "${MODEL_DIR}" "${MODEL_REPO}" "${MODEL_REVISION}"
"${VENV_DIR}/bin/python" "${SCRIPT_DIR}/model_manifest.py" verify \
    "${MODEL_DIR}" "${MODEL_REPO}" "${MODEL_REVISION}"
printf '%s\n' "${MODEL_REVISION}" > "${MODEL_MARKER}"
log "model download complete and pinned marker written"
