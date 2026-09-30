# 升级 Loom

在项目根目录执行：

1. 提交或暂存项目中的所有改动（升级要求工作区干净）。
2. 拉取新版本：`git -C .loom pull`（换了机器、`.loom/` 不存在时，先重新 clone）。
3. 对 AI 说"升级 Loom"，即 `/loom-upgrade`。AI 会依次预览变化、执行升级、处理冲突、评估种子文件模板的变化、执行迁移说明，最后提交。

也可以手动执行：

```bash
py .loom/tools/loom.py upgrade --dry-run   # 预览
py .loom/tools/loom.py upgrade             # 执行
py .loom/tools/loom.py upgrade --to v0.2.0 # 升级到指定版本
git diff                                   # 审阅
git checkout . && git clean -fd            # 不满意时回滚（git clean 会删除新增的文件）
```

批量升级多个项目（任选一个 Loom clone 执行）：

```bash
py <Loom>/tools/loom.py upgrade-all <项目A> <项目B> ...
```

## 升级规则

| 类别 | 例子 | 升级方式 |
|---|---|---|
| 托管 managed | `LOOM-RULES.md`、`scripts/`、`90-Templates/`、Loom 提供的 skill | 三方合并（旧版模板、新版模板、项目当前文件）。项目里没改过就直接更新；改过就保留本地修改；有冲突时写入 `<<<<<<<` 标记 |
| 种子 seeded | `CLAUDE.md`、`00-Hub/*.md`、`10-Brief/项目简报.md` 等 | 不修改，升级报告中给出模板的变化，由 AI 判断是否同步 |
| 合并 merged | `.claude/settings.json`、`.gitignore`、`.obsidian/app.json` | JSON 按键合并，文本按行合并；项目自己添加的内容会保留 |

旧版模板取自 `.kb.json` 中记录的 `loom.commit`，所以 `.loom/` 必须是一个带完整历史的 git clone（不要用 `--depth 1`）。
