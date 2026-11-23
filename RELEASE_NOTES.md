# 0.1.11 GitHub 预发布说明

0.1.11 修复了主人发送“强制退出 MAA 和模拟器进程”后，插件未生成一次性票据、导致无法关闭绑定实例的问题。

- 补全带“进程”的明确退出表达，以及“那就先强制退出模拟器和 MAA 进程”等自然说法。
- 已有本插件任务上下文时，支持“强制退出”“授权强制退出”“强制退出本次进程”等后续请求。
- 退出、关闭和强杀请求会在开始任务的意图校验中被拒绝。
- 请求通过主人私聊来源校验和单次票据执行。日常完成后的清理保留原结果、完成时间、统计及通知去重。

49 项 Node 全量离线测试通过，覆盖原话识别、模拟 QQ 消息至票据消费、结果保留和不可信来源拒绝。2026-11-22 已安装到生产并确认宿主加载 0.1.11。本地还记录到一次真实主人 QQ“强制停止 MAA 和模拟器进程”的 force 票据消费及完成后关闭成功。新增退出短语和省略表达的逐项验证为模拟 QQ 链路测试。

当前继续以预发布提供。支持环境和验收范围见 [README](https://github.com/nanmu-mu/aurabot-maa-controller#readme) 及 [验证记录](https://github.com/nanmu-mu/aurabot-maa-controller/blob/main/docs/VALIDATION.md)。Python 执行器和固定任务参数沿用 0.1.9，MAA、MuMu 和运行时需自行安装。

从 0.1.9 升级时，先结束任务并保留部署器的回滚备份，按 [安装文档](https://github.com/nanmu-mu/aurabot-maa-controller/blob/main/docs/INSTALL.md) 更新模块。控制器配置、专用预设、Python 环境和任务记录保留。首次安装默认停用，示例配置为 `mode=mock`、`realEnabled=false`。

附件包括模块安装包 `aurabot-maa-controller-0.1.11.zip`、完整源码包 `aurabot-maa-controller-0.1.11-source.zip` 和 `SHA256SUMS.txt`。许可证为 AGPL-3.0-only，请同时提供同版本完整源码包。

## 构建

在干净源码根目录以 PowerShell 7 运行 `pwsh -NoProfile -File scripts/release.ps1`，按 `release-files.json` 构建模块 ZIP、完整源码 ZIP 和校验文件。已有输出时先归档，再使用干净目录重建。

