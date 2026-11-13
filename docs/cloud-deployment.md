# 后端部署

部署代码已按上游结构移至独立的 **backend 分支**。前端 main 不再携带 backend 子目录。

- [API 模式启动](https://github.com/KTfine/Hum_Project/blob/backend/README.md)：无需 GPU，前端使用 `--backend api`。
- [MiniCPM 单 GPU 部署](https://github.com/KTfine/Hum_Project/blob/backend/docs/cloud-deployment.md)：原安装、下载和服务脚本。
- [Slurm 部署](https://github.com/KTfine/Hum_Project/blob/backend/docs/slurm.md)：按目标集群适配资源和路径。

前端保留 `scripts/connect_tunnel.ps1` 与 `scripts/start_client.ps1`。SSH 隧道默认访问 `https://localhost:18006`，API 本地服务默认访问 `http://127.0.0.1:8006`。部署与停止命令在 backend 分支维护。
