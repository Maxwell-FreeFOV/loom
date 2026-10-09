"""知识库工具：索引、检查、未归档会话、会话启动提示。属于 Loom skill。

用法（在知识库根目录或其子目录中运行，也可以用 --root 指定根目录）：
  python kb.py index          生成 00-Hub/index.md
  python kb.py lint           检查死链、frontmatter、孤立页、未登记资料、未归档会话、到期决策等
  python kb.py unarchived     列出还没有被会话纪要引用的原始对话
  python kb.py session-start  Claude Code 的 SessionStart hook 使用：输出项目状态、通用规则、hot.md 和提醒
"""
import json
import os
import re
import subprocess
import sys
from collections import namedtuple
from datetime import date, datetime, timedelta
from pathlib import Path

from kbroot import SKILL_DIR, ConfigError, find_root, kb_language, L, load_kb as read_kb, utf8_stdout

ROOT = HUB = RAW_DIR = SOURCES_INDEX = None
RULES = SKILL_DIR / "references" / "rules.md"

# 不属于知识库内容的目录（任何层级）
PRUNE = {".git", ".loom", ".obsidian", ".trash", "repos", "node_modules", "__pycache__"}
# 除上面之外，收集笔记时还要跳过的目录
NOT_NOTES = PRUNE | {".claude", "scripts", "90-Templates"}
ROOT_FILES = {"CLAUDE.md", "LOOM-RULES.md", "AGENTS.md", "README.md"}

FM = re.compile(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", re.S)
LINK = re.compile(r"!?\[\[([^\]\|#]+)(?:#[^\]\|]*)?(?:\\?\|[^\]]*)?\]\]")
CODE = re.compile(r"```.*?```|`[^`\n]*`|<!--.*?-->", re.S)  # 代码和注释里的 [[ ]] 不算链接
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
RECENT_RAW = 15
REVIEW_AHEAD_DAYS = 14
HOT_LINES = 60
# 已关闭的决策状态：不再提示复盘。旧项目的中文状态与新英文状态等价。
CLOSED_DECISIONS = {"已复盘", "已推翻", "reviewed", "superseded"}

Note = namedtuple("Note", "path rel meta has_fm text")


def set_root(root):
    global ROOT, HUB, RAW_DIR, SOURCES_INDEX
    ROOT = Path(root)
    HUB = ROOT / "00-Hub"
    RAW_DIR = ROOT / "40-Sessions" / "raw"
    SOURCES_INDEX = ROOT / "20-Sources" / "sources-index.md"


def load_kb():
    """配置损坏时警告并按空配置继续：kb.py 服务索引、体检和 SessionStart hook，不能因为配置问题崩掉。"""
    try:
        return read_kb(ROOT)
    except ConfigError as e:
        print(f"⚠️ {e}本次按空配置继续；请修复 {ROOT / '.kb.json'} 后再做发布和会改动配置的操作。", file=sys.stderr)
        return {}


def walk(prune):
    # os.walk 默认 followlinks=False，不会跟随符号链接目录；但 Windows 的目录联接（junction）
    # 在 scandir 里不被视为符号链接，os.walk 照样会进入，所以这里显式剔除所有链接目录，
    # 保证遍历结果不会穿过目录链接（快照发布依赖这一点：库外内容不能借链接混进发布范围）。
    for dirpath, dirnames, filenames in os.walk(ROOT):
        kept = []
        for d in dirnames:
            p = Path(dirpath, d)
            if d not in prune and not p.is_symlink() and not os.path.isjunction(p):
                kept.append(d)
        dirnames[:] = kept
        for name in filenames:
            yield Path(dirpath) / name


def unquote(v):
    """只去掉成对包住整个值的引号；值本身以引号结尾时（例如 采用"某方案"）保持原样。"""
    return v[1:-1] if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'" else v


def frontmatter(text):
    m = FM.match(text)
    meta = {}
    for line in (m.group(1).splitlines() if m else []):
        k, sep, v = line.partition(":")
        if sep and not line.startswith((" ", "\t", "-")):
            meta[k.strip()] = unquote(v.split(" #")[0].strip())
    return meta, bool(m)


def collect_notes():
    notes = []
    for p in walk(NOT_NOTES):
        if p.suffix.lower() != ".md" or (p.parent == ROOT and p.name in ROOT_FILES):
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        meta, has_fm = frontmatter(text)
        meta.setdefault("title", p.stem)
        notes.append(Note(p, p.relative_to(ROOT).as_posix(), meta, has_fm, text))
    return notes


def links(text):
    targets = []
    for m in LINK.finditer(CODE.sub("", text)):
        t = m.group(1).rstrip("\\").strip()
        if t:
            targets.append(t)
    return targets


def link(note, in_table=False):
    target = note.rel[:-3] if note.rel.endswith(".md") else note.rel
    sep = "\\|" if in_table else "|"  # 表格内的 | 需要转义
    return f"[[{target}{sep}{note.meta['title']}]]"


def in_dir(notes, prefix, types=None):
    items = [n for n in notes if n.rel.startswith(prefix) and (types is None or n.meta.get("type") in types)]
    return sorted(items, key=lambda n: n.path.name, reverse=True)


def unarchived(notes):
    """还没有被 40-Sessions/notes/ 中任何笔记链接到的原始对话（按时间顺序）。"""
    linked = set()
    for n in notes:
        if n.rel.startswith("40-Sessions/notes/"):
            for t in links(n.text):
                name = t.split("/")[-1]
                linked.add((name[:-3] if name.lower().endswith(".md") else name).lower())
    raws = [n for n in notes if n.rel.startswith("40-Sessions/raw/")]
    return sorted((n for n in raws if n.path.stem.lower() not in linked), key=lambda n: n.path.name)


def due_decisions(notes, ahead_days):
    today = date.today()
    due = []
    for n in in_dir(notes, "40-Sessions/decisions/"):
        rd = n.meta.get("review_date", "")
        if DATE_RE.fullmatch(rd) and n.meta.get("status") not in CLOSED_DECISIONS:
            d = date.fromisoformat(rd)
            if d <= today + timedelta(days=ahead_days):
                due.append((d, n))
    return sorted(due, key=lambda x: x[0])


def table(header, rows, lang):
    if not rows:
        return [L(lang, "（暂无）", "(none)"), ""]
    return ["| " + " | ".join(header) + " |", "|" + "---|" * len(header), *rows, ""]


def summary_of(note, in_table=False):
    """frontmatter 的 summary（一句话结论）：有了它，不打开笔记就能从索引判断相关性。"""
    s = note.meta.get("summary", "")
    return s.replace("|", "\\|") if in_table else s


def count_suffix(lang, n):
    """节标题里的计数：中文用全角括号，英文用半角。"""
    return f"（{n}）" if lang != "en" else f" ({n})"


# ---------- index ----------

def cmd_index():
    notes = collect_notes()
    kb = load_kb()
    lang = kb_language(kb)
    today = date.today()
    title = L(lang, "全库索引", "Index")
    out = [
        "---", "type: hub", f"title: {title}", f"updated: {today}", "---", "",
        f"# {kb.get('name', ROOT.name)} · {title}", "",
        L(lang, "> 由 `scripts/kb.py index` 自动生成，请勿手动编辑。",
          "> Generated by `scripts/kb.py index`; do not edit by hand."), "",
    ]
    nav = [f"[[{n}]]" for n in ("hot", "roadmap", "timeline", "log") if (HUB / f"{n}.md").exists()]
    nav += [link(n) for n in in_dir(notes, "10-Brief/")]
    out += [f"## 🧭 {L(lang, '导航', 'Navigation')}", "", " · ".join(nav) or L(lang, "（暂无）", "(none)"), ""]

    due = due_decisions(notes, REVIEW_AHEAD_DAYS)
    out += [f"## ⏰ {L(lang, f'待复盘决策（{REVIEW_AHEAD_DAYS} 天内）', f'Decisions due for review (within {REVIEW_AHEAD_DAYS} days)')}", ""]
    out += [f"- {L(lang, '⚠️ 已到期', '⚠️ overdue') if d <= today else '⏳'} {d} · {link(n)}" for d, n in due] \
        or [L(lang, "（暂无）", "(none)")]
    out += [""]

    decisions = in_dir(notes, "40-Sessions/decisions/", {"decision"})
    out += [f"## 🧭 {L(lang, '决策记录', 'Decisions')}{count_suffix(lang, len(decisions))}", ""]
    out += table(
        [L(lang, "编号", "ID"), L(lang, "决策", "Decision"), L(lang, "状态", "Status"),
         L(lang, "可逆性", "Reversibility"), L(lang, "信心", "Confidence"), L(lang, "复盘日期", "Review date")],
        [f"| {m.get('id', '')} | {link(n, True)} | {m.get('status', '')} | {m.get('reversible', '')} "
         f"| {m.get('confidence', '')} | {m.get('review_date', '')} |" for n in decisions for m in [n.meta]],
        lang)

    outputs = sorted(in_dir(notes, "50-Outputs/", {"output"}), key=lambda n: n.rel)
    if outputs or (ROOT / "50-Outputs").exists():
        out += [f"## 📦 {L(lang, '产出物', 'Outputs')}{count_suffix(lang, len(outputs))}", ""]
        out += table(
            [L(lang, "文档", "Document"), L(lang, "版本", "Version"), L(lang, "状态", "Status"),
             L(lang, "读者", "Audience"), L(lang, "更新", "Updated")],
            [f"| {link(n, True)} | {m.get('version', '')} | {m.get('status', '')} | {m.get('audience', '')} "
             f"| {m.get('updated', '')} |" for n in outputs for m in [n.meta]],
            lang)

    sessions = in_dir(notes, "40-Sessions/notes/", {"session"})
    out += [f"## 💬 {L(lang, '会话纪要', 'Session notes')}{count_suffix(lang, len(sessions))}", ""]
    out += table(
        [L(lang, "日期", "Date"), L(lang, "主题", "Topic"), L(lang, "摘要", "Summary"), L(lang, "标签", "Tags")],
        [f"| {n.meta.get('created', '')} | {link(n, True)} | {summary_of(n, True)} | {n.meta.get('tags', '')} |"
         for n in sessions],
        lang)

    raws = in_dir(notes, "40-Sessions/raw/")
    pending = unarchived(notes)
    out += ["## 📜 " + L(lang, f"最近原始对话（共 {len(raws)} 个，未归档 {len(pending)} 个，显示最近 {RECENT_RAW} 个）",
                         f"Recent raw sessions ({len(raws)} total, {len(pending)} unarchived, "
                         f"showing the latest {RECENT_RAW})"), ""]
    pending_set = {n.rel for n in pending}
    out += [f"- {n.meta.get('started', '')} · {link(n)}{L(lang, ' · 未归档', ' · unarchived') if n.rel in pending_set else ''}"
            for n in raws[:RECENT_RAW]] or [L(lang, "（暂无）", "(none)")]
    out += [""]

    raw_files = [p for p in walk(PRUNE) if "20-Sources/raw" in p.relative_to(ROOT).as_posix() and p.name != ".gitkeep"]
    cards = sorted(in_dir(notes, "20-Sources/cards/"), key=lambda n: n.rel)
    out += ["## 📥 " + L(lang, f"资料（原件 {len(raw_files)} 个，资料卡 {len(cards)} 张）",
                         f"Sources ({len(raw_files)} raw files, {len(cards)} source cards)"), ""]
    if SOURCES_INDEX.exists():
        out += [L(lang, "- 资料清单：[[sources-index]]", "- Source index: [[sources-index]]")]
    out += [f"- {link(n)}" + (f" — {summary_of(n)}" if summary_of(n) else "") for n in cards]
    out += [""]

    wiki = sorted(in_dir(notes, "30-Wiki/"), key=lambda n: n.rel)
    out += [f"## 📚 Wiki{count_suffix(lang, len(wiki))}", ""]
    group = None
    for n in wiki:
        parts = n.rel.split("/")
        g = parts[1] if len(parts) > 2 else ""
        if g != group:
            group = g
            if g:
                out += ["", f"### {g}", ""]
        out.append(f"- {link(n)} `{n.meta.get('type', '')}`")
    if not wiki:
        out.append(L(lang, "（暂无）", "(none)"))
    out += [""]

    known = ("00-Hub/", "10-Brief/", "20-Sources/", "30-Wiki/", "40-Sessions/", "50-Outputs/")
    others = sorted((n for n in notes if not n.rel.startswith(known)), key=lambda n: n.rel)
    if others:
        out += [f"## 🗂 {L(lang, '其他笔记', 'Other notes')}{count_suffix(lang, len(others))}", ""]
        out += [f"- {link(n)} `{n.meta.get('type', '')}`" for n in others]
        out += [""]

    (HUB / "index.md").parent.mkdir(exist_ok=True)
    (HUB / "index.md").write_text("\n".join(out), encoding="utf-8")
    print(f"index: {len(notes)} notes -> 00-Hub/index.md")


# ---------- lint ----------

def cmd_lint():
    notes = collect_notes()
    lang = kb_language(load_kb())
    colon = L(lang, "：", ": ")
    sep = L(lang, "、", ", ")
    files = list(walk(PRUNE))
    names = set()
    for p in files:
        r = p.relative_to(ROOT).as_posix().lower()
        names |= {r, p.name.lower()}
        if p.suffix.lower() == ".md":
            names |= {r[:-3], p.stem.lower()}

    report = {}
    add = lambda section, line: report.setdefault(section, []).append(line)
    inbound = {}
    # 原始对话里的 [[ ]] 是聊天内容，原始资料是外来文件，都不做链接和 frontmatter 检查
    checked = [n for n in notes if not n.rel.startswith(("40-Sessions/raw/", "20-Sources/raw/"))]
    for n in checked:
        for t in links(n.text):
            key = t.lower()
            if key not in names and key + ".md" not in names:
                add(L(lang, "死链", "Dead links"), f"- {n.rel}{colon}[[{t}]]")
            if n.rel != "00-Hub/index.md":
                inbound.setdefault(key.split("/")[-1], set()).add(n.rel)

    for n in checked:
        declared = frontmatter(n.text)[0]  # n.meta 里的 title 可能是用文件名补上的
        missing = [k for k in ("type", "title") if not declared.get(k)]
        if missing:
            add(L(lang, "缺少 frontmatter 或必填字段", "Missing frontmatter or required fields"),
                f"- {n.rel}{colon}{L(lang, '缺少 ', 'missing ')}{sep.join(missing)}")

    for n in in_dir(notes, "30-Wiki/"):
        if not (inbound.get(n.path.stem.lower(), set()) - {n.rel}):
            add(L(lang, "孤立的 wiki 页（没有其他笔记链接到它）", "Orphan wiki pages (no other note links to them)"),
                f"- {n.rel}")

    idx = SOURCES_INDEX.read_text(encoding="utf-8", errors="ignore") if SOURCES_INDEX.exists() else ""
    for p in files:
        r = p.relative_to(ROOT).as_posix()
        if r.startswith("20-Sources/raw/") and p.name != ".gitkeep" and p.stem not in idx and p.name not in idx:
            add(L(lang, "未在 sources-index.md 中登记的资料", "Sources not registered in sources-index.md"), f"- {r}")

    for n in unarchived(notes):
        add(L(lang, "未归档的会话（运行 /wrapup）", "Unarchived sessions (run /wrapup)"),
            L(lang, f"- {n.rel}（{n.meta.get('started', '')}，{n.meta['title']}）",
              f"- {n.rel} ({n.meta.get('started', '')}, {n.meta['title']})"))

    for d, n in due_decisions(notes, 0):
        add(L(lang, "已到复盘日期的决策", "Decisions past their review date"), f"- {d} · {n.rel}")

    for n in in_dir(notes, "50-Outputs/", {"output"}):
        if n.meta.get("status") == "released" and not n.meta.get("version"):
            add(L(lang, "产出物", "Outputs"), f"- {n.rel}{colon}{L(lang, '已发布但没有 version', 'released but has no version')}")
        if n.meta.get("sources", "[]") in ("", "[]"):
            add(L(lang, "产出物", "Outputs"),
                f"- {n.rel}{colon}{L(lang, 'sources 为空，无法追溯依据', 'sources is empty; the basis cannot be traced')}")

    hot = HUB / "hot.md"
    if hot.exists():
        lines = FM.sub("", hot.read_text(encoding="utf-8"), count=1).strip().splitlines()
        if len(lines) > HOT_LINES:
            add("hot.md", L(lang, f"- 有 {len(lines)} 行，超过 {HOT_LINES} 行，建议精简（会话开始时只注入前 {HOT_LINES} 行）",
                            f"- {len(lines)} lines, over the {HOT_LINES}-line budget; consider trimming "
                            f"(only the first {HOT_LINES} lines are injected at session start)"))

    if not report:
        print(L(lang, "✅ 知识库检查通过，没有发现问题。", "✅ Knowledge base check passed; no issues found."))
        return
    print(L(lang, "# 知识库检查报告\n", "# Knowledge base check report\n"))
    for section, lines in report.items():
        print(f"## {section}{count_suffix(lang, len(lines))}\n")
        print("\n".join(lines) + "\n")


# ---------- unarchived / session-start ----------

def cmd_unarchived():
    lang = kb_language(load_kb())
    pending = unarchived(collect_notes())
    if not pending:
        print(L(lang, "（没有未归档的会话）", "(no unarchived sessions)"))
        return
    for n in pending:
        m = n.meta
        print(L(lang, f"- {n.rel} · {m.get('started', '')} · {m.get('prompts', '?')} 条提问 · {m['title']}",
                f"- {n.rel} · {m.get('started', '')} · {m.get('prompts', '?')} prompts · {m['title']}"))


def prompts_of(note):
    p = note.meta.get("prompts", "")
    return int(p) if p.isdigit() else 0


def git_out(cwd, *args):
    """只读的 git 查询；不是仓库、没有 git 或超时都返回空串（hook 不能因此崩掉）。"""
    try:
        r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def hot_updated():
    """hot.md 最后一次更新的时间。有未提交的改动、未跟踪或不是仓库时，取文件修改时间；
    干净时取"最后一次提交"和"文件修改时间"中较早的那个：改完过了很久才提交时，内容反映的是修改时的状态，
    按提交时间算会漏掉这中间的变化；克隆或切换分支会把修改时间刷新得更晚，这时提交时间才是准的。"""
    hot = HUB / "hot.md"
    if not hot.exists():
        return None
    rel = hot.relative_to(ROOT).as_posix()
    modified = datetime.fromtimestamp(hot.stat().st_mtime).astimezone()
    stamp = git_out(ROOT, "log", "-1", "--format=%cI", "--", rel)
    if stamp and not git_out(ROOT, "status", "--porcelain", "--", rel):
        return min(datetime.fromisoformat(stamp), modified)
    return modified


def drift(notes, lang="zh-CN"):
    """hot.md 最后一次更新之后发生了什么：未归档的会话、repos/ 下各代码库的新提交，以及知识库里未提交的改动。
    归档靠人发起，hot.md 难免过期；过期而不自知比没有更糟，所以由脚本按证据算出来，随 hot.md 一起交给 AI。
    看的是 git 而不是会话，所以没有被导出的工具（或手工）做的改动也算得到。没有变化时返回 None。"""
    since = hot_updated()
    if since is None:
        return None
    items = []
    pending = unarchived(notes)
    if pending:
        n, q = len(pending), sum(prompts_of(p) for p in pending)
        items.append(L(lang, f"{n} 个会话尚未归档（共 {q} 条提问）", f"{n} unarchived session(s) ({q} prompts in total)"))
    repos = ROOT / "repos"
    for d in sorted(repos.iterdir()) if repos.is_dir() else []:
        if not (d / ".git").exists():
            continue
        subjects = git_out(d, "log", f"--since={since.isoformat()}", "--format=%s").splitlines()
        if subjects:
            items.append(L(lang, f"repos/{d.name} 有 {len(subjects)} 次新提交（最新：{subjects[0]}）",
                           f"repos/{d.name} has {len(subjects)} new commit(s) (latest: {subjects[0]})"))
    # 知识库里未提交的改动（原始对话是 Loom 自己导出的，不算）：多半是别的工具或上一次会话留下的，
    # 会和下一次 wrapup 要改的文件撞在一起，所以在开场就说出来。
    loose = git_out(ROOT, "status", "--porcelain", "--", ".", ":(exclude)40-Sessions/raw").splitlines()
    if loose:
        items.append(L(lang, f"知识库有 {len(loose)} 处未提交的改动", f"the knowledge base has {len(loose)} uncommitted change(s)"))
    if not items:
        return None
    return L(lang, f"⚠️ hot.md 最后更新于 {since:%Y-%m-%d %H:%M}，之后：{'；'.join(items)}。"
                   "hot.md 可能已经过期：涉及当前状态时先核对这些变化，不要直接采信。",
             f"⚠️ hot.md was last updated at {since:%Y-%m-%d %H:%M}; since then: {'; '.join(items)}. "
             "hot.md may be out of date: check these changes before relying on it for the current state.")


def reminders(notes, lang="zh-CN", at_start=False, current_session=None):
    """at_start：在会话开始时调用。此时未归档的会话都已经结束，这是唯一能确定"讨论结束了"的时刻，
    所以让 AI 开口问一次，用户只需要回答要不要。只有一条提问的会话多半没有实质内容，不为它打断用户。
    current_session：当前会话的 id。恢复一个已导出过的会话时，它自己也在未归档之列，但还没有结束，不算。"""
    out = []
    pending = unarchived(notes)
    ended = [n for n in pending if not current_session or n.meta.get("session_id") != current_session]
    if at_start and any(prompts_of(n) > 1 for n in ended):
        out.append(L(lang, f"有 {len(ended)} 个已结束的会话尚未归档（最近一个：{ended[-1].path.stem}）。"
                           "在第一次回复的开头用一句话问用户：要不要现在用 loom skill 的 wrapup 补归档。"
                           "只问一次，用户说不用就不再提。",
                     f"{len(ended)} finished session(s) not yet archived (latest: {ended[-1].path.stem}). "
                     "At the top of your first reply, ask the user in one sentence whether to archive them now "
                     "with loom's wrapup. Ask once only; if the user declines, do not bring it up again."))
    elif pending:
        out.append(L(lang, f"有 {len(pending)} 个会话尚未归档（最近一个：{pending[-1].path.stem}）。"
                           "用户结束讨论时，建议用 loom skill 的 wrapup 一并归档。",
                     f"{len(pending)} session(s) not yet archived (latest: {pending[-1].path.stem}). "
                     "When the user finishes a discussion, suggest archiving it together with loom's wrapup."))
    due = due_decisions(notes, 0)
    if due:
        names = [n.meta.get("id") or n.path.stem for _, n in due]
        out.append(L(lang, f"有 {len(due)} 个决策已到复盘日期：" + "、".join(names),
                     f"{len(due)} decision(s) are past their review date: " + ", ".join(names)))
    return out


def settle_previous_sessions():
    """作为 hook 调用时（stdin 是 hook JSON），补导出并收尾没有触发 SessionEnd 的上一次会话。
    返回当前会话的 id；不是作为 hook 调用时返回 None。"""
    if sys.stdin is None or sys.stdin.isatty():
        return None
    try:
        hook = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not hook.get("session_id"):
        return None
    import export_session
    export_session.set_root(ROOT)
    export_session.settle_recent(hook["session_id"])
    return hook["session_id"]


def cmd_session_start():
    current = settle_previous_sessions()
    kb = load_kb()
    lang = kb_language(kb)
    notes = collect_notes()
    status = L(lang, f"状态：{kb.get('status', 'active')}；模块：{', '.join(kb.get('modules', [])) or 'core'}",
               f"status: {kb.get('status', 'active')}; modules: {', '.join(kb.get('modules', [])) or 'core'}")
    print(L(lang, f"【Loom 项目上下文】{kb.get('name', ROOT.name)}（{status}；知识库根目录：{ROOT}）",
            f"[Loom project context] {kb.get('name', ROOT.name)} ({status}; knowledge base root: {ROOT})"))
    if RULES.exists():
        print(L(lang, "\n--- Loom 通用规则（loom skill 的 references/rules.md）---",
                "\n--- Loom common rules (references/rules.md of the loom skill) ---"))
        print(RULES.read_text(encoding="utf-8").strip())
    hot = HUB / "hot.md"
    if hot.exists():
        body = FM.sub("", hot.read_text(encoding="utf-8"), count=1).strip().splitlines()
        print("\n--- 00-Hub/hot.md ---")
        stale = drift(notes, lang)
        if stale:
            print(stale + "\n")
        print("\n".join(body[:HOT_LINES]))
        if len(body) > HOT_LINES:
            print(L(lang, f"……（hot.md 共 {len(body)} 行，以上是前 {HOT_LINES} 行）",
                    f"... (hot.md has {len(body)} lines; the first {HOT_LINES} lines are shown above)"))
    items = reminders(notes, lang, at_start=True, current_session=current)
    if items:
        print(L(lang, "\n--- 提醒 ---", "\n--- Reminders ---"))
        print("\n".join(f"- {r}" for r in items))
    print(L(lang, "\n（以上由 Loom 的 SessionStart hook 注入。归档、导入资料、体检等操作用 loom skill 完成，例如 /loom wrapup。）",
            "\n(Injected by Loom's SessionStart hook. Archiving, ingesting sources, linting and other operations "
            "are done with the loom skill, e.g. /loom wrapup.)"))


CMDS = {"index": cmd_index, "lint": cmd_lint, "unarchived": cmd_unarchived, "session-start": cmd_session_start}


def main():
    utf8_stdout()
    args = sys.argv[1:]
    root_arg = None
    if "--root" in args:
        i = args.index("--root")
        root_arg = args[i + 1] if i + 1 < len(args) else None
        del args[i:i + 2]
    if len(args) != 1 or args[0] not in CMDS:
        print(__doc__)
        sys.exit(2)
    root = find_root(root_arg)
    if root is None:
        if args[0] == "session-start":
            return  # 不是 Loom 项目：hook 静默退出
        # 不在任何项目里，没有项目语言可依，按 CLI 默认姿态用英文
        print("Not in a Loom project (no .kb.json found in this directory or its parents).", file=sys.stderr)
        sys.exit(1)
    set_root(root)
    CMDS[args[0]]()


if __name__ == "__main__":
    main()
