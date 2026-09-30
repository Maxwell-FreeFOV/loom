# migrate：项目结构迁移

loom skill 是全局共用的。新版本改变了知识库的结构时，每个项目都需要迁移一次。当 `loom.py status` 报告"需要迁移"时，按下面的步骤执行。

## 步骤

1. 确认 git 工作区干净，即 `git status --porcelain` 没有输出。如果有输出，先请用户提交。
2. 预览：运行 `$PY "$LOOM/scripts/loom.py" migrate --dry-run`，再结合下面的"各版本说明"，向用户解释将要做哪些改动。
3. 执行：运行 `$PY "$LOOM/scripts/loom.py" migrate`，然后逐项处理输出中的提示。
4. 验证：依次运行 `loom.py status`、`kb.py index`、`kb.py lint`。
5. 用 `git diff --stat` 向用户展示改动。用户确认后，提交 `loom: 迁移项目结构到版本 N`。
   - 如果用户不满意，可以用 `git checkout . && git clean -fd` 回滚。
   - `git clean` 会删除新增的文件，执行前要先向用户说明。

## 各版本说明

### 结构版本 0 → 1（Loom 0.1 → 0.2）

Loom 0.1 会把脚本、skill、hook 和规则复制到每个项目中。从 0.2 开始，这些全部由全局的 loom skill 提供，项目里只保留数据。

**脚本自动完成的改动：**

- 删除以下文件：
  - `scripts/` 下的 `export_session.py`、`kb.py`、`sync_repos.py`；
  - `LOOM-RULES.md`；
  - `.claude/skills/` 下由 Loom 0.1 提供的 skill。
- 去掉 Loom 0.1 添加的 hook：
  - `.claude/settings.json` 中的 hook；
  - `repos/*/.claude/settings.local.json` 中注入的 hook。去掉后如果文件为空，就删除该文件，并同时删除该代码库 `.git/info/exclude` 中对应的那一行。
- 删除 `90-Templates/` 中与 Loom 默认模板完全相同的文件。修改过的模板会保留，继续作为本项目的覆盖版本。
- 把 `CLAUDE.md` 的内容移到 `AGENTS.md`：去掉 `@LOOM-RULES.md` 和 0.1 附带的说明，加入 Loom 区块。之后 `CLAUDE.md` 只保留一行 `@AGENTS.md`。
- `.kb.json`：去掉 `python` 和 `loom` 两个字段，写入 `schema: 1`。

**需要人工处理的事项：**

- `.loom/` 目录已经不再需要。经用户确认后删除它，同时删除 `.gitignore` 中 `.loom/` 那一行。
- 检查 `AGENTS.md` 的内容是否通顺。必要时，把"项目特有约定"改写成与工具无关的写法，例如把 `/wrapup` 改为"用 loom 做 wrapup"。
- 在 Claude Code 中：重启会话，确认 loom 增强层已经加载（能看到 SessionStart 注入的上下文）。
