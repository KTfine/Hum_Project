# 模型文本标签协议

以 `command_protocol.py`、`SpriteController` 和 `dispatch_model_commands` 为准。标签在 `response.output.delta` 的文本中传输，不是独立 WebSocket 消息。

## 当前标签

| 格式 | 含义与校验 |
|---|---|
| `<speak:内容>` | 非空文本；当前只打印，不播报 |
| `<blank>` | 无需回应；不带参数 |
| `<mode:guidance>` / `<mode:co-photo>` | 请求任务切换；同模式请求不重复重建 |
| `<move:to,x=0.35,y=0.95,ms=400>` | 绝对位置，x/y 为 0–1，至少提供一个轴 |
| `<move:by,dx=-0.10,dy=0,ms=300>` | 相对位移，dx/dy 为 -1–1，至少一个轴 |
| `<scale:to,value=0.8,ms=400>` | 绝对缩放，value 为 0.1–3 |
| `<scale:by,factor=1.1,ms=300>` | 相对缩放，factor 为 0.1–3 |
| `<rotate:to,value=10,ms=300>` | 绝对角度，value 为 -180–180 |
| `<rotate:by,value=-5,ms=300>` | 相对角度，value 为 -180–180 |
| `<tachie:smile>` | PNG 文件 stem；解析允许字母、数字、下划线、点、连字符，执行时须存在于已加载目录 |

ms 可省略，默认 350，必须为 0–3000 的整数。数值须有限；未知参数、重复参数、缺少必需参数、非法数值均不执行。角色 x 向右增加、y 向下增加，坐标用于立绘画布，不能直接当作真人身体左右或主摄像头坐标。

相对动作基于已排队目标累加，结果限制在 x/y 0–1、scale 0.1–3、rotation -180–180。未指定的轴保持原状态 / 动画。零时长零位移冻结指定轴的当前插值位置。换立绘不重置几何状态。

## 流式与适配

例如 `<speak:好的。><move:by,dx=-0.1,ms=300>` 可单行连续输出；标签可跨网络分块，每条完整闭合后立即解析执行。未知、非法和未完成标签不猜测执行。

解析器默认严格模式，普通客户端使用 `allow_plain_speech=True` 将标签外文字增量适配为 speak，记录 `parser.plain_text_adapted`。自然语言不会被推断为动作或模式。判断原生标签质量必须检查原始输出。

指导模板不提供角色动作，但客户端没有按模式禁止合法动作；指导期间意外生成的动作仍会改变隐藏的角色状态。模板约束和运行权限是两个不同层次，不能声称已经硬性隔离。

## 切换与旧入口

mode 标签先记录 `session.mode_requested`；新会话收到 `session.created` 后才有 `session.mode_ready` 和新视图。旧上下文会清空，角色几何和设备保留。自定义 prompt 不启用内置模式切换。

`<photo:enter>` 只保留历史解析兼容；分发时记录 `command.skipped`，原因 `legacy_photo_entry_use_mode_tag`，不入画、不切换。没有每轮必需 move、hold 标签、客户端固定询问或动作权限开关。
