# 当前接口索引

2026-11-07 实时客户端基线，2026-11-13 增加 API 网关接入和独立图文实验工具。main 保存前端，backend 分支保存两种后端。各层接口分别维护，避免把模型文本标签误当成网关字段。

| 层 | 文档 | 源码依据 |
|---|---|---|
| 产品前后端连接 | [连接说明](../../CALLING_API.md) | realtime_av_test.py、backend 分支 api_mode/ |
| 独立图文实验、会话与模块回调 | [API 实验工具](../api-experiments.md) | experiments/scripts/hum_api/、experiments/scripts/api_module.py |
| 本地启动、参数和重放 | [客户端 CLI](client-cli.md) | realtime_av_test.py、scripts/*.ps1、experiments/scripts/runtime_effect_probe.py |
| 模型输出、模式标签和角色动作 | [标签协议](command-protocol.md) | command_protocol.py、客户端分发与角色控制器 |
| HTTP(S) / WebSocket | [Realtime API](realtime-api.md) | 客户端消息构造器、backend 分支 API 网关与固定 Demo 补丁 |

`guidance / co-photo` 是产品任务模式；`chat / audio / video` 是网关输入模式，两者不是同一组枚举。当前正常客户端始终连接 video 端点，在不同任务下更换 system prompt 和图像。

固定依赖见 [来源与版本](upstream-sources.md)。接口变更同步相关源码、测试和本目录，旧实验命令不是兼容承诺。
