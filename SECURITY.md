# Security policy

## Supported versions

当前安全维护基线如下：

| Version | Status |
| --- | --- |
| 0.2.x | 接受阻断性兼容与安全修复 |
| 0.1.x | 不再主动维护 |

`v0.2.0` tag 永久保持不变。必要修复进入 `release/0.2`，并以新的补丁版本发布。

## Reporting a vulnerability

请不要在公开 issue 中披露尚未修复的漏洞、凭据、真实题库或个人数据。应通过 GitHub
仓库的 **Security → Report a vulnerability** 私密报告入口提交以下信息：

- 受影响的版本和平台；
- 最小复现步骤；
- 预期与实际安全边界；
- 可能受影响的数据或操作；
- 已知缓解措施。

若仓库尚未启用私密漏洞报告，请仅联系仓库所有者，并在安全沟通渠道建立后再发送复现
材料。项目不在本文中发布个人邮箱。

维护者将确认报告、评估影响并协调修复与披露时间。修复不会通过移动既有 tag 分发。

## Security boundaries

- `questions/` Markdown 与受管逻辑资产是权威数据；SQLite 仅为可重建索引。
- 所有写入先 dry-run，并使用事务、修订检查和仓库级锁。
- 本地资源必须受题库 `assets` 边界约束；外部资源只读并产生警告。
- 自定义 Jinja 模板属于用户需要审查的可信代码边界。
- MCP 是本地 STDIO 接口，不提供远程网络服务；写入使用 prepare/commit 两阶段操作。
- qbank 不存储云端账户、模型 API key 或在线考试用户数据。

完整失败行为和限制见
[兼容性策略](docs/compatibility-policy.md)与
[0.2.0 已知限制](docs/known-limitations-0.2.0.md)。
