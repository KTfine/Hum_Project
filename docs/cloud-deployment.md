# 单 GPU 部署

本说明于 2026-11-07 对照 `scripts/cloud_*.sh` 重写，描述当前脚本要求，不继承此前硬件测试为兼容保证。本轮未重新安装服务或执行 GPU 验收。

## 依赖与目录

安装入口要求已有 CUDA 环境及 `torch 2.8.0+cu128`，会执行 BF16 GPU 运算检查；随后核对 torchaudio 2.8.0 和 Transformers 4.51.0。脚本不是自动选择 CUDA 版本的通用安装器。实际 GPU、显存、驱动、包版本和模型加载结果应在每次部署中单独记录。

Demo / 模型固定 revision 见 [versions.env](../config/versions.env)。安装器应用独立补丁，拒绝复用不同提交的 Demo checkout；下载写入清单，启动验证后离线加载。

| 环境变量 | 默认值 |
|---|---|
| HUMCEN_STORAGE_ROOT | 仓库 `.runtime/` |
| HUMCEN_UPSTREAM_DIR | 仓库 `upstream/` |
| HUMCEN_VENV_DIR | 仓库 `.venv/` |
| HUMCEN_MODEL_DIR | storage root 下 `models/MiniCPM-o-4_5` |
| HUMCEN_DATA_DIR | storage root 下 `data/` |
| HUMCEN_PYTHON | 安装器使用的 python，默认 PATH 中 python |

路径使用绝对路径，安装、下载和启动时保持一致。模型、环境、会话数据及日志均不上传 GitHub。

## 安装与启动

在具备上述环境的 Linux GPU 主机执行，数据盘路径替换为自己的可写目录：

```bash
git clone --branch backend --single-branch https://github.com/KTfine/Hum_Project.git Hum_Project-backend
cd Hum_Project-backend
export HUMCEN_STORAGE_ROOT=/absolute/path/to/humcen-data
bash scripts/cloud_install.sh
bash scripts/cloud_download.sh
mkdir -p logs
nohup bash scripts/cloud_serve.sh > logs/service-launch.log 2>&1 < /dev/null &
echo $! > logs/service.pid
```

安装器单独安装 Token2Wav 依赖，并对 minicpmo-utils 1.0.6 使用 `--no-deps`，依赖版本以脚本和输出的 `logs/runtime-packages.txt` 为准。

服务使用 22500（模型）、22400（Worker）、8006（Gateway）、8007（内部注册），cloud 入口均绑定 127.0.0.1。端口占用会拒绝启动，避免重复加载模型。只转发 8006：

在另一份 main 分支的前端目录中执行：

```powershell
.\scripts\connect_tunnel.ps1 -SshHost YOUR_SSH_HOST -SshUser YOUR_SSH_USER
curl.exe -k https://localhost:18006/health
curl.exe -k https://localhost:18006/status
.\scripts\start_client.ps1
```

服务没有 API Key 校验，依靠 SSH 访问。自签名证书选项限可信隧道。health 只证明网关响应，status 用于检查 Worker 注册、忙闲和队列；模型质量另做实验。

Linux 上检查 `logs/service-launch.log` 和 `logs/service-ready.txt`。停止时先核对 `logs/service.pid` 对应本次启动的进程，再向该 PID 发 TERM，启动器清理自己创建的子进程。客户端退出不会停止服务；停止服务也不会自动结束云实例计费。

## 验证范围

从零安装、补丁应用、模型就绪、chat、video 和真人闭环分别记录。仓库 CI 只做程序 / 脚本 / 固定补丁检查，不证明云端运行或显存足够。单 GPU 与 [Slurm 入口](slurm.md) 的目录布局和监听方式不同，不混用。API 见 [接口索引](../CALLING_API.md)。
