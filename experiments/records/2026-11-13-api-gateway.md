# 2026-11-13：API 接入原前端与分支整理

日期：Asia/Shanghai。工程基线 `c6721c7b5514124c5b34a345efbcd5fbc1803105`，本记录随前端 API 接入与分支整理提交保存；后端版本单独定位在 backend 分支。不是新一轮姿势质量实验。

发布的后端版本：[8d0c452](https://github.com/KTfine/Hum_Project/commit/8d0c4523c36fb090e1a27a66fb2c51144ddbd3d3)。真实重放在提交前工作区执行；随后补充的取消、回压和关闭清理修复通过本地 WebSocket 回归，未重复消耗真实 API 请求。

## 本轮范围

按用户指定的 [DDRP674/AIAA3800](https://github.com/DDRP674/AIAA3800) 组织：main 放前端，backend 独立分支保留原后端部署目录并增加 `api_mode/`。不新增语音识别、合成或播放；原 MiniCPM 麦克风输入与关闭 TTS 的行为保留。

API 前端通过终端文字和摄像头帧接入同一 WebSocket 会话、标签解析器、角色执行器与模式重建流程。后端默认 Flash + low，持续画面按间隔观察，用户新输入可打断旧回复。模式不作为动作权限。

正式 `prompt.py`、`command_protocol.py` 未改，prompt.py SHA-256 为 `fc730a01b4e2c273493beab7aa61e24affaeed22e640e36f266071433352c818`。只在 API 组装时适配真实输入描述：

```diff
- 你持续接收用户麦克风音频和摄像头画面。
+ 你持续接收用户文字输入和摄像头画面。
- 附加要求：用户通过麦克风与你说话；保持回复简短。
+ 附加要求：用户通过文字输入与你交流；你会持续收到摄像头画面；保持回复简短。
```

自定义 `--prompt` 原文不做替换。没有新增强制动作、左右换算或姿势判据。

## 程序检查

| 检查 | 结果与范围 |
|---|---|
| main 全量回归 | 95/95，通过；包括原 88 项和 7 项 API 前端检查 |
| backend API 回归 | 20/20，通过；14 项真实本地 WebSocket + mock 供应商、6 项 HTTP/SSE 传输测试 |
| 原 MiniCPM 补丁回归 | 2/2，通过；固定源码方法的配置转发，无 GPU 推理 |
| 启动与部署脚本 | Bash 语法、PowerShell 语法、CLI help、diff 检查通过 |
| 原始实验材料迁移 | 1230 个文件、1,283,115,158 字节，迁移前后相对路径、大小和 SHA-256 一致 |

检查覆盖多标签和跨块执行、消息中途帧输入、取消与迟到片段、用户补充目标、模式重连、最新帧观察节流、失败历史、供应商 HTTP 错误、关闭清理和输出回压。修复了帧监听事件清空未闭合标签、取消后漏掉原目标两处问题。未用 mock 验证结果证明模型识图质量。

## 真实 API 经网关的图文重放

通过本地 aiohttp 服务连接官方 DeepSeek，再使用前端的会话构造、接收解析和 CanvasSource / SpriteController 执行。没有开启摄像头、麦克风、预览窗口或扬声器。输入为此前生成的草地人物图 `guidance-scene-20261107/images/01-initial.png`，SHA-256：`31559dfb59fe2f2634453894cba6e4b3634d8a31e63d128edc0cd32d75ad8242`。

请求配置：`deepseek-flash`、`thinking=low`、`max_tokens=4096`、整轮超时 90 秒。该次重放设 `visual_interval=0`，主动发送四次输入，不把后台持续观察算作真实模型已验证。返回模型名 `deepseek-flash`、fingerprint `bc19ba97cbe016479903222bb1578db6`，四次 HTTP 均为 200、完整结束。

| 轮次 | 输入目的 | 原生输出与实际结果 | 总时长 / 首文字 |
|---|---|---|---|
| 1 | 结合草地人物图给活力照片建议 | 原生 speak，建议侧身迈步、抬起或张开手臂；角色保持隐藏 | 2.984 / 2.734 秒 |
| 2 | 邀请合照并切换 | speak + `mode:co-photo`；下一轮建立合照会话 | 1.672 / 1.375 秒 |
| 3 | 请立绘向画面左边移动并微笑 | `move:to,x=0.34,y=0.95,ms=400` + `tachie:smile` + speak；真实执行器 x 从 0.5 到 0.34，normal 到 smile | 1.688 / 1.406 秒 |
| 4 | 结束合照，恢复真人指导 | `mode:guidance` + speak；前端记录 guidance 请求 | 2.109 / 1.937 秒 |

四轮均由原生标签组成，没有依赖裸文字适配。第四轮完成后探针退出，未在这次真实调用中另行建立最终 guidance 会话；自动重连流程另由程序测试覆盖。模型第二轮把画面说成夕阳、并说“往左边让一点”，本轮没有验证光照判断或人的左右是否正确。

后端按实际发送内容计算的 system SHA-256：

- 指导（第 1–2 轮）：`fe0fe103a9bc0fa493e80e7af050b34cb55252b450597041d7b6360784a686e1`
- 合照（第 3–4 轮）：`856f8082ba3e2fd1ab6a8a06b066f705051037257159f44ad69a4a8925c3246c`

记录核对发现探针原先每轮按最新角色状态重算 system hash，即使会话没有重建，导致第 4 轮顶层 hash 与实际发送不符。后端 `response.done.metadata.system_sha256` 始终正确；保留原 `result.json`，另存 `result-audited.json` 标记该差异。公开探针已改为只在重建时生成 system，并记录实际会话 prompt，不为修复统计而重复请求模型。

可复用入口：[api_gateway_probe.py](../scripts/api_gateway_probe.py)。原始结果与本机启动脚本保存在忽略的 `experiments/runtime/api-gateway-integration-20261113/`。Key 只在测试进程环境中临时使用，未写入文件。临时 API 服务已关闭，远端 MiniCPM 服务未重启。

## 文件整理与限制

实验记录、候选 prompt、脚本、计划、模板和原始材料统一在 `experiments/`；旧路径对照与迁移清单说明见 [实验入口](../README.md)。可维护脚本更新了路径，原始历史脚本保持字节不变。

本次证明 API 图文回复可以经过原事件与解析执行链路，不证明与 MiniCPM 原生音视频双工等价。真人姿势到位判断、实时摄像头闭环、连续方向指导和长会话体验未在本轮重新验证。相关历史识图限制仍然成立。
