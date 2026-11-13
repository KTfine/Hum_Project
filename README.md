# Human-Centered AI 拍照助手

拍照指导与二次元伙伴互动原型，提供 **DeepSeek API 实验入口**和 **MiniCPM-o 4.5 实时客户端**，沿用 [AIAA3800](https://github.com/DDRP674/AIAA3800/tree/177d70afd6d8e6d95d619621c61117cef8cd59cd) 的客户端与立绘素材。

| 你想做什么 | 入口 |
|---|---|
| 用 API 测 prompt、图片、多轮对话，和合作者开发模块 | [API 快速开始与模块接口](docs/api-experiments.md)，无需 GPU / SSH |
| 使用摄像头、麦克风和立绘窗口连接自部署服务 | 下方 MiniCPM 实时客户端说明 |

API 入口：安装 `requirements-api.txt`，设置自己的 `DEEPSEEK_API_KEY`，在仓库根目录运行 `python -m hum_api --interactive`。支持自定义 prompt、图片、流式指令回调和本地实验记录；尚未接入摄像头、ASR、TTS 或立绘执行。

**维护起点：2026-11-07（Asia/Shanghai）**。此前实验、协议和待办已退出当前依据；当天起的记录绑定具体版本。旧内容仅保留在 Git 历史，来源与固定依赖继续维护。

MiniCPM 客户端启动后默认进行**真人拍照指导**，画面只显示摄像头。用户请求合照时，由模型输出模式标签，客户端重建推理会话并加载**合照互动**提示词。合照模式显示白底立绘窗口，模型看到摄像头及右上角立绘小窗。

目前处于提示词实验阶段，尚未形成稳定的真人拍照闭环。合照模式也不代表已经把角色合成进照片或完成拍摄；说话内容暂时打印到控制台，未启用语音播报。

## MiniCPM 实时客户端快速开始

需要 Python 3.12、已运行的 MiniCPM-o 服务及 SSH 访问配置。在仓库根目录安装客户端依赖：

```powershell
python -m venv .venv-client
.\.venv-client\Scripts\python.exe -m pip install -r requirements-client.txt
```

在单独的 PowerShell 窗口建立隧道，填入自己的连接信息并保持窗口打开：

```powershell
.\scripts\connect_tunnel.ps1 -SshHost YOUR_SSH_HOST -SshPort 22 -SshUser YOUR_SSH_USER
```

回到仓库窗口，检查连接并启动客户端：

```powershell
curl.exe -k https://localhost:18006/health
curl.exe -k https://localhost:18006/status
.\scripts\start_client.ps1
```

客户端会使用摄像头和麦克风。可以先说“帮我看看站姿”，再试“切换到合照模式”或“恢复指导模式”。这些话由模型理解，客户端没有关键词开关。窗口按 **Q** 或终端按 **Ctrl+C** 退出，一次运行一个客户端。部署新服务见 [单 GPU 部署](docs/cloud-deployment.md)。

## 当前基线证据

2026-11-07 保持提示词不变，完成 **32 种表达、98 次纯文本调用**，没有启用摄像头或麦克风：

- 需要切换的请求中，**33/65** 生成正确模式标签；不应切换的对照 **33/33** 没有误切换。
- “切换到合照模式”3/3、“恢复指导模式”4/4；“和我合照”2/4、“退出合照”0/3。
- 主要问题是模型口头答应切换，却没有输出可执行标签。少量重复不能证明稳定性，纯文本结果也不等于实时音视频通过。

逐句结果、条件和限制见 [实验记录](docs/validation/2026-11-07-text-mode-switch.md)，对应 prompt / 画面实现 `684d582`。73 项程序回归覆盖模拟会话、画面选择和流式执行；与真实模型效果分别记录。新实验及本轮维护核对统一收录在 [实验索引](docs/validation/README.md)。

## 项目结构

| 路径 | 内容 |
|---|---|
| `hum_api/`、`requirements-api.txt` | 独立图文 API、命令行、多轮历史与流式回调 |
| `examples/api_module.py`、`prompts/experiments/` | 模块接入示例和可选择的实验提示词 |
| `realtime_av_test.py` | 摄像头、麦克风、预览与会话管理 |
| `prompt.py` | 共用规则 + 指导 / 合照两种提示词 |
| `command_protocol.py` | 标签解析、校验与角色动作调度 |
| `tachie/` | 上游立绘素材 |
| `scripts/`、`backend/` | 启动、部署、固定版本和后端补丁 |
| `tests/`、`tools/` | 回归检查与显式时间线重放工具 |
| `docs/` | 当前说明、当天起的实验、维护协议和接口参考 |

[文档导航](docs/README.md) · [模式与提示词](docs/modes-and-prompts.md) · [接口索引](docs/reference/README.md) · [维护协议](docs/maintenance/README.md) · [来源与版本](docs/reference/upstream-sources.md) · [变更记录](CHANGELOG.md)

全项目本地回归命令（API 独立测试见其使用文档）：

```powershell
.\.venv-client\Scripts\python.exe -m pip install -r requirements-api.txt
.\.venv-client\Scripts\python.exe -m unittest discover -s tests -v
```

GitHub Actions 另检查部署脚本语法及固定上游补丁；不运行 GPU 或真人摄像头实验。原始会话日志和个人媒体留在本地忽略目录，仓库只保存公开结果摘要。
