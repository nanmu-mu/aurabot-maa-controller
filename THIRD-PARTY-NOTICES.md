# 第三方项目与来源说明

本仓库原始代码按 AGPL-3.0-only 发布，完整文本见 [LICENSE](LICENSE)，项目署名见 [NOTICE](NOTICE)。第三方项目各自的许可证及使用条件不由本仓库许可证替代。

| 项目 | 用途 | 官方来源与许可 |
|---|---|---|
| Aurabot | 宿主模块 API v1、QQ 会话与工具接入 | [仓库](https://github.com/aureth-labs/dsh-aurabot-qq)、[MIT 许可证](https://github.com/aureth-labs/dsh-aurabot-qq/blob/main/LICENSE) |
| MaaAssistantArknights | 本机 MaaCore C 接口、任务与回调协议 | [仓库](https://github.com/MaaAssistantArknights/MaaAssistantArknights)、[v6.21.3 AGPLv3 许可证](https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/v6.21.3/LICENSE) |

安装包只包含本插件的代码、固定预设、示例配置和文档；不包含 Aurabot 源码、MaaCore DLL、MAA 资源包、MuMu、Python、Node.js、QQ、SnowLuma 或游戏素材。上述软件由使用者自行取得和安装。

插件通过 Python ctypes 加载用户本机的 MaaCore。接口核验基线为官方 v6.21.3，源码提交为 `561fca9d0ab37e07256b6514fe970847f0fcafa6`；C 接口声明及任务、回调文档见该版本的 `include/AsstCaller.h` 与 `docs/zh-cn/protocol/`。

`presets/daily.json` 是按白名单转换的固定参数，包含版本指纹，不含账号、令牌、聊天记录、第三方统计身份或游戏图像资源。

每份安装包应与同版本的完整源码包一起提供；源码包包含构建脚本、测试和许可证。发布方式见 [发布说明](RELEASE_NOTES.md)。