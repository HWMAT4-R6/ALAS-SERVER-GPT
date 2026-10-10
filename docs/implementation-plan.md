# Windows ALAS 复现实施计划

用户已授权直接执行并发布 public 仓库，当前会话实施，不派子代理。

1. 写离线测试：PNG校验、worker结果边界、旧PT规则移除、暂停与守护重复启动。
2. 迁移配置与workers：路径、模型、价格表参数化，runtime隔离，无游戏点击与邮件发送。
3. 实现doctor/capture/observer/supervisor及PowerShell入口；暂停优先，离线不调用API，有限重启。
4. 写完整部署、运行、故障恢复、邮件与隐私说明；保留无法自动化的步骤。
5. 本地测试、语法检查、敏感内容扫描与文件清单；public仓库发布后验证远端文件。

本地测试不启动游戏、不收费调用API。实际服务器验收必须由部署现场完成。

执行记录：已完成运行入口、配置、worker迁移与四份流程手册。使用假ALAS子进程检验暂停，不启动真实游戏。发现旧toolkit Python不支持Path.unlink(missing_ok)，改为兼容删除。空进程列表必须解析JSON，否则字符串“[]”会被误判为已有进程；已加入回归测试。用户指定仓库ALAS-SERVER-GPT，通过GitHub插件发布，未申请额外凭据。
