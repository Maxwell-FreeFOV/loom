#!/usr/bin/env python3
"""把 loom skill 部署到本机：从源码仓库的某个版本导出 skills/loom，安装为全局 skill。

用法（在 Loom 源码仓库中运行）：
  py tools/deploy.py [--ref <tag 或 commit>] [--agents claude,codex,gemini] [--home <目录>]
                     [--skip-tests] [--allow-dirty] [--claude-hooks]

过程：
  1. 检查：源码仓库工作区干净（--allow-dirty 跳过）；部署 HEAD 时先运行 tests/smoke_test.py（--skip-tests 跳过）。
  2. 用 git archive 导出 <ref> 中的 skills/loom，放到 <home>/.agents/skills/loom，并写入部署标记 .loom-deploy.json。
     已存在但没有部署标记的目录不会被覆盖。
  3. 在各 agent 的 skills 目录下（默认是已安装的 claude、codex）建立指向它的链接：
     依次尝试符号链接、Windows 目录联接，都失败时复制。
  4. --claude-hooks：兜底方案。把 loom 的 hook 直接写进 <home>/.claude/settings.json，
     只在 Claude Code 没有把 skill 文件夹加载为插件（loom@skills-dir）时使用。

部署的是 git 中已提交的内容。开发中的改动不会影响已部署的版本；回滚时用 --ref 指定旧版本重新部署。
"""
import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILL_PATH = "skills/loom"
MARKER = ".loom-deploy.json"
AGENT_DIRS = {"claude": ".claude/skills", "codex": ".codex/skills", "gemini": ".gemini/skills"}
DEFAULT_AGENTS = ("claude", "codex")


class DeployError(Exception):
    pass


def git(*args):
    r = subprocess.run(["git", "-C", str(REPO), "-c", "core.quotepath=off", *args], capture_output=True)
    if r.returncode != 0:
        raise DeployError(f"git {' '.join(args)} 失败：{r.stderr.decode('utf-8', 'replace').strip()}")
    return r.stdout


def is_link(p):
    return os.path.islink(p) or (hasattr(os.path, "isjunction") and os.path.isjunction(p))


def remove_link(p):
    """只删除链接本身，绝不删除链接指向的内容。"""
    try:
        os.unlink(p)
    except OSError:
        os.rmdir(p)


def export(commit, dest):
    """把 commit 中的 skills/loom 导出到 dest（dest 不能已存在）。"""
    data = git("archive", "--format=tar", commit, SKILL_PATH)
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            if sys.version_info >= (3, 12):
                tar.extractall(tmp, filter="data")
            else:
                tar.extractall(tmp)
        shutil.move(str(Path(tmp) / SKILL_PATH), str(dest))


def install_canonical(home, commit, ref, version):
    canonical = home / ".agents" / "skills" / "loom"
    if canonical.exists() or is_link(canonical):
        if is_link(canonical) or not (canonical / MARKER).is_file():
            raise DeployError(f"{canonical} 已存在，但不是由 deploy.py 部署的（没有 {MARKER}），不覆盖。请先手工处理。")
    canonical.parent.mkdir(parents=True, exist_ok=True)
    staging = canonical.with_name(f"loom.new-{os.getpid()}")
    export(commit, staging)
    marker = {"version": version, "commit": commit, "ref": ref, "source": str(REPO),
              "deployed_at": datetime.now().strftime("%Y-%m-%d %H:%M")}
    (staging / MARKER).write_text(json.dumps(marker, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if canonical.exists():
        old = canonical.with_name(f"loom.old-{os.getpid()}")
        canonical.rename(old)
        staging.rename(canonical)
        shutil.rmtree(old)
    else:
        staging.rename(canonical)
    return canonical


def link_agent(home, agent, canonical):
    base = home / AGENT_DIRS[agent]
    if not base.parent.is_dir():
        return f"- {agent}：跳过（没有 {base.parent}，未安装该工具）"
    base.mkdir(parents=True, exist_ok=True)
    target = base / "loom"
    if is_link(target):
        if os.path.realpath(target) == os.path.realpath(canonical):
            return f"- {agent}：{target} 已链接到 {canonical}"
        remove_link(target)
    elif target.exists():
        if not (target / MARKER).is_file():
            return f"- {agent}：⚠️ 跳过，{target} 已存在且不是由 deploy.py 部署的"
        shutil.rmtree(target)  # 以前以复制方式部署的
    try:
        os.symlink(canonical, target, target_is_directory=True)
        return f"- {agent}：{target} → 符号链接"
    except OSError:
        pass
    if os.name == "nt":
        r = subprocess.run(["cmd", "/c", "mklink", "/J", str(target), str(canonical)], capture_output=True)
        if r.returncode == 0:
            return f"- {agent}：{target} → 目录联接"
    shutil.copytree(canonical, target)
    return f"- {agent}：{target} → 复制（以后每次部署都会重新复制）"


def install_claude_hooks(home, canonical):
    settings = home / ".claude" / "settings.json"
    data = json.loads(settings.read_text(encoding="utf-8")) if settings.is_file() else {}
    run = f'bash "{canonical.as_posix()}/scripts/run.sh"'
    wanted = {
        "SessionStart": {"type": "command", "command": f"{run} kb session-start", "timeout": 20},
        "SessionEnd": {"type": "command", "command": f"{run} export_session", "timeout": 30},
    }
    hooks = data.setdefault("hooks", {})
    added = []
    # 0.1.1 起不再用 Stop hook 导出（会让刚提交的 raw 文件马上又变脏），清理旧版写入的项
    stale = [g for g in hooks.get("Stop", []) if any(h.get("command") == f"{run} export_session" for h in g.get("hooks", []))]
    if stale:
        hooks["Stop"] = [g for g in hooks["Stop"] if g not in stale]
        if not hooks["Stop"]:
            del hooks["Stop"]
        added.append("移除 Stop")
    for event, hook in wanted.items():
        groups = hooks.setdefault(event, [])
        if hook["command"] not in [h.get("command") for g in groups for h in g.get("hooks", [])]:
            groups.append({"hooks": [hook]})
            added.append(event)
    if added:
        if settings.is_file():
            shutil.copy2(settings, settings.with_name("settings.json.bak-loom"))
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return f"- 已更新 {settings} 中的 hook：{', '.join(added)}（原文件备份为 settings.json.bak-loom）"
    return f"- {settings} 中已有 loom 的 hook"


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="部署 loom skill 到本机")
    parser.add_argument("--ref", default="HEAD", help="要部署的版本（tag 或 commit），默认 HEAD")
    parser.add_argument("--agents", help=f"要链接的工具，逗号分隔（可选 {', '.join(AGENT_DIRS)}；默认 {', '.join(DEFAULT_AGENTS)}）")
    parser.add_argument("--home", help="用户主目录（默认当前用户，测试时可指定临时目录）")
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--allow-dirty", action="store_true", help="允许源码仓库有未提交的改动（部署的仍是已提交的内容）")
    parser.add_argument("--claude-hooks", action="store_true", help="兜底：把 hook 写进 ~/.claude/settings.json")
    args = parser.parse_args()
    try:
        home = Path(args.home).resolve() if args.home else Path.home()
        agents = [a.strip() for a in (args.agents or ",".join(DEFAULT_AGENTS)).split(",") if a.strip()]
        unknown = [a for a in agents if a not in AGENT_DIRS]
        if unknown:
            raise DeployError(f"不认识的工具：{', '.join(unknown)}。可选：{', '.join(AGENT_DIRS)}")
        if not args.allow_dirty and git("status", "--porcelain").strip():
            raise DeployError("源码仓库有未提交的改动。请先提交（部署的是已提交的内容），或加 --allow-dirty。")
        commit = git("rev-parse", "--verify", f"{args.ref}^{{commit}}").decode().strip()
        version = git("show", f"{commit}:{SKILL_PATH}/VERSION").decode().strip()
        head = git("rev-parse", "HEAD").decode().strip()
        if not args.skip_tests:
            if commit != head:
                print(f"部署的不是 HEAD（{args.ref}），跳过测试。")
            else:
                r = subprocess.run([sys.executable, str(REPO / "tests" / "smoke_test.py")], capture_output=True)
                if r.returncode != 0:
                    raise DeployError("smoke test 未通过，停止部署：\n" + r.stdout.decode("utf-8", "replace")[-3000:])
                print("smoke test 通过。")
        canonical = install_canonical(home, commit, args.ref, version)
        lines = [f"# 已部署 loom {version}（{commit[:7]}）", "", f"- 本体：{canonical}"]
        lines += [link_agent(home, a, canonical) for a in agents]
        if args.claude_hooks:
            lines.append(install_claude_hooks(home, canonical))
        lines += ["", "新版本从下一次会话开始生效。在 Claude Code 中可以用 /plugin 查看 loom@skills-dir 是否已加载（它提供 hook）。"]
        print("\n".join(lines))
    except DeployError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
