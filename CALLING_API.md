# MiniCPM-o 4.5 服务调用手册

本文说明如何从个人电脑调用本目录部署的 MiniCPM-o 4.5 服务，包括连接方式、
输入输出格式、会话行为和可直接使用的客户端。部署、下载模型和提交 Slurm 作业请
参阅 [README.md](README.md)。

## 1. 接口概览

对外只使用计算节点 Gateway 的 `8006` 端口。该端口只监听计算节点的
`127.0.0.1`，必须通过 SSH 隧道访问。

| 用途 | 方法 | 本机隧道后的地址 |
|---|---|---|
| 健康检查 | HTTPS GET | `https://localhost:8006/health` |
| 服务与队列状态 | HTTPS GET | `https://localhost:8006/status` |
| 文字/单轮多模态 | WebSocket | `wss://localhost:8006/v1/realtime?mode=chat` |
| 音频全双工 | WebSocket | `wss://localhost:8006/v1/realtime?mode=audio` |
| 音视频全双工 | WebSocket | `wss://localhost:8006/v1/realtime?mode=video` |
| 官方音频页面 | 浏览器 | `https://localhost:8006/audio_duplex` |
| 官方音视频页面 | 浏览器 | `https://localhost:8006/omni` |

这不是 OpenAI 兼容的 `/v1/chat/completions` REST API。三种推理模式都使用
JSON 文本帧形式的 Realtime WebSocket 协议。音频和图像也放在 JSON 中，以
Base64 字符串传输；不要发送 WebSocket 二进制帧。

当前服务没有 API Key 验证。安全边界是计算节点的 localhost 监听和 SSH
身份认证，因此不要把 `8006` 直接监听或转发到公网地址。

## 2. 每次调用前建立连接

### 2.1 启动作业并等待就绪

在集群登录节点执行：

```bash
cd /hpc2hdd/home/yliu674/aiaa3800/MiniCPM-o-4.5-service
job_id=$(sbatch --parsable slurm/serve.sbatch)
echo "$job_id"
squeue -j "$job_id" -o '%.18i %.20P %.8T %.20R'
tail -f "logs/slurm/minicpmo45-serve_${job_id}.out"
```

等到输出出现 `service ready`。再取得计算节点名：

```bash
compute_host=$(squeue -j "$job_id" -h -o '%N')
echo "$compute_host"
```

作业排队时没有计算节点，也无法建立可用的隧道。默认服务时限为 30 分钟；作业
结束后所有现有连接会断开，下一次作业可能分配到不同节点。

### 2.2 从个人电脑建立 SSH 隧道

Windows PowerShell 示例，其中 `COMPUTE_HOST` 替换为实际节点名：

```powershell
ssh -N -J yliu674@hpc2login.hpc.hkust-gz.edu.cn `
  -L 8006:127.0.0.1:8006 yliu674@COMPUTE_HOST
```

这个 PowerShell 窗口必须保持打开。若电脑上的 `8006` 已被占用，可以改用：

```powershell
ssh -N -J yliu674@hpc2login.hpc.hkust-gz.edu.cn `
  -L 18006:127.0.0.1:8006 yliu674@COMPUTE_HOST
```

随后所有示例中的本机端口也改成 `18006`。不要转发内部端口 `8007`、`22400`
或 `22500`。

### 2.3 自签名证书

服务使用自签名 TLS 证书。第一次使用浏览器时先打开
<https://localhost:8006> 并接受证书警告，否则页面内的 WSS 连接可能失败。

命令行客户端可以在可信的本地隧道场景使用 `--insecure`。自己编写客户端时，
开发阶段可以关闭此连接的证书校验，但不要把关闭校验作为通用互联网客户端的
默认行为。

### 2.4 健康检查

最简单的调用：

```powershell
curl.exe -k https://localhost:8006/health
```

正常响应：

```json
{
  "status": "healthy",
  "timestamp": "2026-10-15T22:07:57.000000"
}
```

`/health` 只证明 Gateway 可响应。`/status` 还能查看 Worker 数量、忙闲状态和
队列长度。项目客户端会检查 `/health`：

```powershell
py health.py --insecure --pretty
```

## 3. 所有模式共有的会话生命周期

一个 WebSocket 连接对应一个模型会话。标准顺序如下：

```text
客户端连接 /v1/realtime?mode=...
  <- session.queued / session.queue_update（仅需排队时）
  <- session.queue_done
  -> session.init
  <- session.created
  -> input.append（一次或持续多次）
  <- response.*
  -> session.close
  <- session.closed
```

重要行为：

- 收到 `session.queue_done` 后再发送 `session.init`。
- `session.created` 表示模型会话已经初始化，可以开始输入。
- 服务当前只有一个 Worker，同时只能执行一个推理会话。其他连接会进入队列。
- 客户端关闭 WebSocket、发送 `session.close`、服务作业到期或后端异常都会结束
  会话。
- `session_id` 由服务端生成。日志和保存的会话数据可用它关联。
- 每个客户端消息都是一个 JSON 对象；字段 `type` 决定消息类型。

### 3.1 排队事件

忙碌时首先收到：

```json
{
  "type": "session.queued",
  "position": 1,
  "estimated_wait_s": 30.0,
  "ticket_id": "...",
  "queue_length": 1
}
```

等待期间服务可能每约 3 秒发送 `session.queue_update`。获得 Worker 后收到：

```json
{"type": "session.queue_done"}
```

队列满时收到 `error`，错误码为 `queue_full`，随后连接以 WebSocket 状态码
`1013` 关闭。没有可用 Worker 时可能返回 `worker_busy`。

### 3.2 初始化与关闭

最低限度的初始化消息：

```json
{
  "type": "session.init",
  "payload": {}
}
```

成功后收到的结构类似：

```json
{
  "type": "session.created",
  "session_id": "sess_ab12cd34ef56",
  "mode": "turn_based",
  "metrics": {},
  "usage": {},
  "server_send_ts": 1792073277.123
}
```

主动关闭：

```json
{"type": "session.close", "reason": "user_stop"}
```

服务端随后返回 `session.closed`，其中通常包含 `session_id`、`reason`、`usage`
和 `server_send_ts`。`reason` 是诊断信息，不应作为固定枚举硬编码。

### 3.3 通用错误

公开 Gateway 错误采用以下结构：

```json
{
  "type": "error",
  "error": {
    "code": "queue_full",
    "message": "Queue full",
    "type": "server_error"
  }
}
```

后端运行时错误也可能表现为 `session.closed` 且
`reason: "backend_error"`。客户端应同时处理 `error`、`session.closed` 和
WebSocket 意外断开。

## 4. 文字对话：`mode=chat`

### 4.1 最简单的现成调用

把项目的 `client/` 目录复制到个人电脑后安装依赖：

```powershell
cd minicpm-client
py -m pip install -r requirements.txt
py text_chat.py --insecure --pretty --prompt "请只回复：连接成功"
```

也可以指定另一个本地端口或完整 WSS 地址：

```powershell
py text_chat.py --url https://localhost:18006 --insecure --pretty `
  --prompt "用一句话介绍你自己"
```

客户端最终输出的不是服务端原始事件，而是方便脚本消费的汇总 JSON：

```json
{
  "type": "text_chat_validation",
  "ok": true,
  "url": "wss://localhost:8006/v1/realtime?mode=chat",
  "session_id": "sess_...",
  "text": "连接成功",
  "client_total_ms": 4433.626,
  "client_first_text_ms": 4280.099,
  "server_reason": "turn_end",
  "server_metrics": {}
}
```

`client_first_text_ms` 从发送 `input.append` 到首个文字增量；
`client_total_ms` 包含 WebSocket 建连、排队、初始化和完整生成时间。

### 4.2 原始输入格式

收到 `session.created` 后发送：

```json
{
  "type": "input.append",
  "input": {
    "input_id": "optional-client-id",
    "messages": [
      {"role": "user", "content": "你好，请用一句话回答。"}
    ],
    "streaming": true,
    "generation": {
      "max_new_tokens": 256,
      "length_penalty": 1.1
    },
    "image": {"max_slice_nums": 1},
    "omni_mode": false,
    "tts": {"enabled": false},
    "use_tts_template": false,
    "enable_thinking": false
  }
}
```

字段说明：

| 字段 | 类型 | 默认值/行为 |
|---|---|---|
| `messages` | array | 对话消息；缺省为空数组，但正常调用应提供 |
| `messages[].role` | string | `system`、`user` 或 `assistant` |
| `streaming` | boolean | 默认 `true` |
| `generation.max_new_tokens` | integer | 默认 `256` |
| `generation.length_penalty` | number | 默认 `1.1` |
| `image.max_slice_nums` | integer/null | 图像切片上限 |
| `tts.enabled` | boolean | 默认 `false`；是否生成语音 |
| `tts.ref_audio_data` | string | 可选，Base64 16 kHz Float32 PCM 参考音频 |
| `use_tts_template` | boolean | 开启 TTS 时会自动视为 `true` |
| `omni_mode` | boolean | 普通文字建议为 `false` |
| `enable_thinking` | boolean | 默认 `false` |
| `input_id` | string | 可选；服务端会在响应中原样带回，便于关联 |

文本消息的 `content` 可以是字符串，也可以是内容项数组。例如图片加问题：

```json
{
  "role": "user",
  "content": [
    {"type": "image", "data": "BASE64_JPEG_OR_PNG"},
    {"type": "text", "text": "图中有什么？"}
  ]
}
```

内容项还支持：

- `{"type":"audio","data":"BASE64_FLOAT32_PCM","sample_rate":16000}`
- `{"type":"video","data":"BASE64_VIDEO_FILE","stack_frames":1}`

这里的 `data` 只放纯 Base64，不要添加 `data:image/jpeg;base64,` 等 Data URL
前缀。音频内容必须为 16 kHz、单声道、Float32 PCM。

多轮对话由客户端负责把历史重新放入 `messages`，例如依次包含
`user`、`assistant`、`user`。服务不会接受一个普通 OpenAI
`conversation_id` 来自动还原历史。

### 4.3 文字流式输出

当 `streaming: true` 时，每段文字事件如下：

```json
{
  "type": "response.output.delta",
  "kind": "text",
  "session_id": "sess_...",
  "response_id": "resp_...",
  "input_id": "optional-client-id",
  "text": "部分文字",
  "server_send_ts": 1792073281.123
}
```

按收到顺序拼接所有 `kind: "text"` 的 `text`。一轮结束时收到：

```json
{
  "type": "response.done",
  "session_id": "sess_...",
  "response_id": "resp_...",
  "input_id": "optional-client-id",
  "text": "完整回答",
  "reason": "turn_end",
  "metrics": {},
  "server_send_ts": 1792073282.456
}
```

稳妥的客户端优先使用 `response.done.text` 作为最终文本；如果该字段为空，再使用
增量拼接结果。

若开启 TTS，流式语音通过 `response.output.delta` 且 `kind: "audio"` 返回，
`audio` 是 Base64 编码的 24 kHz、单声道、little-endian Float32 PCM。非流式
调用会在 `response.done.audio` 中返回整段同格式音频。

## 5. 音频全双工：`mode=audio`

### 5.1 推荐调用方式

需要实时麦克风交互时，直接使用官方页面最稳妥：

```text
https://localhost:8006/audio_duplex
```

浏览器会完成采样、分块、实时节拍、播放缓冲和回声抑制。建议戴耳机，避免模型
播出的声音重新进入麦克风并触发错误打断。

文件输入或自动化基准可使用固定上游中的官方脚本：

```powershell
py upstream/examples/realtime/audio_probe.py `
  --url https://localhost:8006 `
  --input-wav C:\path\to\input.wav `
  --insecure --pretty-json
```

该脚本会自动转成所需格式，并输出首文字/首音频延迟、音频块间隔、抖动和播放
欠载次数。它需要 `numpy`、`websockets`，输入文件须能被 Python `wave`
读取。

### 5.2 初始化输入

```json
{
  "type": "session.init",
  "payload": {
    "system_prompt": "你是一个有帮助的语音助手。",
    "config": {"length_penalty": 1.05},
    "use_tts": true,
    "ref_audio_base64": "OPTIONAL_BASE64_FLOAT32_PCM",
    "tts_ref_audio_base64": "OPTIONAL_BASE64_FLOAT32_PCM"
  }
}
```

- 两个参考音频字段都是纯 Base64 的 16 kHz 单声道 Float32 PCM，不是 WAV
  文件整体的 Base64。
- `ref_audio_base64` 用作模型参考声音；未单独提供 TTS 参考时也会用于 TTS。
- `tts_ref_audio_base64` 可为 TTS 指定另一段参考声音。
- 不需要自定义声音时可以省略二者。

### 5.3 连续音频输入

官方页面按实时节拍，每 1000 ms 发送一个块：

```json
{
  "type": "input.append",
  "input": {
    "input_id": "optional-chunk-id",
    "audio": "BASE64_FLOAT32_PCM",
    "force_listen": false
  }
}
```

音频硬性格式：

- 16000 Hz；
- 单声道；
- little-endian IEEE Float32 PCM；
- 样本值通常在 `[-1.0, 1.0]`；
- Base64 只编码原始样本字节，不包含 WAV 头；
- 推荐一个块正好 16000 个样本，即 1 秒、64000 字节（Base64 前）。

必须按音频的真实时间节拍持续发送。不要一次瞬间灌入几十个 1 秒块；那会改变
实时行为并阻塞输出节奏。语音文件结束后可继续发送静音块，让模型完成当前回复。

Python 编码示意：

```python
import base64
import numpy as np

samples = np.asarray(samples, dtype="<f4")  # 16 kHz mono, one second
audio_b64 = base64.b64encode(samples.tobytes()).decode("ascii")
```

`force_listen: true` 表示要求模型保持/恢复监听，用于打断当前说话。它不是
“结束输入”的标志。全双工会话没有必须发送的单独 end-of-audio 消息。

### 5.4 全双工输出与行为

服务会持续返回 `response.output.delta`，`kind` 有三种：

1. 文字：

```json
{
  "type": "response.output.delta",
  "kind": "text",
  "text": "增量转写或回答",
  "response_id": "resp_...",
  "metrics": {},
  "usage": {},
  "server_send_ts": 1792073282.123
}
```

2. 语音：

```json
{
  "type": "response.output.delta",
  "kind": "audio",
  "audio": "BASE64_FLOAT32_PCM_24KHZ",
  "response_id": "resp_...",
  "metrics": {},
  "server_send_ts": 1792073282.234
}
```

3. 回到监听状态：

```json
{
  "type": "response.output.delta",
  "kind": "listen",
  "response_id": "resp_...",
  "metrics": {},
  "server_send_ts": 1792073282.345
}
```

输出音频为 24000 Hz、单声道、little-endian Float32 PCM。客户端应按到达顺序
排队播放，不能把每个块当成独立 WAV 文件。解码时可使用：

```python
raw = base64.b64decode(message["audio"])
samples = np.frombuffer(raw, dtype="<f4")
```

`kind: "listen"` 表示模型当前不输出语音或本轮说话已经结束，可以结束当前播放
turn，但 WebSocket 会话仍然继续。全双工模式主要靠连续 delta 和 `listen`
表达状态，不应等待每段话都有一个 `response.done`。

`metrics` 可能含有 `prefill_ms`、`wall_clock_ms`、`generate_ms`、
`kv_cache_length` 等；这些字段用于观测，客户端业务逻辑不应依赖它们始终存在。
`usage`、`chunk_usage` 和 `chunk_index` 也可能只附在同一次处理产生的第一个输出
事件中。

## 6. 音视频全双工：`mode=video`

### 6.1 推荐调用方式

摄像头和麦克风实时交互使用官方页面：

```text
https://localhost:8006/omni
```

文件输入基准使用官方脚本（个人电脑需安装 FFmpeg）：

```powershell
py upstream/examples/realtime/video_probe.py `
  --url https://localhost:8006 `
  --video C:\path\to\input.mp4 `
  --insecure --pretty-json
```

它会通过 FFmpeg 提取 16 kHz 单声道音频和 JPEG 帧，并按实时节拍发送。

### 6.2 初始化

初始化与音频模式相同，通常额外指定切片上限：

```json
{
  "type": "session.init",
  "payload": {
    "system_prompt": "你是一个能观察画面的语音助手。",
    "config": {"length_penalty": 1.0},
    "max_slice_nums": 1,
    "use_tts": true
  }
}
```

### 6.3 音频与视频帧输入

每个输入块必须包含音频；视频帧是可选数组：

```json
{
  "type": "input.append",
  "input": {
    "input_id": "optional-chunk-id",
    "audio": "BASE64_FLOAT32_PCM_16KHZ",
    "video_frames": [
      "BASE64_JPEG_FRAME"
    ],
    "force_listen": false,
    "max_slice_nums": 1
  }
}
```

- `audio` 格式和节拍与音频模式完全相同，而且不可省略。
- `video_frames` 的每项是完整 JPEG 文件字节的纯 Base64，不带 Data URL
  前缀。
- 官方实时页面通常每个 1 秒音频块附带一帧。
- 没有新画面时可省略 `video_frames`，但仍继续发送音频。
- `max_slice_nums` 控制图像切片数量，默认 `1`。提高它会增加视觉 token、显存
  和延迟，除非确有小字或高分辨率细节需求，不建议修改。

输出事件和音频模式相同。视觉处理信息可能出现在 `metrics.vision_slices` 和
`metrics.vision_tokens`，但它们不是每个事件都必有。

## 7. 最小 WebSocket 客户端框架

下面的 Python 示例展示文字协议的完整控制流。项目已有的
`client/text_chat.py` 功能更完整，实际使用优先调用它。

```python
import asyncio
import json
import ssl
import websockets

URL = "wss://localhost:8006/v1/realtime?mode=chat"

async def main():
    tls = ssl._create_unverified_context()  # 仅用于本机 SSH 隧道和自签名证书
    async with websockets.connect(URL, ssl=tls, max_size=128 * 1024 * 1024) as ws:
        text_parts = []
        while True:
            event = json.loads(await ws.recv())
            event_type = event.get("type")

            if event_type == "session.queue_done":
                await ws.send(json.dumps({"type": "session.init", "payload": {}}))

            elif event_type == "session.created":
                await ws.send(json.dumps({
                    "type": "input.append",
                    "input": {
                        "messages": [{"role": "user", "content": "你好"}],
                        "streaming": True,
                        "generation": {"max_new_tokens": 128},
                        "tts": {"enabled": False}
                    }
                }, ensure_ascii=False))

            elif event_type == "response.output.delta" and event.get("kind") == "text":
                text_parts.append(event.get("text", ""))

            elif event_type == "response.done":
                print(event.get("text") or "".join(text_parts))
                await ws.send(json.dumps({"type": "session.close", "reason": "done"}))

            elif event_type == "error":
                raise RuntimeError(event)

            elif event_type == "session.closed":
                break

asyncio.run(main())
```

生产型客户端还应设置连接超时、单次推理超时、最大消息大小，捕获连接关闭，并在
作业结束后重新获取计算节点和重建 SSH 隧道。

## 8. 行为与容量约束

- 一个 Worker 同时处理一个会话。长时间打开全双工页面会一直占用 Worker；不用
  时应发送 `session.close` 或关闭页面。
- `mode=chat` 是轮次式调用；一个会话内可再次发送 `input.append`，但对话历史的
  组织仍由客户端负责。
- `mode=audio` 和 `mode=video` 是持续流。输入流可以与模型语音输出同时进行，
  这就是全双工行为。
- 默认 Slurm 作业 30 分钟。服务会在时限前收到终止信号并清理，会话不会跨作业
  恢复。
- WebSocket 单消息上限在官方客户端中设置为 128 MiB，但实时调用应保持小块，
  不要把长音频或整个视频塞进一个全双工 `input.append`。
- 服务会把会话记录写入 `data/sessions/`。输入音频、画面和输出可能包含隐私
  信息。

## 9. 客户端应如何处理异常

建议按以下原则处理：

1. HTTPS `/health` 不通：检查作业是否仍为 `RUNNING`、计算节点是否变化、隧道
   窗口是否仍开着。
2. TLS/WSS 失败：先用浏览器接受证书，或只对 localhost 自签名连接启用
   `--insecure`。
3. 一直停在队列：检查 `/status`；现有会话可能占着唯一 Worker。
4. 收到 `error`：记录完整事件和 `session_id`，然后关闭当前连接。
5. 收到 `session.closed`：停止录音和播放，不能在旧连接上继续发包。
6. WebSocket 意外断开：不要盲目重放全双工音频；先确认作业和节点，再创建新
   会话。
7. 输出音频爆音或语速异常：确认按 little-endian Float32、24 kHz、单声道
   解码，而不是 Int16 或 WAV。
8. 模型听不懂或无响应：确认输入是 16 kHz Float32 单声道，并以实时节拍发送，
   文件末尾附加少量静音。

## 10. 已验证范围

当前部署作业 `13091474` 已实际验证：

- Gateway、Worker、模型 Backend 正常启动；
- BF16、无量化；
- 文字 Realtime 请求成功并返回 `MiniCPM service OK`；
- 文字首次增量约 `4280 ms`，完整请求约 `4434 ms`；
- 服务稳定空跑约 29 分钟，显存约 `21.2 GiB`。

音频与音视频模块已经成功加载，本文中的协议字段来自当前固定版本的官方 Demo
代码和官方探针脚本；麦克风全双工和摄像头全双工尚未在个人电脑端完成实际验收。

## 11. 对照源码

当上游版本变化时，以本部署固定版本中的以下文件为准：

- `client/text_chat.py`：最小文字客户端；
- `client/health.py`：健康检查客户端；
- `upstream/static/duplex/lib/realtime-session.js`：官方浏览器协议实现；
- `upstream/examples/realtime/audio_probe.py`：官方音频探针；
- `upstream/examples/realtime/video_probe.py`：官方视频探针；
- `upstream/py_backend/server.py`：输入解析和输出事件生成。
