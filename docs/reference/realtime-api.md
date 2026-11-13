# Realtime API：当前项目使用范围

前端保留原 WebSocket 会话与文本事件结构。MiniCPM 部分基于固定 [MiniCPM-o Demo](https://github.com/OpenBMB/MiniCPM-o-Demo/tree/47709a9210dfd71afa76c058e017fc8c4db5c8d2) 及 backend 分支补丁；API 网关复用前端需要的生命周期与文本事件，内部调用 DeepSeek HTTP API。完整服务接口见 [backend/CALLING_API.md](https://github.com/KTfine/Hum_Project/blob/backend/CALLING_API.md)。

## API 网关

`python realtime_av_test.py --backend api` 默认连接 `ws://127.0.0.1:8006/v1/realtime?mode=video`。前端传入已组装的 system prompt；收到 `session.created` 后持续发送当前相机帧，终端输入文字时附在同一输入消息中。网关输出 `response.output.delta` 文本增量和 `response.done`，前端继续解析 speak、mode 和立绘动作标签。

完成首轮用户请求后，网关在有新帧且当前生成结束时继续观察，默认间隔为 8 秒；后端 `--visual-interval 0` 可关闭自动观察。新文字优先，打断旧输出并发出 `response.interrupted`，由前端清理未闭合的解析片段。持续观察能力及模型判断质量仍需分别验证。

这一模式不使用音频输入或生成音频。不能把下面 MiniCPM 的 Float32 音频块、`force_listen` 或双工生成配置当作 API 模型原生能力。Key 保留在后端。以下章节记录原 MiniCPM 接口。

## 地址与生命周期

| 用途 | 本地 SSH 隧道地址 |
|---|---|
| 网关存活 / Worker 状态 | `https://localhost:18006/health` / `/status` |
| 文字或单轮多模态 | `wss://localhost:18006/v1/realtime?mode=chat` |
| 音频全双工 | `wss://localhost:18006/v1/realtime?mode=audio` |
| 音视频全双工（本项目正常客户端） | `wss://localhost:18006/v1/realtime?mode=video` |

health 响应不等于 Worker 可推理。当前启动脚本注册一个 Worker，忙时其他会话排队。端口、监听和隧道见 [部署说明](../cloud-deployment.md)。服务不提供 API Key 校验；通过 SSH 访问。所有消息为 JSON 文本帧，媒体在字段内 Base64 编码。

```text
连接 → session.queued / session.queue_update（排队时）
     ← session.queue_done
     → session.init
     ← session.created
     → input.append（一次或连续多次）
     ← response.output.delta / response.done
     → session.close
     ← session.closed
```

客户端收到 queue_done 后发送 init，收到 created 后才发送输入。错误可能是 `{"type":"error","error":{"code":"...","message":"..."}}`、session.closed 或连接断开，均不能算正常回复。

## video 初始化与输入

`realtime_av_test.build_session_init` 当前构造：

```json
{"type":"session.init","payload":{"system_prompt":"实际组装的提示词","config":{"length_penalty":1.0,"generate_audio":false,"max_new_speak_tokens_per_chunk":96,"temperature":0.2,"top_p":0.8,"top_k":10},"max_slice_nums":1,"use_tts":false}}
```

`config.generate_audio` 是双工生成器实际使用的开关；外层 use_tts 为兼容字段。本仓库 `duplex-session-options.patch` 转发音频开关和每块文本上限。正常客户端关闭 TTS，意外收到音频也不播放。

每秒发送一个 `build_video_input` 消息：

```json
{"type":"input.append","input":{"input_id":"chunk-000001","audio":"BASE64_FLOAT32_PCM","force_listen":false,"max_slice_nums":1,"video_frames":["BASE64_JPEG"]}}
```

音频是 16 kHz 单声道 little-endian Float32 PCM，一秒 16000 个采样、64000 字节，不含 WAV 头。video_frames 为 JPEG 字节的 Base64 数组；客户端每块取最新一帧。指导模式没有立绘，合照才加入小窗；无相机时指导发空白帧。`force_listen=true` 只让模型监听，本项目正常发送为 false。

## chat 输入

通用连接探针位于 [backend 分支 client/](https://github.com/KTfine/Hum_Project/tree/backend/client)，不加载拍照助手 prompt。在 backend 分支的独立工作目录执行：

```powershell
python client/text_chat.py --url https://localhost:18006 --insecure --pretty --prompt "请只回复：连接成功"
```

chat 初始化使用空 payload，输入示例如下；实验须自行传入实际 system 内容并记录配置：

```json
{"type":"input.append","input":{"messages":[{"role":"system","content":"实际组装的提示词"},{"role":"user","content":"切换到合照模式。"}],"streaming":true,"generation":{"max_new_tokens":256,"length_penalty":1.0},"image":{"max_slice_nums":1},"omni_mode":false,"tts":{"enabled":false},"use_tts_template":false,"enable_thinking":false}}
```

chat 的 generation 与双工的 config 不同，不把 chat 默认采样宣称为 video 的 temperature/top_p/top_k。多轮实验应明确 messages 中携带的历史。

单轮图片和音频的 content 可使用上游定义的类型化列表：text 使用 text，image 使用 Base64 data，audio 使用 Base64 PCM data 和 sample_rate。完整多模态字段见固定版本 [chat 文档](https://github.com/OpenBMB/MiniCPM-o-Demo/blob/47709a9210dfd71afa76c058e017fc8c4db5c8d2/docs/zh/api/chat.md)。audio 双工不是本项目正常入口，其完整选项见固定版本 [双工文档](https://github.com/OpenBMB/MiniCPM-o-Demo/blob/47709a9210dfd71afa76c058e017fc8c4db5c8d2/docs/zh/api/duplex.md)，不在此承诺已验证所有选项。

## 输出与本地事件

| 服务事件 | 客户端行为 |
|---|---|
| response.output.delta，kind=text | 按 response_id 和到达顺序解析 text，完整标签立即分发 |
| kind=listen | 结束当前解析片段 / 清理状态 |
| kind=audio | 解码后忽略，不播报 |
| response.done | 结束本轮；正常客户端不重复执行其中的汇总 text |
| session.closed / error | 记录关闭或错误，退出或走对应恢复路径 |

关闭消息：`{"type":"session.close","reason":"user_stop"}`。reason 为诊断信息，不视为穷尽枚举。

`session.mode_requested`、`session.mode_ready`、`parser.command`、`parser.plain_text_adapted`、`command.applied`、`command.skipped`、`speak` 是本地 JSONL 事件，不是服务端 API。模型标签见 [标签协议](command-protocol.md)，任务切换见 [模式说明](../modes-and-prompts.md)。日志会缩略媒体载荷；公开实验摘要不能还原完整输入。
