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
