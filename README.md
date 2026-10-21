# ALAS Server + GPT / DeepSeek

碧蓝航线 ALAS Windows 服务器复现项目：部署与调试手册、后台守护、只读观察器和结构化模型分工。

目标硬件：E5-2696 v3 / 64 GB / Quadro P620，Windows 10 IoT Enterprise LTSC 2021。单账号、单模拟器起步。**代码通过本地离线测试；目标服务器尚未实测，不宣称完全无人值守。**

## 架构

```text
Windows交互式用户会话
  雷电 + 碧蓝航线 <── ADB ── ALAS（任务执行）
                           ↑ supervisor（唯一锁、暂停、有限重启）
  observer ── 原图/短状态 ── Imager（观察）
  已核验状态 ── Emailer（草稿） ── 主管审核 ── 外部邮件发送器
  错误摘要   ── Assembler（建议） ── 主管处理
```

项目不会安装或自动启动模拟器，不保存游戏登录凭据，不自动点击，不直接发送邮件或覆盖 ALAS 配置。大世界、补星和领取异常由主管核验处理。模型结构合法不代表读数正确或奖励已到账。

## 快速开始

先完成[部署手册](docs/deployment.md)，手动安装官方雷电、游戏与ALAS，停在支持主页。安装 Python 3.11（项目运行时，与ALAS自带Python分开）：

```powershell
git clone https://github.com/HWMAT4-R6/ALAS-SERVER-GPT.git
cd ALAS-SERVER-GPT
py -3.11 -m venv .venv
& .venv/Scripts/python.exe -m pip install -r requirements.txt
Copy-Item config/settings.example.json config/settings.json
# 编辑 settings.json：ADB、ALAS根目录、ALAS自带Python、serial
& scripts/doctor.ps1
& .venv/Scripts/python.exe -m src.runtime capture --out runtime/preflight.png
```

看图确认主页、无异地登录、无战斗，并检查ALAS任务配置。关闭其他ALAS循环后：

```powershell
& scripts/start.ps1 -Mode supervisor -HomeVerified
& scripts/start.ps1 -Mode observer
# 看 runtime/events.jsonl 与 alas.log 确认实际启动
& scripts/stop.ps1
```

暂停会创建 `runtime/PAUSE`，阻止重启。恢复前重新截图核验支持主页，然后执行：

```powershell
& .venv/Scripts/python.exe -m src.runtime resume --home-verified
& scripts/start.ps1 -Mode supervisor -HomeVerified
& scripts/start.ps1 -Mode observer
```

只有明确执行恢复才删除暂停标记。`HomeVerified` 是操作者确认，程序没有自动证明截图是主页。

## DeepSeek 可选接入

`settings.json` 的 `model` 必须改为账户实际可用且已验证支持图像输入的模型；项目不保证历史 `deepseek-flash` 名称在任意账户可用。先关闭 `vision_enabled` 完成本地验收。密钥只在服务器用户环境配置，**不要输入聊天、README、Git或命令历史**。可在Windows“编辑账户环境变量”窗口配置 `DEEPSEEK_API_KEY`；重新打开终端。

```powershell
& .venv/Scripts/python.exe -m src.workers imager --image runtime/preflight.png
& .venv/Scripts/python.exe -m src.workers imager --image runtime/preflight.png --crop 475 0 981 63
& .venv/Scripts/python.exe -m src.workers emailer --evidence runtime/verified-report.json
& .venv/Scripts/python.exe -m src.workers assembler --evidence runtime/fault-summary.txt
```

模型调用会计费并上传提供的截图/证据。只传所需局部和脱敏摘要。默认日累计不限额；单次30秒超时、最多两次网络重试、单worker互斥。价格表为空时费用显示未知，usage仍记录；自行核验当前厂商价格后填写 `input/cached_input/output`（USD/百万token）。估算不是账单，失败费用不能当零。

## 运行与调试

- [完整部署](docs/deployment.md)
- [日常运行、训练、心情、补星与大世界](docs/runbook.md)
- [故障案例与恢复](docs/troubleshooting.md)
- [邮件、成本与发布隐私](docs/reporting.md)
- [迁移范围和验收](docs/migration.md)

## 本地验证

```powershell
& .venv/Scripts/python.exe -m unittest discover -s tests -v
& .venv/Scripts/python.exe -m compileall -q src
```

测试不连接模拟器、不调用付费API。现场验收需另行测试24小时在线、锁屏/远程断开、两槽连续训练、日常领取、大世界解锁和至少30张不同截图。禁止把旧日期、历史PT余额或旧队伍心情作为当前状态。

## 来源

ALAS由 [LmeSzinc/AzurLaneAutoScript](https://github.com/LmeSzinc/AzurLaneAutoScript) 提供；此仓库不包含其源码和安装包。伴随脚本来自本项目部署实践的重整。软件版本、截图和客户端变化可能影响识别；升级前备份、单项回归。

## 最新养成与服务器交接

- [无大型活动期的主力养成、练级与资源积累](docs/daily-growth-policy.md)
- [完整迁移范围、ALAS本机补丁、邮件与主管心跳交接](docs/server-handoff-20261021.md)

代码同步不等于账号/Gmail授权、模拟器或Codex心跳已迁移。服务器验收前保持刷图默认关闭；公开仓库不保存账号配置、密钥、截图、日志或邮件证据。
