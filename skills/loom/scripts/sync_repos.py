"""按知识库根目录下的 repos.yaml 管理关联的代码库（engineering 模块）。属于 Loom skill。

用法（在知识库根目录或其子目录中运行，也可以用 --root 指定根目录）：
  python sync_repos.py          克隆缺失的代码库，显示各库状态
  python sync_repos.py --pull   另外对每个代码库执行 git pull --ff-only

代码库是独立的 git 仓库，外层知识库不跟踪其内容。在 repos/<名称>/ 中启动的 Claude Code 会话，
由 Loom 的 hook 向上找到知识库并导出对话，不需要在代码库里做任何配置。
"""
import re
import subprocess
import sys

from kbroot import ConfigError, find_root, kb_language, L, load_kb, utf8_stdout


def load_repos(repos_file):
    """解析 repos.yaml（只支持"repos: 下若干个扁平映射"这一种写法）。"""
    if not repos_file.exists():
        return []
    items, cur = [], None
    for raw in repos_file.read_text(encoding="utf-8").splitlines():
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


def main():
    utf8_stdout()
    args = sys.argv[1:]
    root_arg = args[args.index("--root") + 1] if "--root" in args[:-1] else None
    root = find_root(root_arg)
    if root is None:
        print("Not in a Loom project (no .kb.json found in this directory or its parents).", file=sys.stderr)
        sys.exit(1)
    try:
        lang = kb_language(load_kb(root))
    except ConfigError:  # 只读操作：配置损坏时按旧项目的语言继续
        lang = "zh-CN"
    repos = load_repos(root / "repos.yaml")
    if not repos:
        print(L(lang, "repos.yaml 中还没有登记代码库。", "No repositories are registered in repos.yaml yet."))
        return
    rows = []
    for r in repos:
        path = (root / r["path"]).resolve()
        print(L(lang, f"· {r['name']}（{r['path']}）", f"· {r['name']} ({r['path']})"))
        if not path.exists():
            if not r.get("remote"):
                print(L(lang, "  ⚠️ 本地不存在，且没有 remote，无法克隆",
                        "  ⚠️ Missing locally and no remote is given; cannot clone"))
                rows.append(f"| {r['name']} | {r['path']} | — | — | {L(lang, '缺失', 'missing')} | |")
                continue
            # "--" 之后的都是位置参数：repos.yaml 里以 - 开头的 remote 不会被 git 当成选项
            clone = ["clone", *(["-b", r["branch"]] if r.get("branch") else []), "--", r["remote"], str(path)]
            code, _, err = git(root, *clone)
            print(L(lang, "  已克隆", "  Cloned") if code == 0
                  else L(lang, f"  ❌ 克隆失败：{err}", f"  ❌ Clone failed: {err}"))
            if code != 0:
                continue
        elif "--pull" in args:
            code, out, err = git(path, "pull", "--ff-only")
            print(f"  pull{L(lang, '：', ': ')}{out.splitlines()[-1] if code == 0 and out else err}")
        if not (path / ".git").exists():
            print(L(lang, "  ⚠️ 不是 git 仓库", "  ⚠️ Not a git repository"))
        _, branch, _ = git(path, "rev-parse", "--abbrev-ref", "HEAD")
        _, head, _ = git(path, "log", "-1", "--format=%h %cd %s", "--date=short")
        _, dirty, _ = git(path, "status", "--porcelain")
        _, remote, _ = git(path, "remote", "get-url", "origin")
        n = len(dirty.splitlines())
        state = L(lang, f"{n} 处未提交改动", f"{n} uncommitted change(s)") if dirty else L(lang, "干净", "clean")
        rows.append(f"| {r['name']} | {r['path']} | {branch} | {head} | {state} | {remote or r.get('remote', '')} |")
    print(L(lang, "\n| 代码库 | 路径 | 分支 | 最新提交 | 工作区 | 远端 |\n|---|---|---|---|---|---|",
            "\n| Repository | Path | Branch | Latest commit | Worktree | Remote |\n|---|---|---|---|---|---|"))
    print("\n".join(rows))


if __name__ == "__main__":
    main()
