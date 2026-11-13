#!/usr/bin/env bash
set -euo pipefail
umask 077
source "$(dirname -- "${BASH_SOURCE[0]}")/cloud_common.sh"
root="${HUMCEN_PROJECT_ROOT}"
cd "$root"
py="${HUMCEN_VENV_DIR}/bin/python"
model="${HUMCEN_MODEL_DIR}"
run_dir="$root/logs/service-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$run_dir" "$root/certs" "${HUMCEN_DATA_DIR}"
printf '%s\n' "$run_dir" > "$root/logs/latest-service.txt"
test -x "$py"
"$py" - <<'PY'
import socket
busy = []
for port in (8006, 8007, 22400, 22500):
    with socket.socket() as connection:
        connection.settimeout(0.2)
        if connection.connect_ex(('127.0.0.1', port)) == 0:
            busy.append(port)
if busy:
    raise SystemExit(f'Service ports already in use: {busy}. Stop the existing service before starting another.')
PY
"$py" "$root/scripts/apply_upstream_patches.py" "${HUMCEN_UPSTREAM_DIR}"
"$py" "$root/scripts/model_manifest.py" verify "$model" openbmb/MiniCPM-o-4_5 503e754207c94da6bb26850b4469f367c9ea3582
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1
export PYTHONPATH="${HUMCEN_UPSTREAM_DIR}"
export OMP_NUM_THREADS=8
pids=()
cleanup() {
    local status=$?
    trap - EXIT INT TERM HUP
    for pid in "${pids[@]}"; do kill -TERM "$pid" 2>/dev/null || true; done
    for pid in "${pids[@]}"; do wait "$pid" 2>/dev/null || true; done
    exit "$status"
}
trap cleanup EXIT
trap 'exit 143' TERM HUP
trap 'exit 130' INT
if [[ ! -s "$root/certs/cert.pem" || ! -s "$root/certs/key.pem" ]]; then
    openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 365 \
      -keyout "$root/certs/key.pem" -out "$root/certs/cert.pem" \
      -subj /CN=localhost -addext 'subjectAltName=DNS:localhost,IP:127.0.0.1'
fi
"$py" - "$root" "$model" "${HUMCEN_UPSTREAM_DIR}" "${HUMCEN_DATA_DIR}" <<'PY'
import json,sys
from pathlib import Path
root,model,upstream,data_dir=Path(sys.argv[1]),sys.argv[2],Path(sys.argv[3]),sys.argv[4]
config=json.loads((root/'config/service.json').read_text())
config['model']['model_path']=model
config['model']['attn_implementation']='sdpa'
config['service']['data_dir']=data_dir
(upstream/'config.json').write_text(json.dumps(config,indent=2))
PY
cd "${HUMCEN_UPSTREAM_DIR}"
"$py" -u -m py_backend.server --host 127.0.0.1 --port 22500 --worker-index 0 --gpu-id 0 --model-path "$model" > "$run_dir/backend.log" 2>&1 &
pids+=("$!")
backend_pid=$!
ready=0
for ((n=0;n<300;n++)); do
    kill -0 "$backend_pid" || { tail -60 "$run_dir/backend.log"; exit 1; }
    if curl -fsS --max-time 2 http://127.0.0.1:22500/health | "$py" -c 'import json,sys; raise SystemExit(0 if json.load(sys.stdin).get("status")=="ready" else 1)' 2>/dev/null; then ready=1; break; fi
    sleep 2
done
[[ "$ready" == 1 ]]
"$py" -u worker.py --host 127.0.0.1 --port 22400 --worker-index 0 --gpu-id 0 --backend-server-url http://127.0.0.1:22500 > "$run_dir/worker.log" 2>&1 &
pids+=("$!")
worker_pid=$!
ready=0
for ((n=0;n<120;n++)); do
    kill -0 "$worker_pid" || { tail -60 "$run_dir/worker.log"; exit 1; }
    if curl -fsS --max-time 2 http://127.0.0.1:22400/health | "$py" -c 'import json,sys; d=json.load(sys.stdin); raise SystemExit(0 if d.get("status")=="healthy" and d.get("model_loaded") else 1)' 2>/dev/null; then ready=1; break; fi
    sleep 2
done
[[ "$ready" == 1 ]]
"$py" -u gateway.py --host 127.0.0.1 --port 8006 --internal-port 8007 --internal-host 127.0.0.1 --https --ssl-certfile "$root/certs/cert.pem" --ssl-keyfile "$root/certs/key.pem" > "$run_dir/gateway.log" 2>&1 &
pids+=("$!")
gateway_pid=$!
ready=0
for ((n=0;n<60;n++)); do
    kill -0 "$gateway_pid" || { tail -60 "$run_dir/gateway.log"; exit 1; }
    if curl -fsS --max-time 2 http://127.0.0.1:8007/health >/dev/null; then ready=1; break; fi
    sleep 1
done
[[ "$ready" == 1 ]]
curl -fsS -X PUT http://127.0.0.1:8007/internal/workers/cloud-worker-0 -H 'content-type: application/json' --data '{"endpoint":"127.0.0.1:22400","gpu_group":"gpu-0","labels":{"deployment":"cloud"}}' > "$run_dir/worker-registration.json"
printf 'timestamp,index,name,memory_used_mib,memory_total_mib,utilization_gpu_percent\n' > "$run_dir/gpu_memory.csv"
(
    while true; do
        nvidia-smi --query-gpu=timestamp,index,name,memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits >> "$run_dir/gpu_memory.csv"
        sleep 5
    done
) &
pids+=("$!")
printf 'SERVICE_READY %s\n' "$run_dir" | tee "$root/logs/service-ready.txt"
while kill -0 "$backend_pid" && kill -0 "$worker_pid" && kill -0 "$gateway_pid"; do sleep 3; done
exit 1
