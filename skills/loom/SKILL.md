---
name: loom
description: Loom 项目知识库：在一个项目文件夹里和 AI 协同推进想法、研究或工程，把讨论、资料、决策、产出物和对话历史沉淀为 Obsidian 知识库，让 AI 始终有完整上下文。用于：用 Loom 初始化新项目（"用 Loom 初始化这个项目"、"loom init"）；在 Loom 项目（根目录或上级目录有 .kb.json）中归档会话（总结、收尾、归档、wrapup）、导入资料或网页（ingest）、知识库体检（lint）、启用研究/工程/产出物模块、结构迁移、项目暂停或结束（close）。除初始化外，只在 Loom 项目中使用。
license: MIT
compatibility: 需要本机 Python 3 和 git。对话自动归档目前只支持 Claude Code 的会话记录。
metadata:
  version: "0.2.1"
---

# Loom

下文用两个记号：

- `$LOOM`：本 skill 的目录。在 Claude Code 中是 `${CLAUDE_SKILL_DIR}`；在其他工具中，就是本 SKILL.md 所在的目录。
- `$PY`：Python 3 命令。依次尝试 `py`、`python3`、`python`，用第一个能输出 `Python 3.x` 版本号的。

## 第一步：确认项目状态

在项目目录（或它的任意子目录）中运行：

```
$PY "$LOOM/scripts/loom.py" status
```

- 输出"当前目录不在 Loom 项目中"：只有当用户要初始化新项目时才继续，按 `references/init.md` 执行；否则就不要使用本 skill。
- 输出"需要迁移"：先按 `references/migrate.md` 处理，再做其他事。
- 其他情况：记下知识库根目录，以及输出中的提醒（未归档的会话、到期的决策），然后进入第二步。

## 第二步：按用户意图选择操作，并读取对应的说明

| 用户意图 | 操作 | 说明 |
|---|---|---|
| 把当前文件夹初始化为 Loom 项目 | init | `references/init.md` |
| 结束讨论、总结、归档、补归档 | wrapup | `references/wrapup.md` |
| 导入资料、存网页、消化文档 | ingest | `references/ingest.md` |
| 检查知识库 | lint | `references/lint.md` |
| 启用研究、工程、产出物等模块 | module | `references/module.md` |
| 项目结构需要迁移 | migrate | `references/migrate.md` |
| 项目暂停或结束 | close | `references/close.md` |

用户以 `/loom <操作>` 的形式调用时，参数就是操作名。用户只是在 Loom 项目中讨论问题时，不需要执行上面任何操作，只需按通用规则工作，讨论结束时提醒用户做 wrapup。

## 通用规则

在 Loom 项目中工作，必须遵守 `references/rules.md`：目录职责、上下文加载顺序、知识归属、写入规范、决策原则。如果会话开始时已经注入了"Loom 通用规则"（Claude Code 的 hook 会注入），就不必再读一遍。

## 脚本一览

以下脚本都在 `$LOOM/scripts/` 下，用 `$PY` 运行。它们会从当前目录向上查找 `.kb.json`，也可以加 `--root <目录>` 指定知识库根目录。

| 命令 | 作用 |
|---|---|
| `loom.py status` | 补导出对话；检查结构版本和 Loom 区块；列出提醒 |
| `loom.py init --name … --summary … [--modules …]` | 初始化项目 |
| `loom.py module list` / `module add <模块>` | 列出模块 / 启用模块 |
| `loom.py template <模板名>` | 输出应使用的模板路径 |
| `loom.py refresh-block` | 更新 AGENTS.md 中的 Loom 区块 |
| `loom.py migrate [--dry-run]` | 结构迁移 |
| `loom.py doctor` | 检查项目和本机环境 |
| `kb.py index` / `lint` / `unarchived` | 刷新索引 / 体检 / 列出未归档的会话 |
| `export_session.py --all` | 补导出本项目的全部 Claude Code 会话 |
| `sync_repos.py [--pull]` | 按 `repos.yaml` 克隆或更新代码库 |
