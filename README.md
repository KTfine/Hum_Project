# Human-Centered AI 拍照助手

基于 MiniCPM-o 4.5 的实时音视频与二维角色控制原型。客户端发送麦克风音频和摄像头画面，模型返回流式标签，由本地解析器控制立绘。

当前提示词默认指导真人拍照，合照固定为未开启，客户端合照开关和人物入画仍待接入。原动作执行器支持平移、缩放、旋转及换表情；此前 14/14 次用例验证的是旧提示词下的角色控制能力。

实时双工模型仍可能漏掉 speak 标签。客户端现已将标签外的普通文字增量适配为说话指令，原有合法标签继续按原协议解析和分发；这不代表模型原始标签格式已经稳定。普通文字不会被猜测为移动等动作，合照未开启时正常客户端会阻止角色动作。验证过程见 [验证记录](docs/validation/2026-11-06.md)。此前诊断输出的中文乱码已复核为本地终端编码显示问题，原始事件文本正常。

## 输出分发

- `<speak:...><move:...>` 等单行多标签继续支持，一条完整闭合后即可解析；动作还需通过当前客户端动作许可检查。
- 没有标签的自然语言进入同一个说话通道，按文本分块处理，不等待整轮回复。`parser.plain_text_adapted` 日志明确标记适配来源，原始模型输出不被改写。
- 未知、非法、不完整标签不作为普通说话执行，其参数不会被猜测成动作。严格解析仍可使用 `StreamingCommandParser()`，仅实时接收入口开启纯文字适配。
- 当前正常启动入口的角色动作许可为空，邀请合照后的客户端状态切换仍待接入；语音播报也仍关闭。此修复接通文字指导分发，不宣称摄影判断或连续指导闭环已全部完成。

## 目录

- `realtime_av_test.py`、`command_protocol.py`、`prompt.py`：客户端、执行器与控制提示词。
- `tachie/sanae/`：22 张上游立绘。
- `backend/`：固定版本、模型清单工具、上游补丁和原 Slurm 部署工具。
- `scripts/cloud_*.sh`：无需 Slurm 的单 GPU 部署入口。
- `scripts/start_client.ps1`、`scripts/connect_tunnel.ps1`：Windows 客户端及 SSH 隧道。
- `tools/`：可重复语音动作测试和状态验证工具。
- `docs/validation/`：已完成测试的公开摘要，不包含真人画面、麦克风录音或完整会话日志。

## Windows 客户端

使用 Python 3.12，在仓库根目录执行：

```powershell
python -m venv .venv-client
.\.venv-client\Scripts\python.exe -m pip install -r requirements-client.txt
```

在另一个 PowerShell 窗口建立隧道，填入自己平台显示的 SSH 主机与端口：

```powershell
.\scripts\connect_tunnel.ps1 -SshHost YOUR_SSH_HOST -SshPort YOUR_SSH_PORT
```

保持隧道窗口打开，然后启动：

```powershell
.\scripts\start_client.ps1
```

例如说“往右挪一点，换成惊讶的表情”或“把你自己缩小到现在的一半”。角色窗口按 **Q**，或终端按 **Ctrl+C** 退出。一次只运行一个客户端。

脚本连接本机 HTTPS 端口 18006，通过 SSH 到云端 8006；`--insecure` 用于隧道内的 localhost 自签名证书。服务器端口保持监听 `127.0.0.1`。

## 云端部署

已验证环境为 RTX 5090 32GB、Ubuntu 22.04、Python 3.12、预装 PyTorch 2.8.0+cu128。模型为 BF16 未量化，观测显存约 23–25GiB。详细步骤和路径参数见 [单 GPU 部署](docs/cloud-deployment.md)。

```bash
git clone https://github.com/KTfine/Hum_Project.git
cd Hum_Project
export HUMCEN_STORAGE_ROOT=/root/autodl-tmp/humcen
# 如需镜像，可在当前 shell 设置 HF_ENDPOINT、PIP_INDEX_URL。
bash scripts/cloud_install.sh
bash scripts/cloud_download.sh
nohup bash scripts/cloud_serve.sh > logs/service-launch.log 2>&1 < /dev/null &
echo $! > logs/service.pid
```

先完成安装、下载，再启动服务。重新启动前先结束自己已有的服务；启动器检测到端口占用会退出。退出客户端不会停止云端实例，用完后在平台关机。

## 验证与维护

```powershell
.\.venv-client\Scripts\python.exe -m unittest discover -s tests -v
```

GitHub Actions 运行客户端测试、补丁应用及两项后端回归检查，不运行 GPU/摄像头测试。手动动作复测方法与结果见 [验证报告](docs/validation/2026-11-06.md)。

每次更新必须记录改动、原因、检查结果与限制，见 [CHANGELOG](CHANGELOG.md) 和 [维护约定](AGENTS.md)。原始来源、固定提交及素材说明见 [UPSTREAM_SOURCES](UPSTREAM_SOURCES.md)。原来的 Slurm 工具保留在 `backend/`，其整套调度流程尚未在本实例重新验证。
