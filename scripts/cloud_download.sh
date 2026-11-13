#!/usr/bin/env bash
set -euo pipefail
umask 077
source "$(dirname -- "${BASH_SOURCE[0]}")/cloud_common.sh"
cd "${HUMCEN_PROJECT_ROOT}"
export HF_HUB_DISABLE_XET=1
"${HUMCEN_PYTHON:-python}" -m venv --system-site-packages .download-venv
.download-venv/bin/python -m pip install --no-cache-dir 'huggingface_hub==0.33.4'
.download-venv/bin/python - "${MODEL_REPO}" "${MODEL_REVISION}" "${HUMCEN_MODEL_DIR}" <<'PY'
import sys
from huggingface_hub import snapshot_download
print(snapshot_download(repo_id=sys.argv[1], revision=sys.argv[2], local_dir=sys.argv[3], max_workers=4), flush=True)
PY
.download-venv/bin/python scripts/model_manifest.py write "${HUMCEN_MODEL_DIR}" "${MODEL_REPO}" "${MODEL_REVISION}"
.download-venv/bin/python scripts/model_manifest.py verify "${HUMCEN_MODEL_DIR}" "${MODEL_REPO}" "${MODEL_REVISION}"
printf '%s\n' "${MODEL_REVISION}" > "${HUMCEN_MODEL_DIR}/.model_revision"
touch MODEL_READY
