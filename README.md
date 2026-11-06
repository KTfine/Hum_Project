# Human-Centered AI 拍照助手

基于 MiniCPM-o 4.5 的实时音视频与二维角色控制原型。客户端发送麦克风音频和摄像头画面，模型返回流式标签，由本地解析器控制立绘。

默认指导真人拍照，角色留在右上角小窗。现已接入客户端合照状态：模型识别邀请后发出 `<photo:enter>`，客户端确认相机可用后让角色透明叠加进取景画面，首次开启时询问想拍什么样的照片，并只开放移动。缩放、旋转、换立绘与角色动画暂未开放；此前 14/14 次用例验证的是旧提示词下的角色控制能力。

实时双工模型仍可能漏掉动作和 speak 标签。客户端将标签外普通文字增量适配为说话指令，合法标签继续按原协议解析和分发，普通文字不会被猜测为激活或移动。此前 46161bb 的混合提示测试执行了左移和保持，推荐仍漏动作；纯动作短提示执行了三条合成语音指令，真人语音测试也实际执行三次左移。本版拆分提示词并更新状态传递，仅完成本地协议回归，尚未进行 GPU 复测；完整聊天合照闭环仍未通过。历史结果见 [动作与保持实验](docs/validation/2026-11-06-move-or-hold.md)、[合照状态测试](docs/validation/2026-11-06-co-photo.md)。此前诊断输出的中文乱码来自本地终端编码显示，原始事件文本正常。

提示词沿用原始的条目与指令清单结构，删除示例。此前真人站位实验出现将目标位置当作已经到达的位置，连续指导尚未通过；自拍的左右关系需要先确认，不能仅凭“自拍”推断。见 [真人指导实验及失败记录](docs/validation/2026-11-06-photo-guidance.md)。

## 输出分发

- `<speak:...><move:...>` 等单行多标签继续支持，一条完整闭合后即可解析；动作还需通过当前客户端动作许可检查。
- 没有标签的自然语言进入同一个说话通道，按文本分块处理，不等待整轮回复。`parser.plain_text_adapted` 日志明确标记适配来源，原始模型输出不被改写。
- 未知、非法、不完整标签不作为普通说话执行，其参数不会被猜测成动作。严格解析仍可使用 `StreamingCommandParser()`，仅实时接收入口开启纯文字适配。
- 正常入口的合照状态默认关闭，角色动作全部阻止；收到有效 `<photo:enter>` 并确认相机帧可用后才开放 move。入画请求本身不改变位置、缩放或旋转，重复请求不重置状态；其余动作继续阻止。
- 预览与模型输入使用同一合成函数，左上角 `CO-PHOTO: OFF/ON` 表示客户端状态。首次开启后客户端将构图目标问题送入同一个说话通道；当前仅显示文字，语音播报仍关闭。
- 状态角标只保留在用户预览，模型输入不画此标识。正常入口启动发送 OFF 提示词，客户端激活后关闭旧推理会话，再建立携带 ON 提示词的新会话；就绪后询问合照目标一次。角色位置和设备保持，旧模型音视频上下文重置。
- 用户让助手推荐时，提示词要求提供简单方案并分步指导；用户直接给要求时按要求进行。生成方案、发出可执行标签和确认实际站位分别验收，目前尚未完成完整闭环；退出触发和拍照保存仍待实现。
- 合照开启后的有效模型回复要求明确 move 或保持；保持使用 `<move:by,dx=0,dy=0,ms=0>`，会停在动画当前的位置，不跳到旧目标。保持计为有效指令，单独统计，不等于实际移动到位；静默监听不额外生成动作。

## 提示词与客户端状态

编辑 `prompt.py` 中的对应部分，保存后重新启动客户端：

| 常量 | 使用场景 |
|---|---|
| `_COMMON_PROMPT` | 两种正常模式共用的身份、拍照与方向规则 |
| `STREAMING_COMMAND_PROMPT` | 普通拍照，客户端确认 OFF；允许 speak、blank、photo:enter |
| `CO_PHOTO_COMMAND_PROMPT` | 入画后，客户端确认 ON；允许 move、保持、speak |
| `CO_PHOTO_ACTION_DIAGNOSTIC_PROMPT` | 显式纯动作诊断，保留此前短提示 |

左上角是状态显示，无点击切换功能。权限仍由客户端变量决定；模型的模式由新会话提示词明确给出，不依赖读取角标。每种模式只列开放的指令，旧九种格式仍由底层解析器保留。

激活时重建会话会清除旧的模型音视频记忆，因此客户端等待新会话就绪后再问本轮合照目标；尚无结构化保存的旧目标与左右校准需要重新确认。显式 `--prompt` 作为完整自定义覆盖保留，不自动替换或刷新其内容。此轮通过 80 项本地测试，旧 GPU SSH 端口不可用，新的提示词与连接切换尚未进行 GPU 复测，见 [状态同步与精简记录](docs/validation/2026-11-06-state-prompts.md)。

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

## 仅动作测试

在仓库根目录、已有客户端环境和 SSH 隧道可用时，可启动真人语音测试：

```powershell
.\.venv-client\Scripts\python.exe realtime_av_test.py --url https://localhost:18006 --insecure --action-only-test
```

此标志明确从已合照状态开始，使用独立的移动指令短提示词；只测试移动、保持和位置选择，不处理聊天或摄影问答，不验证邀请激活与首次询问。按 Q 退出。不带该标志的正常入口继续使用双职责主提示词。

固定合成语音复测使用：

```powershell
.\scripts\generate_action_probe_speech.ps1 -Profile co-photo -Voice 'Microsoft Kangkang'
.\.venv-client\Scripts\python.exe tools/runtime_effect_probe.py --co-photo --start-co-photo --action-only --seconds 58 --instructions-file tools/fixtures/co-photo-action-required-schedule.json --output-subdir action-only
```

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
