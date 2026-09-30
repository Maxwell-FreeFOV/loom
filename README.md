# Loom

**Loom 是一个用来和 AI 协同推进项目的知识库 skill。** 它把一个项目的讨论、调研资料、决策、产出物、代码库和全部对话历史，组织成同一个文件夹里的 Obsidian 知识库，让 AI 在每一次会话中都能拿到完整的上下文。

适用于想法孵化、研究调研和工程开发。可以从一句话的想法开始，也可以从一堆已有资料开始。

Loom 是一个遵循 [Agent Skills](https://agentskills.io) 开放标准的 skill，只需在本机全局安装一次，所有项目都能使用；项目文件夹里只存放数据。

## 安装

**方式一：从源码部署（推荐，便于升级和回滚）**

```bash
git clone <本仓库地址> loom && cd loom
py tools/deploy.py            # 或 python3 tools/deploy.py
```

部署时，skill 本体会放到 `~/.agents/skills/loom`，然后在已安装的工具的 skills 目录中创建链接：默认是 `~/.claude/skills/loom` 和 `~/.codex/skills/loom`。可以用 `--agents claude,codex,gemini` 指定要链接的工具。

**方式二：手工复制**

把 `skills/loom/` 整个目录复制到对应工具的 skills 目录，例如 `~/.claude/skills/loom/`。

发布到 GitHub 后，也可以用 [skills CLI](https://github.com/vercel-labs/skills) 安装：`npx skills add <owner>/loom`。

## 使用

新建一个空文件夹，或者一个放着已有资料的文件夹，在里面启动 AI，然后说：

> 用 Loom 初始化这个项目

在 Claude Code 中也可以直接输入 `/loom init`。AI 会先访谈你、选择模块，然后生成目录、`AGENTS.md`、项目简报和 hot.md，登记已有的资料，最后提交第一个 git commit。

日常常用的操作（在 Claude Code 中写作 `/loom <操作>`，在其他工具中直接说"用 loom 做 …"）：

| 操作 | 作用 |
|---|---|
| `wrapup` | 讨论结束时，归档会话：写纪要和决策记录，更新 wiki、时间线、路线图和 hot.md |
| `ingest` | 导入资料：原件存入 `raw/`，登记到资料清单，写资料卡，整合进 wiki |
| `lint` | 知识库体检：死链、孤立页、未登记的资料、未归档的会话、到期的决策 |
| `module` | 启用新模块：research、engineering、outputs |
| `migrate` | Loom 升级后，迁移项目结构 |
| `close` | 项目暂停或结束时复盘 |

## 项目结构

```
<项目>/
├── .kb.json          项目名、模块、结构版本
├── AGENTS.md         项目指令（含一段由 Loom 维护的区块）；CLAUDE.md 只引用它
├── 00-Hub/           hot · index · timeline · roadmap · log
├── 10-Brief/         项目简报
├── 20-Sources/       inbox · raw · cards · sources-index
├── 30-Wiki/          知识页（首次用到时创建）
├── 40-Sessions/      raw（原始对话）· notes（会话纪要）· decisions（决策记录）
├── 50-Outputs/       产出物（outputs 模块）
└── repos/ + repos.yaml   代码库（engineering 模块；各自是独立的 git 仓库，不纳入外层仓库）
```

## 不同工具中的能力差异

| 能力 | Claude Code | Codex、Gemini CLI、Cursor 等 |
|---|---|---|
| 初始化、归档、导入资料、体检、模块、迁移 | ✅ | ✅（需要 AI 能执行本地命令） |
| 会话结束时自动导出对话 | ✅ 由 hook 完成 | ❌ 对话不会进入 `40-Sessions/raw/`，靠会话纪要留存 |
| 会话开始时自动注入 hot.md 和提醒 | ✅ 由 hook 完成 | ❌ 靠 `AGENTS.md` 中的提示，由 AI 自己去读 |
| 执行 Loom 操作时补导出之前的对话 | ✅ | ❌（目前只支持 Claude Code 的会话记录格式） |
| 调用方式 | `/loom <操作>`，或用自然语言 | 自然语言；有时需要明确说"用 loom" |

在 Claude Code 中，skill 目录里的 `.claude-plugin/plugin.json` 和 `hooks/hooks.json` 会让这个 skill 同时被加载为插件 `loom@skills-dir`，从而拿到 hook。其他工具会忽略这两个文件。

如果某个 Claude Code 版本没有把 skill 目录加载为插件，可以改用 `py tools/deploy.py --claude-hooks`，把同样的 hook 写进 `~/.claude/settings.json`。

**其他注意事项：**

- 需要本机有 Python 3 和 git。
- Claude Code 会按 `cleanupPeriodDays` 定期清理会话记录，建议把这个值调大，例如设为 365。
- 所有项目共用同一个 Loom 版本。如果新版本改变了项目结构，按照 `migrate` 迁移一次即可。

## 参考与致谢

- Andrej Karpathy 的 LLM Wiki 模式：原始资料不可变，wiki 由 LLM 维护，由一份 schema 约束 LLM 的行为；核心操作是 ingest、query、lint。
- [claude-obsidian](https://github.com/AgriciDaniel/claude-obsidian)：借鉴了它的若干约定，包括 inbox → raw → wiki 的资料流、用标记文件识别知识库、hot/index/log 三件套。
- [Agent Skills](https://agentskills.io) 规范。

参与开发请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。
