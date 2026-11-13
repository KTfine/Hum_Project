# Hum_Project：在 AIAA3800 上增加 API 模式

本项目基于 [DDRP674/AIAA3800](https://github.com/DDRP674/AIAA3800)，保留拍照指导、摄像头画面、立绘动作和流式标签，在原 MiniCPM 部署方式之外增加 DeepSeek API 后端，方便协作者做提示词实验和开发模块。

沿用上游分支结构：**[main](https://github.com/KTfine/Hum_Project/tree/main) 是前端，[backend](https://github.com/KTfine/Hum_Project/tree/backend) 是后端**。分别检出到两个目录，通过 WebSocket 连接，不要将 backend 合并进 main。

## 快速开始：API 模式

需要 Python 3.12。在两个终端分别启动后端和前端。API Key 只在后端环境变量中配置，不写入前端或 Git。

后端（配置详见 [backend README](https://github.com/KTfine/Hum_Project/blob/backend/README.md)）：

```powershell
git clone --branch backend --single-branch https://github.com/KTfine/Hum_Project.git Hum_Project-backend
cd Hum_Project-backend
python -m venv .venv-api
.\.venv-api\Scripts\python.exe -m pip install -r requirements-api.txt
$env:DEEPSEEK_API_KEY = '你的 API Key'
.\.venv-api\Scripts\python.exe -m api_mode
```

前端：

```powershell
git clone --branch main --single-branch https://github.com/KTfine/Hum_Project.git Hum_Project
cd Hum_Project
python -m venv .venv-client
.\.venv-client\Scripts\python.exe -m pip install -r requirements-client.txt
.\.venv-client\Scripts\python.exe realtime_av_test.py --backend api
```

在前端终端输入目标，例如“我想拍一张展现活力的照片”，按 Enter 发送。默认启用摄像头，API 模式不打开麦克风；不接摄像头时加 `--no-camera`。文字输出仍可携带 `<speak:…>`、立绘动作和模式标签，完整标签到达即执行。语音播放保持上游关闭状态，没有新增 ASR 或 TTS。

默认先加载真人指导 prompt，不显示立绘。模型输出 `<mode:co-photo>` 后重建会话，加载合照 prompt 并显示角色；输出 `<mode:guidance>` 则恢复指导。ON/OFF 只是已加载模式的记录，不是动作权限。详见 [模式说明](docs/modes-and-prompts.md)。

## 使用原 MiniCPM 后端

在 backend 分支按其 [部署文档](https://github.com/KTfine/Hum_Project/blob/backend/docs/cloud-deployment.md) 启动服务；前端继续支持原入口：

```powershell
.\scripts\connect_tunnel.ps1 -SshHost YOUR_SSH_HOST -SshUser YOUR_SSH_USER
.\scripts\start_client.ps1
```

也可运行 `python realtime_av_test.py --backend minicpm --url https://localhost:18006 --insecure`。原音视频输入、预览和角色控制路径保留。API 模式通过相同 WebSocket 会话和文本事件接入，使用图文请求及定时观察，不等同于 MiniCPM 原生音视频双工。

## 文件布局

| main 路径 | 用途 |
|---|---|
| `realtime_av_test.py` | 摄像头、文字 / 原麦克风输入、预览、会话与模式切换 |
| `prompt.py` | 共用规则、真人指导和合照模板 |
| `command_protocol.py` | 连续标签、跨分块解析、动作校验 |
| `tachie/` | 上游立绘素材 |
| `scripts/` | 前端启动和 SSH 隧道 |
| `tests/` | 前端与实验工具回归检查 |
| `experiments/` | 实验记录、候选 prompt、脚本和本地原始材料 |
| `docs/` | 使用说明、接口参考、维护约定 |

后端保留上游 `client/`、`config/`、`scripts/`、`slurm/`、`patches/`、`tests/`、`models/`、`logs/` 布局，新增 `api_mode/` 与 API 依赖。开发模块见 [WebSocket 接口](CALLING_API.md)。

## 实验与验证

[实验入口](experiments/README.md) 汇总记录、脚本和评估计划。原始会话、媒体及本机脚本统一保留在忽略的 `experiments/runtime/`，不上传。独立图文请求工具也移入该目录，正常前端连接 backend 分支服务。

```powershell
.\.venv-client\Scripts\python.exe -m pip install -r experiments/requirements.txt
.\.venv-client\Scripts\python.exe -m unittest discover -s tests -v
```

CI 分别验证前后端代码与部署补丁；自动检查不代表真人姿势判断或实际摄像头实验已通过。

[文档导航](docs/README.md) · [接口](CALLING_API.md) · [维护约定](docs/maintenance/README.md) · [来源](docs/reference/upstream-sources.md) · [变更记录](CHANGELOG.md)
