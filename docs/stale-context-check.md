# 过期提示的一次实测 / One run of the stale-context check

[English below](#english)

`hot.md` 靠归档维护，难免过期。在 Claude Code 中，Loom 会在会话开始时按证据算出 `hot.md` 写完之后发生了什么：有没有未归档的会话、`repos/` 下的代码库有没有新提交、知识库里有没有未提交的改动。有变化时，注入的内容里会多一行提示，让 AI 先核对再采信。

下面是这个机制的一次实测，以及怎么自己重做。它只跑过一次，只能说明机制按设计起了作用，不能当作效果的度量。

## 实测（Loom 0.5.1）

一个临时建的 Loom 项目。`hot.md` 写着"还没开始写代码，存储方案未定"。实际情况是：`repos/` 下的代码库已经有提交，上一次会话（没有归档）已经决定用 SQLite。

在这个项目里跑了两次无头会话（`claude -p`），第二次是把第一次的提问重跑一遍：

| | 没有 Loom 的 hook | 有 Loom 的 hook |
|---|---|---|
| Claude Code 版本 | 2.1.81（它没有加载 hook） | 2.1.294 |
| 开场 | 没有提到归档 | 第一句先问要不要补归档 |
| 对 `hot.md` | 照搬"还没开始写代码" | 指出 `hot.md` 已经过期，并去核对了代码库的提交 |
| 费用 | 约 0.29 美元 | 约 0.66 美元 |

回答"先不归档"之后恢复同一个会话，AI 没有再问第二次。

## 局限

- 每种情况只跑了一次。
- 两组的 Claude Code 版本不同。对照组不是有意设计的：那个版本没有加载 hook，才成了对照。版本的差别本身可能影响结果。
- 当时的提问原文没有保存下来。
- 无头会话只能说明开场询问会出现，说明不了它在日常使用中是否烦人。
- 多出来的费用，来自注入的上下文和 AI 为了核对多读的文件。

## 自己重做一遍

1. 在一个临时目录里用 `loom.py init --modules engineering` 建一个项目，在 `repos/demo/` 里 `git init` 并提交一次。
2. 把 `00-Hub/hot.md` 的"当前阶段"写成一个比实际更早的状态（例如"还没有开始写代码"），在知识库里提交。
3. 回到 `repos/demo/`，再提交一次。
4. 在项目根目录运行 `kb.py session-start < /dev/null`，看 Loom 会注入什么。应该有一行以"⚠️ hot.md 最后更新于"开头的提示，写着 `repos/demo` 有新提交。
5. 在项目根目录开一个新的 Claude Code 会话，问"项目现在进行到哪一步了"。上下文开头应该出现"Loom 项目上下文"；AI 的回答里应该提到 `hot.md` 可能过期，而不是照搬它。

第 4 步只验证脚本，第 5 步才验证 hook 确实在生效。

---

## English

`hot.md` is kept up to date by wrapups, so sooner or later it falls behind. In Claude Code, Loom works out at the start of each session what has happened since `hot.md` was last written: sessions that were never archived, new commits in the repositories under `repos/`, and uncommitted changes in the knowledge base. When something has changed, the injected context carries one extra line telling the AI to check before relying on `hot.md`.

Below is one run of that mechanism, and how to repeat it. It was run once. It shows that the mechanism did what it was designed to do; it is not a measurement of how much it helps.

### The run (Loom 0.5.1)

A throwaway Loom project. `hot.md` said "no code written yet, storage undecided". In fact the repository under `repos/` already had commits, and the previous session, which had not been archived, had decided on SQLite.

Two headless sessions (`claude -p`) were run in that project, the second repeating the first one's prompt:

| | Without Loom's hooks | With Loom's hooks |
|---|---|---|
| Claude Code version | 2.1.81 (it did not load the hooks) | 2.1.294 |
| Opening | No mention of archiving | Asked first whether to archive the earlier session |
| Treatment of `hot.md` | Repeated "no code written yet" | Said `hot.md` was out of date and checked the repository's commits |
| Cost | about $0.29 | about $0.66 |

After the answer "not now", the same session was resumed, and the AI did not ask a second time.

### Limits

- Each case was run once.
- The two cases used different Claude Code versions. The control was not planned: that version failed to load the hooks, which is what made it a control. The version difference may itself affect the result.
- The exact prompt was not kept.
- A headless session shows that the opening question appears. It does not show whether the question is annoying in daily use.
- The extra cost comes from the injected context and from the files the AI read in order to check.

### Repeating it

1. In a temporary directory, create a project with `loom.py init --modules engineering`, then `git init` in `repos/demo/` and make one commit there.
2. Write an earlier state than the real one into "Current phase" in `00-Hub/hot.md` (for example "no code written yet") and commit the knowledge base.
3. Go back to `repos/demo/` and make another commit.
4. In the project root, run `kb.py session-start < /dev/null` to see what Loom would inject. It should contain a line starting with "⚠️ hot.md was last updated at", saying that `repos/demo` has new commits.
5. Start a new Claude Code session in the project root and ask "where does the project stand now?". The context should begin with "Loom project context", and the answer should mention that `hot.md` may be out of date instead of repeating it.

Step 4 checks the script only. Step 5 is what shows the hooks are live.
