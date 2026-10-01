"""知识库快照：发布当前知识库中可公开的内容，以及打开别人发布的快照。属于 Loom skill。

用法（在知识库根目录或其子目录中运行，也可以用 --root 指定根目录）：
  python snapshot.py plan [--out 目录]          预览：哪些文件会发布、哪些被排除、哪些内容需要留意。不写任何文件
  python snapshot.py build [--out 目录]         生成快照 zip，默认写到 50-Outputs/_exports/
  python snapshot.py open <zip> [--prev <zip>]  打开别人的快照：解压到临时目录，和上一份比较，生成同名的 .md 提取文本

快照是知识库当前的状态和结果，不包含历史和过程。发布规则写在 .kb.json 的 publish 中，没有配置时用 DEFAULTS；
HARD_EXCLUDE 中的路径，配置和笔记上的 publish: true 都不能打开。清洗只作用于快照里的副本，不改知识库中的源文件。
"""
import argparse
import fnmatch
import hashlib
import json
import os
import re
import sys
import tempfile
import zipfile
from datetime import date, datetime
from pathlib import Path, PurePosixPath

import kb as kbmod
from kbroot import find_root, load_kb, skill_version, utf8_stdout

MANIFEST = "loom-snapshot.json"
README = "快照说明.md"
FORMAT = 1
EXPORTS = "50-Outputs/_exports"
DEFAULTS = {
    "include": ["10-Brief/", "30-Wiki/", "20-Sources/cards/", "50-Outputs/", "00-Hub/roadmap.md"],
    "exclude": [],
    "strip_fields": ["raws", "session", "commits", "decisions"],
    "strip_sections": ["变更记录", "版本历史"],
}
# 历史和过程：对话、纪要、决策记录、时间线、日志；以及索引、待处理资料和导出物
HARD_EXCLUDE = ["40-Sessions/", "00-Hub/timeline.md", "00-Hub/log.md", "00-Hub/index.md",
                "20-Sources/inbox/", EXPORTS + "/"]
ALWAYS_STRIP = ["publish"]  # 发布者自己用的标记，不带进快照

LINK = re.compile(r"!?\[\[([^\]\|#]+)(?:#[^\]\|]*)?(?:\\?\|([^\]]*))?\]\]")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
WATCH = [  # 发布前提醒 AI 和用户留意的内容
    ("本机路径", re.compile(r"\b[A-Za-z]:[\\/][^\s`\"')）]*|/(?:Users|home)/[^\s`\"')）]*")),
    ("邮箱", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("密钥类内容", re.compile(r"(?i)\b(?:password|passwd|secret|api[_-]?key)\b|密码|密钥|\bsk-[A-Za-z0-9_-]{8,}")),
    ("对话记录路径", re.compile(r"40-Sessions/raw[^\s`\"')）]*")),
]
TEXT_SUFFIXES = {".md", ".txt"}


class SnapshotError(Exception):
    pass


# ---------- 发布规则与清洗 ----------

def load_rules(kb):
    conf = kb.get("publish")
    if conf is not None and not isinstance(conf, dict):
        raise SnapshotError(".kb.json 的 publish 应当是一个对象。")
    rules = {}
    for key, default in DEFAULTS.items():
        value = (conf or {}).get(key, default)
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            raise SnapshotError(f".kb.json 的 publish.{key} 应当是字符串列表。")
        rules[key] = value
    return rules, bool(conf)


def matches(rel, patterns):
    """模式以 / 结尾表示目录前缀，否则按 fnmatch 匹配相对路径。"""
    return any(rel.startswith(p) if p.endswith("/") else fnmatch.fnmatchcase(rel, p) for p in patterns)


def select(root, rules):
    """返回（要发布的文件 [(相对路径, 路径)]，在 include 范围内但被排除的 [(相对路径, 原因)]）。"""
    files, excluded = [], []
    for p in sorted(kbmod.walk(kbmod.PRUNE)):
        rel = p.relative_to(root).as_posix()
        if p.name == ".gitkeep" or matches(rel, HARD_EXCLUDE):
            continue
        included = matches(rel, rules["include"])
        meta = {}
        if p.suffix.lower() == ".md":
            meta = kbmod.frontmatter(p.read_text(encoding="utf-8", errors="ignore"))[0]
        flag = meta.get("publish", "").lower()
        if flag == "true":
            files.append((rel, p))
        elif not included:
            continue
        elif flag == "false":
            excluded.append((rel, "笔记标了 publish: false"))
        elif matches(rel, rules["exclude"]):
            excluded.append((rel, "匹配 exclude"))
        elif meta.get("type") == "output" and meta.get("status") != "released":
            excluded.append((rel, f"产出物的状态是 {meta.get('status') or '空'}，不是 released"))
        else:
            files.append((rel, p))
    return files, excluded


def link_names(rels):
    names = set()
    for rel in rels:
        r = rel.lower()
        names |= {r, r.split("/")[-1]}
        if r.endswith(".md"):
            names |= {r[:-3], r.split("/")[-1][:-3]}
    return names


def strip_frontmatter(text, fields):
    m = kbmod.FM.match(text)
    if not m:
        return text
    keep, drop = [], False
    for line in m.group(1).split("\n"):
        if not line.startswith((" ", "\t", "-")):  # 新字段开始；缩进行和列表项跟随上一个字段
            drop = line.partition(":")[0].strip() in fields
        if not drop:
            keep.append(line)
    return "---\n" + "\n".join(keep) + text[m.end(1):]


def strip_sections(text, titles):
    """删除标题在 titles 中的段落：从该标题到下一个同级或更高级的标题。"""
    out, skip, fence = [], 0, False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            fence = not fence
        h = None if fence else HEADING.match(line)
        if h:
            level = len(h.group(1))
            if skip and level <= skip:
                skip = 0
            if not skip and h.group(2) in titles:
                skip = level
        if not skip:
            out.append(line)
    return "\n".join(out).rstrip("\n") + "\n"


def defuse_links(text, names):
    """把指向未发布笔记的 [[链接]] 改成纯文本，返回（文本，改动的链接数）。代码和注释中的不处理。"""
    count = 0

    def repl(m):
        nonlocal count
        target = m.group(1).rstrip("\\").strip()
        key = target.lower()
        if key in names or key + ".md" in names:
            return m.group(0)
        count += 1
        name = target.split("/")[-1]
        return (m.group(2) or "").strip() or (name[:-3] if name.lower().endswith(".md") else name)

    out, pos = [], 0
    for c in kbmod.CODE.finditer(text):
        out += [LINK.sub(repl, text[pos:c.start()]), c.group(0)]
        pos = c.end()
    out.append(LINK.sub(repl, text[pos:]))
    return "".join(out), count


def clean(text, rules, names):
    text = text.replace("\r\n", "\n")
    text = strip_frontmatter(text, set(rules["strip_fields"]) | set(ALWAYS_STRIP))
    text = strip_sections(text, set(rules["strip_sections"]))
    return defuse_links(text, names)


def watch(text):
    hits = []
    for label, pattern in WATCH:
        found = list(dict.fromkeys(m.group(0) for m in pattern.finditer(text)))
        if found:
            more = f" 等 {len(found)} 处" if len(found) > 3 else ""
            hits.append(f"{label}（{'、'.join(found[:3])}{more}）")
    return hits


def render(root, rules):
    """返回（{相对路径: 清洗后的内容 bytes}，{相对路径: 改成纯文本的链接数}，被排除的列表）。"""
    files, excluded = select(root, rules)
    names = link_names(rel for rel, _ in files)
    content, defused = {}, {}
    for rel, p in files:
        data = p.read_bytes()
        if p.suffix.lower() == ".md":
            text, defused[rel] = clean(data.decode("utf-8", errors="replace"), rules, names)
            data = text.encode("utf-8")
        content[rel] = data
    return content, defused, excluded


# ---------- 快照文件 ----------

def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_manifest(path):
    """返回快照清单；不是 Loom 快照时返回 None。"""
    try:
        with zipfile.ZipFile(path) as z:
            m = json.loads(z.read(MANIFEST).decode("utf-8"))
    except (OSError, KeyError, zipfile.BadZipFile, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return m if isinstance(m, dict) and m.get("loom_snapshot") and m.get("project") else None


def zip_hashes(path):
    with zipfile.ZipFile(path) as z:
        return {i.filename: sha(z.read(i)) for i in z.infolist()
                if not i.is_dir() and i.filename not in (MANIFEST, README)}


def previous(folder, project, before=None, skip=None):
    """folder 下（含子目录）同一项目最近的一份快照：(路径, 清单)；没有时返回 None。"""
    best = None
    for p in (folder.rglob("*.zip") if folder and folder.is_dir() else []):
        if skip and p.resolve() == skip:
            continue
        m = read_manifest(p)
        created = (m or {}).get("created", "")
        if m and m["project"] == project and (before is None or created < before) \
                and (best is None or created > best[1].get("created", "")):
            best = (p, m)
    return best


def compare(files, prev):
    """files、prev 都是 {路径: sha256}；prev 为 None 表示没有上一份。"""
    prev = prev or {}
    return {
        "新增": sorted(f for f in files if f not in prev),
        "修改": sorted(f for f in files if f in prev and prev[f] != files[f]),
        "未变": sorted(f for f in files if prev.get(f) == files[f]),
        "删除": sorted(f for f in prev if f not in files),
    }


def summary(diff, removed="不再包含"):
    return f"新 {len(diff['新增'])}、改 {len(diff['修改'])}、未变 {len(diff['未变'])}、{removed} {len(diff['删除'])}"


def write(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.replace("\n", os.linesep).encode("utf-8"))


# ---------- 命令 ----------

def prepare(args):
    root = find_root(args.root)
    if root is None:
        raise SnapshotError("当前目录不在 Loom 项目中（向上找不到 .kb.json）。")
    kbmod.set_root(root)
    kb = load_kb(root)
    rules, configured = load_rules(kb)
    out_dir = Path(args.out).resolve() if args.out else root / EXPORTS
    content, defused, excluded = render(root, rules)
    project = kb.get("name", root.name)
    prev = previous(out_dir, project)
    diff = compare({rel: sha(data) for rel, data in content.items()}, zip_hashes(prev[0]) if prev else None)
    return root, kb, rules, configured, out_dir, content, defused, excluded, prev, diff


def cmd_plan(args):
    root, kb, rules, configured, out_dir, content, defused, excluded, prev, diff = prepare(args)
    out = [f"# 快照预览：{kb.get('name', root.name)}", "",
           f"## 发布规则（{'来自 .kb.json 的 publish' if configured else '默认值，.kb.json 中没有 publish'}）", ""]
    out += [f"- {k}：{'、'.join(f'`{x}`' for x in v) or '（空）'}" for k, v in rules.items()]
    out += [f"- 硬性排除（不能配置）：{'、'.join(f'`{x}`' for x in HARD_EXCLUDE)}"]
    out += [f"- ⚠️ include 中的 `{p}` 属于硬性排除，不会发布" for p in rules["include"]
            if any(p.startswith(h) for h in HARD_EXCLUDE)]

    base = f"相对上一份快照 {prev[0].name}" if prev else "没有上一份快照"
    out += ["", f"## 将发布（{len(content)} 个文件；{base}：{summary(diff)}）", ""]
    label = {f: k for k in ("新增", "修改", "未变") for f in diff[k]}
    short = {"新增": "新", "修改": "改", "未变": "未变"}
    for rel in sorted(content):
        note = f"（{defused[rel]} 个链接转为纯文本）" if defused.get(rel) else ""
        out.append(f"- [{short[label[rel]]}] {rel}{note}")
    if diff["删除"]:
        out += ["", "上一份快照中有、这次不再包含：", *[f"- {f}" for f in diff["删除"]]]

    out += ["", f"## 在发布范围内但被排除（{len(excluded)}）", ""]
    out += [f"- {rel}：{reason}" for rel, reason in excluded] or ["（没有）"]

    watched = [(rel, watch(data.decode("utf-8", errors="replace"))) for rel, data in sorted(content.items())
               if Path(rel).suffix.lower() in TEXT_SUFFIXES]
    watched = [(rel, hits) for rel, hits in watched if hits]
    out += ["", f"## 需要留意（{len(watched)}）", ""]
    out += [f"- {rel}：{'；'.join(hits)}" for rel, hits in watched] or ["（没有）"]
    print("\n".join(out))


def cmd_build(args):
    root, kb, rules, configured, out_dir, content, defused, excluded, prev, diff = prepare(args)
    if not content:
        raise SnapshotError("没有可发布的文件。检查 .kb.json 的 publish.include。")
    project = kb.get("name", root.name)
    now = datetime.now()
    manifest = {
        "loom_snapshot": FORMAT,
        "project": project,
        "summary": kb.get("summary", ""),
        "created": now.isoformat(),
        "loom_version": skill_version(),
        "files": {rel: sha(data) for rel, data in sorted(content.items())},
    }
    readme = "\n".join([
        f"# {project} · 知识库快照", "",
        *([f"> {kb['summary']}", ""] if kb.get("summary") else []),
        f"- 发布时间：{now.strftime('%Y-%m-%d %H:%M')}",
        f"- 由 Loom {skill_version()} 生成。这是发布者的知识库在这一时刻的状态和结果，不包含对话记录和历史。",
        "- 导入方法：把这个 zip 放进 Loom 项目的 `20-Sources/inbox/`，让 AI 用 loom 的 ingest 处理。也可以直接解压阅读。",
        "", f"## 文件（{len(content)}）", "", *[f"- {rel}" for rel in sorted(content)], "",
    ])
    stem = re.sub(r'[\\/:*?"<>|\s]+', "-", project).strip("-") + f"-快照-{now.date()}"
    target, n = out_dir / f"{stem}.zip", 1
    while target.exists():
        n += 1
        target = out_dir / f"{stem}-{n}.zip"
    out_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        z.writestr(README, readme)
        for rel, data in sorted(content.items()):
            z.writestr(rel, data)
    base = f"相对上一份快照 {prev[0].name}" if prev else "没有上一份快照"
    print(f"已生成快照：{target}\n- {len(content)} 个文件；{base}：{summary(diff)}")


def unsafe(name):
    n = name.replace("\\", "/")
    return n.startswith("/") or re.match(r"[A-Za-z]:", n) or ".." in PurePosixPath(n).parts


def extract_text(src, manifest):
    """快照的提取文本：供检索，也是 wiki 引用来源时的链接目标。各文件内容放在围栏里，其中的链接不会生效。"""
    title = f"{manifest['project']} 知识库快照 {manifest.get('created', '')[:10]}"
    today = date.today().isoformat()
    out = ["---", "type: source", f"title: {title}", f"created: {today}", f"updated: {today}", "tags: [快照]",
           f"project: {manifest['project']}", f"published: {manifest.get('created', '')}", "---", "",
           f"# {title}", "", f"> 由 `snapshot.py open` 从 `{src.name}` 提取。原件是同目录下的 zip。", ""]
    with zipfile.ZipFile(src) as z:
        for info in sorted(z.infolist(), key=lambda i: i.filename):
            if info.is_dir() or info.filename in (MANIFEST, README):
                continue
            out += [f"## {info.filename}", ""]
            if Path(info.filename).suffix.lower() in TEXT_SUFFIXES:
                text = z.read(info).decode("utf-8", errors="replace").replace("\r\n", "\n").strip("\n")
                fence = "`" * max(4, max((len(r) for r in re.findall(r"`+", text)), default=0) + 1)
                out += [f"{fence}markdown", text, fence, ""]
            else:
                out += ["（非文本文件，没有提取）", ""]
    return "\n".join(out)


def cmd_open(args):
    src = Path(args.zip).resolve()
    if not src.is_file():
        raise SnapshotError(f"找不到文件：{src}")
    manifest = read_manifest(src)
    if manifest is None:
        raise SnapshotError(f"{src.name} 不是 Loom 快照（zip 中没有有效的 {MANIFEST}）。按普通资料处理。")
    with zipfile.ZipFile(src) as z:
        bad = [i.filename for i in z.infolist() if unsafe(i.filename)]
        if bad:
            raise SnapshotError("快照中有不安全的路径，已拒绝解压：" + "、".join(bad[:5]))
        dest = Path(tempfile.mkdtemp(prefix="loom-snapshot-"))
        z.extractall(dest)

    root = find_root(args.root)
    if args.prev:
        prev_path = Path(args.prev).resolve()
        prev = (prev_path, read_manifest(prev_path))
        if prev[1] is None:
            raise SnapshotError(f"{prev_path.name} 不是 Loom 快照。")
    else:
        prev = previous(root / "20-Sources" / "raw" if root else None, manifest["project"],
                        before=manifest.get("created", ""), skip=src)
    diff = compare(zip_hashes(src), zip_hashes(prev[0]) if prev else None)

    out = [f"# 快照：{manifest['project']}（发布于 {manifest.get('created', '?')[:16].replace('T', ' ')}，"
           f"Loom {manifest.get('loom_version', '?')}）", ""]
    if manifest.get("summary"):
        out.append(f"- 项目简介：{manifest['summary']}")
    out.append(f"- 已解压到：{dest}")
    if prev:
        out.append(f"- 上一份快照：{prev[0].name}（发布于 {prev[1].get('created', '?')[:16].replace('T', ' ')}）。"
                   f"{summary(diff, '删除')}")
    else:
        out.append("- 没有找到同一项目的上一份快照，全部按新增处理")
    if root and root in src.parents:
        note = src.with_suffix(".md")
        if note.exists():
            out.append(f"- 提取文本已存在：{note.relative_to(root).as_posix()}")
        else:
            write(note, extract_text(src, manifest))
            out.append(f"- 已生成提取文本：{note.relative_to(root).as_posix()}")
    else:
        out.append("- 这个 zip 不在知识库内，没有生成提取文本。先把它存入 20-Sources/raw/ 再运行")
    for key in ("新增", "修改", "删除"):
        out += ["", f"## {key}（{len(diff[key])}）", "", *([f"- {f}" for f in diff[key]] or ["（没有）"])]
    out += ["", f"## 未变（{len(diff['未变'])}）", "", "（不需要再读）" if diff["未变"] else "（没有）"]
    print("\n".join(out))


def main():
    utf8_stdout()
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", help="知识库根目录（默认从当前目录向上查找 .kb.json）")
    parser = argparse.ArgumentParser(description="Loom 知识库快照")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, func, text in (("plan", cmd_plan, "预览要发布的内容"), ("build", cmd_build, "生成快照 zip")):
        p = sub.add_parser(name, parents=[common], help=text)
        p.add_argument("--out", help=f"快照所在的目录（默认 {EXPORTS}/）")
        p.set_defaults(func=func)
    p = sub.add_parser("open", parents=[common], help="打开别人发布的快照")
    p.add_argument("zip")
    p.add_argument("--prev", help="指定用来比较的上一份快照（默认在 20-Sources/raw/ 中查找）")
    p.set_defaults(func=cmd_open)

    args = parser.parse_args()
    try:
        args.func(args)
    except SnapshotError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
