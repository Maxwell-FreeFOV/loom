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

### 结构版本 1 → 2（Loom 0.4：项目语言）

schema 2 引入 `.kb.json` 的 `language` 字段（`en` / `zh-CN`）：新项目的模板、索引、报告和快照说明都按项目语言生成。

**脚本自动完成的改动：**

- `.kb.json`：补 `language: zh-CN`（schema 1 及更早的项目都是中文项目），写入 `schema: 2`，更新 `loom_version`。

迁移不重命名任何文件（包括 `10-Brief/项目简报.md`），不改动笔记和自定义模板。迁移后项目仍按中文处理；只有用新版 Loom 初始化、或手工把 `language` 改为 `en` 的项目才生成英文内容。新项目无论语言都使用 `10-Brief/project-brief.md` 这个文件名。

笔记模板从中文文件名改为稳定 ID（`session`、`decision`、`wiki`、`source`、`literature`、`experiment`、`output`、`design`、`adr`），中文名保留为别名；`loom.py template <名称>` 两种叫法都接受，项目 `90-Templates/` 中的覆盖不受影响。

**行为变化（不是结构变化）：会话尾巴不再自动并入上一次提交。** 0.2.1 到 0.3.x 中，hook 会把提交之后的对话尾巴 amend 进刚才的提交；0.4 起默认关闭。升级后，wrapup 提交之后继续对话，会话结束时 `40-Sessions/raw/` 下那份原始对话会留下未提交的改动，由下一次 wrapup 一并提交。想恢复旧行为，在 `.kb.json` 中加 `"auto_amend": true`（只建议在不推送、或只有自己使用的仓库里开启）。迁移时把这一点告诉用户。

决策的已关闭状态新增英文写法 `reviewed` / `superseded`，与 `已复盘` / `已推翻` 等价；历史笔记的状态字段不批量改写。
