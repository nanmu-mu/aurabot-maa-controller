# GitHub 预发布说明

建议标签与标题：`v0.1.7` / `Aurabot MAA Controller 0.1.7`，创建 Release 时勾选 **Pre-release**。

以下内容可作为发布正文：

---

首个公开预发布版本：通过主人QQ私聊控制一份固定本机MAA日常，提供单次授权、重复启动保护、GUI关闭许可、进度查询、温和停止和绑定实例强制终止。

运行基线为Windows x64、DSH Desktop0.2.1-rc.5、Aurabot1.1.24 / API v1、MAA6.21.3与MuMu实例0。仅支持官服固定六项任务、1-7、不补药/碎石；详见README和验证记录。

36项Node、20项Python离线测试通过。真实控制验收已完成；6.21.3整套日常自然结束尚未重跑，完整自然结束的既有基线是6.21.1。本次预发布不扩大兼容性或验收结论。

安装包默认停用、真实执行默认关闭。请先按安装文档核对路径、主人、实例、任务和资源限制，再由使用者明确启用。MAA、模拟器、运行时与游戏需自行安装。

许可证：AGPL-3.0-only。请同时保留并提供同版本完整源码包。

附件：

- `aurabot-maa-controller-0.1.7.zip`：模块安装包。
- `aurabot-maa-controller-0.1.7-source.zip`：完整源码、测试和构建脚本。
- `SHA256SUMS.txt`：上述文件SHA256校验。

---

## 在干净源码目录构建附件

使用 PowerShell 7，在尚无构建输出的源码根目录运行：

```powershell
pwsh -NoProfile -File scripts/release.ps1
```

脚本只在本地构建安装包、按 `release-files.json` 明确清单构建源码包，并生成 `dist/SHA256SUMS.txt`；不会上传、安装到生产或执行游戏任务。已有输出时会拒绝覆盖，先自行归档再重建。安装包文件清单由 `scripts/package.mjs` 维护。

## 发布操作边界

本文件是发布正文草稿，不表示已在GitHub创建仓库、推送代码、提交PR或创建Release。仓库地址确定后再补repository/homepage字段；当前没有编造远程地址或作者个人标识。

公开仓库应来自本公开候选目录；不要从含本机历史的私有开发仓库直接整体推送。安装包和源码包均按明确文件清单构建，不包含Git历史、虚拟环境、运行账本、聊天、凭证、日志或第三方二进制。