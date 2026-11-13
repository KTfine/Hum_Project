# 后端与 Slurm 适配说明

2026-11-07 重写。一般单 GPU 使用 [cloud 部署](cloud-deployment.md)；本目录保留固定依赖、补丁、通用 API 探针和 Slurm 部署代码，不把重置前结果作为当前部署保证。

## 共用部分

- `config/versions.env` 固定 Demo 和模型 revision；`config/service.json` 定义服务配置。
- `patches/` 和 `scripts/apply_upstream_patches.py` 管理可审查、可重复应用的监听地址和会话参数补丁。
- `client/health.py` 检查网关，`client/text_chat.py` 检查通用 chat；它们不会自动加载拍照助手 prompt。
- `tests/test_duplex_session_options.py` 对固定上游方法检查选项传递；`test_gateway_bindings.py` 需要已安装的 Demo 依赖；`test_static.sh` 是带部署阶段 / 环境要求的静态检查，不能等同于普通客户端单测。

## Slurm 当前限制

`slurm/*.sbatch` 仍含原集群的绝对工作目录、日志目录、CPU 分区和 A800 / A40 资源名称，`scripts/check_queue.sh` 同样面向这些分区。这些是待适配的部署代码，不能直接用于任意集群。本轮不迁移调度实现，也没有提交任何作业。

使用前在自己的 checkout 中核对并修改四份 sbatch 的工作目录与 stdout/stderr 路径，以及 partition / QoS / GRES；创建实际的 `logs/slurm/`。`scripts/common.sh` 从脚本位置计算服务根目录。CPU 安装、下载及 GPU 探针 / 服务脚本要求在 Slurm allocation 中运行，不在登录节点直接执行。

适配完成后，在 backend 分支根目录按顺序提交并等待每一步完成：

```bash
sbatch slurm/bootstrap_cpu.sbatch
sbatch slurm/download_model_cpu.sbatch
sbatch slurm/probe_gpu.sbatch
sbatch slurm/serve.sbatch
```

检查每个作业的 stdout/stderr、模型 revision / manifest 和服务日志；失败时修复后再继续。默认服务时限为 30 分钟，实际资源和限制由目标集群决定。

## 监听与隧道

Slurm 的 `scripts/launch_service.sh` 将 Gateway 8006 绑定 0.0.0.0，内部 8007 / 22400 / 22500 绑定 localhost，依赖集群网络隔离；cloud 入口则全部绑定 localhost。服务没有 API Key，不将这些端口公开到公网。

从本地连接计算节点，账号与节点名替换为实际配置：

```powershell
ssh -N -J USER@LOGIN_HOST -L 18006:127.0.0.1:8006 USER@COMPUTE_HOST
python client/health.py --url https://localhost:18006 --insecure --pretty
python client/text_chat.py --url https://localhost:18006 --insecure --pretty --prompt "请只回复：连接成功"
```

保持隧道开启，只转发 8006。具体字段与正常拍照客户端见 [接口索引](../CALLING_API.md)。

## 结果与数据

Slurm 日志通常在 `logs/<job-id>/`，包括 backend / worker / gateway、环境、显存和 validation；完整会话数据在服务数据目录，可能包含图像、音频和文字，不提交。每次部署重新记录实际硬件和运行结果，不从旧集群示例推导可用性。
