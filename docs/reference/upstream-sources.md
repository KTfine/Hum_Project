# 来源与基线

本仓库首次导入基线来源于用户指定的 `DDRP674/AIAA3800`，不是与该仓库共享 Git 历史的 fork。后续修改以本仓库提交和 `CHANGELOG.md` 为准。

| 内容 | 来源及固定提交 |
|---|---|
| 根目录客户端、协议解析器、提示词、测试及 `tachie/` 立绘 | [AIAA3800 main](https://github.com/DDRP674/AIAA3800/tree/177d70afd6d8e6d95d619621c61117cef8cd59cd)，`177d70afd6d8e6d95d619621c61117cef8cd59cd` |
| 本仓库 `backend` 分支的部署配置、脚本和客户端工具 | [AIAA3800 backend](https://github.com/DDRP674/AIAA3800/tree/2accaaff4e616caac397037e41fbcf9324339d63)，`2accaaff4e616caac397037e41fbcf9324339d63` |
| 运行时外部 Demo，不纳入本仓库源码树 | [OpenBMB/MiniCPM-o-Demo](https://github.com/OpenBMB/MiniCPM-o-Demo/tree/47709a9210dfd71afa76c058e017fc8c4db5c8d2)，`47709a9210dfd71afa76c058e017fc8c4db5c8d2` |
| 外部模型权重，不上传 GitHub | [openbmb/MiniCPM-o-4_5](https://huggingface.co/openbmb/MiniCPM-o-4_5/tree/503e754207c94da6bb26850b4469f367c9ea3582)，revision `503e754207c94da6bb26850b4469f367c9ea3582` |

上述是来源定位，不代表当前源码仍与导入版本逐字一致。2026-11-07 起的运行与实验基线见 [模式说明](../modes-and-prompts.md) 和 [实验索引](../../experiments/records/README.md)；重置实验不改变第三方归属或固定运行依赖。

导入时排除了上游历史会话。立绘沿用上游素材，原始归属不变；本仓库没有为第三方素材新增授权或统一开源许可证。
