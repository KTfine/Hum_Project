#!/usr/bin/env bash
set -euo pipefail
umask 077
source "$(dirname -- "${BASH_SOURCE[0]}")/cloud_common.sh"
cd "${HUMCEN_PROJECT_ROOT}"
python_bin="${HUMCEN_PYTHON:-python}"
"${python_bin}" - <<'PY'
import torch
assert torch.__version__.startswith('2.8.0+cu128'), f'Use the tested PyTorch 2.8.0 + CUDA 12.8 image, found {torch.__version__}'
assert torch.cuda.is_available(), 'CUDA is unavailable'
a = torch.randn((512, 512), device='cuda', dtype=torch.bfloat16)
assert torch.isfinite(a @ a).all().item()
print('GPU preflight:', torch.cuda.get_device_name(0), torch.__version__, torch.version.cuda)
PY
if [[ ! -d "${HUMCEN_UPSTREAM_DIR}" ]]; then
    git init "${HUMCEN_UPSTREAM_DIR}"
    git -C "${HUMCEN_UPSTREAM_DIR}" remote add origin "${DEMO_REPO}"
    git -C "${HUMCEN_UPSTREAM_DIR}" fetch --depth 1 origin "${DEMO_COMMIT}"
    git -C "${HUMCEN_UPSTREAM_DIR}" checkout --detach FETCH_HEAD
fi
[[ "$(git -C "${HUMCEN_UPSTREAM_DIR}" rev-parse HEAD)" == "${DEMO_COMMIT}" ]] || { echo 'Unexpected Demo revision' >&2; exit 1; }
"${python_bin}" scripts/apply_upstream_patches.py "${HUMCEN_UPSTREAM_DIR}"
"${python_bin}" -m venv --system-site-packages "${HUMCEN_VENV_DIR}"
py="${HUMCEN_VENV_DIR}/bin/python"
"${py}" -m pip install --no-cache-dir 'torchaudio==2.8.0' --no-deps --index-url https://download.pytorch.org/whl/cu128
"${py}" - "${HUMCEN_UPSTREAM_DIR}" "${HUMCEN_PROJECT_ROOT}/logs/runtime-requirements.txt" <<'PY'
from pathlib import Path
import sys
lines = (Path(sys.argv[1]) / 'requirements.txt').read_text().splitlines()
lines = [line for line in lines if not line.strip().startswith('minicpmo-utils')]
lines += ['huggingface_hub==0.33.4', 'decord==0.6.0', 'pillow==10.4.0', 'moviepy==2.1.2']
Path(sys.argv[2]).write_text('\n'.join(lines) + '\n')
PY
# The toolkit metadata pins old librosa; the Demo's newer requirement is used.
"${py}" -m pip install --no-cache-dir -r logs/runtime-requirements.txt -r config/tts-requirements.txt
"${py}" -m pip install --no-cache-dir --no-deps 'minicpmo-utils==1.0.6'
"${py}" - <<'PY'
import torch, torchaudio, transformers, einops, onnx, onnxruntime, hyperpyyaml, stepaudio2, librosa
assert torch.__version__.startswith('2.8.0+cu128')
assert torchaudio.__version__.startswith('2.8.0')
assert transformers.__version__ == '4.51.0'
print('Runtime imports ready')
PY
"${py}" -m pip freeze > logs/runtime-packages.txt
touch ENV_READY
