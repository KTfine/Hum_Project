# 来源与固定版本

本项目最初从用户指定的 [DDRP674/AIAA3800](https://github.com/DDRP674/AIAA3800) 导入前端和后端代码。Hum_Project 使用自己的 Git 历史，导入不代表当前文件仍与上游逐字相同。现按上游的分支布局管理：main 保存前端，backend 保存部署与服务。

| 内容 | 来源与固定版本 |
|---|---|
| 初始前端、标签协议、提示词、测试和立绘；现在维护于 main 分支 | [AIAA3800 main](https://github.com/DDRP674/AIAA3800/tree/177d70afd6d8e6d95d619621c61117cef8cd59cd)，`177d70afd6d8e6d95d619621c61117cef8cd59cd` |
| 初始部署配置、Slurm 脚本和后端探针；本分支的部署基线 | [AIAA3800 backend](https://github.com/DDRP674/AIAA3800/tree/2accaaff4e616caac397037e41fbcf9324339d63)，`2accaaff4e616caac397037e41fbcf9324339d63` |
| MiniCPM 外部运行时 Demo | [OpenBMB/MiniCPM-o-Demo](https://github.com/OpenBMB/MiniCPM-o-Demo/tree/47709a9210dfd71afa76c058e017fc8c4db5c8d2)，`47709a9210dfd71afa76c058e017fc8c4db5c8d2` |
| MiniCPM 模型权重 | [openbmb/MiniCPM-o-4_5](https://huggingface.co/openbmb/MiniCPM-o-4_5/tree/503e754207c94da6bb26850b4469f367c9ea3582)，revision `503e754207c94da6bb26850b4469f367c9ea3582` |

Demo 和模型的实际安装版本由 [config/versions.env](../config/versions.env) 固定。Demo checkout 和权重保存在本机，未复制进源码仓库；本仓库对固定 Demo 的会话参数与监听地址调整单独保存在 [patches/](../patches/)，由 [补丁脚本](../scripts/apply_upstream_patches.py) 应用。

`scripts/cloud_*.sh` 是 Hum_Project 维护的单 GPU 部署入口；`api_mode/` 是本次新增的 DeepSeek API 网关，不属于上述上游基线。API 依赖固定在 [requirements-api.txt](../requirements-api.txt)，不依赖本地 MiniCPM 权重，也不改变 MiniCPM 的固定版本。

上游会话和本机实验媒体不随代码发布。前端立绘沿用上游素材，第三方归属不变；本项目没有为第三方素材新增授权或统一许可证。代码来源、部署可运行性和模型实验结果分别记录；后两者不能从来源提交推导，实验入口见 [main/experiments](https://github.com/KTfine/Hum_Project/tree/main/experiments)。
