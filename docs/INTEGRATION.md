# 接入设计

## 宿主与执行器

Aurabot API v1 用户模块负责消息来源校验、一次性票据、工具与上下文注册、状态查询和原会话通知。独立 Python 执行器负责固定 MaaCore 任务和绑定 MuMu 实例。

模块使用宿主真实提供的 `api.on`、`api.tool`、`api.context`、`api.every`、`api.sendText`、`api.settings`、`api.dataDir` 和 `api.isOwner`。模块目录保存代码；数据目录保存配置、请求、任务账本、通知状态和独立 Python 环境。运行数据不放进热重载目录。

MaaCore 通过 ctypes 的 C ABI 加载，使用 AsstCreateEx 回调、AsstAppendTask、AsstStart、AsstStop、AsstRunning 和 AsstDestroy。实际开始依据任务链回调，结束依据回调、队列 idle 与执行线程退出的组合，不以创建进程或 AsstStart 返回值替代完成证据。

## 授权链

1. 校验真实 OneBot 原始事件、主人、私聊、消息身份、正文和时效；拒绝引用、转发、模拟来源及不可信内容。
2. 识别明确即时请求，生成短期单次票据；工具只接受票据 ID，不接受聊天指定的动作、路径、PID 或命令。
3. 消费前再次检查主人会话、权限、宿主开关与模块设置；不向其他会话移交票据。
4. GUI 关闭单独绑定 PID、创建时间、可执行文件路径及当前控制配置/预设摘要，五分钟有效、单次消费；目标或配置变化需重新请求。

## 状态与恢复

只允许单任务，使用开始锁、活动指针、设备/安装互斥和持久账本。失败、取消、部分完成和未知分别记录；未知且尚未证明安全释放时阻止新启动。

执行器独立于宿主对象；宿主恢复后读取相同任务与进程记录，不重新启动。开始、异常和最终通知有独立持久记录及发送重试；发送 API 已确认不代表每个 QQ 客户端都已读。故障边界下可能发生至少一次投递，不能承诺跨网络事务的绝对恰好一次。

强制终止核对本次执行器的 PID、创建时间、路径及运行归属，再核对实例 0 的 headless 映射并精确终止。随后使用 MuMu 的固定实例关闭指令收尾设备窗口，核对实例确已停止；不按名称终止进程，不杀公共 ADB 或其他实例。

强制辅助器持久化短期操作标记并持有独立互斥锁。状态轮询在有效标记和辅助器存活期间等待最终结果，避免把预期执行器退出误报未知；辅助器结束或标记过期后仍按实际证据核对。

## 数据边界

任务记录保留必要的授权会话标识、执行状态与诊断，只用于当前功能，不上传本地诊断。配置转换仅白名单迁移任务参数，第三方统计身份和凭证不迁移。

结果只汇总本次可靠回调。已识别掉落不等于完整资产账单，招聘标签预测不等于获得干员；刷到既定连战所需理智不足可以是正常收尾，不会自动改策略或补药/碎石。

接口依据：[Aurabot API](https://github.com/aureth-labs/dsh-aurabot-qq/blob/main/src/modules/API.md)、[MAA v6.21.3 C ABI](https://github.com/MaaAssistantArknights/MaaAssistantArknights/blob/v6.21.3/include/AsstCaller.h)、[MAA 协议目录](https://github.com/MaaAssistantArknights/MaaAssistantArknights/tree/v6.21.3/docs/zh-cn/protocol)。