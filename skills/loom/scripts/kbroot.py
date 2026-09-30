"""定位 Loom 知识库根目录（.kb.json 所在的目录），供其他脚本共用。

查找顺序：显式传入的路径 → 环境变量 CLAUDE_PROJECT_DIR（hook 中由 Claude Code 设置）→ 当前目录；
从起点向上逐级查找 .kb.json，所以在 repos/<名称>/ 等子目录中运行也能找到知识库。
"""
import json
import os
import sys
from pathlib import Path

KB_FILE = ".kb.json"
SKILL_DIR = Path(__file__).resolve().parent.parent
SCHEMA = 1  # 当前 Loom 使用的知识库结构版本，变化时在 references/migrate.md 中写迁移说明


def find_root(start=None):
    p = Path(start or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()
    for d in (p, *p.parents):
        if (d / KB_FILE).is_file():
            return d
    return None


def load_kb(root):
    try:
        return json.loads((root / KB_FILE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def skill_version():
    try:
        return (SKILL_DIR / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "?"


def utf8_stdout():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
