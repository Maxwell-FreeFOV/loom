"""Loom 项目管理：初始化、启用模块、状态检查、模板、Loom 区块、结构迁移、体检。属于 Loom skill。

用法（python 指 Python 3；除 init 外，在项目根目录或其子目录中运行，也可以用 --root 指定根目录）：
  python loom.py init --name 名称 [--summary 一句话] [--modules research,engineering,outputs] [--language en|zh-CN]
  python loom.py module list | add <模块> [...]
  python loom.py status [--no-export]   每个 Loom 操作的第一步：补导出对话，检查结构版本和 Loom 区块，列出提醒
  python loom.py template <名称>        输出应使用的笔记模板路径（稳定 ID 或中文别名均可；项目 90-Templates/ 优先）
  python loom.py refresh-block          把 AGENTS.md 中的 Loom 区块更新为当前版本
  python loom.py migrate [--dry-run]    把项目结构迁移到当前版本
  python loom.py doctor                 检查项目和本机环境

项目模板在 assets/templates/project/<模块>/ 下：shared/ 是语言中立文件，zh-CN/ 与 en/ 按项目语言安装；
其中的路径就是文件在项目中的路径；文件名以 .tmpl 结尾时去掉这个后缀。模板中的 {{PROJECT_NAME}} {{SUMMARY}}
{{DATE}} {{LOOM_BLOCK}} 会被替换。笔记模板在 assets/templates/notes/<语言>/<稳定 ID>.md。
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

from kbroot import KB_FILE, LANGUAGES, SCHEMA, SKILL_DIR, ConfigError, find_root, kb_language, L, load_kb, \
    skill_version, utf8_stdout

TEMPLATES = SKILL_DIR / "assets" / "templates"
PROJECT_TPL = TEMPLATES / "project"
NOTES_TPL = TEMPLATES / "notes"
BLOCK_BEGIN, BLOCK_END = "<!-- loom:begin -->", "<!-- loom:end -->"
MISSING = object()

# 笔记模板的稳定 ID 与中文别名（双向映射；查找时 ASCII 大小写不敏感，ADR 与 adr 等价）
TEMPLATE_IDS = ("session", "decision", "wiki", "source", "literature", "experiment", "output", "design", "adr")
TEMPLATE_ZH = {"session": "会话纪要", "decision": "决策记录", "wiki": "wiki页", "source": "资料卡",
               "literature": "文献卡", "experiment": "实验记录", "output": "产出文档", "design": "设计文档",
               "adr": "ADR"}
TEMPLATE_ALIASES = {k: v for tid in TEMPLATE_IDS for k, v in ((tid, tid), (TEMPLATE_ZH[tid], tid))}

# 不在任何项目里时的界面语言：CLI 的默认姿态（init 的 --language 缺省也是 en）。
# 在项目里一律按项目语言；配置损坏读不出语言时退回 zh-CN（损坏的配置多半是旧项目）。
NO_PROJECT_LANG = "en"


class LoomError(Exception):
    pass


def template_id(name):
    """模板名（稳定 ID 或中文别名）归一为稳定 ID；不认识的返回 None。ASCII 大小写不敏感。"""
    return TEMPLATE_ALIASES.get(name) or TEMPLATE_ALIASES.get(name.lower())


def project_lang(root):
    """项目语言；配置损坏时按 zh-CN（旧项目）处理，由调用方另行警告。"""
    try:
        return kb_language(load_kb(root))
    except ConfigError:
        return "zh-CN"


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
    def __init__(self, lang="zh-CN"):
        self.lang = lang
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
            print(L(self.lang, "（没有变化）", "(no changes)"))


# ---------- 模块与模板 ----------

def available_modules():
    return sorted(p.name for p in PROJECT_TPL.iterdir() if (p / "module.json").is_file())


def module_meta(m):
    return json.loads((PROJECT_TPL / m / "module.json").read_text(encoding="utf-8"))


def module_description(meta, lang):
    """module.json 的 description 是 {语言: 文本}：项目内按项目语言显示，项目外（lang=None）两种都列。"""
    desc = meta.get("description", "")
    if not isinstance(desc, dict):
        return desc
    if lang:
        return desc.get(lang) or next(iter(desc.values()), "")
    return " ｜ ".join(desc.get(lg, "") for lg in LANGUAGES if desc.get(lg))


def resolve_modules(requested, lang="zh-CN"):
    available, out = available_modules(), []

    def visit(m):
        if m in out:
            return
        if m not in available:
            raise LoomError(L(lang, f"没有模块 {m}。可用模块：{', '.join(available)}",
                              f"No module named {m}. Available modules: {', '.join(available)}"))
        for r in module_meta(m).get("requires", []):
            visit(r)
        out.append(m)

    for m in requested:
        visit(m)
    return out


def split_modules(values):
    return [m.strip() for v in values or [] for m in v.split(",") if m.strip()]


def block_text(lang):
    body = read(TEMPLATES / "loom-block" / f"{lang}.md").strip()
    return f"{BLOCK_BEGIN}\n{body}\n{BLOCK_END}"


def render(text, kb):
    ctx = {"PROJECT_NAME": kb["name"], "SUMMARY": kb.get("summary", ""), "DATE": kb["created"],
           "LOOM_BLOCK": block_text(kb_language(kb))}
    for k, v in ctx.items():
        text = text.replace("{{" + k + "}}", v)
    return text


def install_module(root, m, kb, report):
    """安装一个模块：shared 层（语言中立文件）+ 项目语言的 overlay 层，合并规则不变。"""
    base = PROJECT_TPL / m
    lang = kb_language(kb)
    for layer in (base / "shared", base / lang):
        if not layer.is_dir():
            continue
        for f in sorted(layer.rglob("*")):
            if f.is_dir():
                continue
            rel = f.relative_to(layer).as_posix()
            rel = rel[:-5] if rel.endswith(".tmpl") else rel
            new, target = render(read(f), kb), root / rel
            cur = read(target)
            if rel.endswith(".json") or rel.rsplit("/", 1)[-1] == ".gitignore":
                text = merge_text(rel, cur, new)
                if text is not None:
                    write(target, text)
                    report.add(L(lang, "合并的文件", "Merged files"), f"- {rel}")
            elif cur is None:
                write(target, new)
                report.add(L(lang, "新建的文件", "New files"), f"- {rel}")
            elif cur != new:
                write(root / (rel + ".loom-new"), new)
                report.add(L(lang, "⚠️ 已存在同名文件（模板写入 .loom-new，请合并后删除）",
                             "⚠️ File already exists (template written to .loom-new; merge it and delete the "
                             ".loom-new file)"), f"- {rel}")
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
        raise LoomError("Not in a Loom project (no .kb.json found in this directory or its parents). "
                        "To create a new project, run loom.py init.")
    return root


def block_state(root, lang):
    text = read(root / "AGENTS.md")
    if text is None:
        return L(lang, "没有 AGENTS.md", "AGENTS.md is missing")
    if BLOCK_BEGIN not in text or BLOCK_END not in text:
        return L(lang, "AGENTS.md 中没有 Loom 区块", "AGENTS.md has no Loom block")
    current = text[text.index(BLOCK_BEGIN):text.index(BLOCK_END) + len(BLOCK_END)]
    return None if current == block_text(lang) else L(lang, "AGENTS.md 中的 Loom 区块不是当前版本",
                                                      "The Loom block in AGENTS.md is not the current version")


def git_dirty(root):
    if not (root / ".git").exists():
        return None
    r = subprocess.run(["git", "-C", str(root), "status", "--porcelain"], capture_output=True)
    return bool(r.stdout.strip())


# ---------- 命令 ----------

def cmd_init(args):
    root = Path(args.root or os.getcwd()).resolve()
    lang = args.language
    if (root / KB_FILE).exists():
        plang = project_lang(root)  # 用已有项目的语言报错
        raise LoomError(L(plang, f"{root} 已经是 Loom 项目（存在 {KB_FILE}）。启用新模块用 module add。",
                          f"{root} is already a Loom project ({KB_FILE} exists). "
                          f"Use module add to enable more modules."))
    outer = find_root(root.parent) if root.parent != root else None
    if outer and not args.force:
        plang = project_lang(outer)
        raise LoomError(L(plang, f"这个目录位于 Loom 项目 {outer} 之内。请在它外面新建项目，确实需要嵌套时加 --force。",
                          f"This directory is inside Loom project {outer}. Create the project outside it, "
                          f"or add --force if nesting is really intended."))
    mods = resolve_modules(["core", *split_modules(args.modules)], lang)
    kb = {
        "name": args.name or root.name,
        "summary": args.summary or "",
        "created": date.today().isoformat(),
        "status": "active",
        "language": lang,
        "modules": mods,
        "auto_amend": False,  # 显式改为 true 后，hook 才会把提交后的会话尾巴并入那次提交
        "schema": SCHEMA,
        "loom_version": skill_version(),
    }
    report = Report(lang)
    for m in mods:
        install_module(root, m, kb, report)
    save_kb(root, kb)
    report.add(L(lang, "配置", "Configuration"),
               L(lang, f"- 已写入 {KB_FILE}：模块 {', '.join(mods)}，结构版本 {SCHEMA}，语言 {lang}",
                 f"- Wrote {KB_FILE}: modules {', '.join(mods)}, schema {SCHEMA}, language {lang}"))
    report.print(L(lang, f"Loom 初始化：{kb['name']}（Loom {skill_version()}）",
                   f"Loom init: {kb['name']} (Loom {skill_version()})"))


def cmd_module(args):
    if args.action == "list":
        root = find_root(args.root)
        lang = project_lang(root) if root else None  # 项目外两种语言都列
        for m in available_modules():
            meta = module_meta(m)
            req = (f"（{L(lang or 'zh-CN', '依赖', 'requires')}：{', '.join(meta['requires'])}）"
                   if meta.get("requires") else "")
            print(f"- **{m}**：{module_description(meta, lang)}{req}")
        return
    root = require_root(args)
    kb = load_kb(root)
    lang = kb_language(kb)
    new = [m for m in resolve_modules([*kb.get("modules", ["core"]), *split_modules(args.modules)], lang)
           if m not in kb.get("modules", [])]
    if not new:
        print(L(lang, "这些模块都已启用。", "These modules are already enabled."))
        return
    report = Report(lang)
    for m in new:
        install_module(root, m, kb, report)
    kb["modules"] = [*kb.get("modules", []), *new]
    save_kb(root, kb)
    report.print(L(lang, f"启用模块：{', '.join(new)}", f"Modules enabled: {', '.join(new)}"))


def cmd_status(args):
    import export_session
    import kb as kbmod

    root = require_root(args)
    try:
        meta = load_kb(root)
        lang = kb_language(meta)
    except ConfigError as e:  # status 是只读的，配置损坏时警告后继续，不阻断
        print(f"⚠️ {e}", file=sys.stderr)
        meta, lang = {}, "zh-CN"
    out = [L(lang, f"- 知识库根目录：{root}", f"- Knowledge base root: {root}"),
           L(lang, f"- 项目：{meta.get('name', root.name)}（状态 {meta.get('status', 'active')}；"
                   f"模块 {', '.join(meta.get('modules', []))}；语言 {lang}）",
             f"- Project: {meta.get('name', root.name)} (status {meta.get('status', 'active')}; "
             f"modules {', '.join(meta.get('modules', []))}; language {lang})"),
           L(lang, f"- Loom：{skill_version()}（skill 目录 {SKILL_DIR}）",
             f"- Loom: {skill_version()} (skill directory {SKILL_DIR})")]
    schema = meta.get("schema", 0)
    if schema < SCHEMA:
        out.append(L(lang, f"- ⚠️ 需要迁移：项目结构版本是 {schema}，当前 Loom 需要 {SCHEMA}。"
                           "请按 references/migrate.md 执行。",
                     f"- ⚠️ Migration needed: the project schema is {schema}, this Loom requires {SCHEMA}. "
                     "Follow references/migrate.md."))
    elif schema > SCHEMA:
        out.append(L(lang, f"- ⚠️ 项目结构版本 {schema} 比当前 Loom 支持的 {SCHEMA} 新，请先升级 Loom skill。",
                     f"- ⚠️ Project schema {schema} is newer than this Loom supports ({SCHEMA}); "
                     "please upgrade the loom skill first."))
    problem = block_state(root, lang)
    if problem and schema >= SCHEMA:
        out.append(L(lang, f"- ⚠️ {problem}：运行 loom.py refresh-block",
                     f"- ⚠️ {problem}: run loom.py refresh-block"))
    if not args.no_export:
        export_session.set_root(root)
        found, skipped = export_session.project_transcripts()
        for p in found:
            try:
                export_session.export(p)
            except Exception as e:  # 单个记录损坏不影响其他
                out.append(L(lang, f"- ⚠️ 导出 {Path(p).name} 失败：{e}",
                             f"- ⚠️ Failed to export {Path(p).name}: {e}"))
        out.append(L(lang, f"- 已补导出本项目的 Claude Code 会话记录 {len(found)} 个",
                     f"- Exported {len(found)} Claude Code session transcripts for this project"))
        if skipped:
            sep = L(lang, "、", ", ")
            names = sep.join(Path(p).name for p, *_ in skipped[:5])
            out.append(L(lang, f"- ⚠️ 跳过 {len(skipped)} 份无法确认归属的会话记录（缺少 cwd 或不属于本知识库）："
                               + names + (f" 等 {len(skipped)} 份" if len(skipped) > 5 else ""),
                         f"- ⚠️ Skipped {len(skipped)} transcripts whose ownership cannot be confirmed "
                         f"(missing cwd or outside this knowledge base): " + names
                         + (f" and {len(skipped) - 5} more" if len(skipped) > 5 else "")))
    kbmod.set_root(root)
    notes = kbmod.collect_notes()
    stale = kbmod.drift(notes, lang)
    if stale:
        out.append(f"- {stale}")
    out += [f"- {r}" for r in kbmod.reminders(notes, lang)]
    pending = kbmod.unarchived(notes)
    if pending:
        out.append(L(lang, "- 未归档的会话：", "- Unarchived sessions:"))
        out += [L(lang, f"  - {n.rel}（{n.meta.get('started', '')}，{n.meta.get('prompts', '?')} 条提问，"
                        f"{n.meta['title']}）",
                  f"  - {n.rel} ({n.meta.get('started', '')}, {n.meta.get('prompts', '?')} prompts, "
                  f"{n.meta['title']})")
                for n in pending[-10:]]
    print(L(lang, "# Loom 状态", "# Loom status") + "\n\n" + "\n".join(out))


def cmd_template(args):
    """解析顺序：① 项目 90-Templates/ 中按请求名原样命中 → ② 90-Templates/ 中按稳定 ID/别名命中
    （多个自定义文件映射同一 ID 且请求名无法消歧时报冲突，不任意选）→ ③ 内置 notes/<项目语言>/<id>.md。"""
    root = find_root(args.root)
    lang = kb_language(load_kb(root)) if root else NO_PROJECT_LANG  # 配置损坏时报错，不猜语言
    req = args.name[:-3] if args.name.endswith(".md") else args.name
    tpl_dir = root / "90-Templates" if root else None
    custom = sorted(tpl_dir.glob("*.md")) if tpl_dir and tpl_dir.is_dir() else []
    exact = [f for f in custom if f.stem == req]  # 按实际文件名精确比较，不受文件系统大小写影响
    if exact:
        print(exact[0])
        return
    tid = template_id(req)
    if tid:
        candidates = [f for f in custom if template_id(f.stem) == tid]
        if len(candidates) == 1:
            print(candidates[0])
            return
        if len(candidates) > 1:
            sep = L(lang, "、", ", ")
            raise LoomError(L(lang, f"模板冲突：90-Templates/ 中有多个文件对应 {tid}：{sep.join(f.name for f in candidates)}。"
                                    "请求名无法消歧，请改用准确的文件名，或删掉多余的文件。",
                              f"Template conflict: several files in 90-Templates/ map to {tid}: "
                              f"{sep.join(f.name for f in candidates)}. The requested name cannot disambiguate "
                              "them; use an exact file name or remove the extra files."))
        builtin = NOTES_TPL / lang / f"{tid}.md"
        if builtin.is_file():
            print(builtin)
            return
    sep = L(lang, "、", ", ")
    known = sep.join(f"{t}（{TEMPLATE_ZH[t]}）" if lang != "en" else f"{t} (alias: {TEMPLATE_ZH[t]})"
                     for t in TEMPLATE_IDS)
    raise LoomError(L(lang, f"没有模板 {args.name}。可用模板 ID 与别名：{known}",
                      f"No template named {args.name}. Available template IDs and aliases: {known}"))


def refresh_block(root, lang=None):
    if lang is None:
        lang = project_lang(root)
    f = root / "AGENTS.md"
    text, block = read(f), block_text(lang)
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
    lang = kb_language(load_kb(root))  # 配置损坏时报错：不能用猜出来的语言改写区块
    problem = block_state(root, lang)
    if not problem:
        print(L(lang, "AGENTS.md 中的 Loom 区块已是当前版本。", "The Loom block in AGENTS.md is already up to date."))
        return
    refresh_block(root, lang)
    print(L(lang, f"已更新 AGENTS.md 中的 Loom 区块（原因：{problem}）。区块之外的内容没有改动。",
            f"Updated the Loom block in AGENTS.md (reason: {problem}). Content outside the block is unchanged."))


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
        tid = template_id(tpl.stem)
        builtin = NOTES_TPL / "zh-CN" / f"{tid}.md" if tid else None  # 0.1 项目都是中文模板
        if builtin and builtin.is_file() and read(tpl) == read(builtin):
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
            write(root / "CLAUDE.md", read(PROJECT_TPL / "core" / "zh-CN" / "CLAUDE.md.tmpl"))
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


def migrate_1_to_2(root, kb):
    """结构版本 1 → 2（Loom 0.4 引入项目语言）：补 language: zh-CN（schema 1 及更早的项目都是中文项目）、
    写入 schema 2、更新 loom_version。不重命名任何文件，不改动笔记和自定义模板。"""
    plan = []

    def update_kb():
        kb.setdefault("language", "zh-CN")
        kb["schema"], kb["loom_version"] = 2, skill_version()
        save_kb(root, kb)
    plan.append(("更新 .kb.json：补 language: zh-CN，写入 schema 2（文件和笔记不动）", update_kb))
    return plan


MIGRATIONS = {0: migrate_0_to_1, 1: migrate_1_to_2}  # 从结构版本 N 迁移到 N+1


def cmd_migrate(args):
    root = require_root(args)
    kb = load_kb(root)
    lang = kb_language(kb)
    schema = kb.get("schema", 0)
    if schema >= SCHEMA:
        print(L(lang, f"项目结构已是版本 {schema}，不需要迁移。",
                f"Project schema is already version {schema}; no migration needed."))
        return
    dirty = git_dirty(root)
    if not args.dry_run and not args.force:
        if dirty is None:
            raise LoomError(L(lang, "项目不是 git 仓库。迁移前请先 git init 并提交，便于审阅和回滚（或加 --force）。",
                              "The project is not a git repository. Commit before migrating so the result can be "
                              "reviewed and rolled back (or add --force)."))
        if dirty:
            raise LoomError(L(lang, "项目有未提交的改动，请先提交，便于用 git diff 审阅迁移结果（或加 --force）。",
                              "The project has uncommitted changes. Commit them first so the migration can be "
                              "reviewed with git diff (or add --force)."))
    plan = []
    for v in range(schema, SCHEMA):
        plan += MIGRATIONS[v](root, kb)
    print(L(lang, f"# 迁移：结构版本 {schema} → {SCHEMA}", f"# Migration: schema {schema} → {SCHEMA}")
          + (L(lang, "（预览，未执行）", " (dry run, nothing changed)") if args.dry_run else "") + "\n")
    for desc, act in plan:
        if not args.dry_run:
            act()
        print(f"- {desc}")


def cmd_doctor(args):
    root = find_root(args.root)
    kb, lang, broken = {}, NO_PROJECT_LANG, None
    if root:
        try:
            kb = load_kb(root)
            lang = kb_language(kb)
        except ConfigError as e:  # doctor 是只读的，配置损坏时警告后继续
            broken, lang = e, "zh-CN"
    out = []
    ok = lambda s: out.append(f"- ✅ {s}")
    warn = lambda s: out.append(f"- ⚠️ {s}")
    ok(L(lang, f"Loom {skill_version()}，skill 目录 {SKILL_DIR}", f"Loom {skill_version()}, skill directory {SKILL_DIR}"))
    pyver = f"Python {sys.version.split()[0]}"
    (ok if sys.version_info >= (3, 12) else warn)(
        pyver if sys.version_info >= (3, 12) else L(lang, f"{pyver}：Loom 需要 Python 3.12 或更高版本",
                                                    f"{pyver}: Loom requires Python 3.12 or newer"))
    git_path = shutil.which("git")
    (ok if git_path else warn)(L(lang, f"git 可用（{git_path}）", f"git available ({git_path})") if git_path
                               else L(lang, "git 不可用", "git is not available"))
    bash = shutil.which("bash")
    (ok if bash else warn)(L(lang, f"bash 可用（{bash}）", f"bash available ({bash})") if bash else
                           L(lang, "bash 不可用：Claude Code 的 hook 需要可工作的 Bash（Windows 上是 Git Bash）",
                             "bash is not available: Claude Code hooks need a working Bash (Git Bash on Windows)"))
    plugin_ok = (SKILL_DIR / ".claude-plugin" / "plugin.json").is_file() and (SKILL_DIR / "hooks" / "hooks.json").is_file()
    (ok if plugin_ok else warn)(L(lang, "插件文件（.claude-plugin/plugin.json、hooks/hooks.json）存在",
                                  "Plugin files (.claude-plugin/plugin.json, hooks/hooks.json) exist") if plugin_ok
                                else L(lang, "插件文件（.claude-plugin/plugin.json、hooks/hooks.json）缺失",
                                       "Plugin files (.claude-plugin/plugin.json, hooks/hooks.json) are missing"))
    settings = Path.home() / ".claude" / "settings.json"
    try:
        conf = json.loads(read(settings) or "{}")
    except json.JSONDecodeError:
        conf = None
    if conf is None:
        warn(L(lang, f"{settings} 不是合法的 JSON", f"{settings} is not valid JSON"))
        conf = {}
    cmds = [h.get("command", "") for groups in conf.get("hooks", {}).values()
            for g in groups if isinstance(g, dict) for h in g.get("hooks", [])]
    loom_hooks = any("loom" in c and "run.sh" in c for c in cmds)
    (ok if loom_hooks else warn)(
        f"{settings} " + (L(lang, "中已有 loom 的 hook 配置", "already has loom's hook configuration") if loom_hooks
                          else L(lang, "中没有 loom 的 hook 配置（Claude Code 把 skill 目录加载为插件时不需要它；"
                                       "兜底可用 deploy.py --claude-hooks 写入）",
                                 "has no loom hook configuration (not needed when Claude Code loads the skill "
                                 "directory as a plugin; deploy.py --claude-hooks is the fallback)")))
    if settings.parent.is_dir():
        days = conf.get("cleanupPeriodDays")
        if days is None or days < 90:
            warn(L(lang, "Claude Code 会定期清理会话记录（cleanupPeriodDays，默认约 30 天）。Loom 从这些记录补导出对话，"
                         "建议在 ~/.claude/settings.json 中把 cleanupPeriodDays 设为 365 或更大",
                   "Claude Code periodically cleans up session transcripts (cleanupPeriodDays, about 30 days by "
                   "default). Loom re-exports conversations from these transcripts; consider setting "
                   "cleanupPeriodDays to 365 or more in ~/.claude/settings.json"))
    if root is None:
        out.append(L(lang, "- 当前目录不在 Loom 项目中，只检查了本机环境。",
                     "- Not in a Loom project; only the local environment was checked."))
    else:
        if broken:
            warn(L(lang, f"{broken}请先修复 {KB_FILE}。", f"{broken} Fix {KB_FILE} first."))
        schema = kb.get("schema", 0)
        (ok if schema == SCHEMA else warn)(L(lang, f"项目 {kb.get('name', root.name)}：结构版本 {schema}"
                                                   f"（当前 {SCHEMA}），语言 {lang}",
                                             f"Project {kb.get('name', root.name)}: schema {schema} "
                                             f"(current {SCHEMA}), language {lang}"))
        problem = block_state(root, lang)
        (warn if problem else ok)(problem or L(lang, "AGENTS.md 中的 Loom 区块是当前版本",
                                               "The Loom block in AGENTS.md is up to date"))
        if "@AGENTS.md" not in (read(root / "CLAUDE.md") or ""):
            warn(L(lang, "CLAUDE.md 没有引用 @AGENTS.md，Claude Code 可能读不到项目指令",
                   "CLAUDE.md does not reference @AGENTS.md; Claude Code may not see the project instructions"))
        dirty = git_dirty(root)
        if dirty is None:
            warn(L(lang, "项目不是 git 仓库", "The project is not a git repository"))
        leftovers = [p.relative_to(root).as_posix() for p in root.rglob("*.loom-new") if "repos" not in p.parts]
        if leftovers:
            warn(L(lang, "还有未处理的 .loom-new 文件：" + "、".join(leftovers),
                   "Unprocessed .loom-new files: " + ", ".join(leftovers)))
    out += ["",
            L(lang, "以上只是文件与配置层面的检查，不能证明 hook 已生效。实测方法：在临时目录中用 loom.py init 初始化一个项目，"
                    "用 Claude Code 在其中做一次短会话——会话开始时应注入 Loom 上下文（项目状态与 hot.md），"
                    "结束后 40-Sessions/raw/ 下应出现导出的对话。",
              "These are file- and configuration-level checks only; they do not prove the hooks are live. "
              "To verify: run loom.py init in a temporary directory and do a short Claude Code session in it — "
              "the Loom context (project status and hot.md) should be injected at session start, and the exported "
              "conversation should appear under 40-Sessions/raw/ when it ends.")]
    print(L(lang, "# Loom 检查", "# Loom doctor") + "\n\n" + "\n".join(out))


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
    p.add_argument("--language", choices=LANGUAGES, default="en",
                   help="项目语言（缺省 en；没有 language 字段的旧项目按 zh-CN 处理）")
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
    except (LoomError, ConfigError) as e:  # ConfigError：.kb.json 损坏，阻断会改动配置的操作
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
