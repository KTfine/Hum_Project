#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/common.sh"

require_gpu_job
require_command nvidia-smi

printf 'timestamp=%s\n' "$(date --iso-8601=seconds)"
printf 'hostname=%s\n' "$(hostname -f)"
printf 'slurm_job_id=%s\n' "${SLURM_JOB_ID}"
printf 'slurm_partition=%s\n' "${SLURM_JOB_PARTITION:-unknown}"
printf 'cuda_visible_devices=%s\n' "${CUDA_VISIBLE_DEVICES:-unset}"
nvidia-smi
nvidia-smi --query-gpu=index,name,uuid,driver_version,memory.total,memory.free --format=csv,noheader

if [[ -x "${VENV_DIR}/bin/python" ]]; then
    "${VENV_DIR}/bin/python" - <<'PY'
import sys
import torch
import transformers

print("python", sys.version.replace("\n", " "))
print("torch", torch.__version__)
print("torch_cuda_build", torch.version.cuda)
print("cuda_available", torch.cuda.is_available())
if not torch.cuda.is_available():
    raise SystemExit("PyTorch cannot see the allocated GPU")
print("gpu_name", torch.cuda.get_device_name(0))
print("bf16_supported", torch.cuda.is_bf16_supported())
print("transformers", transformers.__version__)
if not torch.cuda.is_bf16_supported():
    raise SystemExit("allocated GPU does not report BF16 support")
PY
else
    die "official venv is missing; run bootstrap_cpu.sbatch before the GPU probe"
fi

ffmpeg_bin="$(resolve_ffmpeg)" || die "neither system ffmpeg nor imageio-ffmpeg is available"
"${ffmpeg_bin}" -version | head -n 3
df -hT "${SERVICE_ROOT}"
curl -fsSI --max-time 15 https://github.com >/dev/null
curl -fsSI --max-time 15 https://huggingface.co >/dev/null
log "GPU, BF16, storage, FFmpeg, and outbound HTTPS probes passed"
