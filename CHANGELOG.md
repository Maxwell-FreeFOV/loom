# 更新记录

版本号遵循语义化版本。项目结构的变化用结构版本（schema）单独标记，迁移说明见 `skills/loom/references/migrate.md`。

## 0.2.0 · 2026-09-30

**架构调整（不兼容）**：Loom 由"安装到每个项目中"改为"全局安装的 Agent Skill"。项目中只保存数据。

- 整个工具只有一个 skill，名为 `loom`，符合 Agent Skills 规范。Claude Code、Codex、Gemini CLI、Cursor 等工具都可以使用。
  - `SKILL.md` 负责按用户意图分派操作；各操作的具体说明放在 `references/` 下。
  - 支持的操作：init、wrapup、ingest、lint、module、migrate、close。
- 新增 Claude Code 增强层：skill 目录中的 `.claude-plugin/plugin.json` 和 `hooks/hooks.json`，使该目录同时作为插件 `loom@skills-dir` 加载，从而在会话开始时注入上下文、在会话结束时导出对话。其他工具会忽略这些文件。
- hook 由 `run.sh` 启动：先向上查找 `.kb.json`，不在 Loom 项目中时立即退出。
- 所有脚本都从当前目录向上定位知识库。在 `repos/<名称>/` 中启动的会话，对话也会导出到知识库，不再需要向代码库注入配置。
- 每个 Loom 操作都先运行 `loom.py status`：补导出对话，检查结构版本和 Loom 区块。
- 项目指令改为 `AGENTS.md`（包含一段由 Loom 维护的区块），`CLAUDE.md` 只引用它。
- 模板默认使用 skill 自带的版本；项目的 `90-Templates/` 中如果有同名文件，则优先使用项目的。
- 新增 `tools/deploy.py`：从指定版本导出 skill，部署到 `~/.agents/skills/loom`，并链接到各工具的 skills 目录。支持回滚，也支持兜底方式 `--claude-hooks`。
- 新增结构版本 1，以及从 0.1 迁移的功能（`loom.py migrate`）。
- 删除：`.loom` clone 流程、`INIT.md`、`UPGRADE.md`、基于 `git merge-file` 的项目级升级机制。

## 0.1.0 · 2026-09-30

首个版本：每个项目把 Loom clone 到 `.loom/`，再把脚本、skill、hook 和规则复制进项目；升级时用 `git merge-file` 做三方合并。
