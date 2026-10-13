# 两小时报告、费用与隐私

**已实现本地发送器（可选启用）**：`src/mailer.py`（纯标准库 QQ SMTP）+ `src/reporter.py`（两小时槽位、证据汇总、收据）。默认 `mail_send_enabled=false` 不发送；Codex/Gmail 路径不再需要，也不能复制本机 Gmail 授权、cookie 或 token——QQ 授权码只进服务器用户环境。

报告槽位以Asia/Shanghai固定时区（服务器时区必须一致），按 `mail_interval_hours`（默认2）对齐整点，例如16/18/20/22点；槽位开始后 `mail_catchup_minutes`（默认30）分钟内发送，错过即记 `report_window_missed` 且不补发。不是让GPT两小时逐次续训，ALAS自己负责训练调度。

流程：读取短状态/日志增量→截图核验→处理已完成委托→更新已核验事实→Emailer草稿→主管核对日期/数字/措辞→查询已发及槽位收据→发送→仅成功ID写入本地收据。未发/失败不记录SENT。报告必须区分已完成、已领取、估计、待办和未知。

推荐事实文件 `runtime/verified-report.json`：

```json
{
  "report_at": "当前北京时间",
  "verified": [{"task": "困难", "result": "日志三次实际结束", "evidence": "原图或日志路径与时间"}],
  "unknown": ["未实测心情"],
  "pending": ["大世界解锁"],
  "historical_only": ["过去活动余额，不可当现在可兑换"]
}
```

## 发送器与收据

- 启动：`python -m src.runtime reporter`（或 `scripts/start.ps1 -Mode reporter`）；PAUSE 时与其他进程一样退出。
- 手动检查：`python -m src.runtime report --dry-run` 只生成 `runtime/report-preview.txt`，不发送（发送开关关闭时也可用，不消耗事件增量）；确认真实投递用 `report --force`（槽位记为 `manual-*`）。
- 每个槽位只尝试一次（进程崩溃也只可能漏发、不会重发）；只有 SMTP 确认成功才写 `SENT` 收据（`runtime/mail-receipts.jsonl`），失败写只含错误类型的 `FAILED` 收据，同槽位不重发。
- 授权码读取顺序：环境变量 `QQ_SMTP_AUTH` → Windows 用户注册表（与 DeepSeek key 同模式）→ `mail_auth_file` 指定的仓库外文件。授权码不进仓库、日志、事件与收据。
- `mail_from`/`mail_to` 在 `config/settings.json`（已被 .gitignore 排除）填写；正文与事件只含本地证据摘要。

## 额度控制

- 常规轮询用本地程序；默认每分钟连接探测，每小时一次截图，离线不调用模型。
- 图片尽量局部；本地摘要只保留变化与必要证据；结构拒绝后主管接管，不反复问同一张图。
- Imager观察、Emailer草稿、Assembler诊断；GPT处理决策与例外，保持用户选择的模型，不自动切Astra或派代理。
- `runtime/usage.jsonl`逐次保留开始、usage、估算或未知失败费用。价格配置核验后使用，准备开发成本与日常运行单列。
- `daily_cost_limit_usd`（默认 null=关闭）：当日估算费用超限时只记录事件并（邮件开启时）当天提醒一次，不阻断 ALAS 与各 worker；估算不是账单。
- 旧797调用包含主线和PPT等不同任务，不能直接作为新系统同任务节省率分母。比较需同账号、同任务范围、完成率、实领PT、有效在线时间与接管次数。

## 发布边界

仓库只发布伴随代码、脱敏示例、流程和测试。`.gitignore`排除运行目录、截图、私密配置、密钥、日志和打包文件；仍需检查Git跟踪列表。报告收件地址只在私密运行配置/主管设置里填写。

环境变量密钥也有本机访问风险，按运行用户权限保护。曾公开到聊天或日志的密钥应更换，不能继续当作迁移默认。API截图上传到配置的服务前核验目的地和内容，不包含账号登录/付费页面。
