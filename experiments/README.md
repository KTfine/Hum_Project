# 实验工作区

这里集中管理 prompt 实验、验证记录和复用工具。日常使用前端连接 API 后端，见 [项目 README](../README.md) 和 [前后端接口](../CALLING_API.md)；独立图文实验工具的用法见 [API 实验说明](../docs/api-experiments.md)。生产 API 服务位于独立的 [backend 分支 api_mode/](https://github.com/KTfine/Hum_Project/tree/backend/api_mode)。

| 目录 | 内容 |
|---|---|
| [records/](records/README.md) | 按日期记录的问题、条件、结果与限制 |
| [prompts/](prompts/) | 有版本的候选提示词，默认客户端不会自动加载 |
| [scripts/](scripts/) | 可维护的实验入口，包括独立 API 图文会话、模块示例和录音重放 |
| [templates/](templates/report.md) | 新实验的记录模板 |
| [plans/](plans/human-evaluation.md) | 尚待执行的真人评估设计 |
| runtime/ | 本机原始日志、媒体、请求及历史脚本；被 Git 忽略 |

## 从哪里开始

所有命令在仓库根目录执行。独立 API 实验需要 Python 3.12，并从 `DEEPSEEK_API_KEY` 进程环境变量读取自己的 Key；安全输入方法与完整参数见 [实验工具说明](../docs/api-experiments.md)。

```powershell
python -m pip install -r experiments/requirements.txt
python -m experiments.scripts.hum_api --interactive
python -m experiments.scripts.hum_api --prompt-file experiments/prompts/p2-20261108.txt --interactive
python -m experiments.scripts.api_module --image 'D:\photos\scene.jpg'
```

录音重放工具另需 `requirements-client.txt` 中的原客户端依赖；运行 `python experiments/scripts/runtime_effect_probe.py --help` 查看参数。它连接 MiniCPM 音视频后端；API 模式不提供语音识别或语音合成。

已启动 backend 分支的 API 服务后，可用下面的探针检查网关与原前端解析执行链路。它需要 `requirements-client.txt`，不打开摄像头、麦克风或预览；只有后端需要 Key。重复 `--text` 可顺序发送多轮，`--image` 可选择本机图片。

```powershell
python experiments/scripts/api_gateway_probe.py --text '你好，请给一个站姿建议。' --output experiments/runtime/gateway-trial/result.json
```

探针默认连接 `http://127.0.0.1:8006`，可用 `--url` 修改；结果写入指定本地文件，同名文件会覆盖。它检验文字/指定图片及协议执行，不代表真人连续摄像头实验。

新一轮先复制 [记录模板](templates/report.md)，记录实际发送的 system 文本及哈希。候选提示词和历史成功率只对应记录中的条件，不能视为当前版本已通过。

## 2026-11-13 路径整理

| 原位置 | 现在的位置 |
|---|---|
| docs/validation/ | experiments/records/ |
| prompts/experiments/ | experiments/prompts/ |
| hum_api/ | experiments/scripts/hum_api/ |
| examples/api_module.py | experiments/scripts/api_module.py |
| tools/runtime_effect_probe.py | experiments/scripts/runtime_effect_probe.py |
| requirements-api.txt | experiments/requirements.txt |
| docs/maintenance/experiment-template.md | experiments/templates/report.md |
| docs/maintenance/human-evaluation.md | experiments/plans/human-evaluation.md |
| runtime_results/ | experiments/runtime/ |

历史报告保留当时运行的命令、路径、版本和结论，Markdown 导航已更新。报告中提到的 `runtime_results/` 现在对应 `experiments/runtime/`，不是丢失的材料。

原始材料迁移前后逐文件核对相对路径、字节数和 SHA-256：1230 个文件、1,283,115,158 字节全部一致。本机核对清单位于被忽略的 `experiments/runtime-migration.local.json`。这只证明材料完整迁移，不新增模型质量结论。

`runtime/` 中的历史脚本保留原字节；其中的绝对机器路径、旧目录名和 `parents[n]` 根目录定位均可能不再适用，不能直接承诺复跑。需要复跑时复制为新实验脚本，明确修正路径并记录差异，不覆盖原始证据。`scripts/` 中迁移的三个公开入口已调整为新目录结构，新增网关探针也使用该结构。
