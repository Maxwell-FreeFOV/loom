"""Loom 端到端测试：在临时目录中模拟安装、会话导出与归档、追加模块、代码库同步、升级和资料编目。

用法：py tests/smoke_test.py [--keep]
  测试使用 Loom 仓库中已提交的内容，修改后请先提交再运行。--keep 表示保留临时目录，便于检查。
"""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

LOOM = Path(__file__).resolve().parents[1]
PY = sys.executable
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


def loom(proj, *args, check=True):
    return run(PY, proj / ".loom" / "tools" / "loom.py", *args, "--project", proj, cwd=proj, check=check)


def kb(proj, *args, **kw):
    return run(PY, "scripts/kb.py", *args, cwd=proj, **kw)


def transcript(path, session_id, cwd, text="我们来讨论第一个问题"):
    lines = [
        {"type": "user", "sessionId": session_id, "cwd": str(cwd), "timestamp": "2026-09-30T02:00:00Z",
         "message": {"role": "user", "content": text}},
        {"type": "assistant", "sessionId": session_id, "cwd": str(cwd), "timestamp": "2026-09-30T02:01:00Z",
         "message": {"role": "assistant", "content": [{"type": "text", "text": "好的，先澄清问题。"}]}},
    ]
    write(path, "\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n")


def edit(path, old, new):
    text = read(path)
    assert old in text, f"{path} 中找不到 {old!r}"
    write(path, text.replace(old, new, 1))


def main():
    tmp = Path(tempfile.mkdtemp(prefix="loom-test-")).resolve()
    print(f"临时目录：{tmp}")
    src = tmp / "loom-src"  # Loom 的一个 clone，用来模拟发布新版本，不影响真实仓库
    git(tmp, "clone", "-q", LOOM, src)

    def new_project(name):
        proj = tmp / name
        proj.mkdir(exist_ok=True)
        git(proj, "clone", "-q", src, ".loom")
        return proj

    print("S1 从一句话想法起步：只安装 core")
    p1 = new_project("idea")
    loom(p1, "install", "--name", "测试想法", "--summary", "一个用来测试的想法")
    meta = json.loads(read(p1 / ".kb.json"))
    check(meta["modules"] == ["core"], ".kb.json 只启用了 core")
    for f in ["CLAUDE.md", "LOOM-RULES.md", "00-Hub/hot.md", "00-Hub/timeline.md", "00-Hub/roadmap.md",
              "10-Brief/项目简报.md", "20-Sources/sources-index.md", "scripts/kb.py", "scripts/export_session.py",
              ".claude/skills/wrapup/SKILL.md", "90-Templates/会话纪要.md", "20-Sources/inbox/.gitkeep"]:
        check((p1 / f).exists(), f"生成了 {f}")
    check(not (p1 / "30-Wiki").exists() and not (p1 / "repos").exists(), "未启用模块的目录没有创建")
    claude_md = read(p1 / "CLAUDE.md")
    check("测试想法" in claude_md and "{{" not in claude_md and "@LOOM-RULES.md" in claude_md, "CLAUDE.md 占位符已替换，并引用了 LOOM-RULES.md")
    check("{{title}}" in read(p1 / "90-Templates/会话纪要.md"), "Obsidian 模板变量 {{title}} 保持不变")
    check(".loom/" in read(p1 / ".gitignore").splitlines(), ".gitignore 包含 .loom/")
    hooks = json.loads(read(p1 / ".claude/settings.json"))["hooks"]
    check(set(hooks) == {"SessionStart", "Stop", "SessionEnd"}, "settings.json 配置了三个 hook")
    check(meta["python"] in hooks["Stop"][0]["hooks"][0]["command"], "hook 使用检测到的 Python 命令")
    git(p1, "init", "-q")
    commit(p1, "init")
    check(".loom/" not in git(p1, "ls-files"), ".loom 没有进入项目仓库")
    kb(p1, "index")
    check((p1 / "00-Hub/index.md").exists(), "kb.py index 生成了索引")
    lint = kb(p1, "lint")
    check("死链" not in lint and "缺少 frontmatter" not in lint, "新项目的 lint 没有死链和 frontmatter 问题", lint)
    ss = kb(p1, "session-start")
    check("测试想法" in ss and "00-Hub/hot.md" in ss, "session-start 输出项目上下文")
    check("托管文件完整" in loom(p1, "doctor"), "doctor 检查通过")
    check("已经初始化" in loom(p1, "install", "--name", "x", check=False), "重复 install 被拒绝")

    print("会话导出与归档")
    fake = tmp / "t1.jsonl"
    transcript(fake, "abcd1234-0000", p1)
    run(PY, "scripts/export_session.py", fake, cwd=p1)
    raws = list((p1 / "40-Sessions/raw").rglob("*.md"))
    check(len(raws) == 1, "对话导出到了 40-Sessions/raw/")
    check(raws[0].stem in kb(p1, "unarchived"), "新会话出现在未归档列表中")
    check("尚未归档" in kb(p1, "session-start"), "session-start 提醒有未归档的会话")
    write(p1 / "40-Sessions/notes/2026-09-30_测试.md",
          f"---\ntype: session\ntitle: 测试\ncreated: 2026-09-30\nupdated: 2026-09-30\ntags: []\n"
          f"raws: [\"[[{raws[0].stem}]]\"]\n---\n\n# 测试\n")
    check("没有未归档" in kb(p1, "unarchived"), "写了纪要之后不再提示未归档")
    run(PY, "scripts/export_session.py", cwd=p1, stdin=json.dumps({"transcript_path": str(fake)}).encode())
    check(len(list((p1 / "40-Sessions/raw").rglob("*.md"))) == 1, "hook 模式重复导出时覆盖同一个文件")

    # --all：按根目录 slug 前缀扫描，并用 cwd 排除名字相近的兄弟目录
    home = tmp / "home"
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(p1)).lower()
    projects = home / ".claude" / "projects"
    transcript(projects / slug / "root.jsonl", "11111111-root", p1, "根目录会话")
    transcript(projects / f"{slug}-repos-demo" / "sub.jsonl", "22222222-sub", p1 / "repos" / "demo", "子目录会话")
    sibling = tmp / "idea-studio"
    transcript(projects / re.sub(r"[^A-Za-z0-9]", "-", str(sibling)).lower() / "sib.jsonl", "33333333-sib", sibling, "兄弟目录会话")
    env = {**os.environ, "USERPROFILE": str(home), "HOME": str(home)}
    out = run(PY, "scripts/export_session.py", "--all", cwd=p1, env=env)
    check("11111111" in out and "22222222" in out, "--all 导出了根目录和子目录启动的会话", out)
    check("33333333" not in out, "--all 没有误收名字相近的兄弟目录的会话", out)
    sub_raw = next((p1 / "40-Sessions/raw").rglob("*_22222222.md"))
    check("launched_in: repos/demo" in read(sub_raw), "子目录会话记录了启动目录")
    raw_dir = p1 / "40-Sessions/raw"
    skipped = "".join(f"- [[{p.stem}]]\n" for sid in ("11111111", "22222222") for p in raw_dir.rglob(f"*_{sid}.md"))
    write(p1 / "40-Sessions/notes/_skipped.md", read(p1 / "40-Sessions/notes/_skipped.md") + skipped)
    check("没有未归档" in kb(p1, "unarchived"), "登记到 _skipped.md 的会话不再提示未归档")
    commit(p1, "sessions")

    print("S7 项目演化：追加 engineering 和 outputs 模块")
    loom(p1, "add", "engineering", "outputs")
    meta = json.loads(read(p1 / ".kb.json"))
    check(meta["modules"] == ["core", "engineering", "outputs"], ".kb.json 的模块列表已更新")
    check((p1 / "repos.yaml").exists() and (p1 / "scripts/sync_repos.py").exists()
          and (p1 / "90-Templates/产出文档.md").exists(), "新模块的文件已安装")
    gi = read(p1 / ".gitignore").splitlines()
    check("/repos/" in gi and ".loom/" in gi, ".gitignore 按行合并，加入了 /repos/")
    check(json.loads(read(p1 / ".obsidian/app.json"))["userIgnoreFilters"] == ["repos/"], "Obsidian 排除了 repos/")
    commit(p1, "add modules")

    print("S4 关联代码库")
    remote = tmp / "remote-repo"
    remote.mkdir()
    git(remote, "init", "-q")
    write(remote / "main.py", "print(1)\n")
    commit(remote, "first")
    write(p1 / "repos.yaml", read(p1 / "repos.yaml") + f"  - name: demo\n    remote: {remote.as_posix()}\n    role: 测试\n")
    run(PY, "scripts/sync_repos.py", cwd=p1)
    run(PY, "scripts/sync_repos.py", cwd=p1)  # 再运行一次，确认不会重复注入
    demo = p1 / "repos" / "demo"
    check((demo / "main.py").exists(), "sync_repos 克隆了代码库")
    local = json.loads(read(demo / ".claude/settings.local.json"))
    check(len(local["hooks"]["Stop"]) == 1 and "../../scripts/export_session.py" in local["hooks"]["Stop"][0]["hooks"][0]["command"],
          "代码库中注入了指向知识库脚本的 hook，且只注入一次")
    check(".claude/settings.local.json" in read(demo / ".git/info/exclude"), "settings.local.json 被排除在代码库的版本控制之外")
    check(git(demo, "status", "--porcelain").strip() == "", "代码库的工作区保持干净")
    check("repos/" not in git(p1, "status", "--porcelain"), "外层仓库看不到代码库的内容")
    commit(p1, "repos")

    print("S6 升级")
    wiki_tpl = p1 / "90-Templates/wiki页.md"
    write(wiki_tpl, read(wiki_tpl) + "\n## 本项目自定义段落\n")
    settings = json.loads(read(p1 / ".claude/settings.json"))
    settings["permissions"] = {"allow": ["Bash(ls)"]}
    write(p1 / ".claude/settings.json", json.dumps(settings, ensure_ascii=False, indent=2) + "\n")
    commit(p1, "local customizations")

    core = src / "modules" / "core"
    edit(core / "managed/90-Templates/wiki页.md", "> 一句话：", "> 一句话（新版）：")
    write(core / "managed/LOOM-RULES.md", read(core / "managed/LOOM-RULES.md") + "\n<!-- test v0.2 -->\n")
    write(core / "managed/scripts/new_tool.py", "print('new')\n")
    (core / "managed/90-Templates/资料卡.md").unlink()
    s = json.loads(read(core / "merged/.claude/settings.json"))
    s["hooks"]["PostToolUse"] = [{"hooks": [{"type": "command", "command": "echo post"}]}]
    write(core / "merged/.claude/settings.json", json.dumps(s, ensure_ascii=False, indent=2) + "\n")
    edit(core / "seeded/00-Hub/hot.md", "## 当前重点", "## 当前重点（本周）")
    write(src / "VERSION", "0.2.0\n")
    write(src / "MIGRATIONS.md", read(src / "MIGRATIONS.md") + "\n## 0.2.0\n- 变化：测试\n")
    commit(src, "v0.2.0")
    git(p1 / ".loom", "pull", "-q", "--ff-only")

    dry = loom(p1, "upgrade", "--dry-run")
    check("预览" in dry and "wiki页.md" in dry and "新版" not in read(wiki_tpl), "dry-run 只预览，不写入", dry)
    out = loom(p1, "upgrade")
    t = read(wiki_tpl)
    check("一句话（新版）" in t and "本项目自定义段落" in t, "托管文件三方合并：新版修改和本地修改都保留", out)
    check("test v0.2" in read(p1 / "LOOM-RULES.md"), "没改过的托管文件直接更新")
    check((p1 / "scripts/new_tool.py").exists(), "新版新增的托管文件已安装")
    check(not (p1 / "90-Templates/资料卡.md").exists(), "新版删除、本地没改过的文件被删除")
    s = json.loads(read(p1 / ".claude/settings.json"))
    check("PostToolUse" in s["hooks"] and "Stop" in s["hooks"] and s.get("permissions"), "settings.json 合并：新 hook 已加入，项目自定义的配置保留")
    check("当前重点（本周）" in out and "当前重点（本周）" not in read(p1 / "00-Hub/hot.md"), "种子文件不被修改，报告中给出模板差异")
    check("MIGRATIONS" in out and "重启" in out, "报告提示了迁移说明和重启会话")
    check(json.loads(read(p1 / ".kb.json"))["loom"]["version"] == "0.2.0", ".kb.json 记录了新版本")
    check("已是最新" in loom(p1, "upgrade"), "再次升级提示已是最新")
    commit(p1, "upgrade 0.2.0")

    decision_tpl = p1 / "90-Templates/决策记录.md"
    edit(decision_tpl, "## 4. 分析", "## 4. 分析（本地）")
    commit(p1, "local edit")
    edit(src / "modules/core/managed/90-Templates/决策记录.md", "## 4. 分析", "## 4. 分析（新版）")
    write(src / "VERSION", "0.3.0\n")
    commit(src, "v0.3.0")
    git(p1 / ".loom", "pull", "-q", "--ff-only")
    out = loom(p1, "upgrade")
    check("冲突" in out and "<<<<<<<" in read(decision_tpl), "同一处的修改产生冲突标记", out)
    write(src / "VERSION", "0.3.1\n")
    commit(src, "v0.3.1")
    git(p1 / ".loom", "pull", "-q", "--ff-only")
    check("未提交的改动" in loom(p1, "upgrade", check=False), "工作区不干净时拒绝升级")

    print("S2 从已有资料起步")
    p2 = tmp / "materials"
    originals = {"需求说明.md": "# 需求\n内容\n", "docs/调研.txt": "调研\n"}
    for f, text in originals.items():
        write(p2 / f, text)
    git(p2, "clone", "-q", src, ".loom")
    loom(p2, "install", "--name", "资料项目", "--modules", "research")
    check(all(read(p2 / f) == text for f, text in originals.items()), "已有资料保持原位，内容不变")
    check((p2 / "90-Templates/文献卡.md").exists() and not (p2 / "30-Wiki").exists(), "research 模板已安装，wiki 目录等到用到时再创建")

    p3 = tmp / "existing"
    write(p3 / "CLAUDE.md", "# 我自己的说明\n")
    git(p3, "clone", "-q", src, ".loom")
    loom(p3, "install", "--name", "已有说明")
    check(read(p3 / "CLAUDE.md") == "# 我自己的说明\n" and (p3 / "CLAUDE.md.loom-new").exists(), "已存在的 CLAUDE.md 不被覆盖，新模板写入 .loom-new")
    check(".loom-new" in loom(p3, "doctor"), "doctor 提示有未处理的 .loom-new")

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
