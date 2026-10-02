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
import sys
from collections import namedtuple
from datetime import date, timedelta
from pathlib import Path

from kbroot import SKILL_DIR, find_root, load_kb as read_kb, utf8_stdout

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
CLOSED_DECISIONS = {"已复盘", "已推翻"}

Note = namedtuple("Note", "path rel meta has_fm text")


def set_root(root):
    global ROOT, HUB, RAW_DIR, SOURCES_INDEX
    ROOT = Path(root)
    HUB = ROOT / "00-Hub"
    RAW_DIR = ROOT / "40-Sessions" / "raw"
    SOURCES_INDEX = ROOT / "20-Sources" / "sources-index.md"


def load_kb():
    return read_kb(ROOT)


def walk(prune):
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in prune]
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


def table(header, rows):
    if not rows:
        return ["（暂无）", ""]
    return ["| " + " | ".join(header) + " |", "|" + "---|" * len(header), *rows, ""]


# ---------- index ----------

def cmd_index():
    notes = collect_notes()
    kb = load_kb()
    today = date.today()
    out = [
        "---", "type: hub", "title: 全库索引", f"updated: {today}", "---", "",
        f"# {kb.get('name', ROOT.name)} · 全库索引", "",
        "> 由 `scripts/kb.py index` 自动生成，请勿手动编辑。", "",
    ]
    nav = [f"[[{n}]]" for n in ("hot", "roadmap", "timeline", "log") if (HUB / f"{n}.md").exists()]
    nav += [link(n) for n in in_dir(notes, "10-Brief/")]
    out += ["## 🧭 导航", "", " · ".join(nav) or "（暂无）", ""]

    due = due_decisions(notes, REVIEW_AHEAD_DAYS)
    out += [f"## ⏰ 待复盘决策（{REVIEW_AHEAD_DAYS} 天内）", ""]
    out += [f"- {'⚠️ 已到期' if d <= today else '⏳'} {d} · {link(n)}" for d, n in due] or ["（暂无）"]
    out += [""]

    decisions = in_dir(notes, "40-Sessions/decisions/", {"decision"})
    out += [f"## 🧭 决策记录（{len(decisions)}）", ""]
    out += table(
        ["编号", "决策", "状态", "可逆性", "信心", "复盘日期"],
        [f"| {m.get('id', '')} | {link(n, True)} | {m.get('status', '')} | {m.get('reversible', '')} "
         f"| {m.get('confidence', '')} | {m.get('review_date', '')} |" for n in decisions for m in [n.meta]],
    )

    outputs = sorted(in_dir(notes, "50-Outputs/", {"output"}), key=lambda n: n.rel)
    if outputs or (ROOT / "50-Outputs").exists():
        out += [f"## 📦 产出物（{len(outputs)}）", ""]
        out += table(
            ["文档", "版本", "状态", "读者", "更新"],
            [f"| {link(n, True)} | {m.get('version', '')} | {m.get('status', '')} | {m.get('audience', '')} "
             f"| {m.get('updated', '')} |" for n in outputs for m in [n.meta]],
        )

    sessions = in_dir(notes, "40-Sessions/notes/", {"session"})
    out += [f"## 💬 会话纪要（{len(sessions)}）", ""]
    out += table(
        ["日期", "主题", "标签"],
        [f"| {n.meta.get('created', '')} | {link(n, True)} | {n.meta.get('tags', '')} |" for n in sessions],
    )

    raws = in_dir(notes, "40-Sessions/raw/")
    pending = unarchived(notes)
    out += [f"## 📜 最近原始对话（共 {len(raws)} 个，未归档 {len(pending)} 个，显示最近 {RECENT_RAW} 个）", ""]
    pending_set = {n.rel for n in pending}
    out += [f"- {n.meta.get('started', '')} · {link(n)}{' · 未归档' if n.rel in pending_set else ''}"
            for n in raws[:RECENT_RAW]] or ["（暂无）"]
    out += [""]

    raw_files = [p for p in walk(PRUNE) if "20-Sources/raw" in p.relative_to(ROOT).as_posix() and p.name != ".gitkeep"]
    cards = sorted(in_dir(notes, "20-Sources/cards/"), key=lambda n: n.rel)
    out += [f"## 📥 资料（原件 {len(raw_files)} 个，资料卡 {len(cards)} 张）", ""]
    if SOURCES_INDEX.exists():
        out += ["- 资料清单：[[sources-index]]"]
    out += [f"- {link(n)}" for n in cards]
    out += [""]

    wiki = sorted(in_dir(notes, "30-Wiki/"), key=lambda n: n.rel)
    out += [f"## 📚 Wiki（{len(wiki)}）", ""]
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
        out.append("（暂无）")
    out += [""]

    known = ("00-Hub/", "10-Brief/", "20-Sources/", "30-Wiki/", "40-Sessions/", "50-Outputs/")
    others = sorted((n for n in notes if not n.rel.startswith(known)), key=lambda n: n.rel)
    if others:
        out += [f"## 🗂 其他笔记（{len(others)}）", ""]
        out += [f"- {link(n)} `{n.meta.get('type', '')}`" for n in others]
        out += [""]

    (HUB / "index.md").parent.mkdir(exist_ok=True)
    (HUB / "index.md").write_text("\n".join(out), encoding="utf-8")
    print(f"index: {len(notes)} notes -> 00-Hub/index.md")


# ---------- lint ----------

def cmd_lint():
    notes = collect_notes()
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
                add("死链", f"- {n.rel}：[[{t}]]")
            if n.rel != "00-Hub/index.md":
                inbound.setdefault(key.split("/")[-1], set()).add(n.rel)

    for n in checked:
        declared = frontmatter(n.text)[0]  # n.meta 里的 title 可能是用文件名补上的
        missing = [k for k in ("type", "title") if not declared.get(k)]
        if missing:
            add("缺少 frontmatter 或必填字段", f"- {n.rel}：缺少 {'、'.join(missing)}")

    for n in in_dir(notes, "30-Wiki/"):
        if not (inbound.get(n.path.stem.lower(), set()) - {n.rel}):
            add("孤立的 wiki 页（没有其他笔记链接到它）", f"- {n.rel}")

    idx = SOURCES_INDEX.read_text(encoding="utf-8", errors="ignore") if SOURCES_INDEX.exists() else ""
    for p in files:
        r = p.relative_to(ROOT).as_posix()
        if r.startswith("20-Sources/raw/") and p.name != ".gitkeep" and p.stem not in idx and p.name not in idx:
            add("未在 sources-index.md 中登记的资料", f"- {r}")

    for n in unarchived(notes):
        add("未归档的会话（运行 /wrapup）", f"- {n.rel}（{n.meta.get('started', '')}，{n.meta['title']}）")

    for d, n in due_decisions(notes, 0):
        add("已到复盘日期的决策", f"- {d} · {n.rel}")

    for n in in_dir(notes, "50-Outputs/", {"output"}):
        if n.meta.get("status") == "released" and not n.meta.get("version"):
            add("产出物", f"- {n.rel}：已发布但没有 version")
        if n.meta.get("sources", "[]") in ("", "[]"):
            add("产出物", f"- {n.rel}：sources 为空，无法追溯依据")

    hot = HUB / "hot.md"
    if hot.exists():
        lines = FM.sub("", hot.read_text(encoding="utf-8"), count=1).strip().splitlines()
        if len(lines) > HOT_LINES:
            add("hot.md", f"- 有 {len(lines)} 行，超过 {HOT_LINES} 行，建议精简（会话开始时只注入前 {HOT_LINES} 行）")

    if not report:
        print("✅ 知识库检查通过，没有发现问题。")
        return
    print("# 知识库检查报告\n")
    for section, lines in report.items():
        print(f"## {section}（{len(lines)}）\n")
        print("\n".join(lines) + "\n")


# ---------- unarchived / session-start ----------

def cmd_unarchived():
    pending = unarchived(collect_notes())
    if not pending:
        print("（没有未归档的会话）")
        return
    for n in pending:
        m = n.meta
        print(f"- {n.rel} · {m.get('started', '')} · {m.get('prompts', '?')} 条提问 · {m['title']}")


def reminders(notes):
    out = []
    pending = unarchived(notes)
    if pending:
        out.append(f"有 {len(pending)} 个会话尚未归档（最近一个：{pending[-1].path.stem}）。"
                   "用户结束讨论时，建议用 loom skill 的 wrapup 一并归档。")
    due = due_decisions(notes, 0)
    if due:
        out.append(f"有 {len(due)} 个决策已到复盘日期：" + "、".join(n.meta.get("id") or n.path.stem for _, n in due))
    return out


def settle_previous_sessions():
    """作为 hook 调用时（stdin 是 hook JSON），补导出并收尾没有触发 SessionEnd 的上一次会话。"""
    if sys.stdin is None or sys.stdin.isatty():
        return
    try:
        hook = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return
    if not hook.get("session_id"):
        return
    import export_session
    export_session.set_root(ROOT)
    export_session.settle_recent(hook["session_id"])


def cmd_session_start():
    settle_previous_sessions()
    kb = load_kb()
    notes = collect_notes()
    status = f"状态：{kb.get('status', 'active')}；模块：{', '.join(kb.get('modules', [])) or 'core'}"
    print(f"【Loom 项目上下文】{kb.get('name', ROOT.name)}（{status}；知识库根目录：{ROOT}）")
    if RULES.exists():
        print("\n--- Loom 通用规则（loom skill 的 references/rules.md）---")
        print(RULES.read_text(encoding="utf-8").strip())
    hot = HUB / "hot.md"
    if hot.exists():
        body = FM.sub("", hot.read_text(encoding="utf-8"), count=1).strip().splitlines()
        print("\n--- 00-Hub/hot.md ---")
        print("\n".join(body[:HOT_LINES]))
        if len(body) > HOT_LINES:
            print(f"……（hot.md 共 {len(body)} 行，以上是前 {HOT_LINES} 行）")
    items = reminders(notes)
    if items:
        print("\n--- 提醒 ---")
        print("\n".join(f"- {r}" for r in items))
    print("\n（以上由 Loom 的 SessionStart hook 注入。归档、导入资料、体检等操作用 loom skill 完成，例如 /loom wrapup。）")


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
        print("当前目录不在 Loom 项目中（向上找不到 .kb.json）。", file=sys.stderr)
        sys.exit(1)
    set_root(root)
    CMDS[args[0]]()


if __name__ == "__main__":
    main()
