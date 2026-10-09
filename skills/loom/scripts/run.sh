#!/usr/bin/env bash
# Loom 的 hook 启动器（仅 Claude Code 使用）：run.sh <脚本名，不含 .py> [参数...]
# 从 $CLAUDE_PROJECT_DIR（没有时用当前目录）向上查找 .kb.json；不在 Loom 项目中时立即退出，不启动 Python。
dir="${CLAUDE_PROJECT_DIR:-$PWD}"
command -v cygpath >/dev/null 2>&1 && dir="$(cygpath -u "$dir")"
while [ ! -f "$dir/.kb.json" ]; do
  parent="$(dirname "$dir")"
  [ "$parent" = "$dir" ] && exit 0
  dir="$parent"
done
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for py in py python3 python; do
  if command -v "$py" >/dev/null 2>&1; then
    # 需要 Python 3.12+：解析 "Python 3.x.y" 中的次版本号，避免把 3.10 之类当成可用
    ver="$("$py" --version 2>&1)"
    case "$ver" in
      "Python 3."*) minor="${ver#Python 3.}"; minor="${minor%%.*}" ;;
      *) continue ;;
    esac
    if [ "$minor" -ge 12 ] 2>/dev/null; then
      exec "$py" "$here/$1.py" "${@:2}"
    fi
  fi
done
echo "Loom：找不到 Python 3.12 或更高版本，跳过 $1" >&2
exit 0
