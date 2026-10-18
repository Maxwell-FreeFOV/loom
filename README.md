# Loom

**English** | [简体中文](README.zh-CN.md)

<p align="center">
  <img src="docs/images/loom-teaser.jpg" alt="Loom weaves AI conversations, discussions, and sources into structured project knowledge: summaries, decision records, and linked notes" width="100%">
</p>

**Loom helps your AI assistant keep the record of a long project: what you decided, why you decided it, where each fact came from, and what to do next.**

When you work with an AI for weeks, most of the work stays in chat logs. Each new session starts from zero. A month later, nobody remembers why a choice was made.

Loom is a skill for AI assistants. The AI writes the project record into Markdown files in your project folder. Each type of record has its own place. Git records each change. You can read the files, correct them, and share them.

## What you get

- **A record for each decision.** It shows the options, the reasons, the strongest argument against, your confidence, and a review date. Loom reminds you when the review date comes.
- **Facts with sources.** Loom keeps your source files unchanged. Each claim in the knowledge pages tells you which source or session it came from.
- **One page that says where the project is.** A new session reads [`hot.md`](examples/reading-notes/en/00-Hub/hot.md) first: the current focus, open questions, recent decisions, and next steps.
- **Sharing with a boundary.** You can send a reviewed snapshot of the results to a collaborator. Conversations, session notes, and decision records never go into a snapshot.
- **Files that belong to you.** The record is plain Markdown under git. You can move it to a different AI tool.

## How you use it

You talk to your AI in normal language. Three sentences make the full cycle:

```text
Initialize this project with Loom. The goal is a personal reading-excerpt tool.

Archive the discussion we just had with Loom.

This is a Loom project. Read hot.md first, then continue with the feature list.
```

1. The first sentence creates the project. The AI asks a few questions first.
2. The second sentence archives the discussion (the `wrapup` operation). Do this when a discussion ends. If you forget, the AI in Claude Code asks you at the start of the next session.
3. The third sentence continues in a new session. There is no "resume" command. The AI reads the saved record.

One archive gives you these files (from a fictional demo project):

| Before the archive | After the archive |
|---|---|
| A decision you made in the chat | A [decision record](examples/reading-notes/en/40-Sessions/decisions/DR-2026-001_v1-local-excerpts.md) with options, reasons, and a review date |
| The discussion | A [session note](examples/reading-notes/en/40-Sessions/notes/2026-10-01_v1-scope.md) with the conclusions and open questions |
| What you learned | A [knowledge page](examples/reading-notes/en/30-Wiki/v1-scope.md) where each claim cites its source |
| To-dos from the chat | An updated [hot.md](examples/reading-notes/en/00-Hub/hot.md) and [roadmap](examples/reading-notes/en/00-Hub/roadmap.md) |

The full demo is in [`examples/reading-notes/en/`](examples/reading-notes/en/) (Chinese: [`zh-CN/`](examples/reading-notes/zh-CN/)). To try it, copy it into a separate folder. Do not run init inside the Loom source repository.

**How Loom talks to you.** By default, the AI uses plain words. It does not use operation names, folder names, or git terms, and it puts file links on the last line. If you want more or less technical detail, tell it. When you say "from now on", the AI writes your preference into the project's `AGENTS.md`. If you say it only once, the AI asks at the next archive if it should keep it.

## Is it right for you?

**Use Loom when:**

- the project lasts weeks or months, with more than four or five sessions;
- you make decisions that you must explain later;
- you must know where each conclusion came from (research, many sources);
- the work stops for weeks, goes to another person, or moves to another AI tool;
- the work spans more than one code repository.

**Do not use Loom when:**

- the task ends in one or two sessions;
- you code in one repository that already has good documentation;
- you use only a web chat, where the AI cannot open local files;
- you expect the AI to remember everything with no action from you;
- several people must edit the same knowledge base at the same time;
- you build an agent product and need memory for its users.

**What it costs you:**

- **You start each archive, or you agree when the AI asks.** If you stop archiving, the record gets old. An old `hot.md` can mislead the next session. In Claude Code, Loom compares `hot.md` with the changes since it was written and warns the AI when it looks out of date ([one test of this check](docs/stale-context-check.md)).
- **An archive takes a few minutes.** The AI reads and writes several files and makes one git commit.
- **Each session carries extra context.** In Claude Code, each session in a Loom project starts with Loom's rules (about 8,200 characters) and your `hot.md` (at most 6,000 characters).
- **Search is simple.** Loom uses an index page and file search in one project. It has no semantic search and no search across projects.

## Install

### The easy way: let your AI install it

You need an AI tool that can run commands on your computer, for example Claude Code or Codex. A web chat cannot do this.

1. Open your AI tool and send it this message:

   ```text
   Please install Loom on this computer. Follow the instructions at https://github.com/Maxwell-FreeFOV/loom.
   ```

2. The AI gets the code, checks Python, git, and Bash, runs the install, and checks the result. Before it runs a command, your tool can ask for your approval. Read the command, then approve it.
3. When the AI is done, close the session and open a new one. Loom starts in the new session. The AI may not tell you this.
4. Make a project folder, start your AI in it, and say: *"Initialize this project with Loom."*

We tested this on a computer that already had Python, git, and Bash. If one of them is missing, the AI can try to install it, but we have not tested that case.

### The manual way

You need **Python 3.12+** and **git**. The Claude Code hooks also need **Bash** (on Windows, Git Bash from Git for Windows).

1. Get the code and deploy it.

   Windows:

   ```powershell
   git clone https://github.com/Maxwell-FreeFOV/loom.git loom
   cd loom
   py tools/deploy.py
   ```

   macOS / Linux: use the same commands, but use `python3` instead of `py`.

2. Open a new session in your AI tool. The new version starts in the next session.

3. Make a project folder, start your AI in it, and say: *"Initialize this project with Loom."* To create a project without the AI, run `py "$HOME/.agents/skills/loom/scripts/loom.py" init --name my-project --language en`.

What deploy does:

- It puts the skill in `~/.agents/skills/loom`.
- It links the skill into the skills folders of the tools it finds. The default tools are Claude Code and Codex. Use `--agents claude,codex,gemini` to choose.
- It runs the tests first. The hook tests need Bash. Use `--skip-tests` to skip them.

**Other ways to install.** You can use the [skills CLI](https://github.com/vercel-labs/skills) (it needs Node.js 22.20 or newer): `npx skills add Maxwell-FreeFOV/loom -g -y`. With `-a claude-code`, it copies the skill to `~/.claude/skills/loom` instead, so change the paths in this README to match. You can also copy `skills/loom/` into a tool's skills folder by hand. **Use one install method only.** If you mix them, you can get two copies of Loom at different versions.

**Check the install:**

1. Run `py "$HOME/.agents/skills/loom/scripts/loom.py" doctor` (`python3 ~/.agents/...` on macOS/Linux).
2. After init, the project has `.kb.json`, `AGENTS.md`, `00-Hub/hot.md`, and `10-Brief/project-brief.md`.
3. In Claude Code, a new session in the project starts with a "Loom project context" block. After the session ends, the conversation appears in `40-Sessions/raw/`. This is the real test: `doctor` checks files and settings, but it cannot prove that the hooks run.

**If the context block does not appear in Claude Code:**

1. Update Claude Code. The hooks work on 2.1.283 and 2.1.294. An older install (2.1.81) did not load them and gave no warning.
2. If they still do not load, run `py tools/deploy.py --claude-hooks`. This writes the same hooks into `~/.claude/settings.json`.
3. Use only one of the two. If `/plugin` shows `loom@skills-dir` and `settings.json` also has the hooks, each hook runs two times. `doctor` warns you about this.

## Upgrade

Upgrading changes Loom on your machine. It does not change the files in your projects. The new version starts in the next session. [CHANGELOG.md](CHANGELOG.md) (Chinese) tells you what changed and what you must do by hand.

**The easy way: let your AI upgrade it.** Send this message to your AI tool:

```text
Please upgrade Loom on this computer to the latest version. Follow the instructions at https://github.com/Maxwell-FreeFOV/loom.
```

The AI finds out how you installed Loom and runs the correct commands. When it is done, open a new session. The AI may not tell you this. We tested this with an install from an old clone.

**To do it yourself:**

- **If you installed from a clone:** run `py tools/deploy.py --latest` in the clone (`python3` on macOS/Linux). It deploys the newest release from GitHub. It does nothing if you already have it.
  - If you forgot where the clone is, look at the `source` field in `~/.agents/skills/loom/.loom-deploy.json`.
  - If `--latest` is unknown, your clone is old. Run `git pull`. If `git pull` fails, delete the folder and clone again.
  - If you used `--claude-hooks`, add it again.
- **If you installed with the skills CLI:** run `npx skills update loom -g -y`. It takes the main branch, which can be newer than the latest release.

After an upgrade, run `doctor` to see the version. If the new version changes the project structure, the AI sees a notice in the next session and follows the steps to migrate the project. To go back to an older version, see [uninstalling and rolling back](docs/uninstall.md).

## Operations

In Claude Code, type `/loom <operation>`. In any tool, you can say what you want, for example "archive this discussion with Loom".

| Operation | What it does |
|---|---|
| `init` | Creates the project. The AI asks a few questions, makes the folders and the project brief, and registers the files you already have. |
| `wrapup` | Archives a discussion: a session note, decision records, and updates to the knowledge pages, roadmap, and `hot.md`. |
| `ingest` | Adds source material: files, web pages, or a snapshot from a collaborator. The AI keeps the original and adds the new knowledge to the knowledge pages. |
| `publish` | Makes a snapshot (a zip) of the results to share. The AI shows you the file list and the items to check. You confirm before it makes the file. |
| `lint` | Checks the knowledge base: broken links, unarchived sessions, decisions due for review. |
| `module` | Turns on a module: `research` (literature cards, experiment records), `engineering` (linked code repositories), `outputs` (versioned documents for other readers). |
| `migrate` | Moves a project to a new structure after an upgrade. |
| `close` | Reviews a project that stops or ends. |

## Loom and AI memory

Many AI assistants have their own memory. It keeps your preferences and some facts. Loom does not change that memory and does not replace it. Loom keeps the project record in files, and the AI reads them when it needs them. There is no database, no background service, and no web interface.

| | Assistant memory | Loom |
|---|---|---|
| Keeps | How you like to work | What the project is and why: sources, knowledge, decisions, documents, conversations |
| Writes | The assistant, at any time | The AI, when you archive or ingest; one git commit each time |
| Decisions | A fact, if anything | Options, reasons, argument against, confidence, review date |
| Shares | Stays with an account or one machine | Reviewed snapshots; the files work in any tool |

If you only need the next session to continue from the last one, built-in memory can be enough. Loom adds sources, decision records, a history you can check, and sharing with a boundary.

## Tools, languages, and privacy

- **Tools.** Loom is tested in **Claude Code**. It follows the [Agent Skills](https://agentskills.io) standard, so it is made to work in other tools that can run local commands (Codex, Gemini CLI). In those tools, it is not fully tested. Only Claude Code has the hooks that export each conversation and load `hot.md` at the start of a session. In other tools, the session notes keep the content, and the AI reads `hot.md` because `AGENTS.md` tells it to.
- **Languages.** A project is English (`init --language en`) or Chinese (`--language zh-CN`). Files, templates, and reports follow the project language. The skill's own rules (`SKILL.md` and `references/`) are in Chinese only. You can use every feature in English.
- **Your data can leave your machine.** The files are local, but your AI service receives what the AI reads.
- **Conversations go into git.** In Claude Code, the hooks export each conversation to `40-Sessions/raw/` in Loom projects only. Each archive, ingest, and publish makes one commit in the project's own git repository, with only the files that operation changed. Use `.gitignore` for files you do not want in git. Loom never pushes and never creates a remote. The hooks do not change existing commits unless you turn on `auto_amend` in `.kb.json`.
- **Keep project repositories private.** To share, use `publish`. Its cleaning rules are mechanical, so you must still read what you send.
- **Keep old transcripts.** Claude Code deletes old transcripts after about 30 days (`cleanupPeriodDays`). Loom exports from them. Set it to 365 or more in `~/.claude/settings.json`.

## Project layout

```
<project>/
├── .kb.json            project name, modules, structure version, language
├── AGENTS.md           project instructions; Loom keeps one block in it. CLAUDE.md points to it
├── 00-Hub/             hot.md (where the project is) · index · timeline · roadmap · log
├── 10-Brief/           the project brief: problem, goals, scope, constraints
├── 20-Sources/         inbox · original files · source cards · source index
├── 30-Wiki/            knowledge pages that the AI keeps up to date
├── 40-Sessions/        conversations · session notes · decision records
├── 50-Outputs/         documents for other readers (outputs module)
└── repos/ + repos.yaml linked code repositories (engineering module)
```

## More documents

- Rules and operations: [`skills/loom/SKILL.md`](skills/loom/SKILL.md) and [`skills/loom/references/`](skills/loom/references/) (Chinese)
- Uninstalling and rolling back: [`docs/uninstall.md`](docs/uninstall.md)
- One test of the out-of-date check, and how to repeat it: [`docs/stale-context-check.md`](docs/stale-context-check.md)
- Security issues: [SECURITY.md](SECURITY.md)
- Changes in each version: [CHANGELOG.md](CHANGELOG.md) (Chinese)
- Contributing: [CONTRIBUTING.md](CONTRIBUTING.md) (Chinese)

## Acknowledgements

- Andrej Karpathy's LLM Wiki pattern: the original sources do not change, the LLM keeps the wiki, and a schema controls the LLM's behavior. Its core operations are ingest, query, and lint.
- [claude-obsidian](https://github.com/AgriciDaniel/claude-obsidian): Loom uses some of its conventions, for example the inbox → raw → wiki flow, a marker file for the knowledge base, and the hot/index/log files.
- The [Agent Skills](https://agentskills.io) specification.
