# Loom 通用规则

> 本文件属于 loom skill，适用于所有 Loom 项目。项目特有的约定写在项目的 `AGENTS.md` 里（Loom 区块之外），与本文件冲突时以项目约定为准。
>
> 下文路径都相对于**知识库根目录**（`.kb.json` 所在的目录）。如果会话是在子目录（例如 `repos/<名称>/`）中启动的，先向上找到 `.kb.json` 确定根目录，再按这些路径读写。
>
> `$LOOM` 指 loom skill 的目录，`$PY` 指 Python 3 命令（依次尝试 `py`、`python3`、`python`），详见 SKILL.md。

## 1. 这是什么

这个文件夹是一个 Loom 项目知识库，同时也是一个 Obsidian vault 和一个 git 仓库。它记录一个项目从想法到落地的全过程：讨论、调研资料、决策、产出物和全部对话历史，让 AI 在任何一次会话里都能拿到完整的上下文。项目里只放数据；脚本、模板和操作流程都由全局安装的 loom skill 提供。

## 2. 目录与职责

| 目录 | 内容 | 模块 | AI 权限 |
|---|---|---|---|
| `00-Hub/` | `hot.md`：快速上下文<br>`index.md`：全库索引（由脚本生成）<br>`timeline.md`：里程碑<br>`roadmap.md`：计划与待办<br>`log.md`：操作日志 | core | 可读写（`index.md` 除外） |
| `10-Brief/` | 项目简报：问题定义、目标、范围、约束、成功标准 | core | 修改前先征得用户同意 |
| `20-Sources/` | `inbox/`：待处理资料<br>`raw/`：原始资料<br>`cards/`：资料卡<br>`sources-index.md`：资料清单 | core | `raw/` 只增不改 |
| `30-Wiki/` | AI 维护的知识页：概念、调研结论、方案对比等。research 模块另有 `literature/`（文献卡）和 `experiments/`（实验记录） | core / research | 可读写 |
| `40-Sessions/` | `raw/`：原始对话（自动导出）<br>`notes/`：会话纪要<br>`decisions/`：决策记录 | core | `raw/` 只读 |
| `50-Outputs/` | 给别人看的产出物，每份一个子目录；`_exports/` 存放导出的 PDF、DOCX 和知识库快照 | outputs | 可读写 |
| `repos/`、`repos.yaml` | 关联的代码库。每个都是独立的 git 仓库，外层仓库不跟踪 | engineering | 遵循各代码库自己的规范 |
| `90-Templates/` | 可选。放在这里的同名模板会覆盖 Loom 默认模板 | — | 按用户意愿 |
| `AGENTS.md`、`CLAUDE.md` | 项目指令。`CLAUDE.md` 只负责引用 `AGENTS.md`；`AGENTS.md` 中有一段由 Loom 维护的区块 | — | 区块之外可以修改 |

- 目录在第一次需要时再创建，不必预先建空目录。
- 本项目启用了哪些模块，见 `.kb.json` 的 `modules`。如果要用到未启用模块的目录（例如写第一份设计文档），先建议用户启用对应的模块。

## 3. 上下文加载顺序

1. 先读 `00-Hub/hot.md`。在 Claude Code 中，会话开始时 hook 已经注入了 hot.md 和提醒，可以跳过这一步。
2. 需要项目全貌时，读 `10-Brief/`、`00-Hub/roadmap.md` 和 `00-Hub/timeline.md`。
3. 查历史讨论时，先看 `00-Hub/index.md`，再 grep `40-Sessions/notes/` 和 `40-Sessions/decisions/` 的 frontmatter（`title`、`tags`）。**只有需要原话时，才去翻 `40-Sessions/raw/`。**
4. 查领域知识时，先读 `30-Wiki/` 中的相关页面，再追溯到它引用的资料卡或原始资料。
5. 写代码时，先读该代码库自己的 `CLAUDE.md` 或 `AGENTS.md` 和相关文档，需要时再回到知识库查设计文档和决策。

不要一次性读取整个库。如果库里的信息和用户当下说的话矛盾，以用户为准，并提醒用户更新对应的文件。

## 4. 知识归属：每样东西只有一个家

| 内容 | 放在 | 说明 |
|---|---|---|
| 事实、理解、调研结论 | `30-Wiki/` | 按主题组织，持续更新；每个论断都注明来源 |
| 讨论过程、当时的想法 | `40-Sessions/notes/` | 按会话组织，写完后基本不再修改 |
| 选择及其理由 | `40-Sessions/decisions/` | 一个决定一份记录，带复盘日期 |
| 给别人看的成品 | `50-Outputs/` | 有版本和状态，把上面三类内容作为依据引用 |
| 原始材料 | `20-Sources/raw/` | 不可修改 |
| 接下来要做什么 | `00-Hub/roadmap.md` | 完成后移到 timeline |
| 项目怎么走到今天 | `00-Hub/timeline.md` | 只记里程碑 |

同一条结论不要在多处重复展开：在它的"家"里写完整，其他地方用 `[[链接]]` 引用。

## 5. 写入规范

- **文件名**：中英文都可以，除空格外不含其他特殊符号。会话纪要命名为 `YYYY-MM-DD_主题.md`，决策记录命名为 `DR-YYYY-NNN_主题.md`。
- **frontmatter**：每篇笔记都必须有，至少包含以下字段：
  ```yaml
  ---
  type: brief | wiki | source | literature | experiment | session | decision | output | adr | hub
  title: 标题
  created: YYYY-MM-DD
  updated: YYYY-MM-DD
  tags: []
  ---
  ```
  列表字段一律写成单行形式，例如 `tags: [a, b]`、`sources: ["[[笔记]]"]`。
- **链接**：引用库内笔记用 `[[笔记名]]`。
- **模板**：新建笔记时，先用 `$PY "$LOOM/scripts/loom.py" template <模板名>` 找到应该使用的模板。可用的模板有：会话纪要、决策记录、wiki页、资料卡、文献卡、实验记录、产出文档、设计文档、ADR。
- **日志**：结构性写入（新建笔记或大幅修改）之后，在 `00-Hub/log.md` 的注释行下方追加一行：`- YYYY-MM-DD HH:MM · 动作 · [[目标]]`。
- **索引**：新增或删除笔记之后，运行 `$PY "$LOOM/scripts/kb.py" index` 刷新索引。

## 6. 资料

- 新资料先放进 `20-Sources/inbox/`，然后用 loom 的 ingest 处理：原件存入 `raw/`，登记到 `sources-index.md`，重要资料写资料卡，最后把新知识整合进 wiki。
- `raw/` 下的原件只增不改。PDF 等二进制文件旁边可以放一个同名的 `.md` 提取文本，方便检索。
- 网络调研中值得留存的网页，保存为 `raw/` 下的 Markdown，frontmatter 中写明 `url` 和抓取日期，然后登记。
- 资料很多时分批消化，在 `sources-index.md` 的状态列中标记为"待读"、"已编目"或"已消化"。
- 引用外部资料要注明出处。自己的推断要标注为推断，不要把推断写成资料的原话。
- 合作者发来的知识库快照（zip 中有 `loom-snapshot.json`）也是资料，同样用 ingest 处理：已有的内容不重复整合，和已有内容冲突时先问用户。

## 7. 对话记录、时间线与路线图

- 原始对话会自动导出到 `40-Sessions/raw/`：
  - 在 Claude Code 中，由 hook 在会话结束时导出；如果这次会话中途已经提交过它，提交之后的对话尾巴会自动并入那次提交（仅当那次提交还是最新提交、未推送、没有 tag），工作区保持干净；
  - 在任何工具中，执行 loom 操作时都会先运行 `loom.py status`，补导出之前遗漏的会话。
  
  目前只支持 Claude Code 的会话记录。在其他工具中讨论时，靠会话纪要来留存内容。
- 一次有实质内容的讨论结束时，提醒用户用 loom 做 wrapup：写会话纪要，必要时写决策记录，并更新 wiki、timeline、roadmap 和 hot.md。
- timeline 的格式是 `- YYYY-MM-DD · 事件 · [[链接]]`。只记里程碑，包括：重要决定、阶段切换、产出物发布、代码里程碑（附 commit）、关键发现。
- roadmap 用 `- [ ]` 列出接下来的任务和里程碑。已完成的里程碑移到 timeline。

## 8. 讨论与决策

- 先澄清问题本身，确认真正要决定的是什么，再展开分析。
- 讨论决策时，给出明确建议，同时写出最强的反方论证和事前验尸（pre-mortem）的结论。
- 区分可逆决策和不可逆决策：可逆的快速决定，不可逆的慢慢想。
- 对照项目简报中的目标和约束做检验，发现冲突时直接指出。
- 不迎合用户：发现逻辑漏洞、信息缺口或情绪化判断时，直接说出来。
- 决策记录中 `review_date` 的默认值：可逆决策为 1 个月后，不可逆决策为 3 个月后。

## 9. 产出物（outputs 模块）

- 每份产出物放在 `50-Outputs/<文档名>/` 下，以 Markdown 作为源文件，使用"产出文档"模板（设计文档使用"设计文档"模板）。
- frontmatter 中的字段：
  - `status`：`draft`、`review` 或 `released`；
  - `version`、`audience`；
  - `sources`、`decisions`、`wiki`：分别链接依据的纪要、决策和知识页。
  
  决策记录的 `outputs` 字段反向链接到产出物。
- 版本由 git 管理，不要用 `v2_final.md` 这类文件名区分版本。正式发布时按以下步骤操作：
  1. 更新 `version`，把 `status` 改为 `released`；
  2. 在文档的版本历史中加一行；
  3. 提交后打 tag，格式为 `<文档名>/v<版本>`；
  4. 在 timeline 中记录。
- 导出的 PDF、DOCX 放在 `50-Outputs/_exports/`，文件名带上版本号。
- 把知识库分享给别人时，不要给出知识库本身或它的 git 仓库，用 loom 的 publish 发布快照：
  - 快照只包含当前的状态和结果。`40-Sessions/`（对话、纪要、决策记录）、timeline 和 log 永远不会进入快照。
  - 发布范围写在 `.kb.json` 的 `publish` 中；单篇笔记可以在 frontmatter 中写 `publish: false` 排除。
  - 发布前由 AI 审阅、用户确认。

## 10. 代码库（engineering 模块）

- 代码库放在 `repos/<名称>/`，并在 `repos.yaml` 中登记。每个代码库都是独立的 git 仓库，外层知识库不跟踪其内容。
- 修改 `repos.yaml` 后，运行 `$PY "$LOOM/scripts/sync_repos.py"`：它会克隆缺失的代码库，并显示各库的状态。加 `--pull` 参数时还会拉取更新。
- 有两种启动方式：
  - 在知识库根目录启动：用于讨论、调研、写文档；
  - 在 `repos/<名称>/` 中启动：用于写代码，此时 git 操作针对的是该代码库。读写知识库时注意使用根目录路径。在 Claude Code 中，这类会话同样会被导出到知识库。
- 代码层面的规范、与实现强绑定的 ADR，放在代码库自己的文档里（如 `docs/adr/`）。跨仓库的、业务层面的决策，放在知识库的 `40-Sessions/decisions/` 中，并在 `commits` 字段中记录相关的 commit hash。
- 代码里程碑（首个可运行版本、发布、重大重构）记入 timeline，附上仓库名和 commit。

## 11. git

- 知识库根目录是一个 git 仓库，`repos/` 不纳入其中。
- wrapup、ingest、publish、lint、close、migrate 完成后各提交一次，提交信息以动作开头，例如 `wrapup: 主题`。其他时候只在用户要求时提交。
- 资料默认全部进入本地仓库。某些文件不想提交时，由用户修改 `.gitignore`。

## 12. Loom 本身

- loom skill 全局安装一次，所有项目共用，项目里不保存脚本和流程。
- 升级 loom skill 后，下一次会话即生效。
- `loom.py status` 如果报告"需要迁移"，按 `references/migrate.md` 处理；如果报告"Loom 区块不是当前版本"，运行 `loom.py refresh-block`。
- 不要修改 `AGENTS.md` 中 `<!-- loom:begin -->` 与 `<!-- loom:end -->` 之间的内容。
