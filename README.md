# Loom

**Loom 是一个和 AI 协同推进项目的知识库工具包。** 它把项目中的讨论、调研资料、决策、产出物、代码库和全部对话历史，组织成一个 Obsidian 知识库，并保存在同一个项目文件夹里。这样，AI 在每一次会话中都能拿到完整的上下文。

适用于三类项目：想法孵化、研究调研、工程开发。项目可以从一句话的想法起步，也可以从一堆已有资料起步。

## 快速开始

```bash
mkdir my-project && cd my-project
git clone <Loom 仓库地址> .loom
claude            # 在项目根目录启动 Claude Code
```

然后对 AI 说：**"按 .loom/INIT.md 初始化这个项目"**。

AI 会依次完成以下工作：
1. 访谈你；
2. 选择模块；
3. 生成目录、`CLAUDE.md`、项目简报和 hot.md；
4. 编目已有资料；
5. 提交第一个 git commit。

完成后，按提示重启 Claude，让 hook 生效。

## 它做了什么

| 机制 | 说明 |
|---|---|
| 对话自动存档 | 通过 Stop / SessionEnd hook，把每次对话导出为 Markdown，保存到 `40-Sessions/raw/`；在代码库子目录中启动的会话也会被收集 |
| 上下文自动注入 | 通过 SessionStart hook，在会话开始时注入 `hot.md`，并提醒未归档的会话和到期的决策 |
| 三层记录 | 原始对话 → 会话纪要与决策记录（`/wrapup`）→ 时间线（里程碑） |
| 资料流 | `inbox/` → `raw/`（不可修改）→ 资料卡 → wiki（`/ingest`） |
| 产出物 | `50-Outputs/` 存放设计文档和报告，带版本和状态，可以追溯到它所依据的讨论和决策 |
| 代码库 | 代码库放在 `repos/` 下，各自是独立的 git 仓库，在 `repos.yaml` 中登记 |
| 体检 | `/lint` 检查死链、孤立页、未登记的资料、未归档的会话、到期的决策 |

## 模块

| 模块 | 内容 |
|---|---|
| `core`（必装） | `00-Hub`（hot、index、timeline、roadmap、log）、`10-Brief`、`20-Sources`、`40-Sessions`、脚本、hook，以及 skill：`/wrapup` `/ingest` `/lint` `/close` `/loom-upgrade` |
| `research` | 文献卡、实验记录模板 |
| `engineering` | `repos/` 与 `repos.yaml`、`sync_repos.py`、设计文档与 ADR 模板 |
| `outputs` | `50-Outputs/` 产出文档模板 |

项目演化时可以追加模块：`py .loom/tools/loom.py add engineering`。

## 项目结构（实例）

```
<项目>/
├── .loom/            Loom 本身（不纳入项目的 git）
├── .kb.json          Loom 版本、已启用的模块、Python 命令
├── CLAUDE.md         项目特有约定，通过 @LOOM-RULES.md 引用通用规则
├── LOOM-RULES.md     通用规则（Loom 托管）
├── .claude/          hook 配置、skill
├── 00-Hub/           hot · index · timeline · roadmap · log
├── 10-Brief/         项目简报
├── 20-Sources/       inbox · raw · cards · sources-index
├── 30-Wiki/          知识页（首次用到时创建）
├── 40-Sessions/      raw · notes · decisions
├── 50-Outputs/       产出物（outputs 模块）
├── repos/            代码库（engineering 模块，不纳入外层 git）
├── 90-Templates/     模板（Loom 托管）
└── scripts/          脚本（Loom 托管）
```

## 升级

```bash
git -C .loom pull
```

然后对 AI 说"升级 Loom"（即 `/loom-upgrade`），或者直接运行 `py .loom/tools/loom.py upgrade`。

Loom 按文件类别处理升级：

| 类别 | 例子 | 升级方式 |
|---|---|---|
| **托管文件** | 脚本、模板、skill、LOOM-RULES.md | 用 `git merge-file` 做三方合并：项目里没改过的直接更新，改过的保留本地修改，冲突会被标出 |
| **种子文件** | CLAUDE.md、hot.md、项目简报 | 永远不会被覆盖，升级报告只列出模板的变化 |
| **合并文件** | `.claude/settings.json`、`.gitignore` | 按键或按行合并 |

升级前要求项目的工作区是干净的，升级后用 `git diff` 审阅，不满意可以回滚。详见 [UPGRADE.md](UPGRADE.md)。

多个项目可以批量升级：`py .loom/tools/loom.py upgrade-all <项目目录> ...`。

## 参考与致谢

- Andrej Karpathy 提出的 LLM Wiki 模式：raw 存不可变的原始资料，wiki 由 LLM 维护，CLAUDE.md 作为 schema；三个核心操作是 ingest、query、lint。
- [claude-obsidian](https://github.com/AgriciDaniel/claude-obsidian)：借鉴了它的约定，包括 inbox → raw → wiki 的资料流、用标记文件识别 vault、hot/index/log。
- [copier](https://copier.readthedocs.io/)：模板带版本，升级时做三方合并。

维护 Loom 本身请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。
