# Loom

[English](README.md) | **简体中文**

<p align="center">
  <img src="docs/images/loom-teaser.jpg" alt="Loom 把 AI 对话、讨论和资料织成结构化的项目知识：摘要、决策记录和互相链接的笔记" width="100%">
</p>

**Loom 帮 AI 助手记下长期项目的记录：定了什么，为什么这样定，每个结论从哪来，下一步做什么。**

和 AI 一起做几周的项目，大部分东西都留在聊天记录里。每次开新会话都要从头讲。一个月后，没人记得当初为什么这样选。

Loom 是一个给 AI 助手用的 skill。AI 把项目记录写成你项目文件夹里的 Markdown 文件。每类记录有固定的位置，每次改动由 git 记下。你可以读、可以改，也可以分享。

## 你能得到什么

- **每个决定一份记录。** 写明有哪些选项、为什么这样选、最强的反对理由、信心度和复盘日期。到了复盘日期，Loom 会提醒你。
- **有出处的结论。** 原始资料原样保存。知识页里的每个结论都写明来自哪份资料或哪次讨论。
- **一页说清项目现在到哪了。** 新会话最先读 [`hot.md`](examples/reading-notes/zh-CN/00-Hub/hot.md)：当前重点、未决问题、最近的决定和下一步。
- **有边界的分享。** 可以把成果做成一份审阅过的快照，发给合作者。对话、会话纪要和决策记录永远不进快照。
- **记录归你。** 全部是 git 管理的普通 Markdown 文件，换一个 AI 工具也能用。

## 怎么用

用平常的话对 AI 说就行。三句话是一个完整的循环：

```text
用 Loom 初始化这个项目，目标是做一个个人阅读摘录工具。

用 Loom 归档刚才的讨论。

这是 Loom 项目。先读 hot.md，再继续完善功能清单。
```

1. 第一句建立项目。AI 会先问你几个问题。
2. 第二句归档这次讨论（操作名是 `wrapup`）。一次讨论结束时做。忘了也没关系：在 Claude Code 里，下次会话开头 AI 会问你。
3. 第三句在新会话里接着做。没有"继续"命令，AI 读已经保存的记录就能接上。

一次归档留下这些文件（来自一个虚构的演示项目）：

| 归档前 | 归档后 |
|---|---|
| 聊天里定下的一件事 | 一份[决策记录](examples/reading-notes/zh-CN/40-Sessions/decisions/DR-2026-001_首版本地摘录.md)，有选项、理由和复盘日期 |
| 这次的讨论 | 一份[会话纪要](examples/reading-notes/zh-CN/40-Sessions/notes/2026-10-01_首版范围讨论.md)，写结论和未决问题 |
| 一路得出的认识 | 一页[知识页](examples/reading-notes/zh-CN/30-Wiki/首版范围.md)，每个结论标明出处 |
| 聊天里提到的待办 | 更新后的 [hot.md](examples/reading-notes/zh-CN/00-Hub/hot.md) 和[路线图](examples/reading-notes/zh-CN/00-Hub/roadmap.md) |

完整的演示在 [`examples/reading-notes/zh-CN/`](examples/reading-notes/zh-CN/)（英文版在 [`en/`](examples/reading-notes/en/)）。想试的话，先复制到一个单独的文件夹。不要在 Loom 源码仓库里初始化。

**Loom 怎么和你说话。** 默认用平常话：不用操作名、目录名和 git 术语，文件链接放在最后一行。想要更多或更少的技术细节，直接告诉 AI。你说"以后都这样"，AI 会把它写进项目的 `AGENTS.md`；只说过一次的，AI 会在下次归档时问你要不要记下来。

## 适合你吗

**适合用 Loom：**

- 项目要做几周到几个月，超过四五次会话；
- 有要做的决定，以后要能说清理由；
- 要知道每个结论从哪来（调研、资料多）；
- 工作会停几周、交给别人，或者换 AI 工具；
- 工作横跨几个代码库。

**不适合用 Loom：**

- 一两次会话就结束的任务；
- 只在一个文档已经很好的代码库里写代码；
- 只用网页聊天，AI 打不开本地文件；
- 希望什么都不做，AI 就能记住一切；
- 几个人要同时编辑同一个知识库；
- 在做 agent 产品，要给终端用户做记忆。

**要付出什么：**

- **归档要你发起，或者在 AI 问的时候同意。** 不再归档，记录就会过时。过时的 `hot.md` 会误导下一次会话。在 Claude Code 里，Loom 会拿 `hot.md` 和它写完之后的变化对照，看起来过时就提醒 AI（[这个检查的一次实测](docs/stale-context-check.md)）。
- **一次归档要几分钟。** AI 要读写几个文件，再做一次 git 提交。
- **每次会话多带一些内容。** 在 Claude Code 里，Loom 项目的每次会话开头会带上 Loom 的规则（约 8200 个字符）和你的 `hot.md`（最多 6000 个字符）。
- **查找比较简单。** 只有一页索引加文件搜索，范围是一个项目。没有语义检索，也不能跨项目查。

## 安装

### 最简单的办法：让 AI 帮你装

需要一个能在你电脑上执行命令的 AI 工具，例如 Claude Code 或 Codex。网页聊天做不到。

1. 打开 AI 工具，把这句话发给它：

   ```text
   请按 https://github.com/Maxwell-FreeFOV/loom 上的说明，帮我在这台电脑上安装 Loom。
   ```

2. AI 会下载代码，检查 Python、git 和 Bash，运行安装，再检查结果。它执行命令之前，工具可能会请你批准。看一眼命令，再批准。
3. AI 说装好之后，关掉这个会话，开一个新会话。Loom 从新会话开始生效。AI 不一定会提醒你这一步。
4. 建一个项目文件夹，在里面启动 AI，说：*"用 Loom 初始化这个项目。"*

我们在已经装有 Python、git 和 Bash 的电脑上实测过。缺其中一样时，AI 可以试着帮你装，但这种情况还没有测过。

### 自己动手装

需要 **Python 3.12+** 和 **git**。Claude Code 的 hook 另外需要 **Bash**（Windows 上是 Git for Windows 自带的 Git Bash）。

1. 下载并部署。

   Windows：

   ```powershell
   git clone https://github.com/Maxwell-FreeFOV/loom.git loom
   cd loom
   py tools/deploy.py
   ```

   macOS / Linux：命令相同，把 `py` 换成 `python3`。

2. 在 AI 工具里开一个新会话。新版本从下一次会话开始生效。

3. 建一个项目文件夹，在里面启动 AI，说：*"用 Loom 初始化这个项目。"* 不想通过 AI，也可以运行 `py "$HOME/.agents/skills/loom/scripts/loom.py" init --name my-project --language zh-CN`。

部署做了什么：

- 把 skill 放到 `~/.agents/skills/loom`。
- 把它链接进找到的工具的 skills 目录，默认是 Claude Code 和 Codex。用 `--agents claude,codex,gemini` 指定。
- 先跑一遍测试。其中 hook 的测试需要 Bash，用 `--skip-tests` 可以跳过。

**其他装法。** 可以用 [skills CLI](https://github.com/vercel-labs/skills)（需要 Node.js 22.20 或更高）：`npx skills add Maxwell-FreeFOV/loom -g -y`。加 `-a claude-code` 时，skill 会被复制到 `~/.claude/skills/loom`，本文里的路径要相应替换。也可以把 `skills/loom/` 手工复制到某个工具的 skills 目录。**只用一种装法。** 混用可能留下两份版本不同的 Loom。

**确认装好了：**

1. 运行 `py "$HOME/.agents/skills/loom/scripts/loom.py" doctor`（macOS/Linux 用 `python3 ~/.agents/...`）。
2. 初始化之后，项目里有 `.kb.json`、`AGENTS.md`、`00-Hub/hot.md` 和 `10-Brief/project-brief.md`。
3. 在 Claude Code 里，项目中的新会话开头会出现"Loom 项目上下文"。会话结束后，对话出现在 `40-Sessions/raw/` 下。这一条才是真正的检验：`doctor` 只检查文件和配置，证明不了 hook 在运行。

**Claude Code 里没有出现"Loom 项目上下文"时：**

1. 升级 Claude Code。hook 在 2.1.283 和 2.1.294 上实测过。较旧的 2.1.81 没有加载 hook，也没有任何提示。
2. 还不行，运行 `py tools/deploy.py --claude-hooks`，把同样的 hook 写进 `~/.claude/settings.json`。
3. 两种方式只用一种。`/plugin` 里能看到 `loom@skills-dir`、`settings.json` 里又有这些 hook 时，每个 hook 会执行两次。`doctor` 会提醒你。

## 升级

升级的是你电脑上的 Loom，项目里的文件不动。新版本从下一次会话开始生效。每个版本改了什么、要不要手动做什么，见 [CHANGELOG.md](CHANGELOG.md)。

**最简单的办法：让 AI 帮你升级。** 把这句话发给 AI 工具：

```text
请按 https://github.com/Maxwell-FreeFOV/loom 上的说明，帮我把这台电脑上的 Loom 升级到最新版。
```

AI 会先查清你当初是怎么装的，再运行对应的命令。升级完，开一个新会话。AI 不一定会提醒你这一步。我们用"很早以前克隆、部署过"的情况实测过。

**自己动手升级：**

- **用克隆的仓库装的：** 在当初克隆的目录里运行 `py tools/deploy.py --latest`（macOS/Linux 用 `python3`）。它从 GitHub 部署最新的发布版；已经是最新时什么都不做。
  - 忘了克隆在哪：看 `~/.agents/skills/loom/.loom-deploy.json` 里的 `source`。
  - 提示不认识 `--latest`：克隆的版本太旧，先运行 `git pull`。`git pull` 失败时，删掉这个目录重新克隆。
  - 用过 `--claude-hooks` 的，升级时再加上它。
- **用 skills CLI 装的：** 运行 `npx skills update loom -g -y`。它取的是主分支，可能比最新的发布版还新。

升级之后，运行 `doctor` 查看版本。新版本改了项目结构时，下一次会话里 AI 会看到提示，并按步骤迁移项目。要退回旧版本，见[卸载与回滚](docs/uninstall.md)。

## 全部操作

在 Claude Code 里输入 `/loom <操作>`。在任何工具里都可以直接说，例如"用 Loom 归档这次讨论"。

| 操作 | 作用 |
|---|---|
| `init` | 建立项目：先问几个问题，再生成目录和项目简报，登记你已有的资料 |
| `wrapup` | 归档一次讨论：写会话纪要和决策记录，更新知识页、路线图和 `hot.md` |
| `ingest` | 导入资料：文件、网页或合作者的快照。原件原样保存，新知识写进知识页 |
| `publish` | 把成果做成快照（一个 zip）用来分享。AI 先列出文件清单和要留意的地方，你确认后才生成 |
| `lint` | 体检：死链、没归档的会话、到了复盘日期的决定等 |
| `module` | 启用模块：`research`（文献卡、实验记录）、`engineering`（关联代码库）、`outputs`（给别人看的、带版本的文档） |
| `migrate` | 升级后把项目迁移到新结构 |
| `close` | 项目暂停或结束时复盘 |

## Loom 和 AI 记忆

很多 AI 助手有自己的记忆，记的是你的偏好和一些事实。Loom 不改变这种记忆，也不替代它。Loom 把项目记录存在文件里，AI 需要时去读。它没有数据库、后台服务或网页界面。

| | AI 助手的记忆 | Loom |
|---|---|---|
| 记什么 | 你喜欢怎样工作 | 项目是什么、为什么：资料、知识、决定、文档、对话 |
| 谁来写 | 助手自己随时写 | 你归档或导入时由 AI 写，每次一个 git 提交 |
| 决定 | 最多记成一条事实 | 选项、理由、反对理由、信心度、复盘日期 |
| 分享 | 留在账号或某台电脑上 | 审阅过的快照；文件在任何工具里都能用 |

如果你只需要下次会话接上这次，AI 自带的记忆可能就够了。Loom 多给的是：有出处的知识、带理由的决定、可以核对的历史，以及有边界的分享。

## 工具、语言和隐私

- **工具。** Loom 在 **Claude Code** 里实测过。它遵循 [Agent Skills](https://agentskills.io) 标准，按设计可以在其他能执行本地命令的工具里用（Codex、Gemini CLI），但还没有完整验证。只有 Claude Code 有 hook，能自动导出对话、在会话开头载入 `hot.md`。其他工具里，内容靠会话纪要留存，AI 按 `AGENTS.md` 的提示自己去读 `hot.md`。
- **语言。** 项目分英文（`init --language en`）和中文（`--language zh-CN`）。文件、模板和报告跟随项目语言。skill 自己的规则（`SKILL.md` 和 `references/`）目前只有中文，不影响用英文使用全部功能。
- **内容会离开你的电脑。** 文件存在本地，但 AI 读到的内容会发给你用的 AI 服务。
- **对话会进 git。** 在 Claude Code 里，hook 只在 Loom 项目中把每次对话导出到 `40-Sessions/raw/`。每次归档、导入、发布，都在项目自己的 git 仓库里提交一次，只提交这次改过的文件。不想提交的文件用 `.gitignore` 排除。Loom 不创建远端，也不推送。除非你在 `.kb.json` 里打开 `auto_amend`，hook 不会改写已有的提交。
- **项目仓库建议保持私有。** 要分享就用 `publish`。它的清洗规则是机械的，发出去的内容你还是要自己看一遍。
- **保留旧的会话记录。** Claude Code 默认约 30 天清理一次会话记录（`cleanupPeriodDays`），Loom 要从这些记录导出对话。建议在 `~/.claude/settings.json` 里设为 365 或更大。

## 项目的目录结构

```
<项目>/
├── .kb.json          项目名、模块、结构版本、语言
├── AGENTS.md         项目指令，其中一段由 Loom 维护；CLAUDE.md 只引用它
├── 00-Hub/           hot.md（项目现在到哪了）· 索引 · 时间线 · 路线图 · 日志
├── 10-Brief/         项目简报：问题、目标、范围、约束
├── 20-Sources/       待处理 · 原始资料 · 资料卡 · 资料清单
├── 30-Wiki/          AI 维护的知识页
├── 40-Sessions/      原始对话 · 会话纪要 · 决策记录
├── 50-Outputs/       给别人看的文档（outputs 模块）
└── repos/ + repos.yaml   关联的代码库（engineering 模块）
```

## 更多文档

- 规则与操作说明：[`skills/loom/SKILL.md`](skills/loom/SKILL.md) 与 [`skills/loom/references/`](skills/loom/references/)
- 卸载与回滚：[`docs/uninstall.md`](docs/uninstall.md)
- 过期提示的一次实测，以及怎么自己重做：[`docs/stale-context-check.md`](docs/stale-context-check.md)
- 安全问题报告：[SECURITY.md](SECURITY.md)
- 版本变化：[CHANGELOG.md](CHANGELOG.md)
- 参与开发：[CONTRIBUTING.md](CONTRIBUTING.md)

## 参考与致谢

- Andrej Karpathy 的 LLM Wiki 模式：原始资料不改动，wiki 由 LLM 维护，用一份 schema 约束 LLM 的行为；核心操作是 ingest、query、lint。
- [claude-obsidian](https://github.com/AgriciDaniel/claude-obsidian)：借鉴了它的几条约定，比如 inbox → raw → wiki 的资料流、用标记文件识别知识库、hot/index/log 三件套。
- [Agent Skills](https://agentskills.io) 规范。
