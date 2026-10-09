# Security Policy

[中文](#中文)

## English

### Supported versions

| Version | Supported |
|---|---|
| 0.4.x | ✅ |
| < 0.4 | ❌ |

### Reporting a vulnerability

Please report security issues through **GitHub Private Vulnerability Reporting**:
`<GITHUB-REPO-URL>/security` (the repository owner needs to enable it in the repository settings —
if the page is unavailable, open a regular issue that asks for a private contact, without any detail).

When reporting:

- **Do not attach private knowledge-base content** — raw conversations, session notes, or unpublished
  material. Describe the issue with a minimal, sanitized reproduction.
- Include your Loom version (`loom.py doctor` output), platform, and Python version (3.12+ required).

Good examples of what to report: ways to bypass the publish exclusions, path traversal or resource
abuse in snapshot import, leaking another project's conversations during export.

## 中文

### 支持的版本

| 版本 | 支持 |
|---|---|
| 0.4.x | ✅ |
| < 0.4 | ❌ |

### 报告安全问题

请通过 **GitHub Private Vulnerability Reporting** 报告：`<GITHUB-REPO-URL>/security`
（需要仓库所有者在仓库设置中开启；如果页面不可用，可以开一个普通 issue 询问私下联系方式，但不要包含任何细节）。

报告时请注意：

- **不要附带私密知识库内容**——原始对话、会话纪要或未公开的资料。请用最小的、已脱敏的复现来描述问题。
- 附上 Loom 版本（`loom.py doctor` 的输出）、平台和 Python 版本（要求 3.12+）。

适合报告的问题举例：绕过发布排除规则的方法、快照导入中的路径穿越或资源滥用、导出时混入其他项目的对话。
