# 后端接口：MiniCPM 与 API 模式

这个 `backend` 分支保留原 MiniCPM 部署，在 `api_mode/` 增加 DeepSeek 文字／图片网关。两种后端使用同一个 `/v1/realtime` WebSocket 会话入口和流式文字事件；API 模式不提供语音识别或语音合成。原 MiniCPM 的音频能力及部署文件不受影响。

启动方式见 [README](README.md)。API 网关默认监听 `http://127.0.0.1:8006`，对应 `ws://127.0.0.1:8006/v1/realtime?mode=video`。`DEEPSEEK_API_KEY` 只配置在后端进程；前端不需要、也不发送供应商 Key。下述 API 模式行为以 [gateway.py](api_mode/gateway.py) 和 [llm.py](api_mode/llm.py) 为准。

## 健康检查与会话建立

| 入口 | API 模式返回／行为 |
|---|---|
| `GET /health` | `{"status":"healthy","backend":"api"}`；表示网关正在运行，不表示供应商请求已验证 |
| `GET /status` | 模型名、当前连接数、`capabilities`、观察间隔；`provider_verified:false` 不冒充外部 API 已可用 |
| `GET /v1/realtime?mode=video` | 文字＋持续图像输入；启用后台观察 |
| `GET /v1/realtime?mode=chat` | 文字／图文请求；不启动后台观察 |
| `GET /v1/realtime?mode=audio` | 保留路由兼容；API 仍不识别音频，也不合成音频 |

省略 `mode` 时默认为 `video`。这个参数是传输模式，与前端的 `guidance`／`co-photo` 任务模式不同。

1. WebSocket 连接后，服务端发送 `session.queue_done`，带 `session_id`。
2. 客户端发送 `session.init`。
3. 服务端成功创建供应商客户端后发送 `session.created`。此时尚未向 DeepSeek 发出推理请求。

```json
{
  "type": "session.init",
  "payload": {
    "system_prompt": "前端组装的完整提示词",
    "config": {"generate_audio": false},
    "max_slice_nums": 1,
    "use_tts": false
  }
}
```

```json
{
  "type": "session.created",
  "session_id": "服务端生成的 ID",
  "mode": "video",
  "backend": "api",
  "capabilities": {"text": true, "image": true, "audio": false}
}
```

`payload.system_prompt` 必须是字符串，省略时为空。一个连接只接受一次成功的初始化；替换提示词需关闭旧会话并重新连接。前端仍负责组装指导／合照 prompt、解释标签、切换画面及执行立绘动作；网关不自行添加角色动作规则。

## 文字与画面输入

原前端每秒发送 `input.append`。API 模式在原字段旁增加 `input.text`：

```json
{
  "type": "input.append",
  "input": {
    "input_id": "chunk-000001",
    "text": "我想拍一张展现活力的照片。",
    "video_frames": ["纯 Base64 JPEG，不含换行"],
    "force_listen": false,
    "max_slice_nums": 1
  }
}
```

- `text` 非空时立即发起一轮请求，并使用当前最新图像；此时已有回复会被打断。客户端可随时发送新的目标、修正或模式请求。
- `video_frames` 是图像字符串数组。网关取最后一张更新最新画面，不排队逐帧推理；单独发送图像不会立刻为每帧调用模型。
- 图片支持 PNG、JPEG、GIF、WebP 的纯 Base64 或 `data:image/...;base64,...`。单个编码字符串最多 12 MiB，整个 WebSocket 消息最多 16 MiB。
- 无文字且服务端空闲时，可以收到 `kind:"listen"`。生成中不发送这种空闲事件，以免客户端清空尚未闭合的标签。
- `input_id` 用于关联空闲事件；模型回复以独立的 `response_id` 标识。

只发送文字也可以使用简写；它会沿用本连接的最新图像：

```json
{"type":"input.text","text":"我改变主意了，就站着摆姿势吧。"}
```

### 原 chat 消息接口

保留 `input.append.input.messages`，适合已有 chat 客户端或自行管理历史的模块。它提供完整的本轮对话快照，替换该请求的服务端历史基底，不是额外追加的一条消息。成功后该快照与新回复成为会话历史。

```json
{
  "type": "input.append",
  "input": {
    "messages": [
      {"role":"user","content":"先前的用户请求"},
      {"role":"assistant","content":"先前的完整回复"},
      {
        "role":"user",
        "content":[
          {"type":"text","text":"现在这个位置可以吗？"},
          {"type":"image","data":"纯 Base64 图片"}
        ]
      }
    ]
  }
}
```

约束如下：

- `messages` 必须是非空数组，最后一条必须是 `user`；角色只接受 `system`、`user`、`assistant`。
- `system` 只能出现在首条。若 `session.init` 已有非空 system，快照中的 system 必须与之完全相同；不能用该字段绕过重建会话来切换提示词。初始化为空时可由快照提供 system。
- `system`、`assistant` 的 `content` 必须是字符串。`user` 可以是字符串，或由 `text`／`image`／`image_url` 组成的数组。
- `image_url` 形式为 `{"type":"image_url","image_url":{"url":"data:image/jpeg;base64,..."}}`。这里接受内嵌图片数据，不抓取远程 HTTP 图片地址。
- 快照请求使用其自己的图片内容，不自动附加先前的 `video_frames`。同一输入不能同时提供 `text` 和 `messages`。

## 流式输出、打断与关闭

网关逐片段转发模型文字，不等待标签闭合，也不把标签改写为 JSON 动作。客户端保留单行连续标签、跨块解析和闭合即执行。

```json
{"type":"response.output.delta","kind":"text","response_id":"r1","text":"<speak:你可以"}
{"type":"response.output.delta","kind":"text","response_id":"r1","text":"向左移动。><move:by,dx=-0.1>"}
{"type":"response.done","response_id":"r1","text":"完整模型文字","metadata":{"status":"ok"}}
```

`response.done.text` 是完整结果，用于记录，客户端不要再次把它送入解析器执行。`metadata` 包含请求／system 的 SHA-256、请求模型、思考设置、时间、完成状态；供应商返回时还会带实际模型、usage、finish_reason 等字段。字段可以缺省，客户端应容忍新增元数据。模型思考内容不会作为动作或 `speak` 片段输出。

新用户文字打断正在生成的回复时：

```json
{"type":"response.interrupted","response_id":"r1","reason":"new_input"}
```

客户端应丢弃 `r1` 的未闭合解析片段，并忽略其后到达的同 ID 内容。新回复的 ID 在新文字片段中出现；打断事件不承诺携带新 ID。已经闭合并执行的动作不会自动回滚。服务端取消旧请求、屏蔽旧片段并串行化后续调用。

关闭会话使用：

```json
{"type":"session.close","reason":"mode_changed"}
```

服务端返回 `session.closed` 并关闭连接。原前端在收到模型模式标签后执行这一流程，再使用对应 prompt 建立新会话；新连接不继承旧连接的对话和最新图像。

## 后台观察与历史

`video` 模式默认 `--visual-interval 8`。用户先发目标并获得成功回复后，网关在模型空闲、有新画面且距上次请求开始至少 8 秒时，用最新画面检查是否需要继续指导。`--visual-interval 0` 关闭该行为；间隔不是模型响应时间保证，也不表示每秒帧都会请求一次供应商。

自动观察单独保留最近一轮，不挤掉用户目标和修正。已经接受但被打断的用户消息会保留到后续请求；半截 assistant 回复不写入成功历史。供应商失败会显式报错、暂停自动观察，不自动重试；待处理用户输入仍保留，等待下一次明确请求。

默认 `--max-turns 20` 按人类 `user` 消息计数，包含已接受的待处理输入；自动观察不计入该上限。达到限制后，新的人类请求返回 `history_limit`，已有目标不会被静默截断。调用方应明确重建会话，并按需要在新 prompt 或新用户消息中提供目标摘要。供应商请求体还限制为 48 MiB，长历史中的图片也计入体积。

## 音频与配置范围

API 模式可以接收原协议的 `input.audio`，但只做格式检查与兼容提示，不转写。格式仍是 Base64 编码的 16 kHz、单声道、little-endian float32 PCM；非静音输入最多每 10 秒提示一次：

```json
{
  "type":"warning",
  "code":"audio_unsupported",
  "message":"API mode accepts text and images only; use text input. Audio was not transcribed."
}
```

这不是断连错误。API 前端默认不打开麦克风；TTS 沿用原前端的关闭状态。API 网关不发送 `kind:"audio"`，即使旧客户端设置 `use_tts:true` 或 `generate_audio:true` 也不会生成语音。

模型调用参数由后端启动参数决定：默认 `--model deepseek-flash --thinking low --timeout 90 --max-tokens 4096`。原 MiniCPM 的 `temperature`、`top_p`、`top_k`、`length_penalty`、`max_new_speak_tokens_per_chunk`、`max_slice_nums`、`force_listen` 等字段可以随旧消息进入网关，但没有被等价映射为 DeepSeek 的采样、切片或半双工控制参数。不能把字段可接收理解为模型行为完全相同。

错误使用原事件形式：

```json
{"type":"error","error":{"code":"provider_error","message":"错误摘要"},"response_id":"r1"}
```

常见 `code` 有 `invalid_request`、`provider_configuration`、`provider_error`、`history_limit`。`response_id` 仅在错误归属某次模型请求时提供。错误不会包含供应商 Key 或原始 HTTP 响应体；原前端会打印错误并清理连接，自行接入的模块可以据此决定何时重建或重试。
