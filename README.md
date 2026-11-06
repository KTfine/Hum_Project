# MiniCPM-o 4.5 Slurm 服务

本目录部署官方 BF16 `openbmb/MiniCPM-o-4_5` 和官方
`OpenBMB/MiniCPM-o-Demo`。它提供文字、音频全双工和音视频全双工
Realtime WebSocket API。服务只监听计算节点的 `127.0.0.1`，不能从公网或
校园网直接访问。

所有 `sbatch` 命令都由你手动执行。不要在登录节点直接运行
`bootstrap_cpu.sh`、`download_model.sh`、`probe_gpu.sh` 或
`launch_service.sh`；脚本也会主动拒绝这种执行方式。

## 目录与固定版本

- 服务目录：`/hpc2hdd/home/yliu674/aiaa3800/MiniCPM-o-4.5-service`
- 官方 Demo commit：`47709a9210dfd71afa76c058e017fc8c4db5c8d2`
- 官方模型 revision：`503e754207c94da6bb26850b4469f367c9ea3582`
- 精度：BF16，不量化
- 单 Worker 官方参考显存：初始化后约 21.5GB；实际值以
  `logs/<job-id>/gpu_memory.csv` 为准
- 服务作业：一张 A800 或 A40，默认 30 分钟

`face` 环境只提供 Python 3.10 引导。官方安装器会在
`upstream/.venv/base` 建立独立环境，不会把现有 `face` 包版本当作运行时。

## 0. 先处理已有密钥

父目录的 `cmds.txt` 含有明文 GitHub 和 Hugging Face token。请先在相应平台
吊销并重建。此项目不会读取该文件，也不会把 token 写入脚本或日志。

## 1. 登录并检查队列

```bash
ssh yliu674@hpc2login.hpc.hkust-gz.edu.cn
cd /hpc2hdd/home/yliu674/aiaa3800/MiniCPM-o-4.5-service
bash scripts/check_queue.sh
```

队列结果只是瞬时快照。两个 emergency 分区要求不同的同名 QoS，单个作业
不能自动跨分区切换 QoS。默认脚本使用 `emergency_gpua40` 和一张 A40；
需要 A800 时必须同时覆盖 partition、QoS 和 GRES。

## 2. CPU 作业：安装官方 Demo

```bash
sbatch slurm/bootstrap_cpu.sbatch
squeue -u "$USER"
```

等待作业完成，再检查：

```bash
tail -n 100 logs/slurm/minicpmo45-bootstrap_<JOB_ID>.out
tail -n 100 logs/slurm/minicpmo45-bootstrap_<JOB_ID>.err
```

它会克隆固定 commit、调用官方 `install.sh`，并生成只用于 localhost 的
自签名 TLS 证书。这个任务不申请 GPU。

## 3. CPU 作业：单独下载模型

模型是公开仓库，通常不需要 token：

```bash
sbatch slurm/download_model_cpu.sbatch
```

如果直连 Hugging Face 较慢，可只对该次提交传镜像：

```bash
HF_ENDPOINT=https://hf-mirror.com sbatch --export=ALL slurm/download_model_cpu.sbatch
```

如确实需要 token，先在当前 shell 中 `export HF_TOKEN=...`，再用
`sbatch --export=ALL ...`。不要把 token 写入脚本或命令历史。下载成功后会
生成 `.model_manifest.json` 和 `.model_revision`；前者逐项记录固定 revision
中的本地文件及大小。GPU 作业会先验证完整清单，再强制 Hugging Face 和
Transformers 离线运行，因此不会在启动时回退到在线下载。

## 4. GPU 探针

先用短作业确认实际节点的驱动、CUDA、BF16、PyTorch、FFmpeg、存储和网络：

```bash
sbatch slurm/probe_gpu.sbatch
```

也可以强制硬件类型：

```bash
sbatch -p emergency_gpu --qos=emergency_gpu --gres=gpu:a800:1 slurm/probe_gpu.sbatch
sbatch slurm/probe_gpu.sbatch  # 默认 A40
```

探针不加载模型。检查对应的 `logs/slurm/minicpmo45-probe_<JOB_ID>.out`，确认：

- `cuda_available True`
- `bf16_supported True`
- GPU 名称为 A800 或 A40
- PyTorch 为 2.8.0，Transformers 为 4.51.0
- 两个 HTTPS 连通性检查没有报错

## 5. 启动 30 分钟服务

默认申请 A40：

```bash
job_id=$(sbatch --parsable slurm/serve.sbatch)
echo "$job_id"
squeue -j "$job_id" -o '%.18i %.20P %.8T %.20R'
```

如果需要强制某一种 GPU：

```bash
sbatch -p emergency_gpu --qos=emergency_gpu --gres=gpu:a800:1 slurm/serve.sbatch
sbatch slurm/serve.sbatch  # 默认 A40
```

作业进入 `RUNNING` 后获取计算节点：

```bash
squeue -j "$job_id" -h -o '%N'
```

启动通常还需要等待模型加载和自动文字验证。查看：

```bash
tail -f "logs/slurm/minicpmo45-serve_${job_id}.out"
```

当日志出现 `service ready` 后再建立隧道。Slurm 会在时限前 60 秒发送 TERM，
启动器只清理自己创建的模型 Backend、转发 Worker、Gateway、验证和显存采样
进程；TERM 后最多等待 10 秒便会强制回收残留子进程。

## 6. Windows PowerShell SSH 隧道

将 `COMPUTE_HOST` 替换成上一步得到的节点名；此 PowerShell 窗口必须保持
打开：

```powershell
ssh -N -J yliu674@hpc2login.hpc.hkust-gz.edu.cn `
  -L 8006:127.0.0.1:8006 yliu674@COMPUTE_HOST
```

如果集群策略不允许 `ProxyJump`，使用等价的嵌套隧道：

```powershell
ssh -t -L 8006:127.0.0.1:8006 yliu674@hpc2login.hpc.hkust-gz.edu.cn `
  "ssh -N -L 8006:127.0.0.1:8006 yliu674@COMPUTE_HOST"
```

浏览器先打开 <https://localhost:8006>，接受仅限本机的自签名证书警告。随后
HTTPS/WSS 才能正常连接。只转发 8006；内部注册端口 8007、Worker 端口
22400 和模型 Backend 端口 22500 不要转发或公开。

## 7. 在电脑上调用 API

完整的输入输出格式、Realtime 事件、全双工行为和客户端实现说明见
[CALLING_API.md](CALLING_API.md)。下面仅保留最短调用路径。

复制轻量客户端到 Windows（在 PowerShell 中执行）：

```powershell
scp -r yliu674@hpc2login.hpc.hkust-gz.edu.cn:/hpc2hdd/home/yliu674/aiaa3800/MiniCPM-o-4.5-service/client .\minicpm-client
cd .\minicpm-client
py -m pip install -r requirements.txt
```

健康检查和文字 Realtime 对话：

```powershell
py health.py --insecure --pretty
py text_chat.py --insecure --pretty --prompt "请只回复：连接成功"
```

官方统一端点是：

```text
wss://localhost:8006/v1/realtime?mode=chat
wss://localhost:8006/v1/realtime?mode=audio
wss://localhost:8006/v1/realtime?mode=video
```

这不是经典 REST `/v1/chat/completions`。客户端必须遵循官方 Realtime 的
`session.queue_done → session.init → session.created → input.append →
response.output.delta/response.done` 生命周期。

## 8. 三种模式验收

### 文字

1. 运行上面的 `text_chat.py`。
2. 确认 JSON 中 `ok` 为 `true`、`text` 非空。
3. 记录 `client_first_text_ms` 和 `client_total_ms`。
4. GPU 作业也会自动做同样的确定性文字请求并写入
   `logs/<job-id>/validation.jsonl`。

### 音频全双工

1. 戴耳机，打开 <https://localhost:8006/audio_duplex>。
2. 允许浏览器使用麦克风。
3. 持续说话并确认模型能够一边监听一边输出语音，而非等待整段录音结束。
4. 观察页面的首段文字/音频响应，并对照 `gateway.log`、`worker.log`、
   `backend.log` 中该会话
   的 metrics。官方说明该模式仍属实验特性；耳机可减少回声造成的打断问题。

### 音视频全双工

1. 打开 <https://localhost:8006/omni>。
2. 允许摄像头和麦克风。
3. 将一个可辨识物体放到镜头前，同时提问；确认模型持续接收画面和声音并输出
   文字/语音。
4. 改变画面后再次提问，确认回答反映新画面，而不是复用第一次内容。
5. 记录页面首响应时间，并对照该时段的 `gpu_memory.csv`、Gateway/Worker 日志。

若要做可重复的文件输入基准，可直接使用固定版本上游提供的官方脚本：

```text
upstream/examples/realtime/audio_probe.py
upstream/examples/realtime/video_probe.py
```

它们会输出 `first_text_ms`、`first_audio_ms`、WebSocket 建连时间、音频块抖动
等指标。通过 SSH 隧道运行时使用 `--url https://localhost:8006 --insecure`；
音频脚本需要 WAV，视频脚本需要带音轨的 MP4。

### 本机摄像头、立绘与麦克风流式控制实验

根目录的 `realtime_av_test.py` 持续采集摄像头，把 `tachie/sanae/*.png` 生成的当前
白底立绘画布缩小后放在摄像头画面右上角，并默认每秒上传一张合成 JPEG。麦克风以
16 kHz Float32 PCM 连续采集并每秒上传一个块。MiniCPM-o 的 TTS 固定关闭；模型
返回的流式指令在完整 `>` 到达时立即执行，不等待整轮结束。

当前指令包括：

```text
<speak:内容>
<move:to,x=0.35,y=0.95,ms=400>
<move:by,dx=-0.10,dy=0,ms=300>
<scale:to,value=0.8,ms=400>
<scale:by,factor=1.1,ms=300>
<tachie:smile>
<rotate:to,value=10,ms=300>
<rotate:by,value=-5,ms=300>
<blank>
```

说话按顺序进入 FIFO；移动、缩放、旋转和立绘切换由独立通道处理。解析器会静默
跳过无法恢复的畸形内容，并继续寻找后续有效指令。

先在本机安装依赖：

```powershell
py -m pip install -r requirements-client.txt
```

启动 HPC 服务、建立 8006 SSH 隧道后运行：

```powershell
py realtime_av_test.py --insecure
```

每次启动都会在 `logs/frontend-<timestamp>.jsonl` 写入结构化前端日志，包括会话初始化、
收发事件、模型文本、解析结果、立绘控制和异常堆栈。音频和图片只记录字节数，不写入
Base64 正文。可用 `--log-file PATH` 指定日志位置。

画布窗口按 `Q`，或在终端按 `Ctrl+C` 退出。常用诊断方式：

```powershell
# 静音输入，只验证摄像头、文字流和控制执行
py realtime_av_test.py --insecure --no-mic

# 不打开摄像头，只上传白底立绘画布
py realtime_av_test.py --insecure --no-camera

# 选择另一台摄像头
py realtime_av_test.py --insecure --camera-device 1

# 使用另一套立绘，并指定初始状态
py realtime_av_test.py --insecure --sprite-dir tachie\sanae --initial-sprite smile

# 本机隧道使用 18006，并打印服务端 metrics
py realtime_av_test.py --url https://localhost:18006 --insecure --verbose
```

如果默认麦克风不对，可以使用 `--input-device` 指定设备；默认摄像头不对则使用
`--camera-device`。还可以使用 `--canvas-width`、`--canvas-height` 和
`--sprite-dir` 调整画布与立绘目录。
运行 `py realtime_av_test.py --help` 查看完整参数。

## 9. 日志与结果

每次服务作业的目录是 `logs/<job-id>/`：

| 文件 | 内容 |
|---|---|
| `environment.log` | 节点、GPU、驱动、CUDA、BF16 和包版本 |
| `backend.log` | 官方 PyTorch 模型 Backend 日志 |
| `worker.log` | 官方 Realtime 转发 Worker 日志 |
| `gateway.log` | 官方 Gateway、队列和 Realtime 会话日志 |
| `validation.jsonl` | 健康检查、文字结果、首字及总延迟 |
| `gpu_memory.csv` | 每 5 秒的显存、利用率和 GPU 型号 |
| `gpu_validation_snapshot.csv` | 自动文字验证时的显存快照 |
| `connection.txt` | 本次节点对应的隧道命令 |

Slurm 自身 stdout/stderr 在 `logs/slurm/`。比较 A40 与 A800 时至少记录：实际
GPU 名称、空闲到启动的等待时间、模型就绪时间、文字首字延迟、音频/视频首音频
延迟，以及 `gpu_memory.csv` 的峰值。

## 10. 常见问题

- **作业立即失败并提示 Slurm allocation**：你直接运行了受保护脚本；请提交
  对应 `.sbatch`。
- **输出文件目录不存在**：确认本目录中的 `logs/slurm/` 未被删除。
- **模型 marker/manifest 缺失或不匹配**：重新提交模型下载 CPU 作业；GPU 作业
  会保持离线并拒绝不完整快照。
- **浏览器 WSS 连接失败**：先访问根页面并接受证书，再检查隧道仍在运行、作业
  仍为 `RUNNING`。
- **麦克风或摄像头不可用**：确认地址是 `https://localhost:8006`，并检查浏览器
  站点权限。
- **端口占用**：关闭电脑上已有的 8006 隧道，或在本地改用
  `-L 18006:127.0.0.1:8006`，随后访问 `https://localhost:18006`。
- **服务突然断开**：默认作业只有 30 分钟，检查 `squeue` 和 Slurm stderr。

## 隐私

官方 Demo 会在服务目录的 `data/` 中保存会话数据。音频、视频帧、参考声音和模型
输出可能包含隐私信息；不要把该目录公开或提交到版本库，不再需要时由你自行按
学校数据规范清理。
