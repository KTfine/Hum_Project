#!/usr/bin/env bash
set -uo pipefail

TEST_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
SERVICE_ROOT="$(cd -- "${TEST_DIR}/.." && pwd -P)"
failures=0
checks=0
test_stage="${TEST_STAGE:-4}"
test_host="$(hostname -s)"

pass() {
    checks=$((checks + 1))
    printf 'ok %d - %s\n' "${checks}" "$1"
}

fail() {
    checks=$((checks + 1))
    failures=$((failures + 1))
    printf 'not ok %d - %s\n' "${checks}" "$1"
}

assert_file() {
    local path="$1"
    local description="$2"
    if [[ -f "${path}" ]]; then
        pass "${description}"
    else
        fail "${description}: missing ${path}"
    fi
}

assert_executable() {
    local path="$1"
    local description="$2"
    if [[ -x "${path}" ]]; then
        pass "${description}"
    else
        fail "${description}: not executable ${path}"
    fi
}

assert_command() {
    local description="$1"
    shift
    if "$@" >/dev/null 2>&1; then
        pass "${description}"
    else
        fail "${description}"
    fi
}

assert_output() {
    local description="$1"
    local expected="$2"
    shift 2
    local actual
    if actual=$("$@" 2>/dev/null) && [[ "${actual}" == "${expected}" ]]; then
        pass "${description}"
    else
        fail "${description}: expected '${expected}', got '${actual:-<command failed>}'"
    fi
}

assert_fails_with() {
    local description="$1"
    local expected_fragment="$2"
    shift 2
    local actual status
    if actual=$("$@" 2>&1); then
        status=0
    else
        status=$?
    fi
    if (( status != 0 )) && [[ "${actual}" == *"${expected_fragment}"* ]]; then
        pass "${description}"
    else
        fail "${description}: status=${status}, output=${actual}"
    fi
}

sbatch_value() {
    local file="$1"
    local key="$2"
    sed -n "s/^#SBATCH[[:space:]]\+--${key}=//p" "${file}" | tail -n 1
}

printf 'TAP version 13\n'

versions_file="${SERVICE_ROOT}/config/versions.env"
config_file="${SERVICE_ROOT}/config/service.json"
tts_requirements="${SERVICE_ROOT}/config/tts-requirements.txt"
assert_file "${versions_file}" "version pins exist"
assert_file "${config_file}" "official service config exists"
assert_file "${tts_requirements}" "Token2Wav runtime requirements exist"

if [[ -f "${tts_requirements}" ]]; then
    assert_command "Token2Wav requirements include every missing runtime import" python - "${tts_requirements}" <<'PY'
import pathlib
import sys

lines = {
    line.strip().split("==")[0].split(">=")[0].lower()
    for line in pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
    if line.strip() and not line.lstrip().startswith("#")
}
assert {"einops", "onnx", "onnxruntime", "hyperpyyaml"} <= lines, lines
PY
fi

if [[ -f "${versions_file}" ]]; then
    # shellcheck disable=SC1090
    source "${versions_file}"
    [[ "${DEMO_REPO:-}" == "https://github.com/OpenBMB/MiniCPM-o-Demo.git" ]] && pass "official Demo repository is pinned" || fail "official Demo repository is pinned"
    [[ "${DEMO_COMMIT:-}" == "47709a9210dfd71afa76c058e017fc8c4db5c8d2" ]] && pass "Demo commit is reproducible" || fail "Demo commit is reproducible"
    [[ "${MODEL_REPO:-}" == "openbmb/MiniCPM-o-4_5" ]] && pass "official model repository is pinned" || fail "official model repository is pinned"
    [[ "${MODEL_REVISION:-}" == "503e754207c94da6bb26850b4469f367c9ea3582" ]] && pass "model revision is reproducible" || fail "model revision is reproducible"
fi

if [[ -f "${config_file}" ]]; then
    assert_command "service config is valid and enforces the selected runtime" python - "${config_file}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    config = json.load(handle)

assert config["model"]["model_path"] == "models/MiniCPM-o-4_5"
assert config["model"]["attn_implementation"] == "auto"
assert config["model"]["pt_path"] is None
assert config["audio"]["chat_vocoder"] == "token2wav"
assert config["service"]["gateway_port"] == 8006
assert config["service"]["worker_base_port"] == 22400
assert config["service"]["compile"] is False
PY
fi

if (( test_stage >= 2 )); then
for path in \
    scripts/common.sh \
    scripts/bootstrap_cpu.sh \
    scripts/download_model.sh \
    scripts/model_manifest.py \
    scripts/probe_gpu.sh \
    scripts/check_queue.sh \
    slurm/bootstrap_cpu.sbatch \
    slurm/download_model_cpu.sbatch \
    slurm/probe_gpu.sbatch; do
    assert_file "${SERVICE_ROOT}/${path}" "${path} exists"
done

for path in \
    scripts/bootstrap_cpu.sh \
    scripts/download_model.sh \
    scripts/probe_gpu.sh \
    scripts/check_queue.sh; do
    assert_executable "${SERVICE_ROOT}/${path}" "${path} is executable"
done

common="${SERVICE_ROOT}/scripts/common.sh"
if [[ -f "${common}" ]]; then
    assert_output "common paths resolve from an arbitrary working directory" "${SERVICE_ROOT}" \
        bash -c 'cd /tmp && source "$1" && printf "%s" "$SERVICE_ROOT"' _ "${common}"
    assert_fails_with "Slurm guard rejects login-node execution" "Slurm allocation" \
        env -u SLURM_JOB_ID -u SLURM_JOB_GPUS -u SLURM_GPUS -u CUDA_VISIBLE_DEVICES \
        bash -c 'source "$1"; require_slurm_job' _ "${common}"
    assert_command "CPU guard accepts a CPU allocation" \
        env SLURM_JOB_ID=123 SLURM_JOB_NODELIST="${test_host}" CUDA_VISIBLE_DEVICES=NoDevFiles \
        bash -c 'source "$1"; require_cpu_job' _ "${common}"
    assert_fails_with "CPU guard rejects a GPU allocation" "CPU-only" \
        env SLURM_JOB_ID=123 SLURM_JOB_NODELIST="${test_host}" CUDA_VISIBLE_DEVICES=0 SLURM_JOB_GPUS=0 \
        bash -c 'source "$1"; require_cpu_job' _ "${common}"
    assert_command "GPU guard accepts an allocated GPU" \
        env SLURM_JOB_ID=123 SLURM_JOB_NODELIST="${test_host}" CUDA_VISIBLE_DEVICES=0 SLURM_JOB_GPUS=0 \
        bash -c 'source "$1"; require_gpu_job' _ "${common}"
    assert_fails_with "GPU guard rejects a CPU allocation" "GPU Slurm allocation" \
        env SLURM_JOB_ID=123 SLURM_JOB_NODELIST="${test_host}" CUDA_VISIBLE_DEVICES=NoDevFiles \
        bash -c 'source "$1"; require_gpu_job' _ "${common}"
    assert_fails_with "Slurm guard rejects an allocation while still on a login host" "not a compute node" \
        env SLURM_JOB_ID=123 SLURM_JOB_NODELIST=definitely-not-this-host CUDA_VISIBLE_DEVICES=NoDevFiles \
        bash -c 'source "$1"; require_cpu_job' _ "${common}"
    broken_scontrol_dir="$(mktemp -d)"
    cat >"${broken_scontrol_dir}/scontrol" <<'SH'
#!/usr/bin/env bash
exit 127
SH
    chmod +x "${broken_scontrol_dir}/scontrol"
    assert_command "Slurm guard uses SLURMD_NODENAME without requiring scontrol on compute nodes" \
        env PATH="${broken_scontrol_dir}:${PATH}" SLURM_JOB_ID=123 SLURM_JOB_NODELIST=compressed-name \
        SLURMD_NODENAME="${test_host}" CUDA_VISIBLE_DEVICES=NoDevFiles \
        bash -c 'source "$1"; require_cpu_job' _ "${common}"
    rm -r "${broken_scontrol_dir}"
    assert_output "compute-node guard drops inherited localhost proxies but keeps a reachable proxy" \
        "unset|unset|unset|http://proxy.example:8080" \
        env SLURM_JOB_ID=123 SLURM_JOB_NODELIST="${test_host}" CUDA_VISIBLE_DEVICES=NoDevFiles \
        HTTP_PROXY=http://127.0.0.1:7893 HTTPS_PROXY=http://localhost:7893 'ALL_PROXY=http://[::1]:7893' \
        http_proxy=http://proxy.example:8080 \
        bash -c 'source "$1"; require_cpu_job; printf "%s|%s|%s|%s" "${HTTP_PROXY-unset}" "${HTTPS_PROXY-unset}" "${ALL_PROXY-unset}" "$http_proxy"' _ "${common}"
    assert_output "CPU jobs default pip to the reachable Tsinghua mirror" \
        "https://pypi.tuna.tsinghua.edu.cn/simple" \
        env -u PIP_INDEX_URL SLURM_JOB_ID=123 SLURM_JOB_NODELIST="${test_host}" CUDA_VISIBLE_DEVICES=NoDevFiles \
        bash -c 'source "$1"; require_cpu_job; printf "%s" "$PIP_INDEX_URL"' _ "${common}"
    assert_output "CPU jobs preserve an explicit pip index override" \
        "https://packages.example/simple" \
        env PIP_INDEX_URL=https://packages.example/simple SLURM_JOB_ID=123 SLURM_JOB_NODELIST="${test_host}" CUDA_VISIBLE_DEVICES=NoDevFiles \
        bash -c 'source "$1"; require_cpu_job; printf "%s" "$PIP_INDEX_URL"' _ "${common}"
    assert_output "CPU install selects pip's legacy resolver for the upstream librosa conflict" \
        "legacy-resolver" \
        env -u PIP_USE_DEPRECATED SLURM_JOB_ID=123 SLURM_JOB_NODELIST="${test_host}" CUDA_VISIBLE_DEVICES=NoDevFiles \
        bash -c 'source "$1"; require_cpu_job; printf "%s" "$PIP_USE_DEPRECATED"' _ "${common}"
    assert_output "CPU jobs default Hugging Face traffic to the reachable mirror" \
        "https://hf-mirror.com" \
        env -u HF_ENDPOINT SLURM_JOB_ID=123 SLURM_JOB_NODELIST="${test_host}" CUDA_VISIBLE_DEVICES=NoDevFiles \
        bash -c 'source "$1"; require_cpu_job; printf "%s" "$HF_ENDPOINT"' _ "${common}"
    assert_output "CPU jobs preserve an explicit Hugging Face endpoint override" \
        "https://hub.example" \
        env HF_ENDPOINT=https://hub.example SLURM_JOB_ID=123 SLURM_JOB_NODELIST="${test_host}" CUDA_VISIBLE_DEVICES=NoDevFiles \
        bash -c 'source "$1"; require_cpu_job; printf "%s" "$HF_ENDPOINT"' _ "${common}"
    assert_command "FFmpeg resolver falls back to imageio-ffmpeg from the venv" bash -c '
        tmp="$(mktemp -d)"
        mkdir -p "$tmp/bin" "$tmp/empty-path"
        printf "#!/bin/bash\nprintf /tmp/bundled-ffmpeg\n" >"$tmp/bin/python"
        chmod +x "$tmp/bin/python"
        source "$1"
        VENV_DIR="$tmp"
        result="$(PATH="$tmp/empty-path" resolve_ffmpeg)"
        rm -r "$tmp"
        [[ "$result" == "/tmp/bundled-ffmpeg" ]]
    ' _ "${common}"
    assert_command "pinned Demo checkout validation works without git at GPU runtime" bash -c '
        tmp="$(mktemp -d)"
        mkdir -p "$tmp/upstream/.git" "$tmp/empty-path"
        printf "%s\n" "$2" >"$tmp/upstream/.git/HEAD"
        source "$1"
        UPSTREAM_DIR="$tmp/upstream"
        DEMO_COMMIT="$2"
        old_path="$PATH"
        PATH="$tmp/empty-path"
        verify_pinned_demo_checkout
        status=$?
        PATH="$old_path"
        rm -r "$tmp"
        exit "$status"
    ' _ "${common}" "${DEMO_COMMIT}"
fi

for path in scripts/bootstrap_cpu.sh scripts/download_model.sh; do
    file="${SERVICE_ROOT}/${path}"
    if [[ -f "${file}" ]]; then
        assert_fails_with "${path} refuses login-node execution" "Slurm allocation" \
            env -u SLURM_JOB_ID -u SLURM_JOB_GPUS -u SLURM_GPUS -u CUDA_VISIBLE_DEVICES bash "${file}"
    fi
done

assert_command "bootstrap installs and verifies Token2Wav runtime dependencies" bash -c \
    'grep -q "tts-requirements.txt" "$1" && grep -q "import einops" "$1" && grep -q "import onnxruntime" "$1"' \
    _ "${SERVICE_ROOT}/scripts/bootstrap_cpu.sh"

for path in scripts/common.sh scripts/bootstrap_cpu.sh scripts/download_model.sh scripts/probe_gpu.sh scripts/check_queue.sh slurm/bootstrap_cpu.sbatch slurm/download_model_cpu.sbatch slurm/probe_gpu.sbatch; do
    file="${SERVICE_ROOT}/${path}"
    [[ ! -f "${file}" ]] || assert_command "${path} has valid Bash syntax" bash -n "${file}"
done

manifest_tool="${SERVICE_ROOT}/scripts/model_manifest.py"
if [[ -f "${manifest_tool}" ]]; then
    assert_command "model manifest tool compiles" python -m py_compile "${manifest_tool}"
    assert_command "model manifest rejects a snapshot missing Token2Wav assets" python - "${manifest_tool}" <<'PY'
import importlib.util
import pathlib
import tempfile
import sys

spec = importlib.util.spec_from_file_location("model_manifest", sys.argv[1])
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)
with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp)
    (root / "config.json").write_text("{}", encoding="utf-8")
    (root / "model-00001-of-00004.safetensors").write_bytes(b"weights")
    try:
        module.build_manifest(root, "repo", "revision")
    except ValueError as exc:
        assert "assets/token2wav" in str(exc)
    else:
        raise AssertionError("incomplete snapshot was accepted")
PY
    assert_command "model manifest detects a changed snapshot file" python - "${manifest_tool}" <<'PY'
import importlib.util
import pathlib
import tempfile
import sys

spec = importlib.util.spec_from_file_location("model_manifest", sys.argv[1])
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)
with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp)
    required = set(module.REQUIRED_FILES) | {"model-00001-of-00004.safetensors"}
    for name in required:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"complete")
    module.write_manifest(root, "repo", "revision")
    module.verify_manifest(root, "repo", "revision")
    (root / "assets/token2wav/flow.pt").write_bytes(b"changed-size")
    try:
        module.verify_manifest(root, "repo", "revision")
    except ValueError as exc:
        assert "changed=" in str(exc)
    else:
        raise AssertionError("changed snapshot was accepted")
PY
    assert_command "model manifest rejects a missing weight shard" python - "${manifest_tool}" <<'PY'
import importlib.util
import pathlib
import tempfile
import sys

spec = importlib.util.spec_from_file_location("model_manifest", sys.argv[1])
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)
with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp)
    for name in module.REQUIRED_FILES - {"model-00004-of-00004.safetensors"}:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"present")
    try:
        module.build_manifest(root, "repo", "revision")
    except ValueError as exc:
        assert "model-00004-of-00004.safetensors" in str(exc)
    else:
        raise AssertionError("snapshot with a missing weight shard was accepted")
PY
fi

bootstrap_job="${SERVICE_ROOT}/slurm/bootstrap_cpu.sbatch"
download_job="${SERVICE_ROOT}/slurm/download_model_cpu.sbatch"
probe_job="${SERVICE_ROOT}/slurm/probe_gpu.sbatch"
if [[ -f "${bootstrap_job}" ]]; then
    assert_output "bootstrap uses a CPU partition" "i64m512u" sbatch_value "${bootstrap_job}" partition
    assert_output "bootstrap preserves the operator's extended time limit" "12:00:00" sbatch_value "${bootstrap_job}" time
fi
if [[ -f "${download_job}" ]]; then
    assert_output "model download uses a CPU partition" "i64m512u" sbatch_value "${download_job}" partition
    assert_output "model download reserves six hours" "06:00:00" sbatch_value "${download_job}" time
fi
if [[ -f "${probe_job}" ]]; then
    assert_output "GPU probe defaults to the A800 emergency partition" "emergency_gpu" sbatch_value "${probe_job}" partition
    assert_output "GPU probe uses the matching A800 QoS" "emergency_gpu" sbatch_value "${probe_job}" qos
    assert_output "GPU probe requests one A800" "gpu:a800:1" sbatch_value "${probe_job}" gres
fi
fi

if (( test_stage >= 3 )); then
for path in scripts/launch_service.sh scripts/validate_service.sh slurm/serve.sbatch client/text_chat.py tests/test_gateway_bindings.py patches/gateway-internal-host.patch; do
    assert_file "${SERVICE_ROOT}/${path}" "${path} exists"
done
for path in scripts/launch_service.sh scripts/validate_service.sh; do
    assert_executable "${SERVICE_ROOT}/${path}" "${path} is executable"
done

for path in scripts/launch_service.sh scripts/validate_service.sh slurm/serve.sbatch; do
    file="${SERVICE_ROOT}/${path}"
    [[ ! -f "${file}" ]] || assert_command "${path} has valid Bash syntax" bash -n "${file}"
done

launcher="${SERVICE_ROOT}/scripts/launch_service.sh"
validator="${SERVICE_ROOT}/scripts/validate_service.sh"
serve_job="${SERVICE_ROOT}/slurm/serve.sbatch"
chat_client="${SERVICE_ROOT}/client/text_chat.py"
gateway_binding_test="${SERVICE_ROOT}/tests/test_gateway_bindings.py"
gateway_python="${SERVICE_ROOT}/upstream/.venv/base/bin/python"
if [[ -f "${launcher}" ]]; then
    assert_fails_with "launcher refuses login-node execution" "Slurm allocation" \
        env -u SLURM_JOB_ID -u SLURM_JOB_GPUS -u SLURM_GPUS -u CUDA_VISIBLE_DEVICES bash "${launcher}"
    assert_command "GPU launcher does not require git at runtime" bash -c \
        '! grep -Eq "require_command[[:space:]]+git" "$1"' _ "${launcher}"
    assert_command "launcher contains no broad process kill" bash -c '! grep -Eq "(^|[[:space:]])pkill([[:space:]]|$)" "$1"' _ "${launcher}"
    assert_command "launcher starts the official backend protocol server" grep -q 'py_backend.server' "${launcher}"
    assert_command "launcher connects the forwarding Worker to the backend" grep -q -- '--backend-server-url http://127.0.0.1:22500' "${launcher}"
    assert_command "launcher exposes only the Gateway on the compute network" bash -c \
        '[[ $(grep -c -- "--host 127.0.0.1" "$1") -eq 2 ]] && grep -q -- "--host 0.0.0.0" "$1"' _ "${launcher}"
    assert_command "launcher keeps the Gateway registry on loopback" \
        grep -q -- '--internal-host 127.0.0.1' "${launcher}"
    assert_command "launcher forces an offline GPU runtime" bash -c \
        'grep -q "HF_HUB_OFFLINE=1" "$1" && grep -q "TRANSFORMERS_OFFLINE=1" "$1"' _ "${launcher}"
    assert_command "launcher verifies the complete model manifest" grep -q 'model_manifest.py.*verify' "${launcher}"
    assert_command "launcher tracks validation outside the foreground" grep -q 'validation_pid=\$!' "${launcher}"
    assert_command "launcher has bounded TERM-to-KILL cleanup" bash -c \
        'grep -q "SECONDS + 10" "$1" && grep -q "kill -KILL" "$1"' _ "${launcher}"
    assert_command "launcher never references a Hub model ID" bash -c '! grep -q "openbmb/MiniCPM-o-4_5" "$1"' _ "${launcher}"
fi
if [[ -f "${gateway_binding_test}" && -x "${gateway_python}" ]]; then
    assert_command "Gateway binds its public and internal servers independently" \
        "${gateway_python}" "${gateway_binding_test}"
fi
if [[ -f "${validator}" ]]; then
    assert_command "validator implements a listener exposure audit" grep -q 'audit_service_listeners' "${validator}"
    fake_bin="$(mktemp -d)"
    trap 'rm -rf "${fake_bin}"' EXIT
    cat >"${fake_bin}/ss" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "${FAKE_SS_OUTPUT}"
SH
    chmod +x "${fake_bin}/ss"
    expected_listeners=$'LISTEN 0 2048 0.0.0.0:8006 0.0.0.0:*\nLISTEN 0 2048 127.0.0.1:8007 0.0.0.0:*\nLISTEN 0 2048 127.0.0.1:22400 0.0.0.0:*\nLISTEN 0 2048 127.0.0.1:22500 0.0.0.0:*'
    loopback_gateway=$'LISTEN 0 2048 127.0.0.1:8006 0.0.0.0:*\nLISTEN 0 2048 127.0.0.1:8007 0.0.0.0:*\nLISTEN 0 2048 127.0.0.1:22400 0.0.0.0:*\nLISTEN 0 2048 127.0.0.1:22500 0.0.0.0:*'
    exposed_backend=$'LISTEN 0 2048 0.0.0.0:8006 0.0.0.0:*\nLISTEN 0 2048 127.0.0.1:8007 0.0.0.0:*\nLISTEN 0 2048 127.0.0.1:22400 0.0.0.0:*\nLISTEN 0 2048 0.0.0.0:22500 0.0.0.0:*'
    assert_command "listener audit accepts an exposed Gateway with loopback-only internals" \
        env PATH="${fake_bin}:${PATH}" FAKE_SS_OUTPUT="${expected_listeners}" bash -c 'source "$1"; audit_service_listeners' _ "${validator}"
    assert_fails_with "listener audit rejects a loopback-only Gateway" "Gateway port 8006 is not reachable" \
        env PATH="${fake_bin}:${PATH}" FAKE_SS_OUTPUT="${loopback_gateway}" bash -c 'source "$1"; audit_service_listeners' _ "${validator}"
    assert_fails_with "listener audit rejects an exposed Backend" "port 22500 is exposed beyond loopback" \
        env PATH="${fake_bin}:${PATH}" FAKE_SS_OUTPUT="${exposed_backend}" bash -c 'source "$1"; audit_service_listeners' _ "${validator}"

    curl_log="$(mktemp)"
    cat >"${fake_bin}/curl" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"${FAKE_CURL_LOG}"
printf '{"status":"healthy"}\n'
SH
    cat >"${fake_bin}/hostname" <<'SH'
#!/usr/bin/env bash
printf 'compute001\n'
SH
    chmod +x "${fake_bin}/curl" "${fake_bin}/hostname"
    assert_command "Gateway health validation checks loopback and the compute hostname directly" bash -c '
        output="$(env PATH="$1:$PATH" FAKE_CURL_LOG="$2" bash -c '\''source "$1"; fetch_gateway_health_checks'\'' _ "$3")"
        [[ "$(grep -c '\''"status":"healthy"'\'' <<<"$output")" -eq 2 ]] &&
        grep -q -- "--noproxy \* .*https://127.0.0.1:8006/health" "$2" &&
        grep -q -- "--noproxy \* .*https://compute001:8006/health" "$2"
    ' _ "${fake_bin}" "${curl_log}" "${validator}"
fi
if [[ -f "${serve_job}" ]]; then
    assert_output "service defaults to the A800 emergency partition" "emergency_gpu" sbatch_value "${serve_job}" partition
    assert_output "service uses the matching A800 QoS" "emergency_gpu" sbatch_value "${serve_job}" qos
    assert_output "service requests one A800" "gpu:a800:1" sbatch_value "${serve_job}" gres
    assert_output "service has a 30-minute limit" "00:30:00" sbatch_value "${serve_job}" time
    assert_output "service receives TERM before timeout" "B:TERM@60" sbatch_value "${serve_job}" signal
fi
if [[ -f "${chat_client}" ]]; then
    assert_command "Realtime text client compiles" python -m py_compile "${chat_client}"
    assert_command "Realtime text client exposes CLI help without optional dependencies" python "${chat_client}" --help
fi
fi

if (( test_stage >= 4 )); then
for path in client/health.py client/requirements.txt README.md; do
    assert_file "${SERVICE_ROOT}/${path}" "${path} exists"
done
health_client="${SERVICE_ROOT}/client/health.py"
if [[ -f "${health_client}" ]]; then
    assert_command "health client compiles" python -m py_compile "${health_client}"
    assert_command "health client exposes CLI help" python "${health_client}" --help
    assert_command "health client handles a real local JSON endpoint" python - "${health_client}" <<'PY'
import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import sys

spec = importlib.util.spec_from_file_location("health_client", sys.argv[1])
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        payload = json.dumps({"status": "healthy"}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        return

server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    result = module.fetch_health(f"http://127.0.0.1:{server.server_port}", timeout=2.0, insecure=False)
    assert result["ok"] is True, result
    assert result["response"]["status"] == "healthy", result
    assert result["client_latency_ms"] >= 0, result
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)
PY
fi

if [[ -f "${chat_client}" ]]; then
    assert_command "Realtime URL normalization preserves the official modes" python - "${chat_client}" <<'PY'
import importlib.util
import sys

spec = importlib.util.spec_from_file_location("text_chat", sys.argv[1])
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)
assert module.normalize_url("https://localhost:8006") == "wss://localhost:8006/v1/realtime?mode=chat"
assert module.normalize_url("wss://localhost:8006/v1/realtime?mode=chat") == "wss://localhost:8006/v1/realtime?mode=chat"
PY
fi
fi

printf '1..%d\n' "${checks}"
if (( failures > 0 )); then
    printf '# %d check(s) failed\n' "${failures}" >&2
    exit 1
fi
printf '# all %d static checks passed\n' "${checks}"
