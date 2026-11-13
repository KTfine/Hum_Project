# API 协作入口发布验证

日期：2026-11-13，Asia/Shanghai。基线提交 `94780dc60c103c8e3f35e07496418dc8a93950da`，开始时工作区干净。新增 hum_api、API 依赖、模块示例、P2 候选文件、API 测试及文档；修改 CI 和导航。此前仅本地忽略目录有 API 探针，本次首次将可运行入口纳入仓库。

## 工程范围

- 独立图文命令行和 Python 模块，不依赖 GPU、SSH、OpenCV 或音频设备。
- 支持多轮成功历史、字面自定义 system、图片字节/文件、外部观测、最终文字增量与完整指令回调。复用现有跨块、多标签解析器，模式不限制动作回调。
- 默认 guidance；内置模式请求在完整响应成功后重建本地历史。custom 不自动覆盖提示词。未实现摄像头、ASR、TTS、立绘渲染/执行和实际拍照。
- HTTPX 0.28.1，整轮 asyncio 超时覆盖连接和流读取，默认 90 秒；本次真实调用用 45 秒。拒绝重定向，不自动重试；中断流不提交历史，已回调的动作不能撤销。
- API 组装仅调整输入渠道描述，正式 prompt.py 未修改。P2 以完整实验候选单独提供，没有默认采用。

## 离线验证

`python -m unittest discover -s tests -v`：**88 项通过**，其中 15 项为新增 API 测试。覆盖 UTF-8 与标签跨网络块、同一行多个标签闭合即回调、指导模式动作回调、图像/观测/历史、模式成功后确认、失败不确认、custom 字面内容、历史上限、裸文字适配统计、思考文本隔离、认证错误与重定向、不完整流、连接/读取总超时、取消、并发拒绝、CLI 日志。

CI 增加只装 requirements-api.txt 的独立 API 作业；原完整回归同时安装 API 依赖。没有修改 MiniCPM 运行代码或部署配置。

首次依赖安装在受限网络下失败，获得执行环境的联网许可后安装成功；这不是模型调用失败。当前功能的网络验证只有下述两次，不混入 11 月 8 日模型准确率统计。

## 真实 API 冒烟测试

直接通过公开入口 `python -m hum_api` 运行，未使用旧忽略目录里的请求脚本。两次均为独立会话。

- 端点：官方 `https://api.deepseek.com/chat/completions`。
- 请求 model=`deepseek-flash`，thinking enabled、effort low、stream=true、include_usage=true、max_tokens=4096；不设置 temperature/top_p。
- 实际返回 model=`deepseek-flash`，fingerprint=`bc19ba97cbe016479903222bb1578db6`；没有可锁定的权重 revision。
- 两次实际 system SHA-256 均为 `ea4b45e3b92742dcbad58f3d31cc08063cfe6bbf606e778610040bde00758799`。
- 图像为此前生成的单人电话亭 PNG，SHA-256=`14d4b7e1ee1a2df7b4560bcc9cb852d88c0ef9c91f5862435a519ad4b6bd3e74`，base64、detail=original。

| 输入 | 实际结果 | 首段文字 / 整轮秒数 | token 总数 |
|---|---|---:|---:|
| 文字：请简单介绍如何帮我拍照 | 原生 speak，介绍姿势/表情/站位指导 | 1.485 / 1.766 | 513 |
| 电话亭图：请求活力姿势建议 | 原生 speak，建议扶门框/把手、侧身、调整重心 | 1.953 / 2.500 | 1473 |

两次均 HTTP 200、finish_reason=stop、收到 DONE，0 次重试，0 次裸文字适配。合计 prompt_tokens=1699、completion_tokens=287。控制台显示响应与本地 guidance 状态。未实际触发模式切换或执行动作，不能当作这些模型能力通过。两次成功也不足以给出一般延迟承诺。

原始日志留在本地忽略目录 `runtime_results/api-release-20261113/`；公开仓库只保留此摘要。授权头与 Key 不写日志，图片只记录哈希；CLI 默认记录对话文字和实际 system，合作者应保留在本地。

入口、提示词选择、模块分工和启动命令见 [API 使用说明](../api-experiments.md)。头部朝向和持续到位判断的模型限制仍以[单人实验](2026-11-08-single-person-guidance.md)为依据，本次工程发布没有声称解决这些问题。
