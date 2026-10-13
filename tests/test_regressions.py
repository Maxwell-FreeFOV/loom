"""Loom 的回归测试：阶段 A（会话归属校验、配置损坏处理、链接绕过发布排除、Stop hook 清理、
auto_amend 默认值、快照导入的资源限制与清单校验）与阶段 B（双语初始化、模板 ID 与解析顺序、
决策状态的中英等价、快照说明文件的新旧名兼容、英文段落清洗）。

用法：py -m unittest discover -s tests
  全部用例在临时目录中自建项目，不依赖 CI 之外的资源；文件符号链接用例在 Windows 上
  可能没有创建权限（需要开发者模式或管理员），此时显式跳过并说明覆盖缺口，
  目录级用例退回 cmd /c mklink /J 的目录联接。
"""
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "skills" / "loom"
SCRIPTS = SKILL / "scripts"
PY = sys.executable


def run(*args, cwd=None, stdin=None, env=None):
    r = subprocess.run([str(a) for a in args], cwd=cwd, capture_output=True, input=stdin, env=env)
    return r.returncode, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")


def git(cwd, *args):
    rc, out = run("git", "-c", "user.name=loom-test", "-c", "user.email=loom-test@example.com", *args, cwd=cwd)
    if rc != 0:
        raise AssertionError(f"git {' '.join(map(str, args))} 失败：\n{out}")
    return out


def write(p, text):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_bytes(text.encode("utf-8"))


def read(p):
    return Path(p).read_bytes().decode("utf-8").replace("\r\n", "\n")


def init_project(path, name="测试项目", lang="zh-CN"):
    """初始化一个项目。默认显式 zh-CN，保住针对中文输出的断言；英文行为由 TestBilingual 覆盖。"""
    path.mkdir(parents=True, exist_ok=True)
    rc, out = run(PY, SCRIPTS / "loom.py", "init", "--name", name, "--language", lang, cwd=path)
    if rc != 0:
        raise AssertionError(f"loom init 失败：\n{out}")


def transcript(path, session_id, cwd=...):
    """写一份最小的会话记录；cwd 传 None 表示记录中没有 cwd 字段。"""
    base = {"type": "user", "sessionId": session_id, "timestamp": "2026-09-30T02:00:00Z",
            "message": {"role": "user", "content": "我们来讨论第一个问题"}}
    if cwd is not None:
        base["cwd"] = str(cwd)
    write(path, json.dumps(base, ensure_ascii=False) + "\n")


def slug(p):
    return re.sub(r"[^A-Za-z0-9]", "-", str(p)).lower()


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="loom-reg-")).resolve()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def home_env(self, home):
        return {**os.environ, "USERPROFILE": str(home), "HOME": str(home)}


# ---------- A1：会话归属校验 ----------

class TestSessionOwnership(TempDirTest):
    def export_all(self, proj, home):
        return run(PY, SCRIPTS / "export_session.py", "--all", "--root", proj, cwd=proj, env=self.home_env(home))

    def test_slug_collision(self):
        """名字撞 slug 的兄弟目录（my proj / my-proj）：只导出 cwd 属于本项目的记录。"""
        proj = self.tmp / "my proj"
        sibling = self.tmp / "my-proj"
        init_project(proj)
        sibling.mkdir()
        self.assertEqual(slug(proj), slug(sibling), "fixture 前提：两个路径撞出同一个 slug")
        home = self.tmp / "home"
        transcript(home / ".claude/projects" / slug(proj) / "mine.jsonl", "11111111-mine", proj)
        transcript(home / ".claude/projects" / slug(proj) / "theirs.jsonl", "22222222-theirs", sibling)
        rc, out = self.export_all(proj, home)
        self.assertEqual(rc, 0, out)
        raws = [p.stem for p in (proj / "40-Sessions/raw").rglob("*.md")]
        self.assertTrue(any("11111111" in s for s in raws), f"本项目的会话应导出：{raws}")
        self.assertFalse(any("22222222" in s for s in raws), f"撞名的兄弟目录会话不能混入：{raws}")
        self.assertIn("跳过 1 份无法确认归属的记录", out)

    def test_chinese_and_space_path(self):
        """中文、带空格的项目路径：slug 只做候选筛选，归属由 cwd 确认。"""
        proj = self.tmp / "中文 项目"
        init_project(proj)
        home = self.tmp / "home"
        transcript(home / ".claude/projects" / slug(proj) / "s.jsonl", "33333333-zh", proj)
        rc, out = self.export_all(proj, home)
        self.assertEqual(rc, 0, out)
        self.assertTrue(any("33333333" in p.stem for p in (proj / "40-Sessions/raw").rglob("*.md")), out)

    def test_missing_cwd_skipped_and_reported(self):
        """没有 cwd 的记录无法确认归属，跳过并在 --all 和 status 中报告。"""
        proj = self.tmp / "nocwd"
        init_project(proj)
        home = self.tmp / "home"
        transcript(home / ".claude/projects" / slug(proj) / "s.jsonl", "44444444-nocwd", cwd=None)
        rc, out = self.export_all(proj, home)
        self.assertEqual(rc, 0, out)
        self.assertFalse(list((proj / "40-Sessions/raw").rglob("*.md")), "缺 cwd 的记录不应导出")
        self.assertIn("跳过 1 份无法确认归属的记录", out)
        rc, out = run(PY, SCRIPTS / "loom.py", "status", cwd=proj, env=self.home_env(home))
        self.assertEqual(rc, 0, out)
        self.assertIn("跳过 1 份无法确认归属", out)


# ---------- A2：配置损坏不退回默认值 ----------

class TestConfigError(TempDirTest):
    def setUp(self):
        super().setUp()
        self.proj = self.tmp / "proj"
        init_project(self.proj)
        write(self.proj / ".kb.json", "{这不是合法的 JSON\n")

    def test_snapshot_plan_and_build_blocked(self):
        rc, out = run(PY, SCRIPTS / "snapshot.py", "plan", cwd=self.proj)
        self.assertNotEqual(rc, 0)
        self.assertIn("不是合法的 JSON", out)
        rc, out = run(PY, SCRIPTS / "snapshot.py", "build", cwd=self.proj)
        self.assertNotEqual(rc, 0)
        self.assertIn("不是合法的 JSON", out)
        exports = self.proj / "50-Outputs/_exports"
        produced = list(exports.glob("*.zip")) if exports.exists() else []
        self.assertFalse(produced, "配置损坏时不能产出快照")

    def test_migrate_and_module_add_blocked(self):
        for args in (["migrate"], ["module", "add", "outputs"]):
            rc, out = run(PY, SCRIPTS / "loom.py", *args, cwd=self.proj)
            self.assertNotEqual(rc, 0, f"{args} 应被拒绝")
            self.assertIn("不是合法的 JSON", out)

    def test_session_start_hook_survives(self):
        """SessionStart hook 不能因配置损坏而崩掉：退出码 0，输出醒目的警告。"""
        rc, out = run(PY, SCRIPTS / "kb.py", "session-start", cwd=self.proj, stdin=b"")
        self.assertEqual(rc, 0, out)
        self.assertIn("不是合法的 JSON", out)

    def test_status_and_doctor_warn_and_continue(self):
        for args in (["status", "--no-export"], ["doctor"]):
            rc, out = run(PY, SCRIPTS / "loom.py", *args, cwd=self.proj)
            self.assertEqual(rc, 0, f"{args} 应继续：\n{out}")
            self.assertIn("不是合法的 JSON", out)

    def test_valid_config_without_publish_uses_defaults(self):
        """配置本身合法、只是没有 publish：退回默认发布范围（与配置损坏区分）。"""
        proj = self.tmp / "ok"
        init_project(proj)
        rc, out = run(PY, SCRIPTS / "snapshot.py", "plan", cwd=proj)
        self.assertEqual(rc, 0, out)
        self.assertIn("默认值", out)


class TestInvalidLanguage(TempDirTest):
    """.kb.json 里手工写了不支持的 language：按配置损坏处理，不静默换成另一种语言，也不崩溃。"""

    def setUp(self):
        super().setUp()
        self.proj = self.tmp / "proj"
        init_project(self.proj)
        meta = json.loads(read(self.proj / ".kb.json"))
        meta["language"] = "fr"
        write(self.proj / ".kb.json", json.dumps(meta, ensure_ascii=False) + "\n")

    def test_writing_commands_blocked_with_clear_error(self):
        for script, args in (("loom.py", ["module", "add", "outputs"]), ("loom.py", ["migrate"]),
                             ("loom.py", ["refresh-block"]), ("loom.py", ["template", "session"]),
                             ("snapshot.py", ["plan"])):
            rc, out = run(PY, SCRIPTS / script, *args, cwd=self.proj)
            self.assertNotEqual(rc, 0, f"{script} {args} 应被拒绝")
            self.assertIn("language", out)
            self.assertNotIn("Traceback", out)

    def test_read_only_commands_warn_and_continue(self):
        for script, args in (("loom.py", ["status", "--no-export"]), ("loom.py", ["doctor"]),
                             ("kb.py", ["session-start"])):
            rc, out = run(PY, SCRIPTS / script, *args, cwd=self.proj, stdin=b"")
            self.assertNotIn("Traceback", out, f"{script} {args} 不应崩溃：\n{out}")
        rc, out = run(PY, SCRIPTS / "loom.py", "status", "--no-export", cwd=self.proj)
        self.assertEqual(rc, 0, out)
        self.assertIn("language", out)


# ---------- A3：链接不能绕过发布排除 ----------

class TestLinkBypass(TempDirTest):
    def make_file_link(self, link, target):
        try:
            os.symlink(target, link)
            return True
        except OSError:
            return False

    def make_dir_link(self, link, target):
        try:
            os.symlink(target, link, target_is_directory=True)
            return True
        except OSError:
            pass
        if os.name == "nt":  # 无符号链接权限时退回目录联接
            r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
            return r.returncode == 0
        return False

    def plan(self, proj):
        rc, out = run(PY, SCRIPTS / "snapshot.py", "plan", cwd=proj)
        self.assertEqual(rc, 0, out)
        return out

    def test_file_symlink_outside_excluded(self):
        proj = self.tmp / "proj"
        init_project(proj)
        outside = self.tmp / "secret.md"
        write(outside, "库外的秘密\n")
        if not self.make_file_link(proj / "30-Wiki" / "泄露.md", outside):
            self.skipTest("本平台无法创建文件符号链接（Windows 需要开发者模式或管理员权限）；"
                          "该覆盖缺口由 CI 的 Linux/macOS 任务补上")
        out = self.plan(proj)
        self.assertIn("30-Wiki/泄露.md：链接指向知识库之外", out)

    def test_file_symlink_into_hard_excluded(self):
        proj = self.tmp / "proj"
        init_project(proj)
        target = proj / "40-Sessions/raw/2026-10/raw.md"
        write(target, "对话原文\n")
        if not self.make_file_link(proj / "30-Wiki" / "借道.md", target):
            self.skipTest("本平台无法创建文件符号链接；该覆盖缺口由 CI 的 Linux/macOS 任务补上")
        out = self.plan(proj)
        self.assertIn("属于硬性排除", out)

    def test_file_symlink_inside_ok(self):
        proj = self.tmp / "proj"
        init_project(proj)
        write(proj / "30-Wiki/正主.md", "---\ntype: wiki\ntitle: 正主\n---\n\n内容\n")
        if not self.make_file_link(proj / "30-Wiki/别名.md", proj / "30-Wiki/正主.md"):
            self.skipTest("本平台无法创建文件符号链接；该覆盖缺口由 CI 的 Linux/macOS 任务补上")
        out = self.plan(proj)
        self.assertIn("[新] 30-Wiki/别名.md", out)

    def test_file_symlink_to_out_of_scope_file_excluded(self):
        """发布范围内的链接指向范围外的库内文件（如原始资料）：不能借链接带出去。"""
        proj = self.tmp / "proj"
        init_project(proj)
        target = proj / "20-Sources/raw/2026-10/原件.md"
        write(target, "没打算发布的原件\n")
        if not self.make_file_link(proj / "30-Wiki" / "借道.md", target):
            self.skipTest("本平台无法创建文件符号链接；该覆盖缺口由 CI 的 Linux/macOS 任务补上")
        out = self.plan(proj)
        self.assertIn("不在发布范围内", out)
        self.assertNotIn("] 30-Wiki/借道.md", out)

    def test_broken_symlink_aborts(self):
        proj = self.tmp / "proj"
        init_project(proj)
        if not self.make_file_link(proj / "30-Wiki" / "断链.md", self.tmp / "不存在.md"):
            self.skipTest("本平台无法创建文件符号链接；该覆盖缺口由 CI 的 Linux/macOS 任务补上")
        rc, out = run(PY, SCRIPTS / "snapshot.py", "plan", cwd=proj)
        self.assertNotEqual(rc, 0)
        self.assertIn("无法确认链接", out)

    def test_dir_junction_outside_not_traversed(self):
        """目录联接指向库外：walk 不穿过链接，其中的文件不会进入发布范围。"""
        proj = self.tmp / "proj"
        init_project(proj)
        outside = self.tmp / "outside"
        write(outside / "secret.md", "库外的秘密\n")
        if not self.make_dir_link(proj / "30-Wiki" / "外部", outside):
            self.skipTest("本平台无法创建符号链接或目录联接；该覆盖缺口由 CI 的 Linux/macOS 任务补上")
        out = self.plan(proj)
        self.assertNotIn("secret.md", out)
        self.assertNotIn("外部", out)

    def test_dir_junction_into_sessions_not_published(self):
        """目录联接指向 40-Sessions/：同样不穿过，对话记录不会借链接发布。"""
        proj = self.tmp / "proj"
        init_project(proj)
        write(proj / "40-Sessions/raw/2026-10/raw.md", "对话原文\n")
        if not self.make_dir_link(proj / "30-Wiki" / "借道", proj / "40-Sessions"):
            self.skipTest("本平台无法创建符号链接或目录联接；该覆盖缺口由 CI 的 Linux/macOS 任务补上")
        out = self.plan(proj)
        self.assertNotIn("raw.md", out)


# ---------- A4：清理旧 Stop hook 不误删同组条目 ----------

spec = importlib.util.spec_from_file_location("deploy", REPO / "tools" / "deploy.py")
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


class TestDeployHooks(TempDirTest):
    def setUp(self):
        super().setUp()
        self.home = self.tmp / "home"
        self.canonical = self.home / ".agents/skills/loom"
        self.settings = self.home / ".claude/settings.json"
        self.loom_stop = {"type": "command",
                          "command": f'bash "{self.canonical.as_posix()}/scripts/run.sh" export_session', "timeout": 30}
        self.other = {"type": "command", "command": "echo 别人的 Stop hook"}

    def load_hooks(self):
        return json.loads(read(self.settings)).get("hooks", {})

    def test_same_group_other_hook_kept(self):
        """同一组里 loom 的旧 Stop hook 被清掉，同组的其他 hook 和组属性保留。"""
        write(self.settings, json.dumps({"hooks": {"Stop": [
            {"matcher": "build", "hooks": [self.loom_stop, self.other]}]}}))
        deploy.install_claude_hooks(self.home, self.canonical)
        hooks = self.load_hooks()
        self.assertEqual(hooks["Stop"], [{"matcher": "build", "hooks": [self.other]}])
        self.assertTrue((self.home / ".claude/settings.json.bak-loom").is_file(), "原文件应有备份")

    def test_group_removed_only_when_empty(self):
        """组里只有 loom 的 hook 时整组删除；Stop 空了才删键。"""
        write(self.settings, json.dumps({"hooks": {"Stop": [{"hooks": [self.loom_stop]}]}}))
        deploy.install_claude_hooks(self.home, self.canonical)
        hooks = self.load_hooks()
        self.assertNotIn("Stop", hooks)
        self.assertIn("SessionStart", hooks)
        self.assertIn("SessionEnd", hooks)


# ---------- A6：auto_amend 默认关闭 ----------

class TestAutoAmend(TempDirTest):
    def setUp(self):
        super().setUp()
        self.proj = self.tmp / "proj"
        init_project(self.proj)
        git(self.proj, "init", "-q")
        # export_session.py 自己调 git commit --amend，不带 -c 身份；CI runner 没有全局身份，写进仓库配置
        git(self.proj, "config", "user.name", "loom-test")
        git(self.proj, "config", "user.email", "loom-test@example.com")
        git(self.proj, "add", "-A")
        git(self.proj, "commit", "-qm", "init")
        self.t = self.tmp / "s.jsonl"
        transcript(self.t, "55555555-amend", self.proj)
        self.hook_stdin = json.dumps({"transcript_path": str(self.t), "cwd": str(self.proj)}).encode()

    def hook_export(self):
        rc, out = run(PY, SCRIPTS / "export_session.py", cwd=self.proj, stdin=self.hook_stdin)
        self.assertEqual(rc, 0, out)

    def dirty(self):
        return git(self.proj, "status", "--porcelain").strip()

    def append_turn(self, text):
        line = {"type": "assistant", "sessionId": "55555555-amend", "timestamp": "2026-09-30T02:05:00Z",
                "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}
        write(self.t, read(self.t) + json.dumps(line, ensure_ascii=False) + "\n")

    def test_default_no_amend(self):
        """默认配置：会话尾巴不并入上一次提交，改动留在工作区。"""
        self.hook_export()
        git(self.proj, "add", "-A")
        git(self.proj, "commit", "-qm", "wrapup: 测试")
        self.append_turn("已经提交了。")
        self.hook_export()
        self.assertTrue(self.dirty(), "auto_amend 默认关闭，导出后的改动应留在工作区")
        self.assertEqual(git(self.proj, "log", "-1", "--format=%s").strip(), "wrapup: 测试")

    def test_amend_when_enabled(self):
        """显式开启 auto_amend 后，尾巴并入上一次提交，工作区保持干净。"""
        meta = json.loads(read(self.proj / ".kb.json"))
        meta["auto_amend"] = True
        write(self.proj / ".kb.json", json.dumps(meta, ensure_ascii=False) + "\n")
        self.hook_export()
        git(self.proj, "add", "-A")
        git(self.proj, "commit", "-qm", "wrapup: 测试")
        self.append_turn("已经提交了。")
        self.hook_export()
        self.assertFalse(self.dirty(), "开启 auto_amend 后尾巴应并入提交，工作区干净")
        self.assertIn("已经提交了。", git(self.proj, "show", "--format=", "HEAD"))


# ---------- A7：不可信快照的资源限制与清单校验 ----------

def sha(data):
    return hashlib.sha256(data).hexdigest()


def make_zip(path, members, loom_snapshot=1, manifest_files=None):
    """members: {名称: bytes}；manifest_files 缺省时按 members 如实计算（清单与说明文件除外，与 build 一致）。"""
    files = {n: sha(d) for n, d in members.items()
             if n not in ("loom-snapshot.json", "快照说明.md", "snapshot-readme.md")}
    manifest = {"loom_snapshot": loom_snapshot, "project": "对方项目", "created": "2026-10-01T00:00:00",
                "files": manifest_files if manifest_files is not None else files}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("loom-snapshot.json", json.dumps(manifest))
        for n, d in members.items():
            z.writestr(n, d)


class TestSnapshotOpen(TempDirTest):
    """打开快照时不在任何项目里，用户可见输出按 CLI 默认姿态用英文。"""

    def open_zip(self, z):
        return run(PY, SCRIPTS / "snapshot.py", "open", z, cwd=self.tmp)

    def temp_snapshot_dirs(self):
        return set(Path(tempfile.gettempdir()).glob("loom-snapshot-*"))

    def test_valid_snapshot_opens(self):
        z = self.tmp / "ok.zip"
        make_zip(z, {"30-Wiki/概念.md": "结论一。\n".encode(), "快照说明.md": "说明\n".encode()})
        rc, out = self.open_zip(z)
        self.assertEqual(rc, 0, out)
        self.assertIn("Extracted to", out)
        dest = Path(re.search(r"Extracted to: (.+)", out).group(1).strip())
        self.addCleanup(lambda: shutil.rmtree(dest, ignore_errors=True))
        self.assertIn("结论一", read(dest / "30-Wiki/概念.md"))

    def test_too_many_entries(self):
        z = self.tmp / "many.zip"
        make_zip(z, {f"f{i}.md": b"" for i in range(10001)}, manifest_files={})
        rc, out = self.open_zip(z)
        self.assertNotEqual(rc, 0)
        self.assertIn("exceeding the limit", out)

    def test_single_file_too_large(self):
        z = self.tmp / "big.zip"
        make_zip(z, {"big.bin": b"\0" * (101 * 1024 * 1024)}, manifest_files={})
        rc, out = self.open_zip(z)
        self.assertNotEqual(rc, 0)
        self.assertIn("100 MiB", out)

    def test_total_too_large(self):
        z = self.tmp / "total.zip"
        make_zip(z, {f"part{i}.bin": b"\0" * (100 * 1024 * 1024) for i in range(11)}, manifest_files={})
        rc, out = self.open_zip(z)
        self.assertNotEqual(rc, 0)
        self.assertIn("1 GiB", out)

    def test_duplicate_normalized_paths(self):
        z = self.tmp / "dup.zip"
        make_zip(z, {"a/b.md": b"1", "a\\b.md": b"2"}, manifest_files={"a/b.md": sha(b"1")})
        rc, out = self.open_zip(z)
        self.assertNotEqual(rc, 0)
        self.assertIn("conflicting", out)

    def test_member_not_in_manifest(self):
        z = self.tmp / "extra.zip"
        make_zip(z, {"ok.md": b"1", "extra.md": b"2"}, manifest_files={"ok.md": sha(b"1")})
        rc, out = self.open_zip(z)
        self.assertNotEqual(rc, 0)
        self.assertIn("not in the manifest", out)

    def test_manifest_member_missing_in_zip(self):
        z = self.tmp / "missing.zip"
        make_zip(z, {"ok.md": b"1"}, manifest_files={"ok.md": sha(b"1"), "missing.md": sha(b"2")})
        rc, out = self.open_zip(z)
        self.assertNotEqual(rc, 0)
        self.assertIn("missing from the zip", out)

    def test_hash_mismatch(self):
        z = self.tmp / "tampered.zip"
        make_zip(z, {"ok.md": "被改过的内容".encode()}, manifest_files={"ok.md": sha("原始内容".encode())})
        rc, out = self.open_zip(z)
        self.assertNotEqual(rc, 0)
        self.assertIn("does not match the manifest", out)

    def test_format_version_rejected(self):
        z = self.tmp / "v2.zip"
        make_zip(z, {"ok.md": b"1"}, loom_snapshot=2)
        rc, out = self.open_zip(z)
        self.assertNotEqual(rc, 0)
        self.assertIn("format version", out)

    def test_temp_dir_cleaned_on_failure(self):
        before = self.temp_snapshot_dirs()
        z = self.tmp / "tampered2.zip"
        make_zip(z, {"ok.md": "被改过的内容".encode()}, manifest_files={"ok.md": sha("原始内容".encode())})
        rc, out = self.open_zip(z)
        self.assertNotEqual(rc, 0)
        self.assertEqual(before, self.temp_snapshot_dirs(), "校验失败后临时目录应已清理")

    def test_invalid_prev_leaves_no_temp_dir(self):
        before = self.temp_snapshot_dirs()
        z = self.tmp / "ok.zip"
        make_zip(z, {"30-Wiki/概念.md": "结论一。\n".encode()})
        bogus = self.tmp / "not-a-snapshot.zip"
        with zipfile.ZipFile(bogus, "w") as zf:
            zf.writestr("readme.txt", "x")
        rc, out = run(PY, SCRIPTS / "snapshot.py", "open", z, "--prev", bogus, cwd=self.tmp)
        self.assertNotEqual(rc, 0)
        self.assertIn("is not a Loom snapshot", out)
        self.assertEqual(before, self.temp_snapshot_dirs(), "--prev 无效时不应留下临时目录")


# ---------- 阶段 B：双语与模板 ----------

NOTES_TPL = SKILL / "assets" / "templates" / "notes"


class TestBilingual(TempDirTest):
    def loom(self, *args, cwd):
        return run(PY, SCRIPTS / "loom.py", *args, cwd=cwd)

    def test_init_defaults_to_english(self):
        """省略 --language 时默认 en：配置、简报、hub、Loom 区块都是英文。"""
        proj = self.tmp / "demo"
        proj.mkdir()
        rc, out = self.loom("init", "--name", "demo", cwd=proj)
        self.assertEqual(rc, 0, out)
        meta = json.loads(read(proj / ".kb.json"))
        self.assertEqual(meta["language"], "en")
        self.assertEqual(meta["schema"], 2)
        self.assertIn("Project Brief", read(proj / "10-Brief/project-brief.md"))
        self.assertIn("Current focus", read(proj / "00-Hub/hot.md"))
        self.assertIn("## Loom Knowledge Base", read(proj / "AGENTS.md"))
        self.assertFalse((proj / "10-Brief/项目简报.md").exists(), "新项目不再有中文简报文件名")

    def test_init_zh(self):
        """--language zh-CN：全部产物为中文。"""
        proj = self.tmp / "zh"
        init_project(proj, "中文项目", lang="zh-CN")
        meta = json.loads(read(proj / ".kb.json"))
        self.assertEqual(meta["language"], "zh-CN")
        self.assertIn("项目简报", read(proj / "10-Brief/project-brief.md"))
        self.assertIn("当前重点", read(proj / "00-Hub/hot.md"))
        self.assertIn("## Loom 知识库", read(proj / "AGENTS.md"))

    def test_agents_template_keeps_state_in_hot(self):
        """AGENTS.md 模板不预置"当前阶段"这类会变的状态（指向 hot.md），并预置"以什么为准"和"不再沿用的说法"两小节。"""
        cases = {"zh-CN": (r"(?m)^- 当前阶段：", ("### 以什么为准", "### 不再沿用的说法")),
                 "en": (r"(?m)^- Current phase:", ("### Source of truth", "### Statements no longer in use"))}
        for lang, (state_line, headings) in cases.items():
            proj = self.tmp / lang
            init_project(proj, "demo", lang=lang)
            text = read(proj / "AGENTS.md")
            self.assertNotRegex(text, state_line, lang)
            self.assertIn("`00-Hub/hot.md`", text, lang)
            for heading in headings:
                self.assertIn(heading, text, lang)

    def test_en_project_index_and_lint_are_english(self):
        proj = self.tmp / "en"
        init_project(proj, "enproj", lang="en")
        rc, out = run(PY, SCRIPTS / "kb.py", "index", cwd=proj)
        self.assertEqual(rc, 0, out)
        self.assertIn("title: Index", read(proj / "00-Hub/index.md"))
        rc, out = run(PY, SCRIPTS / "kb.py", "lint", cwd=proj)
        self.assertEqual(rc, 0, out)
        self.assertIn("no issues found", out)

    def test_invalid_language_rejected(self):
        """非法 --language 由 argparse 拒绝，且不产出任何项目文件。"""
        proj = self.tmp / "bad"
        proj.mkdir()
        rc, out = self.loom("init", "--name", "bad", "--language", "fr", cwd=proj)
        self.assertNotEqual(rc, 0)
        self.assertIn("invalid choice", out)
        self.assertFalse((proj / ".kb.json").exists())

    def test_legacy_project_without_language_is_zh(self):
        """没有 language 字段的旧项目按中文处理：内置模板、索引、提醒都是中文。"""
        proj = self.tmp / "legacy"
        init_project(proj, "旧项目", lang="zh-CN")
        meta = json.loads(read(proj / ".kb.json"))
        del meta["language"]  # 模拟 schema 1 的旧项目
        write(proj / ".kb.json", json.dumps(meta, ensure_ascii=False) + "\n")
        rc, out = self.loom("template", "会话纪要", cwd=proj)
        self.assertEqual(rc, 0, out)
        self.assertEqual(Path(out.strip()), NOTES_TPL / "zh-CN" / "session.md")
        rc, out = run(PY, SCRIPTS / "kb.py", "index", cwd=proj)
        self.assertEqual(rc, 0, out)
        self.assertIn("全库索引", read(proj / "00-Hub/index.md"))


class TestTemplateResolution(TempDirTest):
    def setUp(self):
        super().setUp()
        self.proj = self.tmp / "proj"
        init_project(self.proj, "模板项目", lang="zh-CN")

    def template(self, name):
        return run(PY, SCRIPTS / "loom.py", "template", name, cwd=self.proj)

    def test_builtin_by_id_alias_and_case(self):
        for name in ("session", "会话纪要"):
            rc, out = self.template(name)
            self.assertEqual(rc, 0, out)
            self.assertEqual(Path(out.strip()), NOTES_TPL / "zh-CN" / "session.md")
        rc, out = self.template("ADR")  # ADR 与 adr 等价
        self.assertEqual(rc, 0, out)
        self.assertEqual(Path(out.strip()), NOTES_TPL / "zh-CN" / "adr.md")

    def test_en_project_gets_english_builtin(self):
        proj = self.tmp / "en"
        init_project(proj, "enproj", lang="en")
        rc, out = run(PY, SCRIPTS / "loom.py", "template", "decision", cwd=proj)
        self.assertEqual(rc, 0, out)
        self.assertEqual(Path(out.strip()), NOTES_TPL / "en" / "decision.md")
        self.assertIn("status: pending", read(NOTES_TPL / "en" / "decision.md"))

    def test_unknown_name_lists_ids_and_aliases(self):
        rc, out = self.template("不存在")
        self.assertNotEqual(rc, 0)
        self.assertIn("session", out)
        self.assertIn("会话纪要", out)

    def test_project_exact_name_wins(self):
        write(self.proj / "90-Templates/session.md", "自定义\n")
        rc, out = self.template("session")
        self.assertEqual(rc, 0, out)
        self.assertEqual(Path(out.strip()), self.proj / "90-Templates" / "session.md")

    def test_project_alias_file_hit_by_id_request(self):
        """项目里只有按别名命名的自定义模板时，按 ID 请求也能命中它。"""
        write(self.proj / "90-Templates/会话纪要.md", "自定义\n")
        rc, out = self.template("session")
        self.assertEqual(rc, 0, out)
        self.assertEqual(Path(out.strip()), self.proj / "90-Templates" / "会话纪要.md")

    def test_conflict_reported_not_arbitrary(self):
        """两个自定义文件映射同一 ID 且请求名无法消歧：报冲突，不任意选。"""
        write(self.proj / "90-Templates/Session.md", "甲\n")
        write(self.proj / "90-Templates/会话纪要.md", "乙\n")
        rc, out = self.template("session")
        self.assertNotEqual(rc, 0)
        self.assertIn("冲突", out)
        rc, out = self.template("会话纪要")  # 请求名能精确命中时不算冲突
        self.assertEqual(rc, 0, out)
        self.assertEqual(Path(out.strip()), self.proj / "90-Templates" / "会话纪要.md")


class TestDecisionStatus(TempDirTest):
    def test_closed_statuses_bilingual_equivalent(self):
        """pending/decided/待定/已决定 提示到期复盘；reviewed/superseded/已复盘/已推翻 不提示。"""
        proj = self.tmp / "proj"
        init_project(proj, "决策项目")

        def dec(name, status):
            write(proj / f"40-Sessions/decisions/DR-2026-{name}.md",
                  f"---\ntype: decision\nid: DR-2026-{name}\ntitle: {name}\ncreated: 2026-01-01\n"
                  f"updated: 2026-01-01\nstatus: {status}\nreview_date: 2020-01-01\ntags: []\n---\n\n# {name}\n")

        for s in ("pending", "decided", "待定", "已决定"):
            dec(f"open-{s}", s)
        for s in ("reviewed", "superseded", "已复盘", "已推翻"):
            dec(f"closed-{s}", s)
        rc, out = run(PY, SCRIPTS / "kb.py", "lint", cwd=proj)
        self.assertEqual(rc, 0, out)
        self.assertIn("已到复盘日期的决策", out)
        for s in ("pending", "decided", "待定", "已决定"):
            self.assertIn(f"open-{s}", out, f"status={s} 应提示到期复盘")
        for s in ("reviewed", "superseded", "已复盘", "已推翻"):
            self.assertNotIn(f"closed-{s}", out, f"status={s} 不应提示到期复盘")


class TestSnapshotI18n(TempDirTest):
    def test_old_and_new_readme_names_accepted(self):
        """读取方同时接受旧名 快照说明.md 和新名 snapshot-readme.md。"""
        for readme in ("快照说明.md", "snapshot-readme.md"):
            z = self.tmp / f"{readme}.zip"
            make_zip(z, {"30-Wiki/a.md": "内容\n".encode(), readme: "说明\n".encode()})
            rc, out = run(PY, SCRIPTS / "snapshot.py", "open", z, cwd=self.tmp)
            self.assertEqual(rc, 0, f"{readme} 应被接受：\n{out}")
            dest = Path(re.search(r"Extracted to: (.+)", out).group(1).strip())
            self.addCleanup(lambda d=dest: shutil.rmtree(d, ignore_errors=True))

    def test_build_writes_snapshot_readme_by_language(self):
        """新快照的说明文件名固定为 snapshot-readme.md，内容按项目语言。"""
        for lang, marker in (("zh-CN", "知识库快照"), ("en", "Knowledge Base Snapshot")):
            proj = self.tmp / lang
            init_project(proj, f"proj-{lang}", lang=lang)
            rc, out = run(PY, SCRIPTS / "snapshot.py", "build", cwd=proj)
            self.assertEqual(rc, 0, out)
            z = next((proj / "50-Outputs/_exports").glob("*.zip"))
            with zipfile.ZipFile(z) as zf:
                self.assertIn("snapshot-readme.md", zf.namelist())
                self.assertNotIn("快照说明.md", zf.namelist())
                self.assertIn(marker, zf.read("snapshot-readme.md").decode("utf-8"))

    def test_strip_sections_english_case_insensitive(self):
        """strip_sections 对英文标题忽略大小写（Changelog / change log / VERSION HISTORY）。"""
        proj = self.tmp / "proj"
        init_project(proj, "清洗项目")
        write(proj / "30-Wiki/概念.md",
              "---\ntype: wiki\ntitle: 概念\ncreated: 2026-10-01\nupdated: 2026-10-01\ntags: []\n---\n\n"
              "# 概念\n\n正文。\n\n## Changelog\n\n- alpha-change\n\n## change log\n\n- bravo-log\n\n"
              "## VERSION HISTORY\n\n- charlie-hist\n\n## 相关\n\n- 保留\n")
        rc, out = run(PY, SCRIPTS / "snapshot.py", "build", cwd=proj)
        self.assertEqual(rc, 0, out)
        z = next((proj / "50-Outputs/_exports").glob("*.zip"))
        with zipfile.ZipFile(z) as zf:
            text = zf.read("30-Wiki/概念.md").decode("utf-8")
        self.assertIn("正文", text)
        self.assertIn("## 相关", text)
        for marker in ("alpha-change", "bravo-log", "charlie-hist"):
            self.assertNotIn(marker, text, f"{marker} 所在段落应被清洗")


# ---------- 示例项目 ----------

# ---------- hot.md 过期检测、开场提醒、索引摘要 ----------

class TestHotDrift(TempDirTest):
    """hot.md 靠 wrapup 维护，过期时要由脚本按证据（未归档的会话、代码库的新提交）说出来。"""

    def setUp(self):
        super().setUp()
        self.proj = self.tmp / "proj"
        init_project(self.proj)

    def session_start(self):
        rc, out = run(PY, SCRIPTS / "kb.py", "session-start", cwd=self.proj, stdin=b"")
        self.assertEqual(rc, 0, out)
        return out

    def raw(self, name, prompts):
        write(self.proj / "40-Sessions/raw/2026/09" / f"{name}.md",
              f'---\ntype: raw-session\ntitle: "讨论"\nstarted: 2026-09-30 10:00\nprompts: {prompts}\n---\n\n# 讨论\n')

    def repo_commit(self, msg, when=None):
        demo = self.proj / "repos" / "demo"
        if not demo.exists():
            demo.mkdir(parents=True)
            git(demo, "init", "-q")
        write(demo / "a.txt", msg)
        git(demo, "add", "a.txt")
        env = {**os.environ, **({"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when} if when else {})}
        rc, out = run("git", "-c", "user.name=loom-test", "-c", "user.email=loom-test@example.com",
                      "commit", "-q", "-m", msg, cwd=demo, env=env)
        self.assertEqual(rc, 0, out)

    def test_fresh_project_is_not_stale(self):
        out = self.session_start()
        self.assertNotIn("hot.md 最后更新于", out)
        self.assertNotIn("尚未归档", out)

    def test_unarchived_sessions_reported_and_ai_asks_once(self):
        self.raw("2026-09-30_1000_aaaaaaaa", 3)
        self.raw("2026-09-30_1100_bbbbbbbb", 1)
        out = self.session_start()
        self.assertIn("2 个会话尚未归档（共 4 条提问）", out)
        self.assertIn("hot.md 最后更新于", out)
        self.assertLess(out.index("hot.md 最后更新于"), out.index("## 一句话"), "过期提示要出现在 hot.md 正文之前")
        self.assertIn("在第一次回复的开头用一句话问用户", out)
        rc, status = run(PY, SCRIPTS / "loom.py", "status", "--no-export", cwd=self.proj)
        self.assertEqual(rc, 0, status)
        self.assertIn("hot.md 最后更新于", status)
        self.assertNotIn("第一次回复", status, "会话中途运行 status 时，未归档的可能就是当前会话，不能让 AI 开场发问")

    def test_trivial_session_does_not_interrupt(self):
        """只有一条提问的会话多半是试运行：照常提示，但不让 AI 在开场打断用户。"""
        self.raw("2026-09-30_1000_aaaaaaaa", 1)
        out = self.session_start()
        self.assertIn("1 个会话尚未归档", out)
        self.assertNotIn("第一次回复", out)

    def test_repo_commits_after_hot_reported(self):
        self.repo_commit("旧提交", when="2020-01-01T00:00:00+00:00")
        self.assertNotIn("hot.md 最后更新于", self.session_start(), "hot.md 更新之前的提交不算")
        self.repo_commit("feat: 新功能", when="2099-01-01T00:00:00+00:00")
        out = self.session_start()
        self.assertIn("repos/demo 有 1 次新提交（最新：feat: 新功能）", out)

    def commit_all(self):
        if not (self.proj / ".git").exists():
            git(self.proj, "init", "-q")
            write(self.proj / ".git/info/exclude", "repos/\n")
        git(self.proj, "add", "-A")
        git(self.proj, "commit", "-q", "-m", "init")

    def test_late_commit_does_not_hide_changes(self):
        """hot.md 改完过了很久才提交：基准取修改时间，这中间代码库的提交仍然要报出来。"""
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        hot = self.proj / "00-Hub/hot.md"
        edited = (now - timedelta(hours=2)).timestamp()
        os.utime(hot, (edited, edited))
        self.repo_commit("feat: 中间的提交", when=(now - timedelta(hours=1)).isoformat(timespec="seconds"))
        self.commit_all()  # hot.md 的提交时间是现在，晚于那次代码库提交
        self.assertFalse(git(self.proj, "status", "--porcelain"), "fixture 前提：知识库是干净的")
        self.assertIn("repos/demo 有 1 次新提交（最新：feat: 中间的提交）", self.session_start())

    def test_uncommitted_kb_changes_reported(self):
        self.commit_all()
        self.assertNotIn("hot.md 最后更新于", self.session_start(), "干净的知识库不提示")
        write(self.proj / "30-Wiki/别的工具写的.md", "---\ntype: wiki\ntitle: x\n---\n")
        self.assertIn("知识库有 1 处未提交的改动", self.session_start())

    def test_exported_raw_is_not_an_uncommitted_change(self):
        """原始对话是 Loom 自己导出的：只算作未归档的会话，不算知识库的未提交改动。"""
        self.commit_all()
        self.raw("2026-09-30_1000_aaaaaaaa", 3)
        out = self.session_start()
        self.assertIn("1 个会话尚未归档", out)
        self.assertNotIn("未提交的改动", out)

    def test_resumed_session_is_not_a_finished_one(self):
        """恢复一个已导出过的会话：它还没结束，不能让 AI 开场问要不要给它补归档。"""
        write(self.proj / "40-Sessions/raw/2026/09/2026-09-30_1000_aaaaaaaa.md",
              '---\ntype: raw-session\ntitle: "讨论"\nsession_id: aaaaaaaa-current\nstarted: 2026-09-30 10:00\n'
              'prompts: 3\n---\n')
        env = self.home_env(self.tmp / "home")
        hook = json.dumps({"session_id": "aaaaaaaa-current"}).encode()
        rc, out = run(PY, SCRIPTS / "kb.py", "session-start", cwd=self.proj, stdin=hook, env=env)
        self.assertEqual(rc, 0, out)
        self.assertIn("1 个会话尚未归档", out)
        self.assertNotIn("第一次回复", out)
        rc, out = run(PY, SCRIPTS / "kb.py", "session-start", cwd=self.proj,
                      stdin=json.dumps({"session_id": "bbbbbbbb-other"}).encode(), env=env)
        self.assertIn("在第一次回复的开头用一句话问用户", out, "换一个会话打开时照常询问")

    def test_migrate_ignores_exported_raw(self):
        """只有 Loom 自己导出的原始对话没提交时，迁移不该被挡住；别的未提交改动照旧拒绝。"""
        meta = json.loads(read(self.proj / ".kb.json"))
        del meta["language"]
        meta["schema"] = 1
        write(self.proj / ".kb.json", json.dumps(meta, ensure_ascii=False) + "\n")
        self.commit_all()
        write(self.proj / "30-Wiki/草稿.md", "---\ntype: wiki\ntitle: 草稿\n---\n")
        rc, out = run(PY, SCRIPTS / "loom.py", "migrate", cwd=self.proj)
        self.assertNotEqual(rc, 0, "有别的未提交改动时应拒绝")
        self.assertIn("未提交的改动", out)
        (self.proj / "30-Wiki/草稿.md").unlink()
        self.raw("2026-09-30_1000_aaaaaaaa", 3)
        rc, out = run(PY, SCRIPTS / "loom.py", "migrate", cwd=self.proj)
        self.assertEqual(rc, 0, out)
        self.assertEqual(json.loads(read(self.proj / ".kb.json"))["schema"], 2)

    def test_english_project(self):
        proj = self.tmp / "en"
        init_project(proj, name="Demo", lang="en")
        write(proj / "40-Sessions/raw/2026/09/2026-09-30_1000_aaaaaaaa.md",
              '---\ntype: raw-session\ntitle: "Talk"\nstarted: 2026-09-30 10:00\nprompts: 2\n---\n')
        rc, out = run(PY, SCRIPTS / "kb.py", "session-start", cwd=proj, stdin=b"")
        self.assertEqual(rc, 0, out)
        self.assertIn("hot.md was last updated at", out)
        self.assertIn("At the top of your first reply", out)


class TestIndexSummary(TempDirTest):
    def test_summary_shown_in_index(self):
        proj = self.tmp / "proj"
        init_project(proj)
        write(proj / "40-Sessions/notes/2026-09-30_选型.md",
              "---\ntype: session\ntitle: 选型\ncreated: 2026-09-30\nsummary: 决定用 A|B 中的 A\ntags: [x]\n---\n")
        write(proj / "40-Sessions/notes/2026-09-29_旧纪要.md",
              "---\ntype: session\ntitle: 旧纪要\ncreated: 2026-09-29\ntags: [y]\n---\n")
        write(proj / "20-Sources/cards/某资料.md", "---\ntype: source\ntitle: 某资料\nsummary: 一句话概括\n---\n")
        rc, out = run(PY, SCRIPTS / "kb.py", "index", cwd=proj)
        self.assertEqual(rc, 0, out)
        index = read(proj / "00-Hub/index.md")
        self.assertIn("| 日期 | 主题 | 摘要 | 标签 |", index)
        self.assertIn("| 决定用 A\\|B 中的 A | [x] |", index, "摘要里的 | 要转义，不能撑破表格")
        self.assertIn("旧纪要]] |  | [y] |", index, "没有 summary 的旧笔记留空")
        self.assertIn("某资料]] — 一句话概括", index)

    def test_templates_have_summary(self):
        for lang in ("en", "zh-CN"):
            for tid in ("session", "source"):
                self.assertIn("\nsummary:", read(SKILL / "assets/templates/notes" / lang / f"{tid}.md"), f"{lang}/{tid}")


# ---------- 0.6.1：注入上限、发布边界、开场询问的时机、导出保真、frontmatter ----------

HOOK_CAP = 9500  # Claude Code 把每个 hook 的输出按 10000 字符封顶，超出只留 2000 字符的预览；留一点余量


class TestInjectionCap(TempDirTest):
    """会话开始的注入分成两条 hook 命令（规则、项目上下文），各自都要在宿主的字符上限之内。"""

    def setUp(self):
        super().setUp()
        self.proj = self.tmp / "proj"
        init_project(self.proj)

    def kb(self, cmd, stdin=b""):
        rc, out = run(PY, SCRIPTS / "kb.py", cmd, cwd=self.proj, stdin=stdin)
        self.assertEqual(rc, 0, out)
        return out

    def long_hot(self, lines, width):
        write(self.proj / "00-Hub/hot.md", "---\ntype: hub\ntitle: Hot Context\n---\n\n# 🔥 测试项目\n\n"
              + "\n".join(f"- 第 {i} 条：" + "长" * width for i in range(lines)) + "\n")

    def test_rules_and_context_are_separate_commands(self):
        rules, context = self.kb("rules"), self.kb("session-start")
        self.assertIn("--- Loom 通用规则", rules)
        self.assertIn("## 4. 知识归属", rules, "规则要完整输出")
        self.assertNotIn("--- Loom 通用规则", context, "项目上下文里不再带规则正文")
        self.assertIn("--- 00-Hub/hot.md ---", context)
        self.assertLessEqual(len(rules), HOOK_CAP, "规则变长到接近上限时，先拆规则再发布")

    def test_hooks_json_runs_both_commands(self):
        hooks = json.loads(read(SKILL / "hooks/hooks.json"))["hooks"]
        commands = [h["command"] for g in hooks["SessionStart"] for h in g["hooks"]]
        self.assertTrue(any(c.endswith("kb session-start") for c in commands), commands)
        self.assertTrue(any(c.endswith("kb rules") for c in commands), commands)

    def test_long_hot_stays_within_cap_and_keeps_reminders(self):
        self.long_hot(60, 300)  # 60 行，约 18000 字符：行数没超，字符数远超
        write(self.proj / "40-Sessions/raw/2026/09/2026-09-30_1000_aaaaaaaa.md",
              '---\ntype: raw-session\ntitle: "讨论"\nstarted: 2026-09-30 10:00\nprompts: 3\n---\n')
        out = self.kb("session-start")
        self.assertLessEqual(len(out), HOOK_CAP)
        self.assertIn("在第一次回复的开头用一句话问用户", out)
        self.assertLess(out.index("在第一次回复的开头"), out.index("--- 00-Hub/hot.md ---"), "提醒排在 hot.md 之前，裁剪时不会丢")
        self.assertIn("以上是前", out, "hot.md 被裁时要说明")

    def test_lint_flags_hot_by_characters(self):
        self.long_hot(30, 200)  # 30 行，约 6000 字符
        self.assertIn("个字符", self.kb("lint"))


class TestAskOnlyWhenAConversationStarts(TempDirTest):
    """补归档的询问只在新对话开始时（startup、clear）出现；恢复、压缩、分叉是接着做，不再打断。"""

    def setUp(self):
        super().setUp()
        self.proj = self.tmp / "proj"
        init_project(self.proj)
        write(self.proj / "40-Sessions/raw/2026/09/2026-09-30_1000_aaaaaaaa.md",
              '---\ntype: raw-session\ntitle: "讨论"\nsession_id: aaaaaaaa-old\nstarted: 2026-09-30 10:00\n'
              'prompts: 3\n---\n')

    def start(self, source):
        hook = {"session_id": "bbbbbbbb-now", **({"source": source} if source else {})}
        rc, out = run(PY, SCRIPTS / "kb.py", "session-start", cwd=self.proj, stdin=json.dumps(hook).encode(),
                      env=self.home_env(self.tmp / "home"))
        self.assertEqual(rc, 0, out)
        return out

    def test_asks_on_startup_clear_and_legacy_input(self):
        for source in ("startup", "clear", None):
            self.assertIn("在第一次回复的开头用一句话问用户", self.start(source), source)

    def test_passive_on_resume_compact_fork(self):
        for source in ("resume", "compact", "fork"):
            out = self.start(source)
            self.assertNotIn("第一次回复", out, source)
            self.assertIn("1 个会话尚未归档", out, f"{source}：仍然保留被动提醒")


class TestUnreleasedOutputFolder(TempDirTest):
    """产出物以 50-Outputs/<文档名>/ 为单位：主文档没发布时，目录下的附件也不能进快照。"""

    def setUp(self):
        super().setUp()
        self.proj = self.tmp / "proj"
        init_project(self.proj)
        note = lambda type_, extra="": f"---\ntype: {type_}\ntitle: x\n{extra}---\n正文\n"
        o = self.proj / "50-Outputs"
        write(o / "草稿/草稿.md", note("output", "status: draft\n"))
        write(o / "草稿/附图.png", "png")
        write(o / "草稿/数据/数据.csv", "a,b\n")
        write(o / "草稿/附录.md", note("wiki"))
        write(o / "草稿/可以给.md", note("wiki", "publish: true\n"))
        write(o / "报告/报告.md", note("output", "status: released\nversion: 1.0\nsources: [\"[[x]]\"]\n"))
        write(o / "报告/图.png", "png")
        write(o / "不发/不发.md", note("output", "status: released\nversion: 1.0\npublish: false\n"))
        write(o / "不发/图.png", "png")
        write(o / "散件/图.png", "png")  # 目录里没有产出文档：行为不变

    def test_attachments_follow_their_document(self):
        rc, plan = run(PY, SCRIPTS / "snapshot.py", "plan", cwd=self.proj)
        self.assertEqual(rc, 0, plan)
        for rel in ("草稿/附图.png", "草稿/数据/数据.csv", "草稿/附录.md", "不发/图.png"):
            self.assertIn(f"- 50-Outputs/{rel}：所属产出物未发布", plan)
        rc, out = run(PY, SCRIPTS / "snapshot.py", "build", cwd=self.proj)
        self.assertEqual(rc, 0, out)
        with zipfile.ZipFile(next((self.proj / "50-Outputs/_exports").glob("*.zip"))) as z:
            names = set(z.namelist())
        self.assertFalse({n for n in names if n.startswith(("50-Outputs/草稿/", "50-Outputs/不发/"))}
                         - {"50-Outputs/草稿/可以给.md"}, names)
        self.assertLessEqual({"50-Outputs/草稿/可以给.md", "50-Outputs/报告/报告.md", "50-Outputs/报告/图.png",
                              "50-Outputs/散件/图.png"}, names)

    def test_plan_lists_unchecked_non_text_files(self):
        rc, plan = run(PY, SCRIPTS / "snapshot.py", "plan", cwd=self.proj)
        attention = plan.split("## 需要留意")[1]
        self.assertIn("50-Outputs/报告/图.png", attention, "脚本没检查内容的文件要让人看到")


class TestRawExportFidelity(TempDirTest):
    def test_code_blocks_are_not_rewritten(self):
        proj = self.tmp / "proj"
        init_project(proj)
        reply = "# 方案\n\n```python\n# 这是注释\nx = 1\n```\n\n~~~~\n## 也是代码\n~~~\n# 还在四个波浪线的围栏里\n~~~~\n\n## 小结\n"
        lines = [{"type": "user", "sessionId": "cccccccc-code", "timestamp": "2026-09-30T02:00:00Z", "cwd": str(proj),
                  "message": {"role": "user", "content": "写一段代码"}},
                 {"type": "assistant", "sessionId": "cccccccc-code", "timestamp": "2026-09-30T02:01:00Z",
                  "message": {"role": "assistant", "content": [{"type": "text", "text": reply}]}}]
        src = self.tmp / "t.jsonl"
        write(src, "\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n")
        rc, out = run(PY, SCRIPTS / "export_session.py", src, "--root", proj)
        self.assertEqual(rc, 0, out)
        text = read(next((proj / "40-Sessions/raw").rglob("*_cccccccc.md")))
        self.assertIn("\n# 这是注释\nx = 1\n", text, "围栏里的行原样保留")
        self.assertIn("\n## 也是代码\n~~~\n# 还在四个波浪线的围栏里\n", text, "较短的围栏标记不结束较长的围栏")
        self.assertIn("\n### 方案\n", text, "围栏外的标题照常降两级")
        self.assertIn("\n#### 小结\n", text)


class TestFrontmatterParsing(TempDirTest):
    def setUp(self):
        super().setUp()
        self.proj = self.tmp / "proj"
        init_project(self.proj)

    def test_hash_inside_quotes_is_not_a_comment(self):
        write(self.proj / "40-Sessions/notes/2026-09-30_修复.md",
              '---\ntype: session\ntitle: "修复 issue #12 的讨论"\ncreated: 2026-09-30  # 行尾注释\n'
              'summary: "改用 C# 方案 #1"  # 引号之后的才是注释\ntags: [x]\n---\n')
        rc, out = run(PY, SCRIPTS / "kb.py", "index", cwd=self.proj)
        self.assertEqual(rc, 0, out)
        index = read(self.proj / "00-Hub/index.md")
        self.assertIn("| 2026-09-30 | [[40-Sessions/notes/2026-09-30_修复\\|修复 issue #12 的讨论]] | 改用 C# 方案 #1 | [x] |",
                      index)

    def test_bom_does_not_hide_frontmatter(self):
        """带 BOM 的笔记如果读不出 frontmatter，publish: false 会失效。"""
        write(self.proj / "30-Wiki/内部.md", "﻿---\ntype: wiki\ntitle: 内部\npublish: false\nraws: [\"[[a]]\"]\n---\n正文\n")
        write(self.proj / "30-Wiki/公开.md", "﻿---\ntype: wiki\ntitle: 公开\nraws: [\"[[a]]\"]\n---\n见 [[roadmap]]\n")
        rc, lint = run(PY, SCRIPTS / "kb.py", "lint", cwd=self.proj)
        self.assertNotIn("缺少 frontmatter", lint)
        rc, plan = run(PY, SCRIPTS / "snapshot.py", "plan", cwd=self.proj)
        self.assertIn("30-Wiki/内部.md：笔记标了 publish: false", plan)
        rc, out = run(PY, SCRIPTS / "snapshot.py", "build", cwd=self.proj)
        self.assertEqual(rc, 0, out)
        with zipfile.ZipFile(next((self.proj / "50-Outputs/_exports").glob("*.zip"))) as z:
            self.assertNotIn("raws:", z.read("30-Wiki/公开.md").decode("utf-8"), "带 BOM 的笔记也要清洗 frontmatter")


class TestClaudeHooksFallback(TempDirTest):
    """deploy.py --claude-hooks 写进 settings.json 的兜底 hook，以及 doctor 对它的检查。"""

    def setUp(self):
        super().setUp()
        self.home = self.tmp / "home"
        self.canonical = self.home / ".agents/skills/loom"
        self.settings = self.home / ".claude/settings.json"
        self.proj = self.tmp / "proj"
        init_project(self.proj)

    def commands(self, event):
        hooks = json.loads(read(self.settings))["hooks"]
        return [h["command"] for g in hooks[event] for h in g["hooks"]]

    def doctor(self):
        rc, out = run(PY, SCRIPTS / "loom.py", "doctor", cwd=self.proj, env=self.home_env(self.home))
        self.assertEqual(rc, 0, out)
        return out

    def test_install_writes_both_session_start_commands(self):
        deploy.install_claude_hooks(self.home, self.canonical)
        start = self.commands("SessionStart")
        self.assertEqual(len(start), 2, start)
        self.assertTrue(any(c.endswith("kb session-start") for c in start) and any(c.endswith("kb rules") for c in start))
        deploy.install_claude_hooks(self.home, self.canonical)
        self.assertEqual(len(self.commands("SessionStart")), 2, "重复部署不重复写入")

    def test_upgrade_adds_the_rules_command(self):
        """0.6.0 及更早写入的只有 session-start 一条；重新部署时补上 rules。"""
        run_sh = f'bash "{self.canonical.as_posix()}/scripts/run.sh"'
        write(self.settings, json.dumps({"hooks": {"SessionStart": [{"hooks": [
            {"type": "command", "command": f"{run_sh} kb session-start", "timeout": 20}]}]}}))
        self.assertIn("kb rules", self.doctor(), "doctor 要指出缺少注入规则的那一条")
        deploy.install_claude_hooks(self.home, self.canonical)
        self.assertEqual(len(self.commands("SessionStart")), 2)

    def test_doctor_warns_about_double_hooks(self):
        deploy.install_claude_hooks(self.home, self.canonical)
        self.assertIn("各执行一次", self.doctor(), "settings.json 和插件两份 hook 可能同时生效，要提示")


class TestDeployLatest(TempDirTest):
    """deploy.py --latest：按远端版本号最大的发布 tag 部署。不依赖 git pull，也不改动本地的工作区、分支和 tag。"""

    def setUp(self):
        super().setUp()
        self.upstream = self.tmp / "upstream"
        self.upstream.mkdir()
        git(self.upstream, "init", "-q", "-b", "main")
        shutil.copytree(REPO / "tools", self.upstream / "tools", ignore=shutil.ignore_patterns("__pycache__"))
        self.release("0.9.0")
        self.clone = self.tmp / "clone"
        git(self.tmp, "clone", "-q", self.upstream, self.clone)
        self.home = self.tmp / "home"
        (self.home / ".claude").mkdir(parents=True)

    def release(self, version, tag_args=()):
        """在上游提交一个版本；tag_args 为 None 时不打 tag。"""
        write(self.upstream / "skills/loom/VERSION", version + "\n")
        write(self.upstream / "skills/loom/SKILL.md", f"loom {version}\n")
        git(self.upstream, "add", "-A")
        git(self.upstream, "commit", "-qm", f"Loom {version}")
        if tag_args is not None:
            git(self.upstream, "tag", *tag_args, f"v{version}")

    def deploy(self, *args):
        return run(PY, self.clone / "tools/deploy.py", "--home", self.home, "--agents", "claude", *args)

    def marker(self):
        return json.loads(read(self.home / ".agents/skills/loom/.loom-deploy.json"))

    def test_deploys_highest_release_tag(self):
        """版本号按数值比较（0.10.0 高于 0.9.1），不是发布版的 tag 不算；克隆落后、有未提交的改动也照常部署，且不被改动。"""
        self.release("0.9.1")
        self.release("0.10.0", tag_args=("-a", "-m", "附注 tag"))
        self.release("0.11.0", tag_args=None)
        git(self.upstream, "tag", "v0.11.0-rc1")
        git(self.upstream, "tag", "nightly")
        write(self.clone / "草稿.md", "没提交的改动\n")
        head, tags = git(self.clone, "rev-parse", "HEAD"), git(self.clone, "tag")
        rc, out = self.deploy("--latest")
        self.assertEqual(rc, 0, out)
        self.assertEqual((self.marker()["version"], self.marker()["ref"]), ("0.10.0", "v0.10.0"), out)
        self.assertEqual(read(self.home / ".agents/skills/loom/SKILL.md"), "loom 0.10.0\n")
        self.assertEqual((git(self.clone, "rev-parse", "HEAD"), git(self.clone, "tag")), (head, tags),
                         "--latest 不应移动本地的 HEAD，也不应新建或改写本地的 tag")

    def test_survives_rewritten_history(self):
        """上游改写过历史：git pull 无法快进，本地的同名 tag 指向旧提交，--latest 仍能装上新的发布版。"""
        old = git(self.clone, "rev-parse", "v0.9.0")
        git(self.upstream, "commit", "-q", "--amend", "-m", "改写过的历史")
        git(self.upstream, "tag", "-f", "v0.9.0")
        self.release("0.9.1")
        rc, out = run("git", "pull", "--ff-only", cwd=self.clone)
        self.assertNotEqual(rc, 0, f"fixture 前提：改写历史后 git pull 无法快进\n{out}")
        rc, out = self.deploy("--latest")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.marker()["version"], "0.9.1", out)
        self.assertEqual(git(self.clone, "rev-parse", "v0.9.0"), old, "本地的旧 tag 不应被改写")

    def test_never_redeploys_or_downgrades(self):
        """已装的就是最新发布版时不重复部署；已装的比最新发布版还新（开发者从 HEAD 部署的）时不降级。"""
        rc, out = self.deploy("--latest")
        self.assertEqual((rc, self.marker()["version"]), (0, "0.9.0"), out)
        first = read(self.home / ".agents/skills/loom/.loom-deploy.json")
        rc, out = self.deploy("--latest")
        self.assertEqual(rc, 0, out)
        self.assertIn("没有部署", out)
        self.assertEqual(read(self.home / ".agents/skills/loom/.loom-deploy.json"), first)
        write(self.clone / "skills/loom/VERSION", "0.9.5\n")
        git(self.clone, "commit", "-qam", "开发中的版本")
        rc, out = self.deploy("--skip-tests")
        self.assertEqual((rc, self.marker()["version"]), (0, "0.9.5"), out)
        rc, out = self.deploy("--latest")
        self.assertEqual(rc, 0, out)
        self.assertIn("没有部署", out)
        self.assertEqual(self.marker()["version"], "0.9.5", "不应降回 0.9.0")

    def test_refuses_without_release_tag_or_with_ref(self):
        """远端没有发布 tag 时报错并说明；--latest 和 --ref 不能同时用。"""
        empty = self.tmp / "empty.git"
        git(self.tmp, "init", "-q", "--bare", empty)
        git(self.clone, "remote", "set-url", "origin", empty)
        rc, out = self.deploy("--latest")
        self.assertNotEqual(rc, 0, out)
        self.assertIn("没有发布版的 tag", out)
        self.assertFalse((self.home / ".agents/skills/loom").exists())
        rc, out = self.deploy("--latest", "--ref", "v0.9.0")
        self.assertNotEqual(rc, 0, out)


class TestSmallFixes(TempDirTest):
    def test_lint_points_to_loom_wrapup(self):
        proj = self.tmp / "proj"
        init_project(proj)
        write(proj / "40-Sessions/raw/2026/09/2026-09-30_1000_aaaaaaaa.md",
              '---\ntype: raw-session\ntitle: "讨论"\nstarted: 2026-09-30 10:00\nprompts: 3\n---\n')
        rc, out = run(PY, SCRIPTS / "kb.py", "lint", cwd=proj)
        self.assertNotIn("/wrapup", out.replace("/loom wrapup", ""), "0.1 的 /wrapup 命令早已不存在")

    def test_sync_repos_speaks_the_project_language(self):
        for lang, expected in (("en", "No repositories"), ("zh-CN", "还没有登记代码库")):
            proj = self.tmp / lang
            init_project(proj, lang=lang)
            rc, out = run(PY, SCRIPTS / "sync_repos.py", cwd=proj)
            self.assertEqual(rc, 0, out)
            self.assertIn(expected, out)


class TestLintLeavesUserFilesAlone(TempDirTest):
    """init 的说明要求把用户已有的资料留在原地。这些文件不是 Loom 的笔记，lint 不能因为它们没有 frontmatter 报错：
    否则按流程初始化完的项目过不了体检，AI 还会被引去改用户的原件。（行为测试 s8 发现的）"""

    def setUp(self):
        super().setUp()
        self.proj = self.tmp / "proj"
        init_project(self.proj)

    def lint(self):
        rc, out = run(PY, SCRIPTS / "kb.py", "lint", cwd=self.proj)
        self.assertEqual(rc, 0, out)
        return out

    def test_files_outside_loom_directories_need_no_frontmatter(self):
        write(self.proj / "需求笔记.md", "# 需求笔记\n\n原来就在文件夹里的资料。\n")
        write(self.proj / "资料/方案备选.md", "# 方案备选\n")
        write(self.proj / "20-Sources/inbox/待处理.md", "# 还没导入的资料\n")
        self.assertIn("✅", self.lint())

    def test_loom_notes_still_need_frontmatter(self):
        write(self.proj / "30-Wiki/概念.md", "# 概念\n\n没有 frontmatter 的 wiki 页。\n")
        write(self.proj / "40-Sessions/notes/2026-09-30_讨论.md", "# 讨论\n")
        out = self.lint()
        self.assertIn("30-Wiki/概念.md：缺少 type、title", out)
        self.assertIn("40-Sessions/notes/2026-09-30_讨论.md：缺少 type、title", out)


class TestExamples(TempDirTest):
    def test_examples_are_healthy_loom_projects(self):
        """examples/ 下的演示项目复制出去后就是完整的 Loom 项目：status 没有警告（Loom 区块是当前版本），lint 通过。"""
        for lang in ("en", "zh-CN"):
            proj = self.tmp / lang
            shutil.copytree(REPO / "examples" / "reading-notes" / lang, proj)
            rc, out = run(PY, SCRIPTS / "loom.py", "status", "--no-export", cwd=proj)
            self.assertEqual(rc, 0, out)
            self.assertNotIn("⚠️", out, f"{lang} 示例的 status 有警告")
            rc, out = run(PY, SCRIPTS / "kb.py", "lint", cwd=proj)
            self.assertEqual(rc, 0, out)
            self.assertIn("✅", out, f"{lang} 示例的 lint 未通过")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    unittest.main()
