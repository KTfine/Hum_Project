#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/common.sh"

audit_service_listeners() {
    local listener_output matches address port
    listener_output="$(ss -H -ltn)"
    matches="$(awk '$4 ~ /:8006$/ {print $4}' <<<"${listener_output}")"
    [[ -n "${matches}" ]] || die "expected port 8006 is not listening"
    if ! grep -qx '0.0.0.0:8006' <<<"${matches}"; then
        die "Gateway port 8006 is not reachable beyond loopback"
    fi

    for port in 8007 22400 22500; do
        matches="$(awk -v wanted=":${port}" '$4 ~ wanted "$" {print $4}' <<<"${listener_output}")"
        [[ -n "${matches}" ]] || die "expected port ${port} is not listening"
        while IFS= read -r address; do
            case "${address}" in
                "127.0.0.1:${port}"|"[::1]:${port}") ;;
                *) die "port ${port} is exposed beyond loopback: ${address}" ;;
            esac
        done <<<"${matches}"
    done
}

fetch_gateway_health_checks() {
    local compute_hostname
    compute_hostname="$(hostname)"
    curl -kfsS --noproxy '*' --max-time 10 https://127.0.0.1:8006/health
    printf '\n'
    curl -kfsS --noproxy '*' --max-time 10 "https://${compute_hostname}:8006/health"
    printf '\n'
}

main() {
    require_gpu_job
    local run_dir="${1:-}"
    [[ -n "${run_dir}" && -d "${run_dir}" ]] || die "usage: validate_service.sh RUN_DIR"

    local validation_log="${run_dir}/validation.jsonl"
    local backend_health worker_health gateway_loopback_health gateway_hostname_health
    local status_payload chat_result chat_status now
    local -a gateway_health_checks
    backend_health="$(curl -fsS --max-time 10 http://127.0.0.1:22500/health)"
    worker_health="$(curl -fsS --max-time 10 http://127.0.0.1:22400/health)"
    mapfile -t gateway_health_checks < <(fetch_gateway_health_checks)
    [[ ${#gateway_health_checks[@]} -eq 2 ]] || die "expected two Gateway health responses"
    gateway_loopback_health="${gateway_health_checks[0]}"
    gateway_hostname_health="${gateway_health_checks[1]}"
    status_payload="$(curl -kfsS --noproxy '*' --max-time 10 https://127.0.0.1:8006/status)"
    now="$(date --iso-8601=seconds)"

    "${VENV_DIR}/bin/python" - "${now}" "${backend_health}" "${worker_health}" \
        "${gateway_loopback_health}" "${gateway_hostname_health}" "${status_payload}" >>"${validation_log}" <<'PY'
import json
import sys

timestamp, backend_raw, worker_raw, gateway_loopback_raw, gateway_hostname_raw, status_raw = sys.argv[1:]
backend = json.loads(backend_raw)
worker = json.loads(worker_raw)
gateway_loopback = json.loads(gateway_loopback_raw)
gateway_hostname = json.loads(gateway_hostname_raw)
status = json.loads(status_raw)
assert backend.get("status") == "ready", backend
assert worker.get("status") == "healthy", worker
assert worker.get("model_loaded") is True, worker
assert gateway_loopback.get("status") == "healthy", gateway_loopback
assert gateway_hostname.get("status") == "healthy", gateway_hostname
assert status.get("total_workers", 0) >= 1, status
print(json.dumps({
    "type": "health_validation",
    "timestamp": timestamp,
    "ok": True,
    "backend": backend,
    "worker": worker,
    "gateway_loopback": gateway_loopback,
    "gateway_hostname": gateway_hostname,
    "gateway_status": status,
}, ensure_ascii=False))
PY

    audit_service_listeners
    nvidia-smi --query-gpu=timestamp,index,name,memory.used,memory.total,utilization.gpu \
        --format=csv,noheader,nounits >>"${run_dir}/gpu_validation_snapshot.csv"

    if chat_result="$("${VENV_DIR}/bin/python" "${SERVICE_ROOT}/client/text_chat.py" \
            --url 'wss://127.0.0.1:8006/v1/realtime?mode=chat' \
            --insecure \
            --prompt 'Reply with exactly: MiniCPM service OK' \
            --timeout 120)"; then
        chat_status=0
    else
        chat_status=$?
    fi
    printf '%s\n' "${chat_result}" >>"${validation_log}"
    (( chat_status == 0 )) || die "text validation client failed with status ${chat_status}; details saved in ${validation_log}"
    "${VENV_DIR}/bin/python" - "${chat_result}" <<'PY'
import json
import sys

result = json.loads(sys.argv[1])
assert result.get("ok") is True, result
assert result.get("text", "").strip(), result
print(
    "text validation passed: "
    f"total={result.get('client_total_ms')}ms, "
    f"first_text={result.get('client_first_text_ms')}ms"
)
PY
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
