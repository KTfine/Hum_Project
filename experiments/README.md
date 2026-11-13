# API 接入验证

主要实验材料统一维护在 [main/experiments](https://github.com/KTfine/Hum_Project/tree/main/experiments)。本分支只保存后端接入检查摘要，不复制媒体和提示词实验工具。

2026-11-13：基于前后端分离修改，20 项 API 离线回归（含 14 项真实本地 WebSocket / mock 模型）及 2 项原 MiniCPM 补丁方法检查通过，脚本语法通过。实际 DeepSeek 经网关的 4 次图文请求均完整返回，前端执行了模式标签、立绘移动和表情切换。

详细条件、原生标签、实际执行、延迟与记录 hash 修正见 [本轮报告](https://github.com/KTfine/Hum_Project/blob/main/experiments/records/2026-11-13-api-gateway.md)。没有启用设备或新增语音功能，没有重启 GPU 服务；后台观察、真人闭环与模型姿势判断不据此宣布已通过。

后续后端专用实验脚本与记录放本目录，原始材料放忽略的 `runtime/`。
