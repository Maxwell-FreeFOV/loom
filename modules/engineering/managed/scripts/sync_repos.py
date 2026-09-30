"""按 repos.yaml 管理关联的代码库。由 Loom 托管，请勿在项目中修改。

用法（<python> 见 .kb.json 的 python 字段）：
  <python> scripts/sync_repos.py          克隆缺失的代码库、注入对话导出 hook、显示各库状态
  <python> scripts/sync_repos.py --pull   另外对每个代码库执行 git pull --ff-only

注入的 hook 写在代码库的 .claude/settings.local.json 里（并加入该库的 .git/info/exclude，不会进入团队仓库），
这样在 repos/<名称>/ 里启动的 Claude 会话也会被导出到知识库的 40-Sessions/raw/。
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPOS_FILE = ROOT / "repos.yaml"
LOCAL_SETTINGS = ".claude/settings.local.json"


def load_repos():
    """解析 repos.yaml（只支持"repos: 下若干个扁平映射"这一种写法）。"""
    if not REPOS_FILE.exists():
        return []
    items, cur = [], None
    for raw in REPOS_FILE.read_text(encoding="utf-8").splitlines():
        line = re.sub(r"(^|\s)#.*$", "", raw).rstrip()
        s = line.strip()
        if not s or s == "repos:":
            continue
        if s.startswith("- "):
            cur = {}
            items.append(cur)
            s = s[2:].strip()
        k, sep, v = s.partition(":")
        if sep and cur is not None:
            cur[k.strip()] = v.strip().strip('"').strip("'")
    for r in items:
        r.setdefault("path", f"repos/{r.get('name', '')}")
    return [r for r in items if r.get("name")]


def git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    return r.returncode, r.stdout.decode("utf-8", "replace").strip(), r.stderr.decode("utf-8", "replace").strip()


def python_cmd():
    try:
        return json.loads((ROOT / ".kb.json").read_text(encoding="utf-8")).get("python", "python")
    except (OSError, json.JSONDecodeError):
        return "python"


def inject_hooks(repo):
    """在代码库的 settings.local.json 中加入指向知识库脚本的 hook；返回是否有改动。"""
    rel = Path(os.path.relpath(ROOT, repo)).as_posix()
    py = python_cmd()
    export = f'{py} "$CLAUDE_PROJECT_DIR/{rel}/scripts/export_session.py"'
    start = f'{py} "$CLAUDE_PROJECT_DIR/{rel}/scripts/kb.py" session-start'
    wanted = {
        "SessionStart": {"type": "command", "command": start, "timeout": 20},
        "Stop": {"type": "command", "command": export, "timeout": 30},
        "SessionEnd": {"type": "command", "command": export, "timeout": 30},
    }
    f = repo / LOCAL_SETTINGS
    try:
        settings = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except json.JSONDecodeError:
        print(f"  ⚠️ {f} 不是合法的 JSON，跳过 hook 注入")
        return False
    hooks = settings.setdefault("hooks", {})
    changed = False
    for event, hook in wanted.items():
        groups = hooks.setdefault(event, [])
        commands = [h.get("command") for g in groups for h in g.get("hooks", [])]
        if hook["command"] not in commands:
            groups.append({"hooks": [hook]})
            changed = True
    if changed:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    exclude = repo / ".git" / "info" / "exclude"
    if exclude.parent.is_dir():
        lines = exclude.read_text(encoding="utf-8").splitlines() if exclude.exists() else []
        if LOCAL_SETTINGS not in lines:
            exclude.write_text("\n".join([*lines, LOCAL_SETTINGS]) + "\n", encoding="utf-8")
    return changed


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    pull = "--pull" in sys.argv[1:]
    repos = load_repos()
    if not repos:
        print("repos.yaml 中还没有登记代码库。")
        return
    rows = []
    for r in repos:
        path = (ROOT / r["path"]).resolve()
        print(f"· {r['name']}（{r['path']}）")
        if not path.exists():
            if not r.get("remote"):
                print("  ⚠️ 本地不存在，且没有 remote，无法克隆")
                rows.append(f"| {r['name']} | {r['path']} | — | — | 缺失 | |")
                continue
            args = ["clone", r["remote"], str(path)] + (["-b", r["branch"]] if r.get("branch") else [])
            code, _, err = git(ROOT, *args)
            print("  已克隆" if code == 0 else f"  ❌ 克隆失败：{err}")
            if code != 0:
                continue
        elif pull:
            code, out, err = git(path, "pull", "--ff-only")
            print(f"  pull：{out.splitlines()[-1] if code == 0 and out else err}")
        if not (path / ".git").exists():
            print("  ⚠️ 不是 git 仓库")
        if inject_hooks(path):
            print("  已注入对话导出 hook（.claude/settings.local.json）")
        _, branch, _ = git(path, "rev-parse", "--abbrev-ref", "HEAD")
        _, head, _ = git(path, "log", "-1", "--format=%h %cd %s", "--date=short")
        _, dirty, _ = git(path, "status", "--porcelain")
        _, remote, _ = git(path, "remote", "get-url", "origin")
        state = f"{len(dirty.splitlines())} 处未提交改动" if dirty else "干净"
        rows.append(f"| {r['name']} | {r['path']} | {branch} | {head} | {state} | {remote or r.get('remote', '')} |")
    print("\n| 代码库 | 路径 | 分支 | 最新提交 | 工作区 | 远端 |\n|---|---|---|---|---|---|")
    print("\n".join(rows))


if __name__ == "__main__":
    main()
