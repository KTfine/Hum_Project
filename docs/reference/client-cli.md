# 客户端与重放入口

命令均从仓库根目录执行。完整选项以对应 `--help` 为准。

## 普通客户端

```powershell
.\scripts\connect_tunnel.ps1 -SshHost YOUR_SSH_HOST -SshUser YOUR_SSH_USER -SshPort 22 -LocalPort 18006
# 保持隧道窗口打开，在另一个窗口执行：
.\scripts\start_client.ps1
```

启动器参数：`-GatewayUrl` 默认 `https://localhost:18006`；`-Python` 可指定解释器，未指定时优先 `.venv-client\Scripts\python.exe`，否则使用 PATH 中的 python。它使用仓库内立绘和 `runtime_results/live-时间.jsonl` 日志，并接受本地隧道的自签名证书。

直接启动的等价核心命令：

```powershell
python realtime_av_test.py --url https://localhost:18006 --insecure
python realtime_av_test.py --help
```

| 选项 | 默认值 / 作用 |
|---|---|
| `--url` | 直接 Python 入口默认为 `https://localhost:8006`；使用隧道时显式指定 18006 |
| `--sprite-dir` / `--initial-sprite` | `tachie/sanae` / `normal`；指导模式也初始化立绘资源供以后切换 |
| `--canvas-width` / `--canvas-height` | 1280 / 720，须为正数 |
| `--jpeg-quality` | 80，范围 1–100 |
| `--character-name` / `--character-persona` | 早苗 / 默认自然友善的设定 |
| `--camera-device` / `--input-device` | 相机 0 / 默认麦克风 |
| `--no-camera` | 不采相机；指导发送空白，合照或 custom 使用立绘画布 |
| `--no-mic` | 发送静音；仍为 video 接口 |
| `--no-preview` | 隐藏窗口，不停止采集或发送 |
| `--prompt` | 完整 system 字符串覆盖；custom 模式，不自动切换模板，保留立绘视图 |
| `--log-file` | 默认 `logs/frontend-时间.jsonl` |
| `--connect-timeout` / `--session-timeout` | 建连 10 秒 / 会话初始化 120 秒，不是总运行时长 |
| `--insecure` / `--verbose` | 接受自签名证书 / 输出诊断信息 |

按 Q 或 Ctrl+C 退出。不存在 `--mode`、`--action-only-test` 或手动 ON/OFF 开关。

## 通用重放

`tools/runtime_effect_probe.py` 复用当前双模式与解析执行链路，使用 WAV 文件替代麦克风；默认仍打开摄像头，`--no-camera` 可关闭。它接受本地自签名 TLS，只用于可信隧道。每轮必须显式提供时间线，已移除旧实验的默认动作、旧语音生成器和固定判分器。

时间线是 `[[开始秒数,"相对 runtime_results 的 WAV 路径"], ...]`。例如自行准备两个文件后：

```json
[[3,"trial/invite.wav"],[25,"trial/move.wav"]]
```

```powershell
python tools/runtime_effect_probe.py --url https://localhost:18006 --seconds 50 --instructions-file runtime_results/trial/schedule.json --output-subdir trial-run --no-camera
```

WAV 须为 16 kHz、单声道、16-bit PCM，工具转为网关 Float32。记录真实语音文本及来源，时间线须为每轮设计，不假定邀请已经成功。`[]` 可用于静音诊断。

`--preview` 显示预览；`--prompt-file` UTF-8 全量覆盖 prompt；`--generation-config` 用 JSON 覆盖会话生成配置。输出在 `runtime_results/<output-subdir>/`：`effect-probe.jsonl`、`effect-state.json` 和角色状态截图。每轮使用不同目录，工具会覆盖同名文件。

这是按秒重放工具，模式重建可能影响后续发送时序，不适合直接测量切换耗时或把固定秒数当作响应窗口。角色截图只证明角色画布状态，不是保存的合照；是否通过由该轮明确的判据决定。
