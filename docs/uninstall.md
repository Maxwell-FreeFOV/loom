# 卸载与回滚 / Uninstall and rollback

[English below](#english)

## 卸载

Loom 只在以下位置写东西；卸载就是删掉它们。**你的知识库（各个项目文件夹）不属于 Loom，全部保留。**

用 skills CLI 安装的，运行 `npx skills remove loom -g -y`，它会删掉本体和各工具目录里的链接；下面的第 1、2 步就不用做了。

1. 删除 skill 本体：`~/.agents/skills/loom`
2. 删除各工具 skills 目录中的 loom 链接或副本（存在哪些取决于你部署时用的 `--agents`）：
   - `~/.claude/skills/loom`
   - `~/.codex/skills/loom`
   - `~/.gemini/skills/loom`
3. 如果你用过 `deploy.py --claude-hooks`：打开 `~/.claude/settings.json`，删掉 `hooks.SessionStart` 和
   `hooks.SessionEnd` 里命令中含 `loom` 的条目（把 hook 写进去时 deploy.py 留有备份 `settings.json.bak-loom`，
   也可以直接对照它恢复）。如果 `hooks` 因此空了，删掉 `hooks` 键。

不需要动的东西：

- 你的项目文件夹（知识库）：原样保留，里面的 Markdown 不依赖 Loom 也能读。
- 项目里的 `.kb.json`、`AGENTS.md`：保留无害；不再需要时可以手工删除。
- Claude Code 的插件加载（`loom@skills-dir`）：skill 目录删掉后自然消失，没有额外配置。

## 回滚到旧版本

- 回滚 Loom 本体：在源码仓库中运行 `py tools/deploy.py --ref <旧版本的 tag 或 commit>`。本地没有这个 tag 时先运行 `git fetch --tags`。
- 回滚之后不要再运行 `deploy.py --latest`，它会把本机升回最新的发布版。
- 注意：如果项目已经迁移到 schema 2（`.kb.json` 里有 `language` 字段），旧版 Loom 不认识这个结构。
  Loom 不提供自动降级——要带着 schema 2 的项目回到旧版 Loom，请用迁移前的 git 历史或备份恢复项目，
  或者干脆留在新版。迁移前的提交就是为此保留的（migrate 要求工作区干净才执行）。

---

## English

### Uninstall

Loom only writes to the locations below; uninstalling means deleting them. **Your knowledge bases
(the project folders) do not belong to Loom and are left untouched.**

If you installed with the skills CLI, run `npx skills remove loom -g -y`: it deletes the skill and the
links in each tool's directory, so you can skip steps 1 and 2 below.

1. Delete the skill itself: `~/.agents/skills/loom`
2. Delete the loom link or copy in each tool's skills directory (which ones exist depends on the
   `--agents` you deployed with):
   - `~/.claude/skills/loom`
   - `~/.codex/skills/loom`
   - `~/.gemini/skills/loom`
3. If you used `deploy.py --claude-hooks`: open `~/.claude/settings.json` and remove the entries whose
   command contains `loom` from `hooks.SessionStart` and `hooks.SessionEnd`. (deploy.py kept a backup at
   `settings.json.bak-loom` when it wrote them; you can also restore from it.) If `hooks` becomes empty,
   remove the key.

Things you do not need to touch:

- Your project folders (knowledge bases): left as they are; the Markdown inside is readable without Loom.
- `.kb.json` and `AGENTS.md` in projects: harmless to keep; delete them by hand if you no longer want them.
- Claude Code's plugin loading (`loom@skills-dir`): disappears with the skill directory; no extra configuration.

### Rolling back to an older version

- Roll back Loom itself: run `py tools/deploy.py --ref <tag or commit of the older version>` in the source repository.
  If the tag is not in your clone yet, run `git fetch --tags` first.
- After rolling back, do not run `deploy.py --latest`: it would upgrade the machine to the latest release again.
- Caveat: if a project has already been migrated to schema 2 (its `.kb.json` has a `language` field),
  older Loom versions do not understand that structure. Loom does not offer automatic downgrades — to use
  a schema 2 project with an older Loom, restore the project from its pre-migration git history or backup,
  or simply stay on the newer version. (migrate requires a clean worktree precisely so that this
  pre-migration commit exists.)
