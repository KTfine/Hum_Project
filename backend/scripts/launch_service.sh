#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/common.sh"

require_gpu_job
require_command curl
require_command nvidia-smi
require_command ss
require_command pgrep

[[ -x "${VENV_DIR}/bin/python" ]] || die "official venv missing; submit bootstrap_cpu.sbatch first"
[[ -f "${MODEL_MARKER}" ]] || die "model completion marker missing; submit download_model_cpu.sbatch first"
[[ "$(<"${MODEL_MARKER}")" == "${MODEL_REVISION}" ]] || die "model marker does not match pinned revision ${MODEL_REVISION}"
"${VENV_DIR}/bin/python" "${SCRIPT_DIR}/model_manifest.py" verify \
    "${MODEL_DIR}" "${MODEL_REPO}" "${MODEL_REVISION}" \
    || die "local model snapshot is incomplete; resubmit download_model_cpu.sbatch"
verify_pinned_demo_checkout
[[ -s "${CERT_DIR}/cert.pem" && -s "${CERT_DIR}/key.pem" ]] || die "localhost TLS certificate is missing; rerun bootstrap_cpu.sbatch"

umask 077
job_id="${SLURM_JOB_ID}"
run_dir="${LOG_ROOT}/${job_id}"
mkdir -p "${run_dir}" "${SERVICE_ROOT}/data" "${UPSTREAM_DIR}/tmp"

backend_pid=""
worker_pid=""
gateway_pid=""
telemetry_pid=""
validation_pid=""

owned_pids=()

collect_tree() {
    local root_pid="$1" child
    [[ -n "${root_pid}" ]] || return 0
    while IFS= read -r child; do
        [[ -n "${child}" ]] && collect_tree "${child}"
    done < <(pgrep -P "${root_pid}" 2>/dev/null || true)
    owned_pids+=("${root_pid}")
}

cleanup() {
    local status=$? pid deadline any_alive
    trap - EXIT TERM INT HUP
    for pid in "${validation_pid}" "${gateway_pid}" "${worker_pid}" "${backend_pid}" "${telemetry_pid}"; do
        collect_tree "${pid}"
    done
    for pid in "${owned_pids[@]}"; do
        kill -TERM "${pid}" 2>/dev/null || true
    done
    deadline=$((SECONDS + 10))
    while (( SECONDS < deadline )); do
        any_alive=0
        for pid in "${owned_pids[@]}"; do
            if kill -0 "${pid}" 2>/dev/null; then
                any_alive=1
            fi
        done
        (( any_alive == 0 )) && break
        sleep 1
    done
    for pid in "${owned_pids[@]}"; do
        kill -KILL "${pid}" 2>/dev/null || true
        wait "${pid}" 2>/dev/null || true
    done
    printf '[%s] launcher cleanup complete (status=%s)\n' "$(date '+%Y-%m-%d %H:%M:%S')" "${status}" >>"${run_dir}/lifecycle.log"
    exit "${status}"
}
trap cleanup EXIT
trap 'exit 143' TERM HUP
trap 'exit 130' INT

export HF_HOME="${HF_CACHE_DIR}"
export HF_HUB_CACHE="${HF_CACHE_DIR}/hub"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export HF_HUB_DISABLE_TELEMETRY=1

{
    printf 'timestamp=%s\n' "$(date --iso-8601=seconds)"
    printf 'hostname=%s\n' "$(hostname -f)"
    printf 'slurm_job_id=%s\n' "${SLURM_JOB_ID}"
    printf 'slurm_partition=%s\n' "${SLURM_JOB_PARTITION:-unknown}"
    printf 'cuda_visible_devices=%s\n' "${CUDA_VISIBLE_DEVICES:-unset}"
    printf 'demo_commit=%s\n' "${DEMO_COMMIT}"
    printf 'model_revision=%s\n' "${MODEL_REVISION}"
    nvidia-smi
    "${VENV_DIR}/bin/python" - <<'PY'
import sys
import torch
import transformers
print("python", sys.version.replace("\n", " "))
print("torch", torch.__version__)
print("torch_cuda_build", torch.version.cuda)
print("cuda_available", torch.cuda.is_available())
print("bf16_supported", torch.cuda.is_bf16_supported() if torch.cuda.is_available() else False)
print("transformers", transformers.__version__)
PY
} >"${run_dir}/environment.log" 2>&1

"${VENV_DIR}/bin/python" - "${SERVICE_ROOT}/config/service.json" "${UPSTREAM_DIR}/config.json" "${MODEL_DIR}" "${SERVICE_ROOT}/data" <<'PY'
import json
import sys

source_path, output_path, model_path, data_path = sys.argv[1:]
with open(source_path, encoding="utf-8") as handle:
    config = json.load(handle)
config["model"]["model_path"] = model_path
config["service"]["data_dir"] = data_path
with open(output_path, "w", encoding="utf-8") as handle:
    json.dump(config, handle, ensure_ascii=False, indent=2)
    handle.write("\n")
PY

sample_gpu_memory() {
    printf 'timestamp,index,name,memory_used_mib,memory_total_mib,utilization_gpu_percent\n'
    while true; do
        nvidia-smi --query-gpu=timestamp,index,name,memory.used,memory.total,utilization.gpu \
            --format=csv,noheader,nounits || true
        sleep 5
    done
}
sample_gpu_memory >"${run_dir}/gpu_memory.csv" 2>>"${run_dir}/telemetry.err" &
telemetry_pid=$!

(
    cd "${UPSTREAM_DIR}"
    exec env PYTHONPATH=. "${VENV_DIR}/bin/python" -m py_backend.server \
        --host 127.0.0.1 \
        --port 22500 \
        --worker-index 0 \
        --gpu-id 0 \
        --model-path "${MODEL_DIR}"
) >"${run_dir}/backend.log" 2>&1 &
backend_pid=$!

backend_ready=0
for _ in $(seq 1 300); do
    kill -0 "${backend_pid}" 2>/dev/null || die "Backend exited during startup; inspect ${run_dir}/backend.log"
    if curl -fsS --max-time 3 http://127.0.0.1:22500/health | \
        "${VENV_DIR}/bin/python" -c 'import json,sys; d=json.load(sys.stdin); raise SystemExit(0 if d.get("status") == "ready" else 1)' 2>/dev/null; then
        backend_ready=1
        break
    fi
    sleep 2
done
(( backend_ready == 1 )) || die "Backend did not become ready within 600 seconds"

(
    cd "${UPSTREAM_DIR}"
    exec env PYTHONPATH=. "${VENV_DIR}/bin/python" worker.py \
        --host 127.0.0.1 \
        --port 22400 \
        --worker-index 0 \
        --gpu-id 0 \
        --backend-server-url http://127.0.0.1:22500
) >"${run_dir}/worker.log" 2>&1 &
worker_pid=$!

worker_ready=0
for _ in $(seq 1 180); do
    kill -0 "${worker_pid}" 2>/dev/null || die "Worker exited during startup; inspect ${run_dir}/worker.log"
    if curl -fsS --max-time 3 http://127.0.0.1:22400/health | \
        "${VENV_DIR}/bin/python" -c 'import json,sys; d=json.load(sys.stdin); raise SystemExit(0 if d.get("status") == "healthy" and d.get("model_loaded") else 1)' 2>/dev/null; then
        worker_ready=1
        break
    fi
    sleep 2
done
(( worker_ready == 1 )) || die "Worker did not become healthy within 360 seconds"

(
    cd "${UPSTREAM_DIR}"
    exec env PYTHONPATH=. "${VENV_DIR}/bin/python" gateway.py \
        --host 0.0.0.0 \
        --port 8006 \
        --internal-host 127.0.0.1 \
        --internal-port 8007 \
        --https \
        --ssl-certfile "${CERT_DIR}/cert.pem" \
        --ssl-keyfile "${CERT_DIR}/key.pem"
) >"${run_dir}/gateway.log" 2>&1 &
gateway_pid=$!

gateway_ready=0
for _ in $(seq 1 60); do
    kill -0 "${gateway_pid}" 2>/dev/null || die "Gateway exited during startup; inspect ${run_dir}/gateway.log"
    if curl -fsS --max-time 3 http://127.0.0.1:8007/health >/dev/null 2>&1; then
        gateway_ready=1
        break
    fi
    sleep 1
done
(( gateway_ready == 1 )) || die "Gateway registry did not become healthy within 60 seconds"

curl -fsS --max-time 10 -X PUT http://127.0.0.1:8007/internal/workers/slurm-worker-0 \
    -H 'content-type: application/json' \
    --data '{"endpoint":"127.0.0.1:22400","gpu_group":"gpu-0","labels":{"deployment":"slurm"}}' \
    >"${run_dir}/worker_registration.json"

compute_host="$(hostname -f)"
cat >"${run_dir}/connection.txt" <<EOF
Windows PowerShell tunnel (keep this terminal open):
ssh -N -J yliu674@hpc2login.hpc.hkust-gz.edu.cn -L 8006:127.0.0.1:8006 yliu674@${compute_host}

Browser: https://localhost:8006
Realtime API: wss://localhost:8006/v1/realtime?mode=chat|audio|video
Accept the self-signed localhost certificate warning before using WSS.

Compute-network health check: curl -k --noproxy '*' https://${compute_host}:8006/health
EOF

bash "${SCRIPT_DIR}/validate_service.sh" "${run_dir}" >"${run_dir}/validation_console.log" 2>&1 &
validation_pid=$!
while kill -0 "${validation_pid}" 2>/dev/null; do
    sleep 1
done
if wait "${validation_pid}"; then
    validation_pid=""
    tee -a "${run_dir}/lifecycle.log" <"${run_dir}/validation_console.log"
else
    validation_status=$?
    validation_pid=""
    tee -a "${run_dir}/lifecycle.log" <"${run_dir}/validation_console.log"
    die "startup validation failed with status ${validation_status}"
fi
log "service ready on compute host ${compute_host}; see ${run_dir}/connection.txt"

while kill -0 "${backend_pid}" 2>/dev/null && kill -0 "${worker_pid}" 2>/dev/null && kill -0 "${gateway_pid}" 2>/dev/null; do
    sleep 5
done
kill -0 "${backend_pid}" 2>/dev/null || die "Backend exited unexpectedly; inspect ${run_dir}/backend.log"
kill -0 "${worker_pid}" 2>/dev/null || die "Worker exited unexpectedly; inspect ${run_dir}/worker.log"
die "Gateway exited unexpectedly; inspect ${run_dir}/gateway.log"
