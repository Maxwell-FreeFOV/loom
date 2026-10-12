"""上下文分析器：读一份 DeepSeek Harness（dsh）的会话日志，列出每一步有什么进了上下文。

用法：
  python ctxtrace.py <session.jsonl> [--workspace <夹具项目目录>] [--json]

日志要是一行一个事件的普通 JSONL（见 rig.py 写出的 patch）。只依赖这些事件和字段：
  request/header        data.header.system、data.header.tools
  user/message          data.content、data.source.kind（user / plugin / skill-catalog / agent-instructions）
  tool/call             data.step、data.callId、data.name、data.arguments（JSON 字符串）
  tool/result           data.step、data.message.source.callId、data.message.content
  assistant/message     data.step、data.message、data.usage（inputTokens、cacheReadTokens、outputTokens）
  turn/end              data.reason
dsh 还在预览期，升级后先确认这些字段还在。

口径：每一步的提示词总量以供应商报告的 token 为准（未缓存输入加缓存命中）。各来源的份额按字符数给出，
不换算成 token：中文和英文的换算比例差别很大，换算了反而不准。
"""
import json
import re
import sys
from pathlib import Path

BLOCK_BEGIN, BLOCK_END = "<!-- loom:begin -->", "<!-- loom:end -->"
SCRIPTS = ("loom.py", "kb.py", "snapshot.py", "export_session.py", "sync_repos.py")
WRITE_TOOLS = {"write", "edit", "str_replace_editor"}
SEARCH_TOOLS = {"grep", "glob"}


def text_of(content):
    """把消息内容拍平成文本。内容可能是字符串，也可能是带 text 或嵌套 content 的块列表。"""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return content.get("text", "") + text_of(content.get("content", ""))
    if isinstance(content, list):
        return "".join(text_of(b) for b in content)
    return ""


def load(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def norm(path, workspace):
    """路径统一成正斜杠；在夹具项目里的改成相对路径。"""
    p = str(path).replace("\\", "/")
    if workspace:
        w = str(workspace).replace("\\", "/").rstrip("/")
        if p.lower().startswith(w.lower() + "/"):
            p = p[len(w) + 1:]
    return p[2:] if p.startswith("./") else p


SCRIPT_RE = "(" + "|".join(re.escape(s) for s in SCRIPTS) + ")"


def shell_tags(cmd):
    """一条 shell 命令里做了哪些事。模型常把几件事串在一条命令里，也常先把脚本路径存进变量再调用，
    所以不能只看开头：返回所有找到的标签，如 script:kb.py index、git、search。"""
    tags = []
    for script, sub in re.findall(SCRIPT_RE + r"[\"']?[ \t]+([a-z][\w-]*)", cmd):
        tags.append(f"script:{script} {sub}")
    for var, script in re.findall(r"\$(\w+)\s*=\s*[\"'][^\"'\n]*?" + SCRIPT_RE + r"[\"']", cmd):
        for sub in re.findall(r"\$" + re.escape(var) + r"\b[\"']?[ \t]+([a-z][\w-]*)", cmd):
            tags.append(f"script:{script} {sub}")
    if re.search(r"(^|[\s;&|(])git(\.exe)?\s", cmd):
        tags.append("git")
    if re.search(r"\b(Select-String|findstr|rg|grep)\b", cmd):
        tags.append("search")
    return list(dict.fromkeys(tags))


def classify(name, args, workspace):
    """一次工具调用属于哪一类、对象是什么。返回（类别，对象）。"""
    if name == "skill":
        return "skill", args.get("name", "")
    path = args.get("file_path") or args.get("path") or ""
    if name == "read" or name in WRITE_TOOLS:
        p = norm(path, workspace)
        verb = "write" if name in WRITE_TOOLS and not (name == "str_replace_editor" and args.get("command") == "view") \
            else "read"
        low = p.lower()
        if "/skills/loom/" in low or low.startswith("skills/loom/"):
            tail = low.split("/skills/loom/")[-1]
            if tail == "references/rules.md":
                return f"{verb}:rules", p
            if tail.startswith("references/"):
                return f"{verb}:op", tail[len("references/"):]
            return f"{verb}:skill-file", tail
        if low == "00-hub/hot.md":
            return f"{verb}:hot", p
        if re.match(r"\d\d-[^/]+/", p) or p in ("AGENTS.md", "CLAUDE.md", ".kb.json", "repos.yaml"):
            return f"{verb}:kb", p
        return f"{verb}:other", p
    if name in SEARCH_TOOLS:
        return "search", f"{args.get('pattern', '')} @ {norm(args.get('path') or '.', workspace)}"
    if name in ("pwsh", "bash"):
        cmd = str(args.get("command", ""))
        tags = shell_tags(cmd)
        scripts = [t[len("script:"):] for t in tags if t.startswith("script:")]
        flat = " ".join(cmd.split())[:200]
        if scripts:
            return "script", " + ".join(scripts)
        return ("git" if "git" in tags else "search" if "search" in tags else "shell"), flat
    return name, json.dumps(args, ensure_ascii=False)[:120]


def analyze(events, workspace=None):
    """返回一个字典：baseline（第一步之前的上下文）、steps（逐步账本）、actions（按顺序的工具调用）、
    totals（Loom 各来源的字符数）、answer（最后的回答）、end（结束原因）。"""
    baseline = {"system": 0, "tools": 0, "tool_count": 0, "loom_block": 0, "instructions_other": 0,
                "instruction_files": [], "catalog_loom": 0, "catalog_other": 0, "catalog_names": [],
                "plugin_sections": 0, "user_prompt": 0}
    calls, actions, usage, answer, end = {}, [], {}, "", None
    for ev in events:
        t, d = ev.get("type"), ev.get("data") or {}
        if t == "request/header" and not baseline["system"]:
            h = d.get("header", {})
            baseline["system"] = len(h.get("system") or "")
            baseline["tools"] = len(json.dumps(h.get("tools") or [], ensure_ascii=False))
            baseline["tool_count"] = len(h.get("tools") or [])
        elif t == "user/message":
            src, text = d.get("source") or {}, text_of(d.get("content"))
            kind = src.get("kind")
            if kind == "user":
                baseline["user_prompt"] += len(text)
            elif kind == "plugin":
                baseline["plugin_sections"] += len(text)
            elif kind == "skill-catalog":
                names = [e.get("name") for e in src.get("entries", [])]
                baseline["catalog_names"] = names
                loom = next((e for e in src.get("entries", []) if e.get("name") == "loom"), None)
                loom_chars = len(loom.get("name", "")) + len(loom.get("description", "")) if loom else 0
                baseline["catalog_loom"] += loom_chars
                baseline["catalog_other"] += len(text) - loom_chars
            elif kind == "agent-instructions":
                baseline["instruction_files"] += [c.get("path") for c in src.get("changes", [])]
                block = 0
                for m in re.finditer(re.escape(BLOCK_BEGIN) + r".*?" + re.escape(BLOCK_END), text, re.S):
                    block += len(m.group(0))
                baseline["loom_block"] += block
                baseline["instructions_other"] += len(text) - block
        elif t == "tool/call":
            try:
                args = json.loads(d["arguments"]) if isinstance(d.get("arguments"), str) else (d.get("arguments") or {})
            except json.JSONDecodeError:
                args = {}
            kind, target = classify(d.get("name", "?"), args, workspace)
            calls[d.get("callId")] = len(actions)
            cmd = str(args.get("command", "")) if d.get("name") in ("pwsh", "bash") else ""
            actions.append({"step": d.get("step"), "tool": d.get("name"), "kind": kind, "target": target, "chars": 0,
                            "tags": shell_tags(cmd) if cmd else [], "command": " ".join(cmd.split())})
        elif t == "tool/result":
            msg = d.get("message") or {}
            i = calls.get((msg.get("source") or {}).get("callId"))
            if i is not None:
                actions[i]["chars"] = len(text_of(msg.get("content")))
                actions[i]["result"] = text_of(msg.get("content"))[:2000]
        elif t == "assistant/message":
            usage[d.get("step")] = d.get("usage") or {}
            said = text_of((d.get("message") or {}).get("content"))
            if said.strip():
                answer = said
        elif t == "turn/end":
            end = (d.get("reason") or {}).get("kind")
    steps = []
    for s in sorted(k for k in usage if k is not None):
        u = usage[s]
        steps.append({"step": s, "prompt_tokens": u.get("inputTokens", 0) + u.get("cacheReadTokens", 0),
                      "cached_tokens": u.get("cacheReadTokens", 0), "output_tokens": u.get("outputTokens", 0),
                      "actions": [a for a in actions if a["step"] == s]})
    totals = {}
    for a in actions:
        key = {"skill": "SKILL.md 正文", "read:rules": "通用规则", "read:op": "操作说明", "read:skill-file": "skill 的其他文件",
               "read:hot": "hot.md", "read:kb": "知识库的其他文件", "script": "Loom 脚本的输出"}.get(a["kind"])
        if key:
            totals[key] = totals.get(key, 0) + a["chars"]
    return {"baseline": baseline, "steps": steps, "actions": actions, "totals": totals, "answer": answer, "end": end}


# ---------- 供断言使用的查询 ----------

def first(actions, kind=None, target=None, tool=None):
    """第一个符合条件的工具调用的序号；没有时返回 None。target 是正则。
    kind 既和主类别比，也和 shell 命令的标签比：一条串了几件事的命令，每件事都算发生过。"""
    for i, a in enumerate(actions):
        kinds = [a["kind"], *a.get("tags", [])]
        text = " ".join([a["target"], a.get("command", ""), *a.get("tags", [])])
        if (kind is None or any(k == kind or k.startswith(kind + ":") for k in kinds)) \
                and (tool is None or a["tool"] == tool) \
                and (target is None or re.search(target, text, re.I)):
            return i
    return None


def happened(actions, **kw):
    return first(actions, **kw) is not None


def before(actions, a, b):
    """a 发生在 b 之前（a、b 是 first 的关键字参数）。b 没有发生时，只要 a 发生过就算。"""
    i, j = first(actions, **a), first(actions, **b)
    return i is not None and (j is None or i < j)


def render(result, title="上下文账本"):
    b, out = result["baseline"], [f"## {title}", ""]
    out += ["**第一步之前的上下文**（字符数）", "", "| 来源 | 字符数 |", "|---|---|",
            f"| 系统提示词 | {b['system']} |", f"| 工具定义（{b['tool_count']} 个） | {b['tools']} |",
            f"| 项目指令里的 Loom 区块 | {b['loom_block']} |",
            f"| 项目指令的其余部分（{'、'.join(b['instruction_files']) or '无'}） | {b['instructions_other']} |",
            f"| skill 目录里 loom 那一条 | {b['catalog_loom']} |", f"| skill 目录的其余部分 | {b['catalog_other']} |",
            f"| 权限等系统片段 | {b['plugin_sections']} |", f"| 用户的提问 | {b['user_prompt']} |", ""]
    out += ["**逐步**", "", "| 步 | 提示词 token（缓存命中） | 输出 token | 这一步做了什么（结果的字符数） |", "|---|---|---|---|"]
    for s in result["steps"]:
        acts = "；".join(f"`{a['kind']}` {a['target'][:70].replace('|', '/')}（{a['chars']}）" for a in s["actions"]) or "回答"
        out.append(f"| {s['step']} | {s['prompt_tokens']}（{s['cached_tokens']}） | {s['output_tokens']} | {acts} |")
    out += ["", "**Loom 带进上下文的内容**（字符数，不含上表第一步之前的部分）", ""]
    out += [f"- {k}：{v}" for k, v in sorted(result["totals"].items(), key=lambda x: -x[1])] or ["- （没有）"]
    return "\n".join(out) + "\n"


def main():
    args = sys.argv[1:]
    as_json = "--json" in args
    workspace = args[args.index("--workspace") + 1] if "--workspace" in args else None
    paths = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or args[i - 1] != "--workspace")]
    if len(paths) != 1:
        print(__doc__)
        sys.exit(2)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    result = analyze(load(paths[0]), workspace)
    print(json.dumps(result, ensure_ascii=False, indent=2) if as_json else render(result))


if __name__ == "__main__":
    main()
