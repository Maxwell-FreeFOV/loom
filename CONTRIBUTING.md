# 维护 Loom

## 仓库结构

```
tools/loom.py         安装与升级工具（只依赖 Python 3 标准库和 git）
modules/<模块>/
  module.json         描述、依赖（requires）、安装时要创建的目录（dirs）
  managed/            托管文件：升级时三方合并
  seeded/             种子文件：只在安装时生成
  merged/             合并文件：JSON 按键合并，其他文件按行合并
tests/smoke_test.py   端到端测试
INIT.md               给 AI 执行的初始化流程
```

## 约定

- 类别子目录（`managed/`、`seeded/`、`merged/`）下面的路径，就是文件在项目中的路径。
- 文件名以 `.tmpl` 结尾时，安装时会去掉这个后缀。凡是放在 Loom 仓库里就会产生效果的文件，都要加上这个后缀，比如 `CLAUDE.md`（会被 Claude Code 加载）和 `.gitignore`（会被 git 识别）。
- 模板中可以使用以下占位符：`{{PROJECT_NAME}}`、`{{SUMMARY}}`、`{{DATE}}`（项目创建日期）、`{{PYTHON}}`。`90-Templates/` 中的 `{{title}}`、`{{date}}` 是 Obsidian 模板插件的变量，安装时不会被替换。
- 安装和升级只读取**已提交**的内容。修改后要先提交，才能在测试项目中看到效果。
- 项目中的脚本只能依赖 Python 3 标准库。
- **Loom 仓库里不得出现任何个人信息或具体项目的内容。** 开发 Loom 的讨论和决策，记录在使用 Loom 的开发项目（Loom-Studio）里，不要写进本仓库。

## 发布

1. 运行 `py tests/smoke_test.py`，确认全部通过。
2. 更新 `VERSION`，并在 `CHANGELOG.md` 中新增条目。如果有结构性变化，同时在 `MIGRATIONS.md` 中新增条目。
3. 提交，然后打 tag：`git tag v<版本号>`。

## 升级机制

`.kb.json` 中记录着项目安装时使用的 Loom commit。升级时，对于每个托管文件，工具会取三个版本：

- 旧版模板：该 commit 中的模板；
- 新版模板：目标版本中的模板；
- 项目当前文件。

如果项目文件等于旧版模板，就直接替换为新版；否则调用 `git merge-file` 做三方合并。所有模板在比较前都会先替换占位符，并统一为 LF 换行。
