"""定位 Loom 知识库根目录（.kb.json 所在的目录），供其他脚本共用。

查找顺序：显式传入的路径 → 环境变量 CLAUDE_PROJECT_DIR（hook 中由 Claude Code 设置）→ 当前目录；
从起点向上逐级查找 .kb.json，所以在 repos/<名称>/ 等子目录中运行也能找到知识库。
"""
import json
import os
import sys
from pathlib import Path

if sys.version_info < (3, 12):  # 各脚本都先导入本模块，所以在这里统一预检
    sys.exit("Loom requires Python 3.12 or newer (this is %s)." % sys.version.split()[0])  # 此时还没设置 UTF-8 输出，只用 ASCII

KB_FILE = ".kb.json"
SKILL_DIR = Path(__file__).resolve().parent.parent
SCHEMA = 2  # 当前 Loom 使用的知识库结构版本，变化时在 references/migrate.md 中写迁移说明

LANGUAGES = ("en", "zh-CN")  # 支持的项目语言；loom.py init 的 --language 用这里的取值


class ConfigError(Exception):
    """.kb.json 存在但内容损坏（不是合法 JSON、不是对象，或 language 不受支持）。和"没有 publish 配置"是两回事：
    后者退回默认值，前者必须阻断发布和会改动配置的操作，避免把损坏的配置当作默认值覆盖。"""


def find_root(start=None):
    p = Path(start or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()
    for d in (p, *p.parents):
        if (d / KB_FILE).is_file():
            return d
    return None


def load_kb(root):
    """读取 .kb.json。文件不存在时返回 {}；存在但损坏时抛 ConfigError，由调用方决定阻断还是警告后继续。
    language 写了不支持的值也算损坏：不能静默换成另一种语言。"""
    f = root / KB_FILE
    if not f.is_file():
        return {}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"{KB_FILE} 不是合法的 JSON：{e}。") from e
    if not isinstance(data, dict):
        raise ConfigError(f"{KB_FILE} 应当是一个 JSON 对象。")
    lang = data.get("language")
    if lang is not None and lang not in LANGUAGES:
        raise ConfigError(f"{KB_FILE} 的 language 是 {lang!r}，只支持 {'、'.join(LANGUAGES)}"
                          f"（unsupported language; use one of: {', '.join(LANGUAGES)}）。")
    return data


def kb_language(kb):
    """项目语言：.kb.json 的 language 字段。没有这个字段的旧项目一律按 zh-CN 处理，不因升级变成英文。"""
    return kb.get("language") or "zh-CN"


def L(lang, zh, en):
    """最小 i18n 助手：按项目语言挑选用户可见文案。en 用英文，其余（含缺省）用中文。"""
    return en if lang == "en" else zh


def skill_version():
    try:
        return (SKILL_DIR / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "?"


def utf8_stdout():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
