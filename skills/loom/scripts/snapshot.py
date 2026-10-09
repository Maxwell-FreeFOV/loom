"""知识库快照：发布当前知识库中可公开的内容，以及打开别人发布的快照。属于 Loom skill。

用法（在知识库根目录或其子目录中运行，也可以用 --root 指定根目录）：
  python snapshot.py plan [--out 目录]          预览：哪些文件会发布、哪些被排除、哪些内容需要留意。不写任何文件
  python snapshot.py build [--out 目录]         生成快照 zip，默认写到 50-Outputs/_exports/
  python snapshot.py open <zip> [--prev <zip>]  打开别人的快照：解压到临时目录，和上一份比较，生成同名的 .md 提取文本

快照是知识库当前的状态和结果，不包含历史和过程。发布规则写在 .kb.json 的 publish 中，没有配置时用 DEFAULTS；
HARD_EXCLUDE 中的路径，配置和笔记上的 publish: true 都不能打开。清洗只作用于快照里的副本，不改知识库中的源文件。
快照内的说明文件名固定为 snapshot-readme.md（内容按项目语言）；读取时同时接受旧名 快照说明.md。
"""
import argparse
import fnmatch
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from collections import Counter
from datetime import date, datetime
from pathlib import Path, PurePosixPath

from kbroot import ConfigError, find_root, kb_language, L, load_kb, skill_version, utf8_stdout  # 先导入：含版本预检
import kb as kbmod

MANIFEST = "loom-snapshot.json"
README = "snapshot-readme.md"
README_NAMES = {README, "快照说明.md"}  # 新旧两种说明文件名，读取时都接受
FORMAT = 1
EXPORTS = "50-Outputs/_exports"
DEFAULTS = {
    "include": ["10-Brief/", "30-Wiki/", "20-Sources/cards/", "50-Outputs/", "00-Hub/roadmap.md"],
    "exclude": [],
    "strip_fields": ["raws", "session", "commits", "decisions"],
    "strip_sections": ["变更记录", "版本历史", "Change log", "Changelog", "Version history"],
}
# 历史和过程：对话、纪要、决策记录、时间线、日志；以及索引、待处理资料和导出物
HARD_EXCLUDE = ["40-Sessions/", "00-Hub/timeline.md", "00-Hub/log.md", "00-Hub/index.md",
                "20-Sources/inbox/", EXPORTS + "/"]
ALWAYS_STRIP = ["publish"]  # 发布者自己用的标记，不带进快照

LINK = re.compile(r"!?\[\[([^\]\|#]+)(?:#[^\]\|]*)?(?:\\?\|([^\]]*))?\]\]")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
WATCH = [  # 发布前提醒 AI 和用户留意的内容
    ("本机路径", "local paths", re.compile(r"\b[A-Za-z]:[\\/][^\s`\"')）]*|/(?:Users|home)/[^\s`\"')）]*")),
    ("邮箱", "email addresses", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("密钥类内容", "secret-like content", re.compile(r"(?i)\b(?:password|passwd|secret|api[_-]?key)\b|密码|密钥|\bsk-[A-Za-z0-9_-]{8,}")),
    ("对话记录路径", "session-record paths", re.compile(r"40-Sessions/raw[^\s`\"')）]*")),
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


def is_link(p):
    return p.is_symlink() or os.path.isjunction(p)


def link_reason(root, p, rel, rules, lang):
    """链接（符号链接/目录联接）能否发布：不能时返回原因，能时返回 None。
    目标 resolve 后必须在库内，且用真实相对路径重新过 HARD_EXCLUDE、include 和 exclude 规则：
    放在发布范围里的链接不能把范围之外的文件（例如 20-Sources/raw/ 下的原件）带出去。"""
    try:
        real_rel = p.resolve(strict=True).relative_to(root.resolve()).as_posix()
    except ValueError:
        return L(lang, "链接指向知识库之外", "link target is outside the knowledge base")
    except OSError as e:
        raise SnapshotError(L(lang, f"无法确认链接 {rel} 的目标，已中止：{e}",
                              f"Cannot resolve the target of link {rel}; aborted: {e}"))
    if matches(real_rel, HARD_EXCLUDE):
        return L(lang, f"链接的目标 {real_rel} 属于硬性排除", f"link target {real_rel} is hard-excluded")
    if not matches(real_rel, rules["include"]):
        return L(lang, f"链接的目标 {real_rel} 不在发布范围内", f"link target {real_rel} is outside the publish scope")
    if matches(real_rel, rules["exclude"]):
        return L(lang, f"链接的目标 {real_rel} 匹配 exclude", f"link target {real_rel} matches exclude")
    return None


def select(root, rules, lang):
    """返回（要发布的文件 [(相对路径, 路径)]，在 include 范围内但被排除的 [(相对路径, 原因)]）。"""
    files, excluded = [], []
    for p in sorted(kbmod.walk(kbmod.PRUNE)):
        rel = p.relative_to(root).as_posix()
        if p.name == ".gitkeep" or matches(rel, HARD_EXCLUDE):
            continue
        if is_link(p):
            reason = link_reason(root, p, rel, rules, lang)
            if reason:
                excluded.append((rel, reason))
                continue
        included = matches(rel, rules["include"])
        meta = {}
        if p.suffix.lower() == ".md":
            try:
                meta = kbmod.frontmatter(p.read_text(encoding="utf-8", errors="ignore"))[0]
            except OSError as e:
                raise SnapshotError(L(lang, f"读取 {rel} 失败，已中止：{e}", f"Failed to read {rel}; aborted: {e}")) from e
        flag = meta.get("publish", "").lower()
        if flag == "true":
            files.append((rel, p))
        elif not included:
            continue
        elif flag == "false":
            excluded.append((rel, L(lang, "笔记标了 publish: false", "note is marked publish: false")))
        elif matches(rel, rules["exclude"]):
            excluded.append((rel, L(lang, "匹配 exclude", "matches exclude")))
        elif meta.get("type") == "output" and meta.get("status") != "released":
            excluded.append((rel, L(lang, f"产出物的状态是 {meta.get('status') or '空'}，不是 released",
                                    f"output status is {meta.get('status') or 'empty'}, not released")))
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
    """删除标题在 titles 中的段落：从该标题到下一个同级或更高级的标题。标题比较忽略大小写
    （英文的 Change log / Changelog / VERSION HISTORY 等同；中文不受影响）。"""
    lowered = {t.lower() for t in titles}
    out, skip, fence = [], 0, False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            fence = not fence
        h = None if fence else HEADING.match(line)
        if h:
            level = len(h.group(1))
            if skip and level <= skip:
                skip = 0
            if not skip and h.group(2).lower() in lowered:
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


def watch(text, lang):
    hits = []
    for zh, en, pattern in WATCH:
        found = list(dict.fromkeys(m.group(0) for m in pattern.finditer(text)))
        if found:
            more = L(lang, f" 等 {len(found)} 处", f" and {len(found) - 3} more") if len(found) > 3 else ""
            hits.append(L(lang, f"{zh}（{'、'.join(found[:3])}{more}）", f"{en} ({', '.join(found[:3])}{more})"))
    return hits


def render(root, rules, lang):
    """返回（{相对路径: 清洗后的内容 bytes}，{相对路径: 改成纯文本的链接数}，被排除的列表）。"""
    files, excluded = select(root, rules, lang)
    names = link_names(rel for rel, _ in files)
    content, defused = {}, {}
    for rel, p in files:
        try:
            data = p.read_bytes()
        except OSError as e:
            raise SnapshotError(L(lang, f"读取 {rel} 失败，已中止：{e}", f"Failed to read {rel}; aborted: {e}")) from e
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
                if not i.is_dir() and i.filename not in ({MANIFEST} | README_NAMES)}


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
    """files、prev 都是 {路径: sha256}；prev 为 None 表示没有上一份。键是内部标识，展示时按语言翻译。"""
    prev = prev or {}
    return {
        "new": sorted(f for f in files if f not in prev),
        "changed": sorted(f for f in files if f in prev and prev[f] != files[f]),
        "same": sorted(f for f in files if prev.get(f) == files[f]),
        "removed": sorted(f for f in prev if f not in files),
    }


DIFF_ZH = {"new": "新增", "changed": "修改", "same": "未变", "removed": "删除"}
DIFF_EN = {"new": "Added", "changed": "Changed", "same": "Unchanged", "removed": "Removed"}


def diff_label(lang, key):
    return L(lang, DIFF_ZH[key], DIFF_EN[key])


def summary(diff, lang, removed=None):
    removed = removed or L(lang, "不再包含", "removed")
    return L(lang, f"新 {len(diff['new'])}、改 {len(diff['changed'])}、未变 {len(diff['same'])}、"
                   f"{removed} {len(diff['removed'])}",
             f"{len(diff['new'])} new, {len(diff['changed'])} changed, {len(diff['same'])} unchanged, "
             f"{removed} {len(diff['removed'])}")


def write(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.replace("\n", os.linesep).encode("utf-8"))


def snapshot_readme(project, kb, content, now, lang):
    """快照内的说明文件（文件名固定为 snapshot-readme.md，内容按项目语言）。"""
    if lang == "en":
        return "\n".join([
            f"# {project} · Knowledge Base Snapshot", "",
            *([f"> {kb['summary']}", ""] if kb.get("summary") else []),
            f"- Published: {now.strftime('%Y-%m-%d %H:%M')}",
            f"- Generated by Loom {skill_version()}. This is the state and results of the publisher's knowledge "
            "base at this moment; conversations and history are not included.",
            "- To import: put this zip into `20-Sources/inbox/` of a Loom project and ask the AI to ingest it "
            "with loom. You can also simply unzip and read it.",
            "", f"## Files ({len(content)})", "", *[f"- {rel}" for rel in sorted(content)], "",
        ])
    return "\n".join([
        f"# {project} · 知识库快照", "",
        *([f"> {kb['summary']}", ""] if kb.get("summary") else []),
        f"- 发布时间：{now.strftime('%Y-%m-%d %H:%M')}",
        f"- 由 Loom {skill_version()} 生成。这是发布者的知识库在这一时刻的状态和结果，不包含对话记录和历史。",
        "- 导入方法：把这个 zip 放进 Loom 项目的 `20-Sources/inbox/`，让 AI 用 loom 的 ingest 处理。也可以直接解压阅读。",
        "", f"## 文件（{len(content)}）", "", *[f"- {rel}" for rel in sorted(content)], "",
    ])


# ---------- 命令 ----------

def prepare(args):
    root = find_root(args.root)
    if root is None:
        raise SnapshotError("Not in a Loom project (no .kb.json found in this directory or its parents).")
    kbmod.set_root(root)
    kb = load_kb(root)
    lang = kb_language(kb)
    rules, configured = load_rules(kb)
    out_dir = Path(args.out).resolve() if args.out else root / EXPORTS
    content, defused, excluded = render(root, rules, lang)
    project = kb.get("name", root.name)
    prev = previous(out_dir, project)
    diff = compare({rel: sha(data) for rel, data in content.items()}, zip_hashes(prev[0]) if prev else None)
    return root, kb, lang, rules, configured, out_dir, content, defused, excluded, prev, diff


def cmd_plan(args):
    root, kb, lang, rules, configured, out_dir, content, defused, excluded, prev, diff = prepare(args)
    out = [L(lang, f"# 快照预览：{kb.get('name', root.name)}", f"# Snapshot preview: {kb.get('name', root.name)}"), "",
           L(lang, f"## 发布规则（{'来自 .kb.json 的 publish' if configured else '默认值，.kb.json 中没有 publish'}）",
             f"## Publish rules ({'from publish in .kb.json' if configured else 'defaults; no publish in .kb.json'})"), ""]
    out += [f"- {k}{L(lang, '：', ': ')}{L(lang, '、', ', ').join(f'`{x}`' for x in v) or L(lang, '（空）', '(empty)')}"
            for k, v in rules.items()]
    out += [L(lang, f"- 硬性排除（不能配置）：{'、'.join(f'`{x}`' for x in HARD_EXCLUDE)}",
              f"- Hard exclusions (not configurable): {', '.join(f'`{x}`' for x in HARD_EXCLUDE)}")]
    out += [L(lang, f"- ⚠️ include 中的 `{p}` 属于硬性排除，不会发布",
              f"- ⚠️ `{p}` in include is hard-excluded and will not be published") for p in rules["include"]
            if any(p.startswith(h) for h in HARD_EXCLUDE)]

    base = L(lang, f"相对上一份快照 {prev[0].name}", f"relative to previous snapshot {prev[0].name}") if prev \
        else L(lang, "没有上一份快照", "no previous snapshot")
    out += ["", L(lang, f"## 将发布（{len(content)} 个文件；{base}：{summary(diff, lang)}）",
                  f"## Will publish ({len(content)} files; {base}: {summary(diff, lang)})"), ""]
    label = {f: k for k in ("new", "changed", "same") for f in diff[k]}
    short = {"new": L(lang, "新", "new"), "changed": L(lang, "改", "chg"), "same": L(lang, "未变", "same")}
    for rel in sorted(content):
        note = L(lang, f"（{defused[rel]} 个链接转为纯文本）",
                 f" ({defused[rel]} link(s) turned into plain text)") if defused.get(rel) else ""
        out.append(f"- [{short[label[rel]]}] {rel}{note}")
    if diff["removed"]:
        out += ["", L(lang, "上一份快照中有、这次不再包含：", "In the previous snapshot but no longer included:"),
                *[f"- {f}" for f in diff["removed"]]]

    out += ["", L(lang, f"## 在发布范围内但被排除（{len(excluded)}）",
                  f"## Excluded although in scope ({len(excluded)})"), ""]
    out += [f"- {rel}{L(lang, '：', ': ')}{reason}" for rel, reason in excluded] or [L(lang, "（没有）", "(none)")]

    watched = [(rel, watch(data.decode("utf-8", errors="replace"), lang)) for rel, data in sorted(content.items())
               if Path(rel).suffix.lower() in TEXT_SUFFIXES]
    watched = [(rel, hits) for rel, hits in watched if hits]
    out += ["", L(lang, f"## 需要留意（{len(watched)}）", f"## Needs attention ({len(watched)})"), ""]
    out += [f"- {rel}{L(lang, '：', ': ')}{L(lang, '；', '; ').join(hits)}" for rel, hits in watched] \
        or [L(lang, "（没有）", "(none)")]
    print("\n".join(out))


def cmd_build(args):
    root, kb, lang, rules, configured, out_dir, content, defused, excluded, prev, diff = prepare(args)
    if not content:
        raise SnapshotError(L(lang, "没有可发布的文件。检查 .kb.json 的 publish.include。",
                              "Nothing to publish. Check publish.include in .kb.json."))
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
    readme = snapshot_readme(project, kb, content, now, lang)
    stem = re.sub(r'[\\/:*?"<>|\s]+', "-", project).strip("-") + L(lang, f"-快照-{now.date()}", f"-snapshot-{now.date()}")
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
    base = L(lang, f"相对上一份快照 {prev[0].name}", f"relative to previous snapshot {prev[0].name}") if prev \
        else L(lang, "没有上一份快照", "no previous snapshot")
    print(L(lang, f"已生成快照：{target}\n- {len(content)} 个文件；{base}：{summary(diff, lang)}",
            f"Snapshot written: {target}\n- {len(content)} files; {base}: {summary(diff, lang)}"))


def unsafe(name):
    n = name.replace("\\", "/")
    return n.startswith("/") or re.match(r"[A-Za-z]:", n) or ".." in PurePosixPath(n).parts


# 打开不可信快照时的资源上限：条目数、单文件解压后大小、总解压后大小。首版不提供绕过的 --force。
MAX_ENTRIES = 10000
MAX_FILE = 100 * 1024 * 1024     # 100 MiB
MAX_TOTAL = 1024 * 1024 * 1024   # 1 GiB


def checked_extract(z, manifest, lang):
    """校验并解压快照到临时目录，返回目录。顺序：条目数与头部大小预算 → 路径安全与重复 → 成员集合与清单一致 →
    逐个解压（流式累计实际大小，超限即中止）并核对 sha256。任何失败都清理临时目录。"""
    infos = z.infolist()
    if len(infos) > MAX_ENTRIES:
        raise SnapshotError(L(lang, f"快照有 {len(infos)} 个条目，超过上限 {MAX_ENTRIES}，已拒绝解压。",
                              f"The snapshot has {len(infos)} entries, exceeding the limit of {MAX_ENTRIES}; "
                              "extraction refused."))
    bad = [i.filename for i in infos if not i.is_dir() and unsafe(i.filename)]
    if bad:
        raise SnapshotError(L(lang, "快照中有不安全的路径，已拒绝解压：", "The snapshot contains unsafe paths; "
                              "extraction refused: ") + L(lang, "、", ", ").join(bad[:5]))
    names = [i.filename.replace("\\", "/") for i in infos if not i.is_dir()]
    dup = sorted(n for n, c in Counter(names).items() if c > 1)
    if dup:
        raise SnapshotError(L(lang, "快照中有重复或规范化后冲突的路径，已拒绝解压：",
                              "The snapshot contains duplicate or conflicting paths after normalization; "
                              "extraction refused: ") + L(lang, "、", ", ").join(dup[:5]))
    too_big = [i.filename for i in infos if not i.is_dir() and i.file_size > MAX_FILE]
    if too_big:
        raise SnapshotError(L(lang, f"快照中有解压后超过 100 MiB 的文件（{'、'.join(too_big[:5])}），已拒绝解压。",
                              f"The snapshot contains files larger than 100 MiB after extraction "
                              f"({', '.join(too_big[:5])}); extraction refused."))
    if sum(i.file_size for i in infos if not i.is_dir()) > MAX_TOTAL:
        raise SnapshotError(L(lang, "快照解压后的总大小超过 1 GiB，已拒绝解压。",
                              "The snapshot's total extracted size exceeds 1 GiB; extraction refused."))
    extras = {MANIFEST} | README_NAMES
    members, declared = set(names) - extras, set(manifest["files"])
    if members != declared:
        detail = ([L(lang, f"不在清单中：{'、'.join(sorted(members - declared)[:5])}",
                     f"not in the manifest: {', '.join(sorted(members - declared)[:5])}")]
                  if members - declared else []) \
               + ([L(lang, f"清单中有但 zip 中没有：{'、'.join(sorted(declared - members)[:5])}",
                     f"in the manifest but missing from the zip: {', '.join(sorted(declared - members)[:5])}")]
                  if declared - members else [])
        raise SnapshotError(L(lang, "快照的成员与清单不一致，已拒绝解压：",
                              "Snapshot members do not match the manifest; extraction refused: ")
                            + L(lang, "；", "; ").join(detail))
    dest = Path(tempfile.mkdtemp(prefix="loom-snapshot-"))
    try:
        total = 0
        for i in infos:
            if i.is_dir():
                continue
            name = i.filename.replace("\\", "/")
            target = dest.joinpath(*PurePosixPath(name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            h, size = hashlib.sha256(), 0
            with z.open(i) as fin, open(target, "wb") as fout:
                while chunk := fin.read(1 << 20):
                    size += len(chunk)
                    total += len(chunk)
                    if size > MAX_FILE or total > MAX_TOTAL:
                        raise SnapshotError(L(lang, f"解压 {name} 时实际大小超过预算，已中止。",
                                              f"Actual size exceeded the budget while extracting {name}; aborted."))
                    h.update(chunk)
                    fout.write(chunk)
            if name not in extras and h.hexdigest() != manifest["files"][name]:
                raise SnapshotError(L(lang, f"{name} 的校验值与清单不一致，快照可能被改动过，已拒绝解压。",
                                      f"{name}'s checksum does not match the manifest; the snapshot may have "
                                      "been modified; extraction refused."))
        return dest
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise


def extract_text(src, manifest, lang):
    """快照的提取文本：供检索，也是 wiki 引用来源时的链接目标。各文件内容放在围栏里，其中的链接不会生效。"""
    title = L(lang, f"{manifest['project']} 知识库快照 {manifest.get('created', '')[:10]}",
              f"{manifest['project']} knowledge base snapshot {manifest.get('created', '')[:10]}")
    today = date.today().isoformat()
    out = ["---", "type: source", f"title: {title}", f"created: {today}", f"updated: {today}",
           f"tags: [{L(lang, '快照', 'snapshot')}]",
           f"project: {manifest['project']}", f"published: {manifest.get('created', '')}", "---", "",
           f"# {title}", "",
           L(lang, f"> 由 `snapshot.py open` 从 `{src.name}` 提取。原件是同目录下的 zip。",
             f"> Extracted by `snapshot.py open` from `{src.name}`. The original zip sits next to this file."), ""]
    with zipfile.ZipFile(src) as z:
        for info in sorted(z.infolist(), key=lambda i: i.filename):
            if info.is_dir() or info.filename in ({MANIFEST} | README_NAMES):
                continue
            out += [f"## {info.filename}", ""]
            if Path(info.filename).suffix.lower() in TEXT_SUFFIXES:
                text = z.read(info).decode("utf-8", errors="replace").replace("\r\n", "\n").strip("\n")
                fence = "`" * max(4, max((len(r) for r in re.findall(r"`+", text)), default=0) + 1)
                out += [f"{fence}markdown", text, fence, ""]
            else:
                out += [L(lang, "（非文本文件，没有提取）", "(non-text file; not extracted)"), ""]
    return "\n".join(out)


def cmd_open(args):
    src = Path(args.zip).resolve()
    root = find_root(args.root)
    lang = "en"  # 不在项目里时按 CLI 默认姿态
    if root:
        try:
            lang = kb_language(load_kb(root))
        except ConfigError:
            lang = "zh-CN"
    if not src.is_file():
        raise SnapshotError(L(lang, f"找不到文件：{src}", f"File not found: {src}"))
    manifest = read_manifest(src)
    if manifest is None:
        raise SnapshotError(L(lang, f"{src.name} 不是 Loom 快照（zip 中没有有效的 {MANIFEST}）。按普通资料处理。",
                              f"{src.name} is not a Loom snapshot (no valid {MANIFEST} in the zip). "
                              "Treat it as an ordinary source."))
    if manifest.get("loom_snapshot") != FORMAT:
        raise SnapshotError(L(lang, f"快照的格式版本是 {manifest.get('loom_snapshot')}，当前 Loom 只支持 {FORMAT}，"
                                    "已拒绝打开。",
                              f"The snapshot's format version is {manifest.get('loom_snapshot')}; this Loom "
                              f"supports {FORMAT}; refused to open."))
    if not isinstance(manifest.get("files"), dict):
        raise SnapshotError(L(lang, "快照清单缺少有效的 files 列表，已拒绝打开。",
                              "The snapshot manifest lacks a valid files list; refused to open."))
    if args.prev:  # 先确认上一份快照有效，再解压：避免解压之后才报错，把临时目录遗留下来
        prev_path = Path(args.prev).resolve()
        prev = (prev_path, read_manifest(prev_path))
        if prev[1] is None:
            raise SnapshotError(L(lang, f"{prev_path.name} 不是 Loom 快照。", f"{prev_path.name} is not a Loom snapshot."))
    else:
        prev = previous(root / "20-Sources" / "raw" if root else None, manifest["project"],
                        before=manifest.get("created", ""), skip=src)
    with zipfile.ZipFile(src) as z:
        dest = checked_extract(z, manifest, lang)
    diff = compare(zip_hashes(src), zip_hashes(prev[0]) if prev else None)

    out = [L(lang, f"# 快照：{manifest['project']}（发布于 {manifest.get('created', '?')[:16].replace('T', ' ')}，"
                   f"Loom {manifest.get('loom_version', '?')}）",
             f"# Snapshot: {manifest['project']} (published {manifest.get('created', '?')[:16].replace('T', ' ')}, "
             f"Loom {manifest.get('loom_version', '?')})"), ""]
    if manifest.get("summary"):
        out.append(L(lang, f"- 项目简介：{manifest['summary']}", f"- Project summary: {manifest['summary']}"))
    out.append(L(lang, f"- 已解压到：{dest}", f"- Extracted to: {dest}"))
    if prev:
        out.append(L(lang, f"- 上一份快照：{prev[0].name}（发布于 {prev[1].get('created', '?')[:16].replace('T', ' ')}）。"
                           f"{summary(diff, lang, L(lang, '删除', 'removed'))}",
                     f"- Previous snapshot: {prev[0].name} (published "
                     f"{prev[1].get('created', '?')[:16].replace('T', ' ')}). "
                     f"{summary(diff, lang, 'removed')}"))
    else:
        out.append(L(lang, "- 没有找到同一项目的上一份快照，全部按新增处理",
                     "- No previous snapshot of the same project found; everything counts as added"))
    if root and root in src.parents:
        note = src.with_suffix(".md")
        if note.exists():
            out.append(L(lang, f"- 提取文本已存在：{note.relative_to(root).as_posix()}",
                         f"- Extracted text already exists: {note.relative_to(root).as_posix()}"))
        else:
            write(note, extract_text(src, manifest, lang))
            out.append(L(lang, f"- 已生成提取文本：{note.relative_to(root).as_posix()}",
                         f"- Extracted text written: {note.relative_to(root).as_posix()}"))
    else:
        out.append(L(lang, "- 这个 zip 不在知识库内，没有生成提取文本。先把它存入 20-Sources/raw/ 再运行",
                     "- This zip is not inside the knowledge base, so no extracted text was generated. "
                     "Put it into 20-Sources/raw/ first and run again"))
    def heading(key):
        n = len(diff[key])
        return f"## {diff_label(lang, key)}（{n}）" if lang != "en" else f"## {diff_label(lang, key)} ({n})"

    for key in ("new", "changed", "removed"):
        out += ["", heading(key), "",
                *([f"- {f}" for f in diff[key]] or [L(lang, "（没有）", "(none)")])]
    out += ["", heading("same"), "",
            L(lang, "（不需要再读）", "(no need to re-read)") if diff["same"] else L(lang, "（没有）", "(none)")]
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
    except (SnapshotError, ConfigError) as e:  # ConfigError：.kb.json 损坏，不能退回默认发布范围
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
