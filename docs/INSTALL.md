# 安装与配置

本指南适用于 Windows x64、已正常工作的 Aurabot/QQ 主人私聊，以及自行安装的 MAA 和 MuMu。当前模块只支持 README 列出的固定版本和任务范围。

## 1. 取得候选包

从同一个 Release 取得模块 ZIP、完整源码 ZIP 和 SHA256SUMS.txt。用 `Get-FileHash -Algorithm SHA256` 核对 ZIP；解压模块 ZIP 到临时目录，得到含 `manifest.json` 的 `maa-controller` 文件夹。不要把源码 ZIP 或带历史数据的开发目录直接覆盖进生产模块目录。

以下路径是示例。自定义 DSH 配置目录的用户应按实际 Aurabot 数据位置调整。

```powershell
$bundleDir = 'C:\Temp\aurabot-maa-controller\maa-controller'
$aurabotDataDir = Join-Path $env:USERPROFILE '.dsh\plugins-data\aurabot'
$moduleDir = Join-Path $aurabotDataDir 'modules\maa-controller'
$dataDir = Join-Path $aurabotDataDir 'modules-data\maa-controller'
```

## 2. 安装默认停用模块

已有插件任务应先正常结束，或由主人明确停止并核实结果。活动或未知未核清任务会阻止安装/回滚。

```powershell
node "$bundleDir\scripts\deploy.mjs" install --source $bundleDir --destination $moduleDir --data $dataDir --confirm-install
```

部署器校验清单、原子替换本模块，并输出旧模块的备份路径。首次安装默认停用；升级会保留宿主中已有的模块开关，不会自动把已启用模块改成停用。升级前请在 Aurabot 面板停用本模块。数据目录与其他模块不被替换。

部署器使用安装包中的 `manifest.json` 校验文件；生产模块目录本身不保留这份清单。请保留原下载包用于后续校验和回滚。

## 3. 准备独立 Python 环境

使用已安装的 Python 3.14；已验收版本为 3.14.4。不要把虚拟环境放在会被宿主监视的模块文件夹内。

```powershell
py -3.14 -m venv "$dataDir\.venv"
```

在 Aurabot 的本模块设置中填写：

- Python 解释器：上一步生成的 `python.exe` 的实际完整路径，末尾为 `modules-data\maa-controller\.venv\Scripts\python.exe`。
- 控制器配置：可留空使用默认数据目录的 `controller.json`；自定义时填写实际完整路径。
- 先保持请求处理开关关闭。

首次加载会在数据目录生成默认控制器示例；已有 `controller.json` 会保留。

## 4. 核对路径、版本和连接

编辑数据目录的 `controller.json`，先保留 `mode=mock`、`realEnabled=false`。示例中的 `C:\Applications\MAA` 和 `C:\Applications\MuMu` 都是占位路径，应改成自己的安装位置。

- `maaDir`：MAA 6.21.3 安装目录。
- `emulator.manager`：对应 MuMu 安装中的 `nx_main\MuMuManager.exe`。
- `emulator.adb`：同一 MuMu 安装中的 `shell\adb.exe`。
- `emulator.headlessExecutable`：当前支持标准 Program Files 下的 `MuMuVMMVbox\Hypervisor\MuMuVMMHeadless.exe`；不要填写其他实例或共享服务的路径。
- `index=0`、`address=127.0.0.1:16384` 是当前硬边界，不是任意实例选择器。

MAA 自身应能使用 MuMu 实例 0 正常执行目标日常。只支持官服、MiniTouch、AdbLite关闭、Default配置中的六个已启用任务及已核查参数。额外任务、账号切换、动态关卡或特殊基建策略可能被转换器拒绝。

当前预设指纹覆盖 MAA 安装根目录 DLL、resource 根 JSON 及 tasks 子目录 JSON。图片模板没有逐个校验。版本字符串一致也不代表任意修改后的资源包兼容；指纹不符时先核对来源、架构和资源版本，再决定是否同步，不能只重新生成指纹绕过检查。

## 5. 显式转换日常预设

确认 MAA 已停止更新、没有活动插件任务，先审查 GUI 中的任务和消费选项。以下转换只读 GUI 配置，输出插件专用预设，不启动 Core、模拟器或游戏，也不会修改 GUI。

```powershell
$maaDir = 'C:\Applications\MAA' # 改为实际安装目录
node "$moduleDir\scripts\cli.mjs" convert --gui "$maaDir\config\gui.new.json" --maa $maaDir --out "$dataDir\presets\daily.json" --data $dataDir
```

转换成功后，在数据目录的 `controller.json` 中把 `presetFile` 设为 `presets/daily.json`，相对路径按该配置文件所在目录解析。

转换器保留固定范围内的有效策略，显式关闭吃药、碎石、加急、寻访入口及外部统计上报。GUI 中未启用的药剂数量不会变成实际消费；GUI 中的统计账号或令牌不迁移。

以后修改 GUI 不会自动同步。无任务时重新审查并转换；MAA 或资源升级必须先重新核验兼容性。转换成功不替代真实控制和游戏验收。

## 6. 明确启用真实执行

审查完成后，由使用者明确将数据目录配置改为 `mode=real`、`realEnabled=true`。重载本模块以读取设置，再开启本模块请求处理。

Aurabot 的主人身份、完整工具权限、总开关和非试运行设置也必须满足模块要求。不要为使其运行而授予群聊或陌生人本地执行权限。

从主人 QQ 私聊发送一次新的明确请求，例如“帮我把明日方舟日常清一下”。无需在聊天中输入系统命令，也不要发送密钥或游戏登录信息。

- 只有收到真实开始通知才表示任务已开始；受理回复不等于开始或完成。
- 模拟器未启动时，仅启动已绑定实例；超时就通知，不重启、切换或重跑。
- 遇到游戏登录或验证页面，由使用者自行处理，不把凭证交给模块。
- 首次实际接入应观察任务、消费限制、结果与通知；未知结果先核对，不直接重发新任务。

## 升级与回滚

先结束任务、停用本模块，再用新包运行部署器。保留原 `controller.json`、专用预设、请求和任务记录；不要删除锁或账本来强行升级。

回滚时使用部署器输出的同父目录备份路径：

```powershell
$backupDir = '填写部署器输出的本模块备份完整路径'
node "$bundleDir\scripts\deploy.mjs" rollback --destination $moduleDir --data $dataDir --backup $backupDir --confirm-install
```

回滚只恢复模块文件，保留数据目录，不替换人格、记忆、成长引擎或其他扩展。恢复后核对版本和配置，再由使用者决定是否启用。