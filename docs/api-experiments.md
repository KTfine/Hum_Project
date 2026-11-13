# 独立 API 图文实验

入口：`python -m experiments.scripts.hum_api`。需要 Python 3.12，直接连接 DeepSeek 官方 API；无需 GPU、SSH、OpenCV、麦克风或摄像头。默认 `deepseek-flash`、思考强度 `low`，支持文字、图片、多轮历史和流式标签。

这是 experiments/ 中供合作者做 prompt 对照与模块回调实验的工具，只输出文本和指令事件。日常使用原前端及立绘执行，应在 [backend 分支](https://github.com/KTfine/Hum_Project/tree/backend/api_mode) 启动 API 服务，再运行 `python realtime_av_test.py --backend api`；该模式使用终端文字和摄像头，不启用 ASR/TTS。完整启动见 [项目 README](../README.md)，服务接口见 [前后端连接](../CALLING_API.md)。

## 快速开始

PowerShell：

```powershell
git clone https://github.com/KTfine/Hum_Project.git
cd Hum_Project
python -m venv .venv-api
.\.venv-api\Scripts\python.exe -m pip install -r experiments/requirements.txt
$apiSecret = Read-Host '输入你自己的 DeepSeek API Key' -AsSecureString
$env:DEEPSEEK_API_KEY = [System.Net.NetworkCredential]::new('', $apiSecret).Password
.\.venv-api\Scripts\python.exe -m experiments.scripts.hum_api --text '你好，我想拍一张展现活力的照片。'
```

每人使用自己的 Key；从进程环境读取，不提供 Key 命令行参数，不自动读取 `.env`。结束后可执行 `Remove-Item Env:\DEEPSEEK_API_KEY`。

Linux/macOS Bash 在仓库根目录执行：

```bash
python3 -m venv .venv-api
.venv-api/bin/python -m pip install -r experiments/requirements.txt
read -rsp 'DeepSeek API Key: ' DEEPSEEK_API_KEY; echo
export DEEPSEEK_API_KEY
.venv-api/bin/python -m experiments.scripts.hum_api --text '你好，我想拍一张展现活力的照片。'
```

## 图片和连续实验

以下 `python` 指安装了 API 依赖的解释器，命令在仓库根目录运行：

```powershell
python -m experiments.scripts.hum_api --image 'D:\photos\scene.jpg' --text '看看场景，给一个有活力的姿势建议。'
python -m experiments.scripts.hum_api --interactive
```

交互示例：

```text
/image D:\photos\first.jpg
我想拍一张展现活力的照片。
/image D:\photos\next.jpg
现在到位了吗？
我改主意了，就想原地站着拍。
/quit
```

`/image 路径` 为下一轮附图，可多次添加、可包含空格；已发送图片保留在历史中。`/clear-images` 清除待发送图片；`/reset` 清空历史和待发送图片；`/mode guidance` 或 `/mode co-photo` 手动换模板并清空历史。

| 参数 | 默认与用途 |
|---|---|
| `--text` / `--image` | 首轮文字 / 图片；图片选项可重复，支持 PNG/JPEG/GIF/WebP |
| `--interactive` | 保持本进程历史 |
| `--prompt-file` | 完整 UTF-8 system 文本，按字面使用，不填占位符 |
| `--mode` | 默认 `guidance`，也可 `co-photo` |
| `--character-persona` | 修改内置模板的角色设定 |
| `--model` | 默认 `deepseek-flash`；更换后需确认图像能力 |
| `--thinking` | `off / low / high / max`，默认 `low` |
| `--timeout` | 整轮请求默认 90 秒，覆盖连接、上传和读取流，不自动重试 |
| `--max-tokens` | 默认 4096，截断算失败 |
| `--max-turns` | 默认 20 个成功轮次，达到后要求显式 reset，不自动删旧目标 |
| `--allow-plain-speech` | 显式启用裸文字转 speak，日志单独记录适配数量 |
| `--log-file` | 默认唯一文件 `experiments/runtime/api/*.jsonl` |

## Prompt 和模式

默认从 [prompt.py](../prompt.py) 的共用规则和当前模式模板组装。API 适配层仅调整输入渠道描述：把麦克风/实时摄像头描述改为文字和按需图片，附加说明改为图文对话。没有默认加入姿势实验的方向与核对规则；实际文本和 SHA-256 写入日志，新文本不继承旧模型成功率。

11 月 8 日 P2 完整 system 原样保存在 [p2-20261108.txt](../experiments/prompts/p2-20261108.txt)，按 Python 文本读取、统一换行为 LF 后的 system SHA-256 为 `39618c6ca2ee25720bfa52251ef2d795c6bc7630325b7d79097b8484fd0ab09a`。为复现当时输入，文件仍保留历史麦克风描述，这不会开启音频。P2 仍有头方向误判，见[实验记录](../experiments/records/2026-11-08-single-person-guidance.md)。

```powershell
python -m experiments.scripts.hum_api --prompt-file experiments/prompts/p2-20261108.txt --interactive
```

自定义文件不自动切换成内置模板；mode 标签仍解析并进入回调，但不会覆盖自定义 prompt。`/reset` 可清历史，修改文件后重启 CLI 读取新文本。合作者应各建独立候选文件，一轮改变一个明确问题，报告绑定 system 哈希。

本实验工具的内置模式在完整响应成功后采用最后一个合法 mode 请求、清空旧历史，下一轮发送对应 system。重复当前模式不清历史，失败流不确认切换。工具直连供应商 HTTP 接口，没有 `session.created`；这是本地对话重建。原前端连接 API 网关时仍按 WebSocket 会话流程确认切换，见 [模式说明](modes-and-prompts.md)。合法角色动作不会按模式屏蔽。

合照模板假设图片为真人主画面和右上角立绘小窗；**调用方负责合成图片**。CLI 不渲染或执行立绘动作，其角色状态是初始快照；接入 UI 后，由模块提供实际立绘目录和状态。

## 模块接口

可运行的示例：[experiments/scripts/api_module.py](../experiments/scripts/api_module.py)。

```powershell
python -m experiments.scripts.api_module --image 'D:\photos\scene.jpg'
```

示例还支持 `--observations-json`，读取你自己的观测模块输出；项目当前没有内置姿态/表情识别器。

```python
import asyncio
from experiments.scripts.hum_api import DeepSeekClient, Image, PhotoSession

async def main():
    async with DeepSeekClient() as client:
        session = PhotoSession(client)
        result = await session.ask(
            '我想拍一张展现活力的照片。',
            images=[Image.from_path('scene.jpg')],
            on_delta=lambda text: print(text, end='', flush=True),
            on_command=lambda command: print(command),
        )
        # 同一个 session 自动携带先前成功的文字和图片历史。
        await session.ask('现在到位了吗？', images=[Image.from_path('next.jpg')])

asyncio.run(main())
```

| 接口 | 接入方用途 |
|---|---|
| `Image(encoded_bytes)` / `Image.from_path(path)` | 相机编码的图片字节或文件 |
| `ask(..., observations=dict)` | 附加真实帧时间、镜像标记、姿态点等，作为 user 数据 |
| `on_delta(text)` | 最终文字增量，思考正文不进入回调 |
| `on_command(command)` | 现有解析器，标签闭合即回调，支持跨块和单行多个标签 |
| `result.text / commands / metadata` | 原文、指令、usage、耗时、system/request 哈希等 |
| `session.reset(mode=None)` | 清历史，可选择内置模板 |
| `PhotoSession(..., sprite_ids=..., character_state=...)` | UI 提供立绘目录和状态，每轮组装读取 |
| `PhotoSession(..., system_prompt=...)` | 程序传入完整实验提示词 |
| `DeepSeekClient.complete(messages, on_delta=...)` | 自行管理历史和目标；首条必须是文本 system |

回调同步运行，应快速把任务放进队列；不要在里面做阻塞 TTS、图像识别或 UI 等待。每个 PhotoSession 同时只处理一轮。取消、超时、不完整流不提交历史；但已经回调的动作不能撤销，因此不自动重试。mode 回调表示请求，提交结果看成功返回后的 `session.mode` 或 `metadata.mode_after`。

如扩展观测模块，建议相机提供原始帧，姿态/表情模块提供带时间的观测，会话模块管理目标和 API 请求，UI/立绘模块消费指令。人体观测在叠加立绘前完成；这些观测模块尚未内置。

## 日志与验证

CLI 记录 Git commit/dirty、实际 system 文本和哈希、输入文字、图片哈希、输出、指令、裸文字适配数、HTTP 状态、模型/fingerprint、usage、首段文字和完整指令时间、总耗时。HTTP 耗时从请求编码后开始，指令耗时从会话调用开始，两者起点略有不同。授权头、图片 base64 和思考正文不写日志。

历史在内存中，不自动跨进程恢复；图片须自行保留才能复现。日志含对话文字，默认放忽略目录；公开实验只提交必要摘要。库调用方自行保存 `ApiResult`。输入错误、API 错误与取消单独记录；缺少正常流结束或最终回答不能视为成功。

只安装 API 依赖即可运行离线测试：

```powershell
python -m unittest discover -s tests -p test_api_client.py -v
```

全项目回归与前端 CI 同时安装 `requirements-client.txt` 和 `experiments/requirements.txt`，检查实验入口及客户端回归。离线测试模拟 HTTP/SSE，不消耗 Key。独立实验工具的真实调用见[发布记录](../experiments/records/2026-11-13-api-client.md)。

官方依据：[图像输入](https://api-docs.deepseek.com/guides/vision/)、[思考配置和多轮消息](https://api-docs.deepseek.com/guides/thinking_mode/)。模型质量和实时音视频能力仍须分别验证。
