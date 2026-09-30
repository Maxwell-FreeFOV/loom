#!/usr/bin/env python3
"""Loom：项目知识库工具包的安装与升级工具。

在项目根目录执行（Loom 已 clone 到项目的 .loom/ 下）：
  py .loom/tools/loom.py install --name 名称 [--summary 一句话] [--modules research,engineering]
  py .loom/tools/loom.py add <模块> [...]        启用新模块
  py .loom/tools/loom.py upgrade [--to <版本>]   升级到 .loom 当前版本（或指定版本）
  py .loom/tools/loom.py upgrade-all <项目目录> [...]
  py .loom/tools/loom.py doctor                  检查安装状态
  py .loom/tools/loom.py modules                 列出可用模块

通用参数 --project <目录>：默认是 .loom 的上一级目录；本仓库不叫 .loom 时默认是当前目录。

模块目录约定：modules/<模块>/{managed,seeded,merged}/<项目内路径>
  managed  托管文件：升级时三方合并（项目里没改过就等于直接覆盖）
  seeded   种子文件：只在安装时生成；升级时不改动，只报告模板的变化
  merged   合并文件：JSON 按键合并，其他文件按行合并
文件名以 .tmpl 结尾时，安装时去掉这个后缀（避免 CLAUDE.md、.gitignore 模板在 Loom 仓库里生效）。
模板中的 {{PROJECT_NAME}} {{SUMMARY}} {{DATE}} {{PYTHON}} 会被替换为项目的值。
安装和升级只使用 Loom 仓库中已提交的内容。
"""
import argparse
import difflib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

LOOM = Path(__file__).resolve().parents[1]
CATEGORIES = ("managed", "seeded", "merged")
KB_FILE = ".kb.json"
MISSING = object()


class LoomError(Exception):
    pass


def git(*args, cwd=LOOM, check=True):
    r = subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=cwd, capture_output=True)
    if check and r.returncode != 0:
        raise LoomError(f"git {' '.join(args)} 失败：{r.stderr.decode('utf-8', 'replace').strip()}")
    return r


def text_of(data):
    return data.decode("utf-8").replace("\r\n", "\n")


class Source:
    """Loom 仓库在某个 commit 上的模板内容。"""

    def __init__(self, ref):
        r = git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False)
        if r.returncode != 0:
            raise LoomError(f"Loom 仓库中找不到版本 {ref}，可能需要先执行 git -C .loom fetch --tags")
        self.commit = r.stdout.decode().strip()
        out = git("ls-tree", "-r", "-z", "--name-only", self.commit).stdout
        self.files = {p.decode("utf-8") for p in out.split(b"\0") if p}
        self.version = self.read("VERSION").strip() if "VERSION" in self.files else "?"

    @property
    def label(self):
        return f"{self.version} · {self.commit[:7]}"

    def read(self, path):
        return text_of(git("show", f"{self.commit}:{path}").stdout)

    def modules(self):
        return sorted({p.split("/")[1] for p in self.files if p.startswith("modules/") and p.count("/") >= 2})

    def module_meta(self, m):
        path = f"modules/{m}/module.json"
        return json.loads(self.read(path)) if path in self.files else {}

    def module_files(self, m):
        """{(类别, 项目内路径): 仓库内路径}"""
        prefix, out = f"modules/{m}/", {}
        for p in self.files:
            if not p.startswith(prefix):
                continue
            parts = p[len(prefix):].split("/", 1)
            if len(parts) == 2 and parts[0] in CATEGORIES:
                rel = parts[1][:-5] if parts[1].endswith(".tmpl") else parts[1]
                out[(parts[0], rel)] = p
        return out


class Report:
    def __init__(self, title):
        self.title, self.sections = title, {}

    def add(self, section, line):
        self.sections.setdefault(section, []).append(line)

    def render(self):
        out = [f"# {self.title}", ""]
        for section, lines in self.sections.items():
            out += [f"## {section}", "", *lines, ""]
        if not self.sections:
            out.append("（没有变化）")
        return "\n".join(out)


# ---------- 文件读写与合并 ----------

def read_file(p):
    return text_of(p.read_bytes()) if p.is_file() else None


def write_file(p, text, dry):
    """内部统一用 LF 处理，写出时换成平台的换行符（与 git 的 autocrlf 习惯一致）。"""
    if not dry:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.replace("\n", os.linesep).encode("utf-8"))


def render(text, ctx):
    for k, v in ctx.items():
        text = text.replace("{{" + k + "}}", v)
    return text


def merge_file(cur, base, new):
    """用 git merge-file 做三方合并，返回 (结果, 冲突数)。"""
    with tempfile.TemporaryDirectory() as d:
        paths = []
        for name, t in (("cur", cur), ("base", base), ("new", new)):
            f = Path(d) / name
            f.write_bytes(t.encode("utf-8"))
            paths.append(str(f))
        r = subprocess.run(
            ["git", "merge-file", "-p", "-L", "项目当前", "-L", "旧版 Loom", "-L", "新版 Loom", *paths],
            capture_output=True,
        )
    if r.returncode >= 128:
        raise LoomError(f"git merge-file 失败：{r.stderr.decode('utf-8', 'replace').strip()}")
    return text_of(r.stdout), r.returncode


def merge3(cur, old, new):
    """JSON 值的三方合并：字典按键递归，列表按元素增删，标量冲突时保留项目的值。"""
    if cur is MISSING:
        return new
    if old is not MISSING and new == old:
        return cur
    if old is not MISSING and cur == old:
        return new
    if isinstance(cur, dict) and isinstance(new, dict):
        o = old if isinstance(old, dict) else {}
        out = dict(cur)
        for k, v in new.items():
            out[k] = merge3(cur.get(k, MISSING), o.get(k, MISSING), v)
        for k, v in o.items():
            if k not in new and k in out and out[k] == v:
                del out[k]
        return out
    if isinstance(cur, list) and isinstance(new, list):
        o = old if isinstance(old, list) else []
        out = [x for x in cur if not (x in o and x not in new)]
        return out + [x for x in new if x not in out]
    return cur


def merge_lines(cur, old, new):
    """按行的三方合并：删掉新版去掉的行，追加新版新增的行，项目自己加的行保留。"""
    if cur is None:
        return new if new.endswith("\n") else new + "\n"
    c, n = cur.splitlines(), new.splitlines()
    o = old.splitlines() if old is not None else None
    if o is not None and n == o:
        return cur
    if o is not None and c == o:
        return new
    removed = set(o or []) - set(n)
    out = [line for line in c if not (line.strip() and line in removed)]
    add = [line for line in n if line.strip() and line not in out]
    if add:
        if out and out[-1].strip():
            out.append("")
        out += add
    return "\n".join(out) + "\n"


def load_json(text, rel):
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise LoomError(f"{rel} 不是合法的 JSON：{e}")


def merge_text(rel, cur, old, new):
    """返回合并后的文本；内容没有实质变化时返回 None。"""
    if rel.endswith(".json"):
        c = load_json(cur, rel) if cur and cur.strip() else MISSING
        o = load_json(old, rel) if old else MISSING
        result = merge3(c, o, load_json(new, rel))
        if c is not MISSING and result == c:
            return None
        return json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    text = merge_lines(cur, old, new)
    return None if text == cur else text


def apply_install(proj, cat, rel, new, report, dry):
    target = proj / rel
    cur = read_file(target)
    if cat == "merged":
        text = merge_text(rel, cur, None, new)
        if text is not None:
            write_file(target, text, dry)
            report.add("合并文件", f"- {rel}")
    elif cur is None:
        write_file(target, new, dry)
        report.add("新增文件", f"- {rel}")
    elif cur != new:
        write_file(proj / (rel + ".loom-new"), new, dry)
        report.add("⚠️ 已存在同名文件（新模板写入 .loom-new，请合并后删除）", f"- {rel}")


def apply_upgrade(proj, cat, rel, old, new, report, dry):
    target = proj / rel
    cur = read_file(target)
    if cat == "merged":
        if new is None:
            if cur is not None:
                report.add("合并文件", f"- {rel}：新版不再提供此文件，项目文件保留")
            return
        text = merge_text(rel, cur, old, new)
        if text is not None:
            write_file(target, text, dry)
            report.add("合并文件", f"- {rel}")
        return

    if cat == "seeded":
        if new is None:
            if old is not None and cur is not None:
                report.add("种子文件", f"- {rel}：新版不再提供此文件，项目文件保留")
        elif old is None:
            if cur is None:
                write_file(target, new, dry)
                report.add("新增文件", f"- {rel}")
            elif cur != new:
                report.add("种子文件", f"- {rel}：新版新增了这个种子文件，但项目中已有同名文件，未改动")
        elif old != new:
            diff = "".join(difflib.unified_diff(
                old.splitlines(True), new.splitlines(True), f"旧版模板/{rel}", f"新版模板/{rel}"))
            note = "（项目中已没有这个文件）\n\n" if cur is None else ""
            report.add("种子文件的模板有变化（未自动修改，请评估是否同步到项目文件）",
                       f"### {rel}\n\n{note}```diff\n{diff.rstrip()}\n```\n")
        return

    # managed
    if new is None:
        if cur is None:
            return
        if cur == old:
            if not dry:
                target.unlink()
            report.add("删除（新版已移除，本地没有修改）", f"- {rel}")
        else:
            report.add("⚠️ 新版已移除，但本地有修改，已保留", f"- {rel}")
    elif cur is None:
        write_file(target, new, dry)
        report.add("新增文件", f"- {rel}")
    elif cur == new:
        return
    elif old is not None and cur == old:
        write_file(target, new, dry)
        report.add("更新", f"- {rel}")
    elif old is None:
        write_file(proj / (rel + ".loom-new"), new, dry)
        report.add("⚠️ 已存在同名文件（新模板写入 .loom-new，请合并后删除）", f"- {rel}")
    else:
        merged, conflicts = merge_file(cur, old, new)
        write_file(target, merged, dry)
        if conflicts:
            report.add("⚠️ 冲突（文件中有 <<<<<<< 标记，需要手工处理）", f"- {rel}：{conflicts} 处")
        else:
            report.add("合并（保留了本地修改）", f"- {rel}")


def ensure_dirs(proj, dirs, dry):
    for d in dirs:
        p = proj / d
        if dry:
            continue
        p.mkdir(parents=True, exist_ok=True)
        if not any(p.iterdir()):
            (p / ".gitkeep").write_bytes(b"")


# ---------- 项目配置 ----------

def project_dir(args):
    if args.project:
        return Path(args.project).resolve()
    return LOOM.parent if LOOM.name == ".loom" else Path.cwd()


def load_kb(proj):
    f = proj / KB_FILE
    if not f.is_file():
        raise LoomError(f"{proj} 不是 Loom 项目（没有 {KB_FILE}）。新项目请先按 .loom/INIT.md 初始化。")
    return json.loads(f.read_text(encoding="utf-8"))


def save_kb(proj, kb, dry=False):
    write_file(proj / KB_FILE, json.dumps(kb, ensure_ascii=False, indent=2) + "\n", dry)


def context(kb):
    return {
        "PROJECT_NAME": kb["name"],
        "SUMMARY": kb.get("summary", ""),
        "DATE": kb["created"],
        "PYTHON": kb["python"],
    }


def stamp(src):
    return {"version": src.version, "commit": src.commit, "updated": datetime.now().strftime("%Y-%m-%d %H:%M")}


def detect_python():
    for cand in ("py", "python3", "python"):
        exe = shutil.which(cand)
        if not exe:
            continue
        try:
            r = subprocess.run([exe, "--version"], capture_output=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if r.returncode == 0 and b"Python 3" in r.stdout + r.stderr:
            return cand
    return "python"


def resolve_modules(src, requested):
    available, out = src.modules(), []

    def visit(m):
        if m in out:
            return
        if m not in available:
            raise LoomError(f"Loom {src.label} 中没有模块 {m}。可用模块：{', '.join(available)}")
        for r in src.module_meta(m).get("requires", []):
            visit(r)
        out.append(m)

    for m in requested:
        visit(m)
    return out


def split_modules(values):
    return [m.strip() for v in values or [] for m in v.split(",") if m.strip()]


def warn_loom_dirty():
    if git("status", "--porcelain", check=False).stdout.strip():
        print("⚠️ Loom 仓库有未提交的改动；安装和升级只使用已提交的内容。", file=sys.stderr)


def require_clean(proj):
    if not (proj / ".git").exists():
        raise LoomError("项目还不是 git 仓库。请先 git init 并提交，升级后才能用 git diff 审阅和回滚（或加 --force 跳过检查）。")
    if git("status", "--porcelain", cwd=proj).stdout.strip():
        raise LoomError("项目工作区有未提交的改动，请先提交或暂存（或加 --force 跳过检查）。")


def install_module(proj, src, m, ctx, report, dry=False):
    for (cat, rel), path in sorted(src.module_files(m).items()):
        apply_install(proj, cat, rel, render(src.read(path), ctx), report, dry)
    ensure_dirs(proj, src.module_meta(m).get("dirs", []), dry)


# ---------- 命令 ----------

def cmd_install(args):
    proj = project_dir(args)
    if (proj / KB_FILE).exists():
        raise LoomError("这个目录已经初始化过（存在 .kb.json）。启用新模块用 add，升级用 upgrade。")
    warn_loom_dirty()
    src = Source(args.to or "HEAD")
    mods = resolve_modules(src, ["core", *split_modules(args.modules)])
    kb = {
        "name": args.name or proj.name,
        "summary": args.summary or "",
        "created": date.today().isoformat(),
        "status": "active",
        "modules": mods,
        "python": args.python or detect_python(),
        "loom": stamp(src),
    }
    report = Report(f"Loom 安装报告：{kb['name']}（Loom {src.label}）")
    ctx = context(kb)
    for m in mods:
        install_module(proj, src, m, ctx, report)
    save_kb(proj, kb)
    report.add("配置", f"- 已写入 {KB_FILE}：模块 {', '.join(mods)}；Python 命令 `{kb['python']}`")
    print(report.render())


def cmd_add(args):
    proj = project_dir(args)
    kb = load_kb(proj)
    src = Source(kb["loom"]["commit"])
    try:
        mods = resolve_modules(src, [*kb["modules"], *split_modules(args.modules)])
    except LoomError as e:
        raise LoomError(f"{e}。如果这是新版本才有的模块，请先升级（/loom-upgrade）。")
    new = [m for m in mods if m not in kb["modules"]]
    if not new:
        print("这些模块都已启用。")
        return
    report = Report(f"启用模块：{', '.join(new)}（Loom {src.label}）")
    ctx = context(kb)
    for m in new:
        install_module(proj, src, m, ctx, report)
    kb["modules"] += new
    save_kb(proj, kb)
    report.add("提醒", "- 如果 .claude/settings.json 有变化，需要重启 Claude 会话才能生效。")
    print(report.render())


def upgrade_project(proj, to=None, dry=False, force=False):
    kb = load_kb(proj)
    base = Source(kb["loom"]["commit"])
    target = Source(to or "HEAD")
    if base.commit == target.commit:
        print(f"{kb['name']}：已是最新（Loom {target.label}）")
        return
    if not dry and not force:
        require_clean(proj)
    title = f"Loom 升级报告：{kb['name']}，{base.label} → {target.label}" + ("（预览，未写入）" if dry else "")
    report = Report(title)
    if git("merge-base", "--is-ancestor", base.commit, target.commit, check=False).returncode != 0:
        report.add("⚠️ 版本", "- 目标版本不是当前版本的后续版本（可能是降级或分叉），请确认。")
    ctx = context(kb)
    settings_changed = False
    for m in kb["modules"]:
        if m not in target.modules():
            report.add("⚠️ 模块", f"- 新版中已没有模块 {m}，其文件保持不变")
            continue
        old_files = base.module_files(m) if m in base.modules() else {}
        new_files = target.module_files(m)
        # 先处理删除，再处理新增和修改，这样文件换了类别也能正确处理
        for key in sorted(set(old_files) | set(new_files), key=lambda k: (k in new_files, k)):
            old = render(base.read(old_files[key]), ctx) if key in old_files else None
            new = render(target.read(new_files[key]), ctx) if key in new_files else None
            before = len(report.sections.get("合并文件", []))
            apply_upgrade(proj, *key, old, new, report, dry)
            if key[1] == ".claude/settings.json" and len(report.sections.get("合并文件", [])) > before:
                settings_changed = True
        ensure_dirs(proj, target.module_meta(m).get("dirs", []), dry)
        for r in target.module_meta(m).get("requires", []):
            if r not in kb["modules"]:
                report.add("⚠️ 模块", f"- 新版的模块 {m} 依赖 {r}，请运行 loom.py add {r}")
    mig = "MIGRATIONS.md"
    old_mig = base.read(mig) if mig in base.files else ""
    if mig in target.files and target.read(mig) != old_mig:
        report.add("迁移说明", f"- MIGRATIONS.md 有新条目，请阅读 .loom/MIGRATIONS.md 中 {base.version} 之后的部分并逐条执行。")
    if settings_changed:
        report.add("提醒", "- .claude/settings.json 有变化，需要重启 Claude 会话才能生效。")
    if not dry:
        kb["loom"] = stamp(target)
        save_kb(proj, kb)
    print(report.render())


def cmd_upgrade(args):
    upgrade_project(project_dir(args), args.to, args.dry_run, args.force)


def cmd_upgrade_all(args):
    failed = 0
    for d in args.dirs:
        try:
            upgrade_project(Path(d).resolve(), args.to, args.dry_run, args.force)
        except LoomError as e:
            failed += 1
            print(f"# {d}\n\n❌ {e}\n")
        print()
    if failed:
        sys.exit(1)


def cmd_doctor(args):
    proj = project_dir(args)
    kb = load_kb(proj)
    out = [f"# Loom 检查：{kb['name']}", ""]
    ok = lambda s: out.append(f"- ✅ {s}")
    warn = lambda s: out.append(f"- ⚠️ {s}")

    base = Source(kb["loom"]["commit"])
    head = Source("HEAD")
    ok(f"状态 {kb.get('status', 'active')}；模块 {', '.join(kb['modules'])}；已安装 Loom {base.label}")
    if head.commit == base.commit:
        ok("与 .loom 当前版本一致")
    else:
        warn(f".loom 当前是 {head.label}，与项目安装的版本不同，可以运行 /loom-upgrade")

    exe = shutil.which(kb["python"])
    if exe:
        ok(f"Python 命令 `{kb['python']}` 可用")
    else:
        warn(f"找不到 Python 命令 `{kb['python']}`，hook 会失败；请修改 .kb.json 和 .claude/settings.json")

    gi = read_file(proj / ".gitignore") or ""
    for entry, mod in ((".loom/", "core"), ("/repos/", "engineering")):
        if mod in kb["modules"] and entry not in gi.splitlines():
            warn(f".gitignore 中缺少 `{entry}`")

    settings = read_file(proj / ".claude" / "settings.json") or ""
    for needle, what in (("export_session.py", "对话导出 hook"), ("session-start", "SessionStart hook")):
        (ok if needle in settings else warn)(f"{what}：{'已配置' if needle in settings else '未配置'}")

    ctx = context(kb)
    modified, missing = [], []
    for m in kb["modules"]:
        if m not in base.modules():
            continue
        for (cat, rel), path in sorted(base.module_files(m).items()):
            cur = read_file(proj / rel)
            if cur is None:
                if cat != "seeded":  # 种子文件允许用户删除
                    missing.append(rel)
            elif cat == "managed" and cur != render(base.read(path), ctx):
                modified.append(rel)
    if missing:
        warn("缺少文件：" + "、".join(missing))
    if modified:
        warn("以下托管文件在项目中被修改过（升级时会三方合并）：" + "、".join(modified))
    if not missing and not modified:
        ok("托管文件完整，且未被修改")
    leftovers = [p.relative_to(proj).as_posix() for p in proj.rglob("*.loom-new") if ".loom" not in p.parts]
    if leftovers:
        warn("还有未处理的 .loom-new 文件：" + "、".join(leftovers))
    print("\n".join(out))


def cmd_modules(args):
    src = Source(args.to or "HEAD")
    print(f"# Loom {src.label} 的模块\n")
    for m in src.modules():
        meta = src.module_meta(m)
        req = f"（依赖：{', '.join(meta['requires'])}）" if meta.get("requires") else ""
        print(f"- **{m}**：{meta.get('description', '')}{req}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--project", help="项目根目录")
    parser = argparse.ArgumentParser(description="Loom 安装与升级工具")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("install", parents=[common], help="初始化项目")
    p.add_argument("--name")
    p.add_argument("--summary")
    p.add_argument("--modules", action="append", help="除 core 外要启用的模块，逗号分隔")
    p.add_argument("--python", help="hook 使用的 Python 命令（默认自动检测）")
    p.add_argument("--to", help="安装指定版本（默认 .loom 的 HEAD）")
    p.set_defaults(func=cmd_install)

    p = sub.add_parser("add", parents=[common], help="启用新模块")
    p.add_argument("modules", nargs="+")
    p.set_defaults(func=cmd_add)

    for name, func in (("upgrade", cmd_upgrade), ("upgrade-all", cmd_upgrade_all)):
        p = sub.add_parser(name, parents=[common], help="升级项目" if name == "upgrade" else "批量升级多个项目")
        if name == "upgrade-all":
            p.add_argument("dirs", nargs="+")
        p.add_argument("--to", help="目标版本（默认 Loom 仓库的 HEAD）")
        p.add_argument("--dry-run", action="store_true", help="只预览，不写入")
        p.add_argument("--force", action="store_true", help="跳过工作区干净检查")
        p.set_defaults(func=func)

    sub.add_parser("doctor", parents=[common], help="检查安装状态").set_defaults(func=cmd_doctor)
    p = sub.add_parser("modules", parents=[common], help="列出可用模块")
    p.add_argument("--to")
    p.set_defaults(func=cmd_modules)

    args = parser.parse_args()
    try:
        args.func(args)
    except LoomError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
