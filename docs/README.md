# 文档导航

第一次使用从 [项目 README](../README.md) 开始。当前程序机制与历史实验分开阅读：旧实验里出现的权限开关、强制动作或 photo:enter 流程，不代表现在仍在使用。

| 你想了解 | 文档 |
|---|---|
| 程序如何组装 prompt、切换模式和执行标签 | [模式与提示词](modes-and-prompts.md) |
| 最新实验、哪些结果通过或尚未验证 | [验证索引](validation/README.md) |
| 在服务器上部署 MiniCPM-o | [单 GPU 部署](cloud-deployment.md) |
| 调用文字 / 音频 / 视频 WebSocket 接口 | [Realtime API 参考](reference/realtime-api.md) |
| 上游代码、模型和素材来自哪里 | [来源与固定版本](reference/upstream-sources.md) |
| 修改项目时需要保留哪些约定 | [维护约定及整理说明](maintenance/README.md) |
| 真人方向与连续指导如何验收 | [真人指导评估](maintenance/human-evaluation.md) |
| 早期设计为何与现在不同 | [历史档案](archive/README.md) |
| 每次更新改了什么 | [变更记录](../CHANGELOG.md) |

`backend/README.md` 保留原 Slurm 部署方式；一般单 GPU 部署使用上表入口。运行代码仍位于原路径，本次整理不改变启动方式。
