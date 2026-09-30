# module：启用模块

项目可以逐步演化，例如从一个想法发展成研究项目，再发展成工程项目。相应的模块随时都可以追加启用。

| 模块 | 作用 |
|---|---|
| core | 必装：hub、项目简报、资料、会话记录 |
| research | 研究调研：文献卡写在 `30-Wiki/literature/`，实验记录写在 `30-Wiki/experiments/` |
| engineering | 工程开发：代码库放在 `repos/`，在 `repos.yaml` 中登记，用 `sync_repos.py` 管理；提供设计文档和 ADR 模板 |
| outputs | 产出物：设计文档和报告放在 `50-Outputs/`，带版本、状态和来源追溯 |

## 步骤

1. 运行 `$PY "$LOOM/scripts/loom.py" module list`，确认模块名。

2. 运行 `$PY "$LOOM/scripts/loom.py" module add <模块> [...]`，阅读输出的报告，其中会列出：
   - 新建了哪些文件；
   - 合并了哪些文件（例如 `.gitignore`、`.obsidian/app.json`）；
   - 是否生成了 `.loom-new` 文件。如果有，把内容合并进原文件，然后删掉 `.loom-new`。

3. 按模块做后续工作：
   - engineering：在 `repos.yaml` 中登记代码库，运行 `$PY "$LOOM/scripts/sync_repos.py"`，并在 timeline 中记录各代码库当前的 commit。
   - research 和 outputs：不需要额外操作，相关目录在第一次写入时才创建。

4. 在 `00-Hub/log.md` 中追加一行，在 timeline 中记录"启用 X 模块"，然后提交：`loom: 启用 <模块>`。
