# 开发 Loom

## 仓库结构

```
skills/loom/                   要安装的 skill（部署时只导出这个目录）
  SKILL.md                     入口：检查状态，按意图分派到 references/ 中的说明
  VERSION                      版本号（需与 SKILL.md 的 metadata.version、.claude-plugin/plugin.json 保持一致）
  references/                  rules.md（通用规则），以及各操作的说明：init、wrapup、ingest、lint、module、migrate、close
  scripts/                     loom.py、kb.py、export_session.py、sync_repos.py、kbroot.py（共享）、run.sh（hook 启动器）
  assets/templates/notes/      笔记模板
  assets/templates/project/<模块>/   init 和 module add 时生成的项目文件，以及 module.json
  assets/templates/loom-block.md     AGENTS.md 中 Loom 区块的内容
  .claude-plugin/plugin.json   Claude Code 增强层：让 skill 目录同时作为插件 loom@skills-dir 加载
  hooks/hooks.json             SessionStart、Stop、SessionEnd，都通过 run.sh 调用
tools/deploy.py                部署到本机
tests/smoke_test.py            端到端测试
```

## 约定

- **SKILL.md 的 frontmatter 只能使用 Agent Skills 规范中的字段**：`name`、`description`、`license`、`compatibility`、`metadata`、`allowed-tools`。只有这样，才能在 Claude Code 以外的工具中使用，也能上传到 claude.ai。
- **路径写法**：在 skill 正文中，脚本路径写成 `$LOOM/scripts/...`，并在 SKILL.md 中说明 `$LOOM` 的含义（在 Claude Code 中是 `${CLAUDE_SKILL_DIR}`）。不要在 references 中直接使用 Claude Code 专有的变量。
- **脚本依赖**：只依赖 Python 3 标准库和 git。脚本从当前目录向上查找 `.kb.json` 来定位知识库，也接受 `--root` 参数。
- **hook 性能**：hook 在所有 Claude Code 会话中都会触发，所以 `run.sh` 必须先判断当前目录是否属于 Loom 项目，不是就立即退出，保证非 Loom 项目几乎没有额外开销。
- **模板文件名后缀**：`assets/templates/project/` 下的模板，如果放在源码仓库里就会直接生效（如 `CLAUDE.md`、`AGENTS.md`、`.gitignore`），文件名要加 `.tmpl` 后缀。
- **占位符**：模板中可以使用 `{{PROJECT_NAME}}`、`{{SUMMARY}}`、`{{DATE}}`、`{{LOOM_BLOCK}}`。笔记模板中的 `{{title}}`、`{{date}}` 属于 Obsidian 模板插件，Loom 不会替换。
- **结构版本**：项目结构发生变化时（目录改名、字段改名等），做以下三件事：
  1. 把 `kbroot.py` 中的 `SCHEMA` 加 1；
  2. 在 `loom.py` 的 `MIGRATIONS` 中加入迁移函数；
  3. 在 `references/migrate.md` 中写明迁移说明。
- **Loom 区块**：修改 `loom-block.md` 后，旧项目会在 `loom.py status` 中收到"区块不是当前版本"的提示，运行 `refresh-block` 即可更新。
- **不得出现个人信息或具体项目的内容。** 开发 Loom 的讨论和决策，记录在使用 Loom 的开发项目里，不写进本仓库。

## 发布与部署

1. 运行 `py tests/smoke_test.py`，确认全部通过。
2. 更新以下三处的版本号：`skills/loom/VERSION`、`SKILL.md` 的 `metadata.version`、`.claude-plugin/plugin.json` 的 `version`。然后更新 `CHANGELOG.md`。
3. 提交，然后打 tag：`git tag v<版本>`。
4. 运行 `py tools/deploy.py`。部署前它会再跑一遍测试。新版本从下一次会话开始生效。
5. 需要回滚时，运行 `py tools/deploy.py --ref v<旧版本>`。
