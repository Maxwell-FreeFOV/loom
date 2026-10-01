"""Loom 端到端测试：在临时目录中模拟初始化、会话导出与归档、hook、模块、代码库、模板、快照、迁移和部署。

用法：py tests/smoke_test.py [--keep]
  直接使用工作区中的 skills/loom（部署测试除外，它使用一个临时 clone 中已提交的内容）。
  --keep 表示保留临时目录，便于检查。
"""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "skills" / "loom"
SCRIPTS = SKILL / "scripts"
PY = sys.executable
SPEC_FIELDS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
passed = 0


def run(*args, cwd=None, check=True, stdin=None, env=None):
    r = subprocess.run([str(a) for a in args], cwd=cwd, capture_output=True, input=stdin, env=env)
    out = r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")
    if check and r.returncode != 0:
        raise AssertionError(f"命令失败：{' '.join(map(str, args))}\n{out}")
    return out


def git(cwd, *args, check=True):
    return run("git", "-c", "user.name=loom-test", "-c", "user.email=loom-test@example.com", *args, cwd=cwd, check=check)


def commit(cwd, msg):
    git(cwd, "add", "-A")
    git(cwd, "commit", "-qm", msg)


def read(p):
    return Path(p).read_bytes().decode("utf-8").replace("\r\n", "\n")


def write(p, text):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_bytes(text.encode("utf-8"))


def check(cond, msg, detail=""):
    global passed
    if not cond:
        raise AssertionError(f"✗ {msg}\n{detail}")
    passed += 1
    print(f"  ✓ {msg}")


def loom(cwd, *args, check=True, env=None):
    return run(PY, SCRIPTS / "loom.py", *args, cwd=cwd, check=check, env=env)


def kb(cwd, *args, **kw):
    return run(PY, SCRIPTS / "kb.py", *args, cwd=cwd, **kw)


def snapshot(cwd, *args, check=True):
    return run(PY, SCRIPTS / "snapshot.py", *args, cwd=cwd, check=check)


def zip_names(path):
    with zipfile.ZipFile(path) as z:
        return set(z.namelist())


def zip_text(path, name):
    with zipfile.ZipFile(path) as z:
        return z.read(name).decode("utf-8")


def hook(script, project_dir, stdin=b"", env=None):
    """模拟 Claude Code 调用 hook：bash run.sh <脚本>，CLAUDE_PROJECT_DIR 为会话启动目录。"""
    e = {**(env or os.environ), "CLAUDE_PROJECT_DIR": str(project_dir)}
    # 按 PATH 解析 bash：Windows 上直接用 "bash" 会先找到 System32 中 WSL 的 bash.exe
    bash = shutil.which("bash") or "bash"
    return subprocess.run([bash, str(SCRIPTS / "run.sh"), *script.split()], cwd=project_dir,
                          capture_output=True, input=stdin, env=e)


def transcript(path, session_id, cwd, text="我们来讨论第一个问题"):
    lines = [
        {"type": "user", "sessionId": session_id, "cwd": str(cwd), "timestamp": "2026-09-30T02:00:00Z",
         "message": {"role": "user", "content": text}},
        {"type": "assistant", "sessionId": session_id, "cwd": str(cwd), "timestamp": "2026-09-30T02:01:00Z",
         "message": {"role": "assistant", "content": [{"type": "text", "text": "好的，先澄清问题。"}]}},
    ]
    write(path, "\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n")


def append_turn(path, text, ts):
    session_id = json.loads(read(path).splitlines()[0])["sessionId"]
    line = {"type": "assistant", "sessionId": session_id, "timestamp": ts,
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}
    write(path, read(path) + json.dumps(line, ensure_ascii=False) + "\n")


def slug(p):
    return re.sub(r"[^A-Za-z0-9]", "-", str(p)).lower()


def frontmatter_keys(text):
    body = text.split("---", 2)[1]
    return {line.split(":", 1)[0].strip() for line in body.splitlines() if line and not line.startswith((" ", "\t"))}


def test_package():
    print("skill 包结构")
    keys = frontmatter_keys(read(SKILL / "SKILL.md"))
    check(keys <= SPEC_FIELDS and {"name", "description"} <= keys, "SKILL.md 的 frontmatter 只用 Agent Skills 规范中的字段", keys)
    desc = re.search(r"^description: (.*)$", read(SKILL / "SKILL.md"), re.M).group(1)
    check(len(desc) <= 1024, f"description 不超过 1024 个字符（{len(desc)}）")
    version = read(SKILL / "VERSION").strip()
    check(json.loads(read(SKILL / ".claude-plugin/plugin.json"))["version"] == version
          and f'version: "{version}"' in read(SKILL / "SKILL.md"), "VERSION、plugin.json、SKILL.md 的版本号一致")
    hooks = json.loads(read(SKILL / "hooks/hooks.json"))["hooks"]
    check(set(hooks) == {"SessionStart", "SessionEnd"}
          and all("${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" in g["hooks"][0]["command"] for v in hooks.values() for g in v),
          "hooks.json 只有 SessionStart、SessionEnd，都通过 run.sh 调用（不用 Stop）")
    refs = re.findall(r"`references/(\w+)\.md`", read(SKILL / "SKILL.md"))
    check(refs and all((SKILL / "references" / f"{r}.md").is_file() for r in refs), "SKILL.md 引用的说明文件都存在")


def test_tail(tmp):
    print("会话尾巴：提交之后的对话并入那次提交")
    p = tmp / "tail"
    p.mkdir()
    loom(p, "init", "--name", "尾巴测试", "--summary", "测试会话尾巴")
    git(p, "init", "-q")
    git(p, "config", "user.name", "loom-test")
    git(p, "config", "user.email", "loom-test@example.com")
    commit(p, "init")
    t = tmp / "tail.jsonl"
    transcript(t, "55555555-tail", p)
    end = json.dumps({"transcript_path": str(t), "cwd": str(p)}).encode()
    hook("export_session", p, stdin=end)
    rel = next((p / "40-Sessions/raw").rglob("*.md")).relative_to(p).as_posix()
    commit(p, "wrapup: 测试")
    count = git(p, "rev-list", "--count", "HEAD")
    status = lambda: git(p, "status", "--porcelain").strip()

    append_turn(t, "已经提交了。", "2026-09-30T02:05:00Z")
    hook("export_session", p, stdin=end)
    check(status() == "" and git(p, "rev-list", "--count", "HEAD") == count
          and "已经提交了" in git(p, "show", f"HEAD:{rel}") and "wrapup: 测试" in git(p, "log", "-1", "--format=%s"),
          "会话结束时尾巴并入 wrapup 提交，提交数不变，工作区干净", status())

    write(p / "30-Wiki/别的.md", "---\ntitle: 别的\n---\n")
    commit(p, "别的提交")
    append_turn(t, "尾巴二。", "2026-09-30T02:06:00Z")
    hook("export_session", p, stdin=end)
    check(rel in status() and "别的提交" in git(p, "log", "-1", "--format=%s"), "最新提交没动过这个文件时不并入，留给下次提交", status())

    commit(p, "wrapup: 第二次")
    git(p, "tag", "设计文档/v1.0")
    append_turn(t, "尾巴三。", "2026-09-30T02:07:00Z")
    hook("export_session", p, stdin=end)
    check(rel in status(), "最新提交打了 tag 时不并入", status())
    git(p, "tag", "-d", "设计文档/v1.0")

    home = tmp / "home-tail"
    prev = home / ".claude" / "projects" / slug(p) / "66666666-prev.jsonl"
    transcript(prev, "66666666-prev", p, "上一次会话")
    env = {**os.environ, "USERPROFILE": str(home), "HOME": str(home)}
    hook("export_session", p, stdin=json.dumps({"transcript_path": str(prev), "cwd": str(p)}).encode())
    commit(p, "wrapup: 上一次")
    append_turn(prev, "没有触发 SessionEnd 的尾巴。", "2026-09-30T02:08:00Z")
    r = hook("kb session-start", p, stdin=json.dumps({"session_id": "77777777-now"}).encode(), env=env)
    check(r.returncode == 0 and status() == "" and "wrapup: 上一次" in git(p, "log", "-1", "--format=%s"),
          "SessionStart 兜底：上次会话没触发 SessionEnd，尾巴也会并入", status() + r.stderr.decode("utf-8", "replace"))


def note(type_, title, extra=""):
    return f"---\ntype: {type_}\ntitle: {title}\ncreated: 2026-10-01\nupdated: 2026-10-01\ntags: []\n{extra}---\n\n# {title}\n\n"


def test_snapshot(tmp):
    print("快照：发布")
    a = tmp / "share-a"
    a.mkdir()
    loom(a, "init", "--name", "甲 项目", "--summary", "发布方", "--modules", "outputs")
    write(a / "30-Wiki/概念.md", note("wiki", "概念", 'raws: ["[[2026-10-01_0900_abcd]]"]\nsources: ["[[2026-10-01_讨论]]"]\n')
          + "结论一。见 [[细节]]、[[DR-2026-001_选型|选型决定]] 和 [[2026-10-01_讨论]]。\n\n`[[代码里的不算]]`\n\n"
            "## 变更记录\n\n- 2026-10-01：创建\n\n### 更早\n\n- 旧\n")
    write(a / "30-Wiki/细节.md", note("wiki", "细节") + "正文。\n\n## 变更记录\n\n- x\n\n## 相关\n\n- [[概念]]\n")
    write(a / "30-Wiki/内部.md", note("wiki", "内部", "publish: false\n") + "不公开的判断。\n")
    write(a / "40-Sessions/notes/2026-10-01_讨论.md", note("session", "讨论") + "过程。\n")
    write(a / "40-Sessions/decisions/DR-2026-001_选型.md", note("decision", "选型", "publish: true\n") + "理由。\n")
    write(a / "40-Sessions/raw/2026-10/2026-10-01_0900_abcd.md", "---\ntype: raw\n---\n对话原文\n")
    write(a / "50-Outputs/报告/报告.md",
          note("output", "报告", 'status: released\nversion: 1.0\ndecisions: ["[[DR-2026-001_选型]]"]\nsources: ["[[概念]]"]\n')
          + "正文。\n\n## 版本历史\n\n| 版本 |\n|---|\n| 1.0 |\n")
    write(a / "50-Outputs/草稿/草稿.md", note("output", "草稿", "status: draft\nversion: 0.1\n"))
    write(a / "50-Outputs/_exports/报告-v1.0.pdf", "pdf")
    exports = a / "50-Outputs/_exports"

    plan = snapshot(a, "plan")
    check("默认值" in plan and "[新] 30-Wiki/概念.md" in plan and "30-Wiki/内部.md：笔记标了 publish: false" in plan
          and "50-Outputs/草稿/草稿.md：产出物的状态是 draft" in plan, "plan 按默认规则列出要发布和被排除的笔记", plan)
    check(not list(exports.glob("*.zip")), "plan 不写任何文件")

    snapshot(a, "build")
    z1 = next(exports.glob("*.zip"))
    names = zip_names(z1)
    check(z1.name == f"甲-项目-快照-{date.today()}.zip"
          and {"loom-snapshot.json", "快照说明.md", "30-Wiki/概念.md", "30-Wiki/细节.md", "50-Outputs/报告/报告.md",
               "10-Brief/项目简报.md", "00-Hub/roadmap.md"} <= names,
          "build 生成 zip：包含 wiki、简报、已发布的产出物、roadmap、清单和说明", names)
    check(not any(n.startswith(("40-Sessions/", "50-Outputs/_exports/", "50-Outputs/草稿/"))
                  or n in ("30-Wiki/内部.md", "00-Hub/timeline.md", "00-Hub/log.md", "00-Hub/hot.md") for n in names),
          "快照不含对话、纪要、决策记录（标了 publish: true 也不行）、时间线、日志、草稿和 publish: false 的笔记", names)
    text = zip_text(z1, "30-Wiki/概念.md")
    check("raws:" not in text and "变更记录" not in text and "更早" not in text and "结论一" in text,
          "清洗：去掉 raws 字段和变更记录段落（含子段落）", text)
    check("[[细节]]" in text and "选型决定" in text and "[[DR-2026-001" not in text and "[[2026-10-01_讨论]]" not in text
          and "2026-10-01_讨论" in text and "`[[代码里的不算]]`" in text,
          "清洗：指向未发布笔记的链接转为纯文本，指向已发布笔记的和代码里的保留", text)
    text = zip_text(z1, "50-Outputs/报告/报告.md")
    check("decisions:" not in text and "版本历史" not in text and "[[概念]]" in text, "清洗：去掉 decisions 字段和版本历史", text)
    text = zip_text(z1, "30-Wiki/细节.md")
    check("变更记录" not in text and "## 相关" in text, "删除段落后，后面的同级段落保留", text)
    manifest = json.loads(zip_text(z1, "loom-snapshot.json"))
    check(manifest["project"] == "甲 项目" and manifest["loom_snapshot"] == 1
          and set(manifest["files"]) == names - {"loom-snapshot.json", "快照说明.md"}, "清单记录了项目名和每个文件的校验值")
    check("raws:" in read(a / "30-Wiki/概念.md") and "变更记录" in read(a / "30-Wiki/概念.md"), "知识库中的源文件没有被改动")

    kb_file = read(a / ".kb.json")
    meta = json.loads(kb_file)
    meta["publish"] = {"include": ["30-Wiki/", "00-Hub/hot.md", "40-Sessions/"], "exclude": ["30-Wiki/细节.md"]}
    write(a / ".kb.json", json.dumps(meta, ensure_ascii=False))
    plan = snapshot(a, "plan")
    check("来自 .kb.json" in plan and "[新] 00-Hub/hot.md" in plan and "30-Wiki/细节.md：匹配 exclude" in plan
          and "[改] 30-Wiki/概念.md" in plan and "- 10-Brief/项目简报.md" in plan,
          "plan 按 .kb.json 的 publish 规则计算，并和上一份快照比较", plan)
    check("`40-Sessions/` 属于硬性排除" in plan and "40-Sessions/notes" not in plan, "配置也不能打开硬性排除的目录", plan)
    write(a / ".kb.json", kb_file)

    write(a / "30-Wiki/细节.md", read(a / "30-Wiki/细节.md").replace("正文。", "正文，有更新。"))
    plan = snapshot(a, "plan")
    check("[改] 30-Wiki/细节.md" in plan and "[未变] 30-Wiki/概念.md" in plan, "修改笔记后，plan 只把它标为改", plan)
    snapshot(a, "build")
    z2 = exports / f"{z1.stem}-2.zip"
    check(z2.is_file(), "同一天再次发布，文件名加序号")

    print("快照：导入")
    b = tmp / "share-b"
    b.mkdir()
    loom(b, "init", "--name", "乙项目")
    raw = b / "20-Sources/raw/2026-10"
    raw.mkdir(parents=True)
    shutil.copy(z1, raw / z1.name)
    out = snapshot(b, "open", raw / z1.name)
    dest = Path(re.search(r"已解压到：(.+)", out).group(1).strip())
    check("没有找到同一项目的上一份快照" in out and f"## 新增（{len(manifest['files'])}）" in out
          and "结论一" in read(dest / "30-Wiki/概念.md"), "open 把快照解压到临时目录，全部列为新增", out)
    shutil.rmtree(dest)
    extracted = raw / f"{z1.stem}.md"
    check(extracted.is_file() and "type: source" in read(extracted) and "## 30-Wiki/概念.md" in read(extracted)
          and "结论一" in read(extracted), "open 在 zip 旁边生成同名的提取文本")
    write(b / "20-Sources/sources-index.md", read(b / "20-Sources/sources-index.md")
          + f"| S001 | [[{z1.stem}]] | 知识库快照 | 甲 项目 | 2026-10-01 | 已消化 | 对方的快照 |\n")
    lint = kb(b, "lint")
    check("✅" in lint, "整个快照在资料清单中登记一行，lint 通过", lint)
    shutil.copy(z2, raw / z2.name)
    out = snapshot(b, "open", raw / z2.name)
    check(f"上一份快照：{z1.name}" in out and "## 修改（1）" in out and "- 30-Wiki/细节.md" in out and "## 新增（0）" in out,
          "导入第二份快照时，只列出相对上一份的变化", out)
    shutil.rmtree(Path(re.search(r"已解压到：(.+)", out).group(1).strip()))

    evil = tmp / "evil.zip"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("loom-snapshot.json", json.dumps({"loom_snapshot": 1, "project": "x", "files": {}}))
        z.writestr("../evil.md", "x")
    check("不安全的路径" in snapshot(b, "open", evil, check=False), "拒绝解压含 ../ 路径的快照")
    plain = tmp / "plain.zip"
    with zipfile.ZipFile(plain, "w") as z:
        z.writestr("a.md", "x")
    check("不是 Loom 快照" in snapshot(b, "open", plain, check=False), "没有清单的 zip 不当作快照")


def main():
    tmp = Path(tempfile.mkdtemp(prefix="loom-test-")).resolve()
    print(f"临时目录：{tmp}")
    test_package()

    print("S1 从一句话想法起步")
    p1 = tmp / "idea"
    p1.mkdir()
    out = loom(p1, "init", "--name", "测试想法", "--summary", "一个用来测试的想法")
    meta = json.loads(read(p1 / ".kb.json"))
    check(meta["modules"] == ["core"] and meta["schema"] == 1, ".kb.json：只启用 core，结构版本 1")
    for f in ["AGENTS.md", "CLAUDE.md", "00-Hub/hot.md", "00-Hub/timeline.md", "00-Hub/roadmap.md",
              "10-Brief/项目简报.md", "20-Sources/sources-index.md", "20-Sources/inbox/.gitkeep", ".gitignore"]:
        check((p1 / f).exists(), f"生成了 {f}")
    check(not any((p1 / d).exists() for d in ("scripts", ".claude", "90-Templates", "30-Wiki", "repos", "LOOM-RULES.md")),
          "项目中没有脚本、skill、hook、模板，未启用模块的目录也没有创建")
    agents = read(p1 / "AGENTS.md")
    check("测试想法" in agents and "<!-- loom:begin -->" in agents and "{{" not in agents, "AGENTS.md 包含项目名和 Loom 区块")
    check(read(p1 / "CLAUDE.md").startswith("@AGENTS.md"), "CLAUDE.md 引用 AGENTS.md")
    check("已经是 Loom 项目" in loom(p1, "init", "--name", "x", check=False), "重复初始化被拒绝")
    (p1 / "sub").mkdir()
    check("位于 Loom 项目" in loom(p1 / "sub", "init", "--name", "x", check=False), "在另一个 Loom 项目内部初始化被拒绝")
    git(p1, "init", "-q")
    commit(p1, "init")

    print("定位知识库根目录")
    deep = p1 / "a" / "b"
    deep.mkdir(parents=True)
    kb(deep, "index")
    check((p1 / "00-Hub/index.md").exists(), "在子目录中运行 kb.py index，索引写到知识库根目录")
    lint = kb(deep, "lint")
    check("✅" in lint, "新项目 lint 通过", lint)
    check("不在 Loom 项目中" in kb(tmp, "index", check=False), "不在 Loom 项目中时报错")
    status = loom(deep, "status", "--no-export")
    check(str(p1) in status and "需要迁移" not in status and "Loom 区块" not in status, "status 找到根目录，结构和区块都正常", status)

    print("hook（Claude Code 增强层）")
    nokb = tmp / "plain"
    nokb.mkdir()
    r = hook("export_session", nokb, stdin=b'{"transcript_path": "x", "cwd": "."}')
    check(r.returncode == 0 and not any(nokb.iterdir()), "不在 Loom 项目中时 run.sh 立即退出，不产生任何文件")
    r = hook("kb session-start", p1)
    ss = r.stdout.decode("utf-8", "replace")
    check("测试想法" in ss and "Loom 通用规则" in ss and "00-Hub/hot.md" in ss, "SessionStart 注入项目状态、通用规则和 hot.md", ss[:300])
    demo = p1 / "repos" / "demo"
    demo.mkdir(parents=True)
    fake = tmp / "t1.jsonl"
    transcript(fake, "abcd1234-0000", demo)
    r = hook("export_session", demo, stdin=json.dumps({"transcript_path": str(fake), "cwd": str(demo)}).encode())
    raws = list((p1 / "40-Sessions/raw").rglob("*.md"))
    check(r.returncode == 0 and len(raws) == 1, "在 repos/demo 中启动的会话，SessionEnd hook 把对话导出到知识库",
          r.stderr.decode("utf-8", "replace"))
    check("launched_in: repos/demo" in read(raws[0]), "导出的对话记录了启动目录")
    hook("export_session", demo, stdin=json.dumps({"transcript_path": str(fake), "cwd": str(demo)}).encode())
    check(len(list((p1 / "40-Sessions/raw").rglob("*.md"))) == 1, "重复导出覆盖同一个文件")
    shutil.rmtree(p1 / "repos")
    test_tail(tmp)

    print("补导出与归档")
    home = tmp / "home"
    projects = home / ".claude" / "projects"
    transcript(projects / slug(p1) / "root.jsonl", "11111111-root", p1, "根目录会话")
    transcript(projects / f"{slug(p1)}-repos-demo" / "sub.jsonl", "22222222-sub", p1 / "repos" / "demo", "子目录会话")
    sibling = tmp / "idea-studio"
    transcript(projects / slug(sibling) / "sib.jsonl", "33333333-sib", sibling, "兄弟目录会话")
    env = {**os.environ, "USERPROFILE": str(home), "HOME": str(home)}
    out = run(PY, SCRIPTS / "export_session.py", "--all", cwd=p1, env=env)
    check("11111111" in out and "22222222" in out, "--all 导出根目录和子目录启动的会话", out)
    check("33333333" not in out, "--all 没有误收名字相近的兄弟目录的会话", out)
    transcript(projects / slug(p1) / "later.jsonl", "44444444-later", p1, "后来的会话")
    status = loom(p1, "status", env=env)
    check((next((p1 / "40-Sessions/raw").rglob("*_44444444.md"), None) is not None) and "未归档" in status,
          "status 补导出了新会话，并提示未归档", status)
    raw_dir = p1 / "40-Sessions/raw"
    stems = [p.stem for p in raw_dir.rglob("*.md")]
    write(p1 / "40-Sessions/notes/2026-09-30_测试.md",
          f"---\ntype: session\ntitle: 测试\ncreated: 2026-09-30\nupdated: 2026-09-30\ntags: []\n"
          f"raws: [\"[[{stems[0]}]]\"]\n---\n\n# 测试\n")
    write(p1 / "40-Sessions/notes/_skipped.md",
          read(p1 / "40-Sessions/notes/_skipped.md") + "".join(f"- [[{s}]]\n" for s in stems[1:]))
    check("没有未归档" in kb(p1, "unarchived"), "写纪要或登记到 _skipped.md 后，不再提示未归档")
    commit(p1, "sessions")

    print("Loom 区块")
    write(p1 / "AGENTS.md", read(p1 / "AGENTS.md").replace("本项目是一个 Loom 项目知识库", "被改坏的区块")
          + "\n## 用户自己加的一节\n- 保留我\n")
    check("Loom 区块不是当前版本" in loom(p1, "status", "--no-export"), "status 发现 Loom 区块被改动")
    loom(p1, "refresh-block")
    agents = read(p1 / "AGENTS.md")
    check("被改坏的区块" not in agents and "本项目是一个 Loom 项目知识库" in agents and "保留我" in agents,
          "refresh-block 只替换区块内容，区块外的内容保留")

    print("S7 启用模块")
    loom(p1, "module", "add", "engineering", "outputs")
    meta = json.loads(read(p1 / ".kb.json"))
    check(meta["modules"] == ["core", "engineering", "outputs"], ".kb.json 的模块列表已更新")
    check((p1 / "repos.yaml").exists() and (p1 / "repos/.gitkeep").exists(), "engineering：repos.yaml 和 repos/ 已创建")
    gi = read(p1 / ".gitignore").splitlines()
    check("/repos/" in gi and "*.loom-new" in gi, ".gitignore 按行合并，加入了 /repos/")
    check(json.loads(read(p1 / ".obsidian/app.json"))["userIgnoreFilters"] == ["repos/"], "Obsidian 排除了 repos/")
    commit(p1, "modules")

    print("S4 代码库")
    remote = tmp / "remote-repo"
    remote.mkdir()
    git(remote, "init", "-q")
    write(remote / "main.py", "print(1)\n")
    commit(remote, "first")
    write(p1 / "repos.yaml", read(p1 / "repos.yaml") + f"  - name: demo\n    remote: {remote.as_posix()}\n    role: 测试\n")
    out = run(PY, SCRIPTS / "sync_repos.py", cwd=p1)
    check((p1 / "repos/demo/main.py").exists() and "干净" in out, "sync_repos 克隆了代码库，并显示状态", out)
    check(not (p1 / "repos/demo/.claude").exists(), "不再往代码库里注入任何配置")
    check("repos/" not in git(p1, "status", "--porcelain"), "外层仓库看不到代码库的内容")

    print("模板")
    check(Path(loom(p1, "template", "会话纪要").strip()) == SKILL / "assets/templates/notes/会话纪要.md", "默认使用 skill 自带的模板")
    write(p1 / "90-Templates/会话纪要.md", "---\ntype: session\ntitle: 自定义\n---\n")
    check(Path(loom(p1, "template", "会话纪要").strip()) == p1 / "90-Templates/会话纪要.md", "项目中的同名模板优先")
    check("可用模板" in loom(p1, "template", "不存在", check=False), "模板不存在时列出可用模板")
    test_snapshot(tmp)

    print("S2 从已有资料起步")
    p2 = tmp / "materials"
    originals = {"需求说明.md": "# 需求\n内容\n", "docs/调研.txt": "调研\n", "AGENTS.md": "# 我自己的说明\n"}
    for f, text in originals.items():
        write(p2 / f, text)
    loom(p2, "init", "--name", "资料项目", "--modules", "research")
    check(all(read(p2 / f) == text for f, text in originals.items()), "已有资料和说明文件保持原样")
    check((p2 / "AGENTS.md.loom-new").exists(), "已存在的 AGENTS.md 不被覆盖，模板写入 .loom-new")
    check(".loom-new" in loom(p2, "doctor"), "doctor 提示有未处理的 .loom-new")

    print("迁移：Loom 0.1 项目 → 结构版本 1")
    p3 = tmp / "legacy"
    tpl = read(SKILL / "assets/templates/notes/会话纪要.md")
    write(p3 / ".kb.json", json.dumps({"name": "旧项目", "summary": "", "created": "2026-09-30", "status": "active",
                                       "modules": ["core", "engineering"], "python": "py",
                                       "loom": {"version": "0.1.0", "commit": "abc"}}, ensure_ascii=False))
    write(p3 / "CLAUDE.md", "# 旧项目\n\n> 一句话\n\n@LOOM-RULES.md\n\n本项目由 Loom 管理。通用规则见上面引入的 `LOOM-RULES.md`。\n\n"
                            "## 项目特有约定\n\n- 我的约定\n")
    write(p3 / "LOOM-RULES.md", "旧规则\n")
    write(p3 / "scripts/kb.py", "# 旧脚本\n")
    write(p3 / "scripts/my_tool.py", "# 用户自己的脚本\n")
    write(p3 / ".claude/skills/wrapup/SKILL.md", "---\nname: wrapup\n---\n`$PY` 指 `.kb.json` 中 `python` 字段的值\n")
    write(p3 / ".claude/skills/mine/SKILL.md", "---\nname: mine\n---\n用户自己的 skill\n")
    old_hook = {"type": "command", "command": 'py "$CLAUDE_PROJECT_DIR/scripts/export_session.py"'}
    write(p3 / ".claude/settings.json", json.dumps({"permissions": {"allow": ["Bash(ls)"]},
                                                    "hooks": {"Stop": [{"hooks": [old_hook]}]}}))
    write(p3 / "90-Templates/会话纪要.md", tpl)
    write(p3 / "90-Templates/自定义.md", "我的模板\n")
    write(p3 / "repos/demo/.claude/settings.local.json", json.dumps({"hooks": {"Stop": [{"hooks": [
        {"type": "command", "command": 'py "$CLAUDE_PROJECT_DIR/../../scripts/export_session.py"'}]}]}}))
    write(p3 / "repos/demo/.git/info/exclude", "# git 默认内容\n.claude/settings.local.json\n")
    write(p3 / ".gitignore", ".loom/\n/repos/\n")
    git(p3, "init", "-q")
    commit(p3, "0.1 项目")
    check("需要迁移" in loom(p3, "status", "--no-export"), "status 发现需要迁移")
    dry = loom(p3, "migrate", "--dry-run")
    check("预览" in dry and (p3 / "LOOM-RULES.md").exists(), "migrate --dry-run 只预览，不改动", dry)
    out = loom(p3, "migrate")
    meta = json.loads(read(p3 / ".kb.json"))
    check(meta["schema"] == 1 and "python" not in meta and "loom" not in meta, ".kb.json 已迁移到结构版本 1", out)
    check(not (p3 / "LOOM-RULES.md").exists() and not (p3 / "scripts/kb.py").exists()
          and (p3 / "scripts/my_tool.py").exists(), "删除了 Loom 0.1 的规则和脚本，保留用户自己的脚本")
    check(not (p3 / ".claude/skills/wrapup").exists() and (p3 / ".claude/skills/mine").exists(),
          "删除了 Loom 0.1 的 skill，保留用户自己的 skill")
    s = json.loads(read(p3 / ".claude/settings.json"))
    check("hooks" not in s and s["permissions"]["allow"] == ["Bash(ls)"], "去掉了 settings.json 中 Loom 的 hook，保留其他配置")
    check(not (p3 / "90-Templates/会话纪要.md").exists() and (p3 / "90-Templates/自定义.md").exists(),
          "删除了与默认模板相同的模板，保留自定义模板")
    check(not (p3 / "repos/demo/.claude/settings.local.json").exists()
          and ".claude/settings.local.json" not in read(p3 / "repos/demo/.git/info/exclude"), "清除了注入代码库的 hook")
    agents = read(p3 / "AGENTS.md")
    check("我的约定" in agents and "LOOM-RULES" not in agents and "<!-- loom:begin -->" in agents
          and read(p3 / "CLAUDE.md").startswith("@AGENTS.md"), "CLAUDE.md 的内容移到了 AGENTS.md，并加入了 Loom 区块", agents)
    status = loom(p3, "status", "--no-export")
    check("需要迁移" not in status and "Loom 区块" not in status, "迁移后 status 正常", status)
    check("不需要迁移" in loom(p3, "migrate"), "再次迁移提示不需要迁移")

    print("部署")
    src = tmp / "loom-src"
    git(tmp, "clone", "-q", REPO, src)
    dirty = [line for line in git(REPO, "status", "--porcelain").splitlines() if line.strip()]
    if dirty:  # 让临时 clone 与工作区一致，部署测试针对的是当前代码
        for d in ("skills", "tools", "tests"):
            shutil.rmtree(src / d, ignore_errors=True)
            shutil.copytree(REPO / d, src / d)
        commit(src, "工作区的改动")
    home2 = tmp / "home2"
    for d in (".claude", ".codex"):
        (home2 / d).mkdir(parents=True)
    out = run(PY, src / "tools/deploy.py", "--home", home2, "--skip-tests")
    canonical = home2 / ".agents/skills/loom"
    marker = json.loads(read(canonical / ".loom-deploy.json"))
    check((canonical / "SKILL.md").exists() and marker["version"] == read(SKILL / "VERSION").strip(), "部署了 skill 本体并写入部署标记", out)
    check((home2 / ".claude/skills/loom/SKILL.md").exists() and (home2 / ".codex/skills/loom/SKILL.md").exists(),
          "Claude Code 和 Codex 的 skills 目录都能访问到 loom", out)
    check(not (home2 / ".gemini").exists(), "默认不链接未指定的工具")
    out = run(PY, src / "tools/deploy.py", "--home", home2, "--skip-tests")
    check((home2 / ".claude/skills/loom/SKILL.md").exists() and "已部署" in out, "重复部署正常替换", out)
    write(src / "skills/loom/SKILL.md", read(src / "skills/loom/SKILL.md") + "\n改动\n")
    check("未提交的改动" in run(PY, src / "tools/deploy.py", "--home", home2, "--skip-tests", check=False), "源码有未提交改动时拒绝部署")
    git(src, "checkout", "--", ".")
    home3 = tmp / "home3"
    write(home3 / ".agents/skills/loom/SKILL.md", "别人的 loom\n")
    check("不覆盖" in run(PY, src / "tools/deploy.py", "--home", home3, "--skip-tests", check=False), "不覆盖不是由 deploy 创建的目录")
    out = run(PY, src / "tools/deploy.py", "--home", home2, "--skip-tests", "--claude-hooks")
    s = json.loads(read(home2 / ".claude/settings.json"))
    check(set(s["hooks"]) == {"SessionStart", "SessionEnd"}, "--claude-hooks 把 hook 写进 settings.json", out)
    run(PY, src / "tools/deploy.py", "--home", home2, "--skip-tests", "--claude-hooks")
    s = json.loads(read(home2 / ".claude/settings.json"))
    check(len(s["hooks"]["SessionEnd"]) == 1, "重复写入 hook 不会产生重复项")
    run_sh = f'bash "{(home2 / ".agents/skills/loom").as_posix()}/scripts/run.sh"'
    other = {"type": "command", "command": "echo 别人的 Stop hook"}
    s["hooks"]["Stop"] = [{"hooks": [{"type": "command", "command": f"{run_sh} export_session", "timeout": 30}]},
                          {"hooks": [other]}]
    write(home2 / ".claude/settings.json", json.dumps(s, ensure_ascii=False))
    out = run(PY, src / "tools/deploy.py", "--home", home2, "--skip-tests", "--claude-hooks")
    s = json.loads(read(home2 / ".claude/settings.json"))
    check(s["hooks"]["Stop"] == [{"hooks": [other]}], "--claude-hooks 清理旧版的 Stop 导出 hook，保留别人的 Stop hook", out)

    print(f"\n全部通过：{passed} 项检查")
    if "--keep" in sys.argv:
        print(f"已保留临时目录：{tmp}")
    else:
        shutil.rmtree(tmp, onerror=lambda f, p, _: (os.chmod(p, stat.S_IWRITE), f(p)))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        main()
    except AssertionError as e:
        print(f"\n{e}")
        sys.exit(1)
