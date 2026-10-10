# 碧蓝航线 ALAS Windows 服务器复现项目设计

日期：2026-10-10。状态：用户已授权整理并发布；尚未部署或验收服务器。

## 1. 目标与环境

把本机部署、日常运行、DeepSeek 分工和故障处理整理成可复制的项目。服务器为用户提供的 E5-2696 v3、64 GB、Quadro P620、Windows 10 IoT Enterprise LTSC 2021；单账号、单安卓模拟器起步。不复用旧活动任务、账号登录状态或日期绑定的观察器。

P620 官方资料列出 OpenGL 4.5、DirectX 12 及 Windows 10 支持，这支持将它作为模拟器候选显卡，但不等于本机已完成实测。建议初始模拟器配置 4 vCPU、4 GB RAM、1280×720；这是调试起点，不是性能结论。先验证驱动、BIOS VT、截图与游戏运行，再调整资源。安装准确版本应记录 SHA256、ALAS Git 提交及实际依赖版本，不能仅用 AlasApp 压缩包名称标识源码。

远程连接、断开连接、锁屏分别测试 ADB 截图与游戏持续运行。保留交互式 Windows 用户会话；不把模拟器未经验证地部署成 Session 0 服务，不自动修改 Hyper-V/VBS 或系统安全设置。

## 2. 项目交付结构

项目目录拟为 `alas-server-repro/`，与现有 ALAS 安装分离。

- `README.md`：从零部署与快速开始。
- `docs/deployment.md`：驱动、VT、雷电、游戏、ALAS、远程会话和版本记录。
- `docs/runbook.md`：启动、日常、训练、补星、大世界、领取证据和两小时报告。
- `docs/troubleshooting.md`：本次合作发现的问题、诊断、恢复及验证方法。
- `docs/migration.md`：原始脚本来源、迁移差异、历史限制。
- `config/settings.example.json`：路径、ADB serial、ALAS配置名、轮询、模型与邮件设置。
- `config/task-policy.example.json`：任务开关、油量和心情等约束。
- `scripts/doctor.ps1`：只读环境检查；不启动模拟器或购买游戏资源。
- `scripts/start.ps1`、`scripts/stop.ps1`：明确启动和暂停入口。
- `src/supervisor.py`：唯一进程、有限重启、暂停标记、运行时限和进程记录。
- `src/observer.py`：连接检测、PNG验证、变化检测、离线退避与短状态。
- `src/workers.py`：从已有 Imager/Emailer/Assembler 提取的参数化实现。
- `tests/`：离线验证、进程控制和结果校验测试；不依赖真实账号或收费API。
- `runtime/`：本机生成的日志、状态、截图、邮件收据；不进入发布包。

交付源代码目录、脱敏 ZIP、文件清单和本地测试结果。ALAS、雷电及游戏客户端由用户从官方来源安装，不混入项目包。

## 3. 系统分工与接口

ALAS执行其已验证的日常流程。普通程序负责守护、观察、去重、状态和用量记录。DeepSeek负责图像观察、报告草稿和诊断建议。GPT或用户主管处理例外、核验关键事实和批准具体操作。

Imager返回结构化观察，不能据此标记“领取成功”；关键PT/余额要求局部放大或独立OCR核验。保留原图路径、时间和SHA256。Emailer只生成草稿，日期、数字、完成状态须主管审核。Assembler不修改ALAS源码、不点击、不重启进程。

模型、API地址、单次超时与价格表可配置；原 `deepseek-flash` 与2026-10-03单价只作为历史，接入时验证实际模型与图像支持。无密钥仍可运行ALAS和本地诊断。每日额度默认不限制，保留单次超时、有限重试、结构拒绝、故障退避；失败费用未知，不计作零。不得把ChatGPT账户限额等同于API费用。

## 4. 配置与安全运行边界

不复制用户 `alas.json` 全量配置。生成经说明的策略模板，应用前备份、输出差异，默认 Main/Event/Opsi 关闭；Daily/Hard/Exercise/Tactical/Dorm 等按当天账号实际解锁情况启用。

油储备1000、Main OilLimit1250；心情calculate/prevent_green_face。训练两个已有槽优先T1，不扩槽、不花钻。追加普通出击前读取实际心情；补星逐关核验缺星、RunCount=1、StageIncrease=false。保护稀有船、布里和待练船，满船坞交主管处理，不沿用旧脚本的宽泛强化规则。

大世界只消耗已有AP及核验免费的补给；先核验剧情/自动搜索解锁。原NY页面识别卡住、日常任务板LOCKED、自动搜索未出现分别作为证据，不能把其中一种现象直接当作具体剧情原因。失败任务关闭后不得由守护循环重新开启。

启动前检查暂停标记、ADB连接、支持主页、唯一进程；模拟器关闭不自动启动。异地登录立即停用并等待人工恢复。手动操作在非战斗窗口，先停守护再停止其ALAS子进程；回到支持主页、截图核验后恢复。只停止本项目记录且验证身份的进程，不按名称杀死所有python。

## 5. 邮件与凭据

DeepSeek密钥仅从本机环境读取，不带入源码、ZIP、日志和示例。此前在聊天中公开过的密钥不得作为迁移默认，建议用户换新密钥后本地配置。账号密码、登录cookie、截图、收件人和邮件授权默认不发布。

现有邮件发送依赖Codex已授权的Gmail工具，本机连接授权不能复制。基础版提供草稿及发件收据接口；服务器无人值守直接发邮件需另行选定并配置Gmail OAuth或SMTP，默认发送关闭，不伪装成已经迁移。两小时触发只生成一个报告槽位，发送成功ID才标记已发，重试前查询已有收据/发件记录。

## 6. 从历史脚本迁移

- `work/run_alas_10h.py`：提取守护行为，移除绝对路径，增加所有权验证、唯一锁和暂停入口。
- `work/daily-pilot/monitor.py`：移除10月4日至5日固定窗口；先connect，再判断离线；离线不调用模型。
- `work/daily-pilot/workers.py`：保留角色边界、序列化调用与脱敏日志；移除新服每日PT只能200/500的过期规则，改为可选活动策略。
- `work/daily-pilot/capture.py`：参数化ADB与serial，检查返回码和PNG头。
- `work/fix_alas_connection.py`：作为历史串口异常案例，不自动套用字符串替换补丁。按实际版本复现后再决定修复。
- `work/configure_alas_run.py`：禁止直接复用；它含过期活动、OilLimit500、StageIncrease及宽泛强化，和最新约束冲突。
- `oct*-state.json`、历史报告及PT余额：仅供整理案例，不作为服务器起始状态。

## 7. 验收与成功标准

1. 本地离线测试通过：配置解析、脱敏、图像/结构校验、请求失败退避、重复启动拒绝、暂停停止与报告去重。
2. 服务器只读验收：设备在线，PNG有效1280×720，记录驱动/模拟器/ALAS版本；远程连接与断开后均取得有效截图。
3. 训练验收：已有两槽正常收取与续训，记录真实结束时间，不等两小时主管轮询。
4. 日常验收：单项运行，日志结束与游戏证据对应，再扩展到一天；资源及心情有时间戳，完成委托及时验收。
5. 大世界单独验收：解锁条件与页面识别通过，才允许有限一次任务，不因日常成功宣称大世界成功。
6. 分工试运行：至少30张不同截图覆盖主页、任务、余额、奖励、委托、后宅、战斗与异常；统计误读、拒绝、接管、用量及在线时间。

完成代码与本地测试只能称“复现项目准备完成”；未连接服务器不能称“服务器部署成功”或“完全无人值守”。

## 8. 依据

- NVIDIA P620官方资料：https://www.nvidia.com/content/dam/en-zz/Solutions/design-visualization/productspage/quadro/quadro-desktop/quadro-pascal-p620-data-sheet-us-nv-704415-r1.pdf
- 微软LTSC 2021生命周期：https://learn.microsoft.com/lifecycle/products/windows-10-iot-enterprise-ltsc-2021
- 雷电官方要求：https://www.ldplayer.net/support/pc-system-requirements-for-android-emulator.html?n=55531286
- ALAS官方发布：https://github.com/LmeSzinc/AzurLaneAutoScript/releases
- 本工作区已读取的守护、观察器、workers、连接修复及配置脚本。

## 9. 实施决定

交付单模拟器、主管审核、邮件草稿接口的复现项目，完整保留既有工作流程。将直接无人值守发邮件留作单独接入步骤。用户已要求直接整理并发布，由当前会话执行，不派子代理。
