"""Loom 项目管理：初始化、启用模块、状态检查、模板、Loom 区块、结构迁移、体检。属于 Loom skill。

用法（python 指 Python 3；除 init 外，在项目根目录或其子目录中运行，也可以用 --root 指定根目录）：
  python loom.py init --name 名称 [--summary 一句话] [--modules research,engineering,outputs]
  python loom.py module list | add <模块> [...]
  python loom.py status [--no-export]   每个 Loom 操作的第一步：补导出对话，检查结构版本和 Loom 区块，列出提醒
  python loom.py template <名称>        输出应使用的笔记模板路径（项目 90-Templates/ 中的同名文件优先）
  python loom.py refresh-block          把 AGENTS.md 中的 Loom 区块更新为当前版本
  python loom.py migrate [--dry-run]    把项目结构迁移到当前版本
  python loom.py doctor                 检查项目和本机环境

项目模板在 assets/templates/project/<模块>/ 下，其中的路径就是文件在项目中的路径；文件名以 .tmpl 结尾时
去掉这个后缀。模板中的 {{PROJECT_NAME}} {{SUMMARY}} {{DATE}} {{LOOM_BLOCK}} 会被替换。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

from kbroot import KB_FILE, SCHEMA, SKILL_DIR, find_root, load_kb, skill_version, utf8_stdout

TEMPLATES = SKILL_DIR / "assets" / "templates"
PROJECT_TPL = TEMPLATES / "project"
NOTES_TPL = TEMPLATES / "notes"
BLOCK_BEGIN, BLOCK_END = "<!-- loom:begin -->", "<!-- loom:end -->"
MISSING = object()


class LoomError(Exception):
    pass


# ---------- 文件读写与合并 ----------

def read(p):
    return p.read_bytes().decode("utf-8").replace("\r\n", "\n") if p.is_file() else None


def write(p, text):
    """内部统一用 LF 处理，写出时换成平台的换行符（与 git 的 autocrlf 习惯一致）。"""
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.replace("\n", os.linesep).encode("utf-8"))


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


def merge_lines(cur, new):
    """按行合并：保留项目原有的行，追加模板中缺少的行。"""
    if cur is None:
        return new if new.endswith("\n") else new + "\n"
    out = cur.splitlines()
    add = [line for line in new.splitlines() if line.strip() and line not in out]
    if add and out and out[-1].strip():
        out.append("")
    return "\n".join(out + add) + "\n"


def merge_text(rel, cur, new):
    """返回合并后的文本；内容没有实质变化时返回 None。"""
    if rel.endswith(".json"):
        try:
            c = json.loads(cur) if cur and cur.strip() else MISSING
        except json.JSONDecodeError as e:
            raise LoomError(f"{rel} 不是合法的 JSON：{e}")
        result = merge3(c, MISSING, json.loads(new))
        return None if c is not MISSING and result == c else json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    text = merge_lines(cur, new)
    return None if text == cur else text


class Report:
    def __init__(self):
        self.sections = {}

    def add(self, section, line):
        lines = self.sections.setdefault(section, [])
        if line not in lines:
            lines.append(line)

    def print(self, title):
        print(f"# {title}\n")
        for section, lines in self.sections.items():
            print(f"## {section}\n\n" + "\n".join(lines) + "\n")
        if not self.sections:
            print("（没有变化）")


# ---------- 模块与模板 ----------

def available_modules():
    return sorted(p.name for p in PROJECT_TPL.iterdir() if (p / "module.json").is_file())


def module_meta(m):
    return json.loads((PROJECT_TPL / m / "module.json").read_text(encoding="utf-8"))


def resolve_modules(requested):
    available, out = available_modules(), []

    def visit(m):
        if m in out:
            return
        if m not in available:
            raise LoomError(f"没有模块 {m}。可用模块：{', '.join(available)}")
        for r in module_meta(m).get("requires", []):
            visit(r)
        out.append(m)

    for m in requested:
        visit(m)
    return out


def split_modules(values):
    return [m.strip() for v in values or [] for m in v.split(",") if m.strip()]


def block_text():
    body = read(TEMPLATES / "loom-block.md").strip()
    return f"{BLOCK_BEGIN}\n{body}\n{BLOCK_END}"


def render(text, kb):
    ctx = {"PROJECT_NAME": kb["name"], "SUMMARY": kb.get("summary", ""), "DATE": kb["created"],
           "LOOM_BLOCK": block_text()}
    for k, v in ctx.items():
        text = text.replace("{{" + k + "}}", v)
    return text


def install_module(root, m, kb, report):
    base = PROJECT_TPL / m
    for f in sorted(base.rglob("*")):
        if f.is_dir() or f == base / "module.json":
            continue
        rel = f.relative_to(base).as_posix()
        rel = rel[:-5] if rel.endswith(".tmpl") else rel
        new, target = render(read(f), kb), root / rel
        cur = read(target)
        if rel.endswith(".json") or rel.rsplit("/", 1)[-1] == ".gitignore":
            text = merge_text(rel, cur, new)
            if text is not None:
                write(target, text)
                report.add("合并的文件", f"- {rel}")
        elif cur is None:
            write(target, new)
            report.add("新建的文件", f"- {rel}")
        elif cur != new:
            write(root / (rel + ".loom-new"), new)
            report.add("⚠️ 已存在同名文件（模板写入 .loom-new，请合并后删除）", f"- {rel}")
    for d in module_meta(m).get("dirs", []):
        p = root / d
        p.mkdir(parents=True, exist_ok=True)
        if not any(p.iterdir()):
            (p / ".gitkeep").write_bytes(b"")


def save_kb(root, kb):
    write(root / KB_FILE, json.dumps(kb, ensure_ascii=False, indent=2) + "\n")


def require_root(args):
    root = find_root(args.root)
    if root is None:
        raise LoomError("当前目录不在 Loom 项目中（向上找不到 .kb.json）。新项目请先初始化（loom.py init）。")
    return root


def block_state(root):
    text = read(root / "AGENTS.md")
    if text is None:
        return "没有 AGENTS.md"
    if BLOCK_BEGIN not in text or BLOCK_END not in text:
        return "AGENTS.md 中没有 Loom 区块"
    current = text[text.index(BLOCK_BEGIN):text.index(BLOCK_END) + len(BLOCK_END)]
    return None if current == block_text() else "AGENTS.md 中的 Loom 区块不是当前版本"


def git_dirty(root):
    if not (root / ".git").exists():
        return None
    r = subprocess.run(["git", "-C", str(root), "status", "--porcelain"], capture_output=True)
    return bool(r.stdout.strip())


# ---------- 命令 ----------

def cmd_init(args):
    root = Path(args.root or os.getcwd()).resolve()
    if (root / KB_FILE).exists():
        raise LoomError(f"{root} 已经是 Loom 项目（存在 {KB_FILE}）。启用新模块用 module add。")
    outer = find_root(root.parent) if root.parent != root else None
    if outer and not args.force:
        raise LoomError(f"这个目录位于 Loom 项目 {outer} 之内。请在它外面新建项目，确实需要嵌套时加 --force。")
    mods = resolve_modules(["core", *split_modules(args.modules)])
    kb = {
        "name": args.name or root.name,
        "summary": args.summary or "",
        "created": date.today().isoformat(),
        "status": "active",
        "modules": mods,
        "schema": SCHEMA,
        "loom_version": skill_version(),
    }
    report = Report()
    for m in mods:
        install_module(root, m, kb, report)
    save_kb(root, kb)
    report.add("配置", f"- 已写入 {KB_FILE}：模块 {', '.join(mods)}，结构版本 {SCHEMA}")
    report.print(f"Loom 初始化：{kb['name']}（Loom {skill_version()}）")


def cmd_module(args):
    if args.action == "list":
        for m in available_modules():
            meta = module_meta(m)
            req = f"（依赖：{', '.join(meta['requires'])}）" if meta.get("requires") else ""
            print(f"- **{m}**：{meta.get('description', '')}{req}")
        return
    root = require_root(args)
    kb = load_kb(root)
    new = [m for m in resolve_modules([*kb.get("modules", ["core"]), *split_modules(args.modules)])
           if m not in kb.get("modules", [])]
    if not new:
        print("这些模块都已启用。")
        return
    report = Report()
    for m in new:
        install_module(root, m, kb, report)
    kb["modules"] = [*kb.get("modules", []), *new]
    save_kb(root, kb)
    report.print(f"启用模块：{', '.join(new)}")


def cmd_status(args):
    import export_session
    import kb as kbmod

    root = require_root(args)
    meta = load_kb(root)
    out = [f"- 知识库根目录：{root}",
           f"- 项目：{meta.get('name', root.name)}（状态 {meta.get('status', 'active')}；"
           f"模块 {', '.join(meta.get('modules', []))}）",
           f"- Loom：{skill_version()}（skill 目录 {SKILL_DIR}）"]
    schema = meta.get("schema", 0)
    if schema < SCHEMA:
        out.append(f"- ⚠️ 需要迁移：项目结构版本是 {schema}，当前 Loom 需要 {SCHEMA}。请按 references/migrate.md 执行。")
    elif schema > SCHEMA:
        out.append(f"- ⚠️ 项目结构版本 {schema} 比当前 Loom 支持的 {SCHEMA} 新，请先升级 Loom skill。")
    problem = block_state(root)
    if problem and schema >= SCHEMA:
        out.append(f"- ⚠️ {problem}：运行 loom.py refresh-block")
    if not args.no_export:
        export_session.set_root(root)
        found = export_session.project_transcripts()
        for p in found:
            try:
                export_session.export(p)
            except Exception as e:  # 单个记录损坏不影响其他
                out.append(f"- ⚠️ 导出 {Path(p).name} 失败：{e}")
        out.append(f"- 已补导出本项目的 Claude Code 会话记录 {len(found)} 个")
    kbmod.set_root(root)
    notes = kbmod.collect_notes()
    out += [f"- {r}" for r in kbmod.reminders(notes)]
    pending = kbmod.unarchived(notes)
    if pending:
        out.append("- 未归档的会话：")
        out += [f"  - {n.rel}（{n.meta.get('started', '')}，{n.meta.get('prompts', '?')} 条提问，{n.meta['title']}）"
                for n in pending[-10:]]
    print("# Loom 状态\n\n" + "\n".join(out))


def cmd_template(args):
    name = args.name if args.name.endswith(".md") else args.name + ".md"
    root = find_root(args.root)
    candidates = ([root / "90-Templates" / name] if root else []) + [NOTES_TPL / name]
    for c in candidates:
        if c.is_file():
            print(c)
            return
    raise LoomError(f"没有模板 {name}。可用模板：{'、'.join(p.stem for p in sorted(NOTES_TPL.glob('*.md')))}")


def refresh_block(root):
    f = root / "AGENTS.md"
    text, block = read(f), block_text()
    if text is None:
        kb = load_kb(root)
        text = f"# {kb.get('name', root.name)}\n\n{block}\n"
    elif BLOCK_BEGIN in text and BLOCK_END in text:
        start, end = text.index(BLOCK_BEGIN), text.index(BLOCK_END) + len(BLOCK_END)
        text = text[:start] + block + text[end:]
    else:
        lines = text.split("\n")
        at = 1 if lines and lines[0].startswith("# ") else 0
        text = "\n".join(lines[:at] + ["", block, ""] + lines[at:])
    write(f, text)


def cmd_refresh_block(args):
    root = require_root(args)
    problem = block_state(root)
    if not problem:
        print("AGENTS.md 中的 Loom 区块已是当前版本。")
        return
    refresh_block(root)
    print(f"已更新 AGENTS.md 中的 Loom 区块（原因：{problem}）。区块之外的内容没有改动。")


# ---------- 迁移 ----------

LOOM01_SKILLS = ("wrapup", "ingest", "lint", "close", "loom-upgrade")
LOOM01_SCRIPTS = ("export_session.py", "kb.py", "sync_repos.py")


def strip_loom01_hooks(settings_file, plan):
    """去掉 Loom 0.1 写入的 hook（命令中含 scripts/export_session.py 或 scripts/kb.py）。"""
    text = read(settings_file)
    if text is None:
        return
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return
    hooks = data.get("hooks", {})
    is_loom = lambda h: any(s in h.get("command", "") for s in ("scripts/export_session.py", "scripts/kb.py"))
    changed = False
    for event in list(hooks):
        groups = []
        for g in hooks[event]:
            kept = [h for h in g.get("hooks", []) if not is_loom(h)]
            changed |= len(kept) != len(g.get("hooks", []))
            if kept:
                groups.append({**g, "hooks": kept})
        if groups:
            hooks[event] = groups
        else:
            del hooks[event]
    if not changed:
        return
    if not hooks:
        data.pop("hooks", None)
    rel = settings_file.as_posix()

    def act():
        if data:
            write(settings_file, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        else:
            settings_file.unlink()
            exclude = settings_file.parent.parent / ".git" / "info" / "exclude"
            lines = (read(exclude) or "").splitlines()
            if ".claude/settings.local.json" in lines:
                write(exclude, "\n".join(x for x in lines if x != ".claude/settings.local.json") + "\n")
    plan.append((f"去掉 {rel} 中 Loom 0.1 的 hook" + ("" if data else "（文件因此为空，删除）"), act))


def migrate_0_to_1(root, kb):
    """Loom 0.1（每个项目各装一份）→ 0.2（全局 skill，项目中只有数据）。"""
    plan = []

    def remove(p, desc):
        plan.append((desc, lambda: shutil.rmtree(p) if p.is_dir() else p.unlink()))

    for name in LOOM01_SCRIPTS:
        if (root / "scripts" / name).is_file():
            remove(root / "scripts" / name, f"删除 scripts/{name}（改由 loom skill 提供）")
    if (root / "LOOM-RULES.md").is_file():
        remove(root / "LOOM-RULES.md", "删除 LOOM-RULES.md（规则改由 loom skill 提供）")
    for name in LOOM01_SKILLS:
        skill = root / ".claude" / "skills" / name
        if ".kb.json" in (read(skill / "SKILL.md") or ""):
            remove(skill, f"删除 .claude/skills/{name}（改用全局的 loom skill）")
    strip_loom01_hooks(root / ".claude" / "settings.json", plan)
    for tpl in sorted((root / "90-Templates").glob("*.md")):
        if read(tpl) == read(NOTES_TPL / tpl.name):
            remove(tpl, f"删除 90-Templates/{tpl.name}（与 Loom 默认模板相同）")
    repos = root / "repos"
    for repo in sorted(repos.iterdir()) if repos.is_dir() else []:
        strip_loom01_hooks(repo / ".claude" / "settings.local.json", plan)

    claude, agents = read(root / "CLAUDE.md"), read(root / "AGENTS.md")
    if agents is None:
        def to_agents():
            lines = [x for x in (claude or f"# {kb.get('name', root.name)}\n").split("\n")
                     if "LOOM-RULES" not in x and "`.kb.json` 的 `modules`" not in x]
            write(root / "AGENTS.md", "\n".join(lines))
            refresh_block(root)
            write(root / "AGENTS.md", re.sub(r"\n{3,}", "\n\n", read(root / "AGENTS.md")))  # 去掉删行留下的空行
            write(root / "CLAUDE.md", read(PROJECT_TPL / "core" / "CLAUDE.md.tmpl"))
        plan.append(("把 CLAUDE.md 的内容移到 AGENTS.md（去掉 @LOOM-RULES.md 等 0.1 的说明，加入 Loom 区块），"
                     "CLAUDE.md 改为只引用 AGENTS.md", to_agents))
    else:
        plan.append(("在 AGENTS.md 中加入 Loom 区块；CLAUDE.md 中的 @LOOM-RULES.md 需要手工删除", lambda: refresh_block(root)))

    def update_kb():
        for key in ("python", "loom"):
            kb.pop(key, None)
        kb["schema"], kb["loom_version"] = 1, skill_version()
        save_kb(root, kb)
    plan.append(("更新 .kb.json：去掉 python、loom 字段，写入 schema 1", update_kb))

    def cleanup_dirs():
        for d in ("scripts", "90-Templates", ".claude/skills", ".claude"):
            p = root / d
            if p.is_dir() and not any(p.iterdir()):
                p.rmdir()
    plan.append(("删除因此变空的目录", cleanup_dirs))
    if (root / ".loom").is_dir():
        plan.append(("提示：.loom/ 已不再需要，确认后可以手工删除（以及 .gitignore 中的 .loom/ 一行）", lambda: None))
    return plan


MIGRATIONS = {0: migrate_0_to_1}  # 从结构版本 N 迁移到 N+1


def cmd_migrate(args):
    root = require_root(args)
    kb = load_kb(root)
    schema = kb.get("schema", 0)
    if schema >= SCHEMA:
        print(f"项目结构已是版本 {schema}，不需要迁移。")
        return
    dirty = git_dirty(root)
    if not args.dry_run and not args.force:
        if dirty is None:
            raise LoomError("项目不是 git 仓库。迁移前请先 git init 并提交，便于审阅和回滚（或加 --force）。")
        if dirty:
            raise LoomError("项目有未提交的改动，请先提交，便于用 git diff 审阅迁移结果（或加 --force）。")
    plan = []
    for v in range(schema, SCHEMA):
        plan += MIGRATIONS[v](root, kb)
    print(f"# 迁移：结构版本 {schema} → {SCHEMA}" + ("（预览，未执行）" if args.dry_run else "") + "\n")
    for desc, act in plan:
        if not args.dry_run:
            act()
        print(f"- {desc}")


def cmd_doctor(args):
    out = []
    ok = lambda s: out.append(f"- ✅ {s}")
    warn = lambda s: out.append(f"- ⚠️ {s}")
    ok(f"Loom {skill_version()}，skill 目录 {SKILL_DIR}")
    ok(f"Python {sys.version.split()[0]}")
    (ok if shutil.which("git") else warn)("git " + ("可用" if shutil.which("git") else "不可用"))
    if (SKILL_DIR / ".claude-plugin" / "plugin.json").is_file():
        ok("包含 Claude Code 增强层（hook）。在 Claude Code 中可用 /plugin 查看 loom@skills-dir 是否已加载")
    settings = Path.home() / ".claude" / "settings.json"
    try:
        days = json.loads(read(settings) or "{}").get("cleanupPeriodDays")
    except json.JSONDecodeError:
        days = None
    if settings.parent.is_dir() and (days is None or days < 90):
        warn("Claude Code 会定期清理会话记录（cleanupPeriodDays，默认约 30 天）。Loom 从这些记录补导出对话，"
             "建议在 ~/.claude/settings.json 中把 cleanupPeriodDays 设为 365 或更大")
    root = find_root(args.root)
    if root is None:
        out.append("- 当前目录不在 Loom 项目中，只检查了本机环境。")
    else:
        kb = load_kb(root)
        schema = kb.get("schema", 0)
        (ok if schema == SCHEMA else warn)(f"项目 {kb.get('name', root.name)}：结构版本 {schema}（当前 {SCHEMA}）")
        problem = block_state(root)
        (warn if problem else ok)(problem or "AGENTS.md 中的 Loom 区块是当前版本")
        if "@AGENTS.md" not in (read(root / "CLAUDE.md") or ""):
            warn("CLAUDE.md 没有引用 @AGENTS.md，Claude Code 可能读不到项目指令")
        dirty = git_dirty(root)
        if dirty is None:
            warn("项目不是 git 仓库")
        leftovers = [p.relative_to(root).as_posix() for p in root.rglob("*.loom-new") if "repos" not in p.parts]
        if leftovers:
            warn("还有未处理的 .loom-new 文件：" + "、".join(leftovers))
    print("# Loom 检查\n\n" + "\n".join(out))


def main():
    utf8_stdout()
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", help="知识库根目录（默认从当前目录向上查找 .kb.json；init 时为要初始化的目录）")
    parser = argparse.ArgumentParser(description="Loom 项目管理")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", parents=[common], help="初始化项目")
    p.add_argument("--name")
    p.add_argument("--summary")
    p.add_argument("--modules", action="append", help="除 core 外要启用的模块，逗号分隔")
    p.add_argument("--force", action="store_true", help="允许在另一个 Loom 项目内部初始化")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("module", parents=[common], help="列出或启用模块")
    p.add_argument("action", choices=["list", "add"])
    p.add_argument("modules", nargs="*")
    p.set_defaults(func=cmd_module)

    p = sub.add_parser("status", parents=[common], help="项目状态")
    p.add_argument("--no-export", action="store_true", help="不补导出对话")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("template", parents=[common], help="输出模板路径")
    p.add_argument("name")
    p.set_defaults(func=cmd_template)

    sub.add_parser("refresh-block", parents=[common], help="更新 Loom 区块").set_defaults(func=cmd_refresh_block)

    p = sub.add_parser("migrate", parents=[common], help="迁移项目结构")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true", help="跳过 git 工作区检查")
    p.set_defaults(func=cmd_migrate)

    sub.add_parser("doctor", parents=[common], help="检查项目和本机环境").set_defaults(func=cmd_doctor)

    args = parser.parse_args()
    try:
        args.func(args)
    except LoomError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
