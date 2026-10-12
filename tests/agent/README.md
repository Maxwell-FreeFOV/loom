# 行为测试：在 DeepSeek Harness 里跑 Loom

`smoke_test.py` 和 `test_regressions.py` 测的是脚本。这里测的是另一半：AI 拿到 Loom 之后实际怎么做，以及每一步有什么进了它的上下文。

做法是让 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)（dsh）在一个隔离环境里，对着虚构的夹具项目跑一句提示，然后读它的会话日志。dsh 的日志逐步记录了请求头、每条注入消息的来源、每次工具调用和供应商报告的 token 用量，所以不需要改 dsh。

**它测不了的**：Claude Code 的 hook 这一层（dsh 里没有 hook）；换一个模型会怎样（结论只对运行时用的模型成立）。

## 运行

需要本机装有 dsh（`npm i -g @deepseek-ai/dsh`），并且有一个配置过模型的 dsh home（缺省 `~/.dsh`）。会产生模型调用费用，所以不进 CI。

```bash
py tests/agent/run.py --list                       # 列出场景
py tests/agent/run.py --scenario s1 --repeat 3     # 跑一个场景三次
py tests/agent/run.py --scenario s1,s3 --inject    # 模拟 Claude Code 的会话开始注入
py tests/agent/run.py --ref v0.6.0                 # 测某个已提交的版本，缺省 HEAD
py tests/agent/ctxtrace.py <session.jsonl>         # 单独分析一份 dsh 会话日志
```

报告写到 `tests/agent/.runs/<时间>/`（不进 git）：每次运行一份 Markdown（检查结果、上下文账本、最后的回答），加一份汇总和一份 JSON。

测的是**已提交**的内容：改了规则或 skill 之后先提交，再跑。

## 隔离是怎么做的

每次运行在系统临时目录里新建一个环境，跑完删除：

| 环境变量 | 指向 | 作用 |
|---|---|---|
| `DSH_HOME` | `home/` | dsh 的 profile、设置和会话日志 |
| `DSH_AGENTS_HOME` | `userhome/.agents` | skill 只从这里发现 |
| `USERPROFILE`、`HOME` | `userhome/` | 模型自己拼出 `~/.agents/skills/loom` 时也落在这里 |
| `DSH_PERMISSION_MODE` | `danger-full-access` | 无人值守，不询问 |
| `DSH_TELEMETRY_MODE` | `DISABLED` | 关闭遥测 |

- 被测的 Loom 由 `tools/deploy.py --home` 部署进 `userhome/`。
- 模型设置从已有的 dsh home 复制 `settings.yaml`。凭据文件 `.credentials.yaml` 只在运行期间复制进来，不读取、不打印，结束后删除。
- 一个 patch 把会话日志改成一行一个事件的普通 JSONL。
- 因为换了 `USERPROFILE`，git 读不到全局身份，测试用环境变量给一个固定的测试身份。

**注意**：`danger-full-access` 没有沙箱，模型在运行期间能动到本机的任何文件。夹具里的提示都是良性的，但不要往夹具里放真实内容，也不要把这套东西接到不可信的提示上。夹具内容会发给模型供应商，所以全部是虚构的。

## 场景

| 场景 | 测什么 |
|---|---|
| `s1` | 冷启动问现状：hot.md 过期时，会不会先读它、会不会照搬 |
| `s2-zh`、`s2-en`、`s2-implicit` | 触发：中文点名、英文点名、不点名 Loom 时，会不会加载 skill 并运行体检 |
| `s3` | 补归档：纪要、写入前对账、旧说法的处理、只提交本次的文件 |
| `s4` | 导入的资料里带着指令时，会不会执行 |
| `s5` | 在 `repos/<名称>/` 里启动时，还找不找得到知识库 |
| `s7` | 发布快照前会不会停下来等确认 |
| `s8` | 从一个普通文件夹初始化 |

每个场景有两种检查。硬性检查（✅ 或 ❌）对应流程里规定必须做到的事；观察项（·）只记录看到了什么。模型的输出不确定，一个场景至少跑三次，看次数。

## 加一个场景

在 `scenarios.py` 里写一个建夹具的函数和一个检查函数，登记进 `SCENARIOS`。检查函数拿到的是 `ctxtrace.analyze()` 的结果：`actions` 是按顺序的工具调用（类别、对象、结果的字符数），用 `happened()`、`before()`、`first()` 查询；另外可以直接看夹具目录在运行之后的样子。

## 依赖的 dsh 细节

dsh 还在预览期。这套测试依赖的东西列在 `ctxtrace.py` 和 `rig.py` 的文件头里：会话日志的几种事件和字段、几个环境变量、headless profile，以及"patch 会整体替换一行的 config"这个行为。升级 dsh 之后先跑一次 `s1` 确认日志还读得出来。写这份说明时用的是 dsh 0.1.1-rc.2。
