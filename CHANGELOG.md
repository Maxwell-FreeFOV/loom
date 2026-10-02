# 更新记录

版本号遵循语义化版本。项目结构的变化用结构版本（schema）单独标记，迁移说明见 `skills/loom/references/migrate.md`。

## 0.3.1 · 2026-10-03

- 修复：frontmatter 的值以引号结尾时（例如标题 `采用"某方案"`），索引页等处显示时会丢掉最后一个引号。现在只去掉成对包住整个值的引号。

## 0.3.0 · 2026-10-01

新增：把知识库分享给合作者。对方拿到的是一个快照 zip，接触不到知识库本身；对方的更新通过 ingest 进入你的知识库。

- 新操作 `publish`（`references/publish.md`）和脚本 `snapshot.py`：
  - `snapshot.py plan` 预览要发布的文件（相对上一份快照标注新、改、未变）、被排除的笔记和需要留意的内容；`snapshot.py build` 生成 zip，默认写到 `50-Outputs/_exports/`。
  - 快照只包含当前的状态和结果。`40-Sessions/`（对话、纪要、决策记录）、timeline、log、index、inbox 和 `_exports/` 硬性排除，不能通过配置打开。
  - 发布范围写在 `.kb.json` 的可选键 `publish` 中（`include`、`exclude`、`strip_fields`、`strip_sections`），没有配置时使用默认值。单篇笔记可以用 frontmatter 的 `publish: false` 或 `publish: true` 覆盖。状态不是 `released` 的产出物默认不发布。
  - 清洗只作用于快照中的副本：删除指定的 frontmatter 字段和段落，把指向未发布笔记的链接改成纯文本。
  - 发布前由 AI 审阅新增和修改的笔记，用户确认后才生成。
- `ingest` 支持别人发布的快照：整个快照算一份资料；`snapshot.py open` 解压、和同一项目的上一份快照比较、生成同名的提取文本；只读新增和修改的文件；已有的内容不重复整合；和已有内容冲突时先问用户再写入。
- 项目结构版本不变，不需要迁移。

## 0.2.1 · 2026-09-30

- 修复：wrapup、init 等操作提交后，Claude 的最后一条回复会让刚提交的原始对话文件马上又显示为已修改。
  - 去掉 `Stop` hook（每轮回复后导出），只在会话结束时（`SessionEnd`）导出。会话中途由 `loom.py status` 补导出，提交时内容仍是最新的。
  - 会话结束时，如果最新提交就是提交过这个文件的那次提交，且未推送、没有 tag，就用 `git commit --amend --only` 把提交之后的对话尾巴并入它；否则留给下一次提交。
  - SessionStart 兜底：最近 3 天内没触发 SessionEnd 的会话（崩溃、直接关窗口），在下次会话开始时补导出并做同样的收尾。
  - `deploy.py --claude-hooks` 会清理旧版写入的 `Stop` hook。

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
