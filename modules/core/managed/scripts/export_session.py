"""把 Claude Code 会话记录（JSONL）导出为 Markdown，存入 40-Sessions/raw/YYYY/MM/。由 Loom 托管，请勿在项目中修改。

用法：
  1. 作为 hook（Stop / SessionEnd）运行：从 stdin 读取 hook JSON，从中取 transcript_path。
     在 repos/<名称>/ 等子目录启动的会话，由注入到该目录 .claude/settings.local.json 的 hook 调用本脚本。
  2. 手动补导出：<python> scripts/export_session.py <transcript.jsonl> [...]
     补导出本项目的全部历史会话（包括在子目录启动的）：<python> scripts/export_session.py --all

文件名按"会话开始时间 + session id 前 8 位"命名，保持稳定；同一会话重复导出时覆盖同一个文件。
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "40-Sessions" / "raw"

STRIP_TAGS = re.compile(
    r"<(system-reminder|ide_opened_file|ide_selection|ide_diagnostics|local-command-stdout|local-command-caveat)>.*?</\1>",
    re.S,
)
CMD_NAME = re.compile(r"<command-name>(.*?)</command-name>", re.S)
CMD_ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.S)
HEADING = re.compile(r"^(#{1,4} )", re.M)
TOOL_KEYS = ("description", "command", "file_path", "pattern", "url", "query", "prompt", "skill")


def local_time(ts):
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()


def clean_user_text(text):
    m = CMD_NAME.search(text)
    if m:
        args = CMD_ARGS.search(text)
        return f"{m.group(1).strip()} {args.group(1).strip() if args else ''}".strip()
    return STRIP_TAGS.sub("", text).strip()


def summarize_tool(block):
    name, inp = block.get("name", "?"), block.get("input") or {}
    if name == "AskUserQuestion":
        lines = ["> ❓ **提问**"]
        for q in inp.get("questions", []):
            opts = " / ".join(o.get("label", "") for o in q.get("options", []))
            lines.append(f"> - {q.get('question', '')}（{opts}）")
        return "\n".join(lines)
    detail = next((str(inp[k]) for k in TOOL_KEYS if inp.get(k)), "")
    detail = detail.replace("\n", " ")
    if len(detail) > 120:
        detail = detail[:120] + "…"
    return f"> 🔧 `{name}` {detail}"


def tool_result_text(block):
    c = block.get("content")
    if isinstance(c, list):
        c = "\n".join(b.get("text", "") for b in c if isinstance(b, dict))
    return c or ""


def parse(path):
    """返回 (session_id, title, cwd, events)。events: [(role, time, markdown)]"""
    session_id, title, cwd, events = None, None, None, []
    ask_ids = set()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        session_id = session_id or d.get("sessionId")
        cwd = cwd or d.get("cwd")
        t = d.get("type")
        if t == "ai-title":
            title = d.get("aiTitle") or title
            continue
        if t not in ("user", "assistant") or d.get("isSidechain") or d.get("isMeta"):
            continue
        ts = local_time(d.get("timestamp"))
        content = (d.get("message") or {}).get("content")
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        for b in content or []:
            bt = b.get("type")
            if t == "user" and bt == "text":
                text = clean_user_text(b.get("text", ""))
                if text:
                    events.append(("user", ts, text))
            elif t == "user" and bt == "tool_result" and b.get("tool_use_id") in ask_ids:
                events.append(("user", ts, "> ✅ **回答**：" + tool_result_text(b).split(". Read the answers")[0]))
            elif t == "assistant" and bt == "text" and b.get("text", "").strip():
                events.append(("assistant", ts, b["text"].strip()))
            elif t == "assistant" and bt == "tool_use":
                if b.get("name") == "AskUserQuestion":
                    ask_ids.add(b.get("id"))
                events.append(("assistant", ts, summarize_tool(b)))
    return session_id, title, cwd, events


def launched_in(cwd):
    """会话启动目录相对知识库根目录的路径；在根目录启动时返回 None。"""
    if not cwd:
        return None
    try:
        rel = Path(cwd).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return None
    return None if rel == "." else rel


def render(session_id, title, cwd, events):
    users = [e for e in events if e[0] == "user" and not e[2].startswith("> ✅")]
    start, end = events[0][1], events[-1][1]
    title = title or users[0][2].splitlines()[0][:40]
    fm = [
        "---",
        "type: raw-session",
        f'title: "{title.replace(chr(34), chr(39))}"',
        f"session_id: {session_id}",
        f"started: {start:%Y-%m-%d %H:%M}",
        f"ended: {end:%Y-%m-%d %H:%M}",
        f"prompts: {len(users)}",
    ]
    sub = launched_in(cwd)
    if sub:
        fm.append(f"launched_in: {sub}")
    fm += ["tags: [raw]", "---", "", f"# {title}", ""]
    out, last_role = fm, None
    for role, ts, text in events:
        if role != last_role:
            who = "👤 我" if role == "user" else "🤖 Claude"
            out.append(f"\n## {who} · {ts:%H:%M}\n")
            last_role = role
        # 正文标题降两级，避免与角色标题（##）同级而打乱大纲
        out.append(HEADING.sub(r"##\1", text) + "\n")
    return "\n".join(out)


def export(path):
    session_id, title, cwd, events = parse(path)
    if not session_id or not any(e[0] == "user" for e in events):
        return None
    start = events[0][1]
    target = RAW_DIR / f"{start:%Y}" / f"{start:%m}" / f"{start:%Y-%m-%d_%H%M}_{session_id[:8]}.md"
    text = render(session_id, title, cwd, events)
    if target.exists() and target.read_text(encoding="utf-8") == text:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


def transcript_cwd(path):
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i > 200:
                break
            try:
                cwd = json.loads(line).get("cwd")
            except json.JSONDecodeError:
                continue
            if cwd:
                return cwd
    return None


def project_transcripts():
    # Claude Code 把启动目录中的非字母数字字符替换为 "-" 作为目录名（盘符大小写可能不一致）。
    # 在子目录（如 repos/xxx）启动的会话目录名以根目录的名字为前缀；但名字相近的兄弟目录也可能
    # 有同样的前缀（如 Foo 和 Foo-Studio），所以再用记录里的 cwd 确认会话确实属于本知识库。
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(ROOT)).lower()
    base = Path.home() / ".claude" / "projects"
    if not base.is_dir():
        return []
    found = []
    for d in base.iterdir():
        name = d.name.lower()
        if name != slug and not name.startswith(slug + "-"):
            continue
        for f in d.glob("*.jsonl"):
            cwd = transcript_cwd(f)
            if name == slug or (cwd and launched_in(cwd)):
                found.append(f)
    return found


def main():
    args = sys.argv[1:]
    if args == ["--all"]:
        paths = project_transcripts()
    elif args:
        paths = args
    else:
        hook = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
        paths = [hook["transcript_path"]] if hook.get("transcript_path") else []
    for p in paths:
        try:
            target = export(p)
            if target and args:
                print(target.relative_to(ROOT).as_posix())
        except Exception as e:  # hook 不能因导出失败而打断会话
            print(f"export failed for {p}: {e}", file=sys.stderr)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
