# 前后端连接

本分支是前端，后端代码与完整服务接口见 [backend/CALLING_API.md](https://github.com/KTfine/Hum_Project/blob/backend/CALLING_API.md)。布局与 [AIAA3800](https://github.com/DDRP674/AIAA3800) 的 main / backend 分支对应。

| 方式 | 前端入口 | 输入与输出 |
|---|---|---|
| 原 MiniCPM | `python realtime_av_test.py --url https://localhost:18006 --insecure` | 原麦克风与摄像头输入；流式文字和立绘指令；不播放语音 |
| API | `python realtime_av_test.py --backend api` | 终端文字与摄像头输入；流式文字和同一套立绘指令；不启用语音 |

两者使用 `/v1/realtime?mode=video`，等待 `session.queue_done` 后发送 `session.init`，收到 `session.created` 后发送 `input.append`。模式切换由前端按模型标签重建会话与提示词，后端不另外复制任务 prompt。

API 入口默认 `http://127.0.0.1:8006`，可用 `--url` 覆盖。后端持有 API Key；前端不直接访问 DeepSeek，也不需要 API 依赖。新模块可以对接服务的流式文本事件，或复用前端的 `StreamingCommandParser`。

[Realtime 字段](docs/reference/realtime-api.md) · [动作标签](docs/reference/command-protocol.md) · [提示词组装](docs/modes-and-prompts.md) · [独立图文实验](docs/api-experiments.md)
