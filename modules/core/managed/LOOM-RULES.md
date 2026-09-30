# Loom 通用规则

> 本文件由 Loom 托管，升级时会被更新，**请不要在项目里修改**。项目特有的约定写在 `CLAUDE.md`，与本文件冲突时以 `CLAUDE.md` 为准。
>
> 本文件中的路径都相对于**知识库根目录**（`.kb.json` 所在的目录）。如果会话是在子目录（例如 `repos/<名称>/`）里启动的，先向上找到 `.kb.json` 确定根目录，再按下面的路径读写。
>
> 下文的 `$PY` 指 `.kb.json` 中 `python` 字段的值（例如 `py` 或 `python3`）。

## 1. 这是什么

这个文件夹是一个由 Loom 管理的项目知识库，它同时是一个 Obsidian vault 和一个 git 仓库，记录一个项目从想法到落地的全过程：讨论、调研资料、决策、产出物，以及全部对话历史。有了它，AI 在任何一次会话里都能拿到完整的上下文。

## 2. 目录与职责

| 目录 | 内容 | 模块 | AI 权限 |
|---|---|---|---|
| `00-Hub/` | `hot.md` 快速上下文；`index.md` 全库索引（由脚本生成）；`timeline.md` 里程碑；`roadmap.md` 计划与待办；`log.md` 操作日志 | core | 可读写，`index.md` 除外 |
| `10-Brief/` | 项目简报：问题定义、目标、范围、约束、成功标准 | core | 修改前先征得用户同意 |
| `20-Sources/` | `inbox/` 待处理资料；`raw/` 原始资料；`cards/` 资料卡；`sources-index.md` 资料清单 | core | `raw/` 只增不改 |
| `30-Wiki/` | AI 维护的知识页：概念、调研结论、方案对比等。research 模块另有 `literature/`（文献卡）和 `experiments/`（实验记录） | core / research | 可读写 |
| `40-Sessions/` | `raw/` 原始对话（由 hook 自动导出）；`notes/` 会话纪要；`decisions/` 决策记录 | core | `raw/` 只读 |
| `50-Outputs/` | 给别人看的产出物，每份一个子目录；`_exports/` 存放导出的 PDF、DOCX | outputs | 可读写 |
| `repos/`、`repos.yaml` | 关联的代码库，各自是独立的 git 仓库，外层仓库不跟踪 | engineering | 遵循各代码库自己的规范 |
| `90-Templates/` | 笔记模板 | core | 只读（Loom 托管） |
| `scripts/` | 自动化脚本 | core | 只读（Loom 托管） |
| `.loom/` | Loom 工具包本身 | — | 只读 |

- 目录在第一次需要时再创建，不必预先建空目录。
- 本项目启用了哪些模块，见 `.kb.json` 的 `modules`。用到未启用模块的目录时（例如要写第一份设计文档），先建议用户启用对应模块。

## 3. 上下文加载顺序

1. 会话开始时，SessionStart hook 已经注入了项目状态、`hot.md` 和提醒（未归档的会话、到期的决策）。如果没有看到这些内容，就自己读 `00-Hub/hot.md`。
2. 需要项目全貌时，读 `10-Brief/`、`00-Hub/roadmap.md`、`00-Hub/timeline.md`。
3. 查历史讨论：先看 `00-Hub/index.md`，再 grep `40-Sessions/notes/` 和 `40-Sessions/decisions/` 的 frontmatter（`title`、`tags`）。**只有需要原话时才去读 `40-Sessions/raw/`。**
4. 查领域知识：先读 `30-Wiki/` 的相关页面，再追溯到它引用的资料卡或原始资料。
5. 写代码时：先读该代码库自己的 `CLAUDE.md` 和文档，需要时再回到知识库查设计文档和决策。

不要一次性读取整个库。库里的信息如果和用户当下说的话矛盾，以用户为准，并提醒用户更新对应的文件。

## 4. 知识归属：每样东西只有一个家

| 内容 | 放在 | 说明 |
|---|---|---|
| 事实、理解、调研结论 | `30-Wiki/` | 按主题组织，持续更新；每个论断都注明来源 |
| 讨论过程、当时的想法 | `40-Sessions/notes/` | 按会话组织，写完后基本不再修改 |
| 选择及其理由 | `40-Sessions/decisions/` | 一个决定一份记录，带复盘日期 |
| 给别人看的成品 | `50-Outputs/` | 有版本和状态，引用上面三类内容作为依据 |
| 原始材料 | `20-Sources/raw/` | 不可修改 |
| 接下来要做什么 | `00-Hub/roadmap.md` | 完成后移入 timeline |
| 项目怎么走到今天 | `00-Hub/timeline.md` | 只记里程碑 |

同一条结论不要在多处重复展开：在它的"家"里写完整，其他地方用 `[[链接]]` 引用。

## 5. 写入规范

- **文件名**：中英文均可，除空格外不含其他特殊符号。会话纪要命名为 `YYYY-MM-DD_主题.md`，决策记录命名为 `DR-YYYY-NNN_主题.md`。
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
- **模板**：新建笔记时优先使用 `90-Templates/` 中的模板。
- **日志**：每次结构性写入（新建笔记或大幅修改）后，在 `00-Hub/log.md` 的注释行下方追加一行：`- YYYY-MM-DD HH:MM · 动作 · [[目标]]`。
- **索引**：新增或删除笔记后，运行 `$PY scripts/kb.py index` 刷新索引。

## 6. 资料

- 新资料先放进 `20-Sources/inbox/`，再用 `/ingest` 处理：原件存入 `raw/`，登记到 `sources-index.md`，重要的写资料卡，最后把新知识整合进 wiki。
- `raw/` 下的原件只增不改。PDF 等二进制文件旁边可以放一个同名的 `.md` 提取文本，方便检索。
- 网络调研时，值得留存的网页保存为 `raw/` 下的 Markdown，frontmatter 中写明 `url` 和抓取日期，然后登记。
- 资料很多时分批消化：`sources-index.md` 的状态列标记为"待读 / 已编目 / 已消化"。
- 引用外部资料要注明出处。自己的推断要标注为推断，不要把推断写成资料里的原话。

## 7. 对话记录、时间线与路线图

- 原始对话由 hook 自动导出到 `40-Sessions/raw/`，不需要手动处理。
- 每次有实质内容的讨论结束时，提醒用户运行 `/wrapup`：写会话纪要，必要时写决策记录，并更新 wiki、timeline、roadmap 和 hot.md。
- timeline 的格式为 `- YYYY-MM-DD · 事件 · [[链接]]`，只记里程碑：重要决定、阶段切换、产出物发布、代码里程碑（附 commit）、关键发现。
- roadmap 用 `- [ ]` 列出接下来的任务和里程碑。已完成的里程碑移入 timeline。

## 8. 讨论与决策

- 先澄清问题本身，确认真正要决定的是什么，再展开分析。
- 讨论决策时给出明确建议，同时写出最强的反方论证，以及事前验尸（pre-mortem）的结论。
- 区分可逆决策和不可逆决策：可逆的快速决定，不可逆的慢慢想。
- 对照项目简报中的目标和约束进行检验。发现冲突时直接指出。
- 不迎合用户：发现逻辑漏洞、信息缺口或情绪化判断时直接说出来。
- 决策记录的 `review_date` 默认值：可逆决策为 1 个月后，不可逆决策为 3 个月后。

## 9. 产出物（outputs 模块）

- 每份产出物放在 `50-Outputs/<文档名>/` 下，以 Markdown 为源文件，模板为 `90-Templates/产出文档.md`（engineering 模块另有 `设计文档.md`）。
- frontmatter 中的 `status` 取值为 `draft`、`review` 或 `released`，另外需要填写 `version`、`audience`，并在 `sources`、`decisions`、`wiki` 中链接依据的纪要、决策和知识页。决策记录的 `outputs` 字段反向链接到产出物。
- 版本由 git 管理，不要用 `v2_final.md` 这类文件名区分版本。正式发布时：
  1. 更新 `version`，把 `status` 改为 `released`；
  2. 在文档的版本历史中加一行；
  3. 提交后打 tag，格式为 `<文档名>/v<版本>`，例如 `设计文档/v1.0`；
  4. 在 timeline 中记录一条。
- 导出的 PDF、DOCX 放在 `50-Outputs/_exports/`，文件名带上版本号。

## 10. 代码库（engineering 模块）

- 代码库放在 `repos/<名称>/`，并在 `repos.yaml` 中登记。每个代码库是独立的 git 仓库，外层知识库不跟踪其内容。
- 修改 `repos.yaml` 后，运行 `$PY scripts/sync_repos.py`：它会克隆缺失的代码库，给每个代码库注入对话导出 hook，并显示各库的状态。加 `--pull` 参数时还会拉取更新。
- 两种启动方式：
  - 在知识库根目录启动：用于讨论、调研、写文档；
  - 在 `repos/<名称>/` 中启动：用于写代码，此时 git 操作针对的是该代码库。这种情况下本文件仍然有效（Claude Code 会加载父目录的 CLAUDE.md），读写知识库时注意使用根目录路径。
- 代码层面的规范、与实现强绑定的 ADR，放在代码库自己的 `CLAUDE.md` 和 `docs/adr/` 中。跨仓库的、业务层面的决策，放在知识库的 `40-Sessions/decisions/` 中，并在 `commits` 字段中记录相关的 commit hash。
- 代码里程碑（首个可运行版本、发布、重大重构）记入 timeline，并附上仓库名和 commit。

## 11. git

- 知识库根目录是一个 git 仓库，`.loom/` 和 `repos/` 不纳入其中。
- `/wrapup`、`/ingest`、`/lint`、`/close`、`/loom-upgrade` 完成后各提交一次，提交信息以动作开头，例如 `wrapup: 主题`。其他时候只在用户要求时提交。
- 资料默认全部进入本地仓库。如果某些文件不想提交，由用户自行修改 `.gitignore`。

## 12. Loom 托管与升级

- 以下文件由 Loom 托管，不要在项目中直接修改：
  - `LOOM-RULES.md`
  - `scripts/` 下的脚本
  - `90-Templates/` 下的模板
  - `.claude/skills/` 下由 Loom 提供的 skill：`wrapup`、`ingest`、`lint`、`close`、`loom-upgrade`

  项目需要不同的规则时，写进 `CLAUDE.md`；需要自己的 skill 时，在 `.claude/skills/` 下另起名字新建，升级不会动它们。
- 启用新模块：`$PY .loom/tools/loom.py add <模块>`
- 检查安装状态：`$PY .loom/tools/loom.py doctor`
- 升级：`/loom-upgrade`
- 可用的 skill：
  - `/wrapup`：归档会话
  - `/ingest`：资料入库
  - `/lint`：知识库体检
  - `/close`：项目收尾
  - `/loom-upgrade`：升级 Loom
