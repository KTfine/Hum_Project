# 单 GPU 云端部署

## 已验证的组合

RTX 5090（32607 MiB 显存）、Ubuntu 22.04.5、Python 3.12.3、预装 PyTorch 2.8.0+cu128、torchaudio 2.8.0+cu128、Transformers 4.51.0。BF16 未量化模型约 18.7GiB；短测试的显存采样峰值约 23–25GiB，不代表所有输入和长期运行的上限。

安装器复用镜像中的 PyTorch，不重新安装大体积 CUDA 框架；它会先核对版本并执行 BF16 GPU 运算。其他镜像组合未在本轮验证。

发布时 GPU 已解除挂载。整理后的脚本通过本地语法检查，尚未重新执行云端启动或从零安装；上述硬件和推理结果来自此前已完成的部署测试。

## 路径与版本

Demo 与模型的固定版本见 `backend/config/versions.env`。Demo 放在 `upstream/`，通过独立补丁应用 Gateway 监听地址及本次会话参数修复；安装器拒绝复用不同提交的 Git checkout，不会重置本地修改。

| 环境变量 | 默认位置 |
|---|---|
| `HUMCEN_STORAGE_ROOT` | 仓库内 `.runtime/`，建议改到云端数据盘 |
| `HUMCEN_UPSTREAM_DIR` | 仓库内 `upstream/` |
| `HUMCEN_VENV_DIR` | 仓库内 `.venv/` |
| `HUMCEN_MODEL_DIR` | `$HUMCEN_STORAGE_ROOT/models/MiniCPM-o-4_5` |
| `HUMCEN_DATA_DIR` | `$HUMCEN_STORAGE_ROOT/data` |

这些变量应使用绝对路径，并在安装、下载、启动的 shell 中保持一致。数据目录保存模型会话记录，不上传 GitHub。

## 安装、下载与启动

在云端已有可用 CUDA 镜像时：

```bash
git clone https://github.com/KTfine/Hum_Project.git
cd Hum_Project
export HUMCEN_STORAGE_ROOT=/root/autodl-tmp/humcen
# 网络需要时设置，例如：
# export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
# export HF_ENDPOINT=https://hf-mirror.com
bash scripts/cloud_install.sh
bash scripts/cloud_download.sh
nohup bash scripts/cloud_serve.sh > logs/service-launch.log 2>&1 < /dev/null &
echo $! > logs/service.pid
```

安装步骤显式安装 Demo 和 Token2Wav 的依赖，再用 `--no-deps` 安装 minicpmo-utils 1.0.6，以处理它的旧 librosa 元数据与 Demo 新版本要求的冲突。这与本次实际运行方案一致；它不是对所有 toolkit 组合的通用兼容保证。

模型下载固定 revision，写入并核验文件清单。启动时再次检查清单，并启用离线模式。服务依次启动 PyTorch 后端 22500、Worker 22400、Gateway 8006/8007，均监听 `127.0.0.1`，通过健康检查后注册单个 Worker。

查看状态：

```bash
curl -sk https://127.0.0.1:8006/status
cat logs/service-ready.txt
```

启动器检查 8006、8007、22400、22500；端口已被占用时不会再加载一份模型。确认 `logs/service.pid` 属于本次启动后，可用 `kill -TERM "$(cat logs/service.pid)"` 结束自己的服务；主脚本会结束自己创建的子进程。不要对其他进程使用批量 kill。

## 本机连接

SSH 主机、端口和账号从自己的平台实例页读取，通过 `scripts/connect_tunnel.ps1` 参数传入。密码仅交给 SSH 的交互提示，不保存在仓库。保持 SSH 窗口打开，再运行 `scripts/start_client.ps1`。

退出客户端后云端服务仍运行；停止服务也不等于停止租用实例。不使用时在云平台关机。
