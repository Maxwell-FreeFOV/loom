# reading-notes-demo（演示数据 / demo data）

这是 Loom 文档使用的**虚构示例项目**：一个"个人阅读摘录工具"的立项讨论。
所有需求、选项和结论都是演示设定，不是真实项目的历史。

This is a **fictional example project** used in Loom's documentation: the kickoff discussion
of a personal reading-excerpt tool. All requirements, options and conclusions are invented
for demonstration; they are not a real project's history.

两个目录是同一个项目在两种项目语言下的样子（逻辑标识一致，例如决策编号都是 `DR-2026-001`）：
The two directories are the same project under the two project languages (same logical
identifiers — the decision is `DR-2026-001` in both):

- `en/`：英文项目（`language: en`）
- `zh-CN/`：中文项目（`language: zh-CN`）

试用方式：把 `en/` 或 `zh-CN/` **复制到一个独立目录**（不要在 Loom 源码仓库里初始化或运行），
然后在那个目录里让 AI 读取 `00-Hub/hot.md`，或者用 loom skill 的 `kb.py index` / `lint` 检查它。

To try it out: copy `en/` or `zh-CN/` **into a separate directory** (do not initialize or run
anything inside the Loom source repository), then ask your AI there to read `00-Hub/hot.md`,
or run the loom skill's `kb.py index` / `lint` on it.
