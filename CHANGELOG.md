# 更新记录

版本号遵循语义化版本：修订号用于修复；次版本号用于新增功能（兼容）；主版本号用于需要迁移的结构性变化（见 MIGRATIONS.md）。

## 0.1.0 · 2026-09-30

首个版本。

- 安装与升级工具 `tools/loom.py`，提供 install、add、upgrade、upgrade-all、doctor、modules 命令。升级基于 `git merge-file` 做三方合并。
- core 模块：
  - hub 文件：hot、index、timeline、roadmap、log；
  - 项目简报、资料清单；
  - 会话记录：原始对话、纪要、决策；
  - 脚本 `export_session.py`：导出对话，支持在子目录启动的会话；
  - 脚本 `kb.py`：生成索引、检查知识库、列出未归档的会话、在会话开始时注入上下文；
  - skill：`/wrapup` `/ingest` `/lint` `/close` `/loom-upgrade`。
- research 模块：文献卡、实验记录模板。
- engineering 模块：`repos.yaml`、`sync_repos.py`（克隆代码库，并为其注入对话导出 hook）、设计文档与 ADR 模板。
- outputs 模块：产出文档模板。
