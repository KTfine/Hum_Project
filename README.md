# Human-Centered AI 拍照助手

基于 MiniCPM-o 4.5 的实时音视频与二维立绘控制原型。当前按人工提示词实验的新基线运行：共用规则 + 真人拍照指导 / 合照互动两种模式规则，默认加载指导提示词，由 LLM 决定说话、动作和模式切换。

## 前端与动作

指导模式下，用户预览与模型输入都只显示真人摄像头，不包含立绘。合照模式保留 [AIAA3800 固定版本 177d70a](https://github.com/DDRP674/AIAA3800/tree/177d70afd6d8e6d95d619621c61117cef8cd59cd) 的白底立绘预览，模型看到摄像头画面及右上角立绘小窗。按 Q 退出，没有 ON/OFF 角标、相机叠加入画或手动模式按键。

画面在对应提示词的新会话成功创建后切换；切换请求或失败不提前改变画面。指导模式相机不可用时显示/发送空白帧，不用立绘冒充真人输入。角色几何状态始终保留，隐藏角色不等于禁止执行动作。

两种模式均执行合法的 move、scale、rotate、tachie；客户端不设模式动作白名单，只保留格式、参数范围和立绘 ID 检查。ON/OFF 不代表动作许可或角色已入画。

- 单行连续多个标签保持支持，一条完整闭合后即可解析分发，允许标签跨网络分块。
- 标签外普通文字保留增量说话适配；它不会被猜测为模式切换或角色动作。判断模型是否原生生成标签时，检查原始输出及 parser.plain_text_adapted。
- 未知、非法、不完整标签不猜测执行。TTS 关闭，说话内容当前打印到控制台。
- 已移除每轮必须 move、强制零位移保持、固定动作顺序、speak 前缀强化、纯动作诊断提示词及客户端固定目标询问。是否说话、动作或询问由模型依据提示词决定。

## 提示词与模式记录

| 组成 | 用途 |
|---|---|
| _COMMON_PROMPT | 共用身份、语言风格、说话/空指令/模式切换及流式输出协议 |
| PHOTO_GUIDANCE_PROMPT | 共用规则 + 真人拍照指导职责，默认加载；不含立绘目录、几何状态或动作协议 |
| CO_PHOTO_COMMAND_PROMPT | 共用规则 + 合照互动职责、立绘说明/目录/状态、完整动作格式与参数规则 |

用户邀请“和我合照”时，LLM 应输出 mode:co-photo 标签；用户要求“恢复指导模式”时，应输出 mode:guidance 标签。客户端只处理模型标签，不对用户语音做关键词匹配。重复请求当前模式不重建会话。

收到切换标签后，客户端关闭旧推理会话，再发送对应 system_prompt 建立新会话；保留相机、麦克风与角色几何状态，不重载 GPU 权重。旧音视频上下文会重置，历史构图目标不保证继承；旧会话尚未完成的生成随切换结束。

ON/OFF 只是最后成功加载提示词的记录：

- OFF：guidance，真人拍照指导。
- ON：co-photo，合照互动。
- 收到请求记 session.mode_requested；新会话创建成功才记 session.mode_ready 和 co_photo_active。失败不能提前记为成功。
- 控制台显示 [mode] loaded: OFF (guidance) 或 [mode] loaded: ON (co-photo)，日志写入本地 JSONL。
- 显式 --prompt 或重放工具 --prompt-file 仍作为完整覆盖，模式记为 custom，不自动替换，不宣称加载了任一种内置模板；保留原立绘预览和带立绘小窗的模型输入。

编辑 prompt.py 后重启本地客户端即可，无须更新云端代码。旧 --action-only-test、重放 --co-photo / --start-co-photo / --action-only 已移除；旧 photo:enter 标签只保留解析兼容，不再切换或入画。

## 当前验证状态

73 项本地回归通过，覆盖双向模式切换后实际发送的图像、指导模式无立绘、缺相机空白回退、加载失败、角色状态保留、全部动作不受模式限制与流式标签分发。测试使用模拟连接与合成图像，不代表真实模型能稳定理解语音和输出标签。

本次拆分未进行新的 GPU / 真人语音 / 长期稳定性实验。详见 [指导模式无角色记录](docs/validation/2026-11-07-guidance-without-character.md)；此前的 [恢复记录](docs/validation/2026-11-07-prompt-modes-reset.md) 保留为历史，不能直接算作本版效果通过。后续由用户安排输入与观察，每轮只修改一项提示词要求。

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

## 重放工具

已有合成输入可使用 tools/runtime_effect_probe.py 重放，默认同样从指导模式开始，模型的 mode 标签触发双向会话重建。该工具不是独立动作诊断模式；记录实际标签、角色变化和成功加载的模式。

人工提示词实验使用上面的正常客户端即可，不需要额外模式启动标志。后续实验按照用户指定的单项问题逐轮修改并记录。

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
