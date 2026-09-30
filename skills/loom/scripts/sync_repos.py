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

from kbroot import find_root, utf8_stdout


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
        print("当前目录不在 Loom 项目中（向上找不到 .kb.json）。", file=sys.stderr)
        sys.exit(1)
    repos = load_repos(root / "repos.yaml")
    if not repos:
        print("repos.yaml 中还没有登记代码库。")
        return
    rows = []
    for r in repos:
        path = (root / r["path"]).resolve()
        print(f"· {r['name']}（{r['path']}）")
        if not path.exists():
            if not r.get("remote"):
                print("  ⚠️ 本地不存在，且没有 remote，无法克隆")
                rows.append(f"| {r['name']} | {r['path']} | — | — | 缺失 | |")
                continue
            clone = ["clone", r["remote"], str(path)] + (["-b", r["branch"]] if r.get("branch") else [])
            code, _, err = git(root, *clone)
            print("  已克隆" if code == 0 else f"  ❌ 克隆失败：{err}")
            if code != 0:
                continue
        elif "--pull" in args:
            code, out, err = git(path, "pull", "--ff-only")
            print(f"  pull：{out.splitlines()[-1] if code == 0 and out else err}")
        if not (path / ".git").exists():
            print("  ⚠️ 不是 git 仓库")
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
