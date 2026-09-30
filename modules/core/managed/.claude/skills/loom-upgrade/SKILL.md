---
name: loom-upgrade
description: 把本项目使用的 Loom 工具包升级到新版本：拉取 .loom，三方合并托管文件，评估种子文件模板的变化，并执行迁移说明。用户说"升级 Loom"、"更新模板"、"loom-upgrade"时使用。
---

# /loom-upgrade · 升级 Loom

`$PY` 指 `.kb.json` 中 `python` 字段的值。

1. **确认工作区干净**：`git status --porcelain` 的输出应为空。如果不为空，先请用户提交或暂存改动。
2. **拉取新版本**：运行 `git -C .loom pull --ff-only`。如果用户要升级到指定版本，改为运行 `git -C .loom fetch --tags`，并在第 4 步加上 `--to <tag>`。
   - 如果 `.loom/` 不存在（例如换了一台机器），先把 Loom 重新 clone 到 `.loom/`。
3. **预览**：
   - 运行 `$PY .loom/tools/loom.py upgrade --dry-run`；
   - 查看 `git -C .loom log --oneline <旧 commit>..HEAD`（旧 commit 记录在 `.kb.json` 的 `loom.commit` 中）；
   - 阅读 `.loom/CHANGELOG.md` 中的新条目。

   然后向用户概述这次升级带来了哪些变化。
4. **执行**：运行 `$PY .loom/tools/loom.py upgrade`，按报告逐项处理：
   - **冲突文件**：打开文件，处理 `<<<<<<<` 标记。原则是保留项目的本地定制，同时吸收新版的修复；拿不准的问用户。
   - **种子文件模板有变化**：报告中给出了新旧模板的差异。判断这些变化是否需要同步到本项目的 CLAUDE.md、hot.md 等文件，提出修改建议，用户同意后再改。
   - **`.loom-new` 文件**：新模板与项目中的同名文件并存。合并后删除 `.loom-new`。
   - **迁移说明**：阅读 `.loom/MIGRATIONS.md` 中介于新旧版本之间的条目，逐条执行（例如目录改名）。执行前先告诉用户要做什么。
5. **验证**：依次运行 `$PY .loom/tools/loom.py doctor`、`$PY scripts/kb.py index`、`$PY scripts/kb.py lint`。
6. **提交**：用 `git diff --stat` 向用户展示改动，确认后提交 `loom: 升级到 vX.Y.Z`。
   - 如果用户对结果不满意，可以用 `git checkout . && git clean -fd` 回滚，`.kb.json` 也会一起恢复。注意 `git clean` 会删除新增的文件，执行前要先向用户说明。
7. 如果报告中提到 `.claude/settings.json` 有变化，提醒用户重启 Claude 会话，新配置才会生效。
