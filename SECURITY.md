# Security policy

## Supported versions

当前支持范围如下：

| Version | Support status |
| --- | --- |
| 0.3.0-beta.x | 当前开发线；接受安全、数据安全和阻断性兼容修复 |
| 0.2.x | 有限维护；核心 CLI 与数据边界接受安全和阻断性兼容修复，Qt 桌面端作为 QBank Studio Legacy 仅处理安全、数据损坏或严重兼容问题 |
| 0.1.x | 不提供支持或补丁回移 |

已发布版本通过新的补丁版本接收修复；维护者不会移动或重建已有版本 tag。

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
