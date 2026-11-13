# Hum_Project 后端：MiniCPM + API 模式

基于 [DDRP674/AIAA3800 的 backend 分支](https://github.com/DDRP674/AIAA3800/tree/backend)，保留原 MiniCPM 部署和探针，在此基础上增加 DeepSeek API 网关。前端仍在 [main 分支](https://github.com/KTfine/Hum_Project/tree/main)，两者通过原 WebSocket 事件格式连接。

## API 启动

需要 Python 3.12，无需 GPU、模型权重或语音组件。

```powershell
python -m venv .venv-api
.\.venv-api\Scripts\python.exe -m pip install -r requirements-api.txt
$env:DEEPSEEK_API_KEY = '你的 API Key'
.\.venv-api\Scripts\python.exe -m api_mode
```

Linux / macOS 使用 `python3 -m venv .venv-api`，再运行 `.venv-api/bin/python -m pip install -r requirements-api.txt`、`export DEEPSEEK_API_KEY='你的 API Key'`、`.venv-api/bin/python -m api_mode`。

默认只监听 `127.0.0.1:8006`，使用 `deepseek-flash`、`thinking=low`。在前端 main 目录运行 `python realtime_av_test.py --backend api`，终端输入用户目标，摄像头继续提供画面。按 Ctrl+C 停止 API 服务。启动 API 不会启动 MiniCPM GPU 进程。

检查入口：

```powershell
curl.exe http://127.0.0.1:8006/health
curl.exe http://127.0.0.1:8006/status
.\.venv-api\Scripts\python.exe -m api_mode --help
```

health 证明服务存活，不证明 Key、额度或上游模型可用；真实请求失败会发送明确的 error。Key 仅由后端读取环境变量，不写入日志或传给前端。网关未提供用户认证；跨机器使用 SSH 隧道，保持默认回环监听。

## 与原接入的关系

保留 `session.queue_done → session.init → session.created → input.append → response.output.delta / response.done` 流程。API 将文字和最新图片转换为 DeepSeek 图文请求，再把文字流转换回原事件，动作与模式仍由前端解释。

API 支持文字、摄像头帧、多轮上下文、连续观察、流式标签、新输入打断，以及前端重建模式会话。没有新增语音识别、合成或播放；MiniCPM 原有音频路径仍保留。API 不是原生音视频双工实现，也不保证所有 MiniCPM 专有采样配置都生效。

前端发送唯一实际 system prompt，后端不维护额外的拍照角色模板。成功轮次进入有界历史；连续视觉观察只保留近期观察，避免每秒相机帧产生排队请求。新文字输入优先，取消旧输出并发出 `response.interrupted`。

具体字段、错误和模块开发见 [CALLING_API.md](CALLING_API.md)。

## 文件结构

| 路径 | 用途 |
|---|---|
| `api_mode/` | 新增 API 网关和 DeepSeek 流式传输 |
| `requirements-api.txt` | API 服务依赖 |
| `client/` | 原 health / chat 协议探针 |
| `config/`、`patches/` | 原 MiniCPM 固定版本、服务配置及补丁 |
| `scripts/`、`slurm/` | 原部署脚本与 API 启动入口 |
| `tests/` | API 网关和原部署检查 |
| `models/`、`logs/` | 本地运行目录，内容忽略 |
| `docs/` | MiniCPM 部署说明 |
| `experiments/` | 本分支 API 接入验证记录 |

提示词实验、媒体、实验工具统一放在 [main/experiments](https://github.com/KTfine/Hum_Project/tree/main/experiments)，不复制进后端产品模块。

## MiniCPM 与验证

[单 GPU 部署](docs/cloud-deployment.md) · [Slurm 适配](docs/slurm.md)。脚本仍固定 Demo / 权重版本；本次仅迁移目录，不启动或重新验收 GPU 服务。

API 离线回归：

```powershell
.\.venv-api\Scripts\python.exe -m unittest discover -s tests -p "test_api_*.py" -v
```

GitHub Actions 另外检查部署脚本语法和固定补丁。真人摄像头、姿势识别质量和模型延迟须分别记录，不能由程序测试代替。

上游导入提交、Demo 与模型固定版本见 [来源与版本](docs/upstream-sources.md)。
