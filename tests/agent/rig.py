"""隔离的 dsh 运行环境：让 DeepSeek Harness 只看到被测的 Loom 和一个虚构的夹具项目。

目录布局（root 是一个临时目录，用完可以整个删掉）：
  root/home/        DSH_HOME：profile、设置、会话日志
  root/userhome/    USERPROFILE / HOME：被测的 Loom 部署在 userhome/.agents/skills/loom
  root/ws/          夹具项目
  root/loom-test.patch.yml  把会话日志改成一行一个事件的普通 JSONL

为什么连 USERPROFILE 都换掉：模型运行脚本时常常自己拼出 ~/.agents/skills/loom 这个路径，不换的话执行的是
本机真正部署的那一份，而不是被测的提交。换掉之后 git 读不到全局身份，所以另外用环境变量给一个测试身份。

模型路由和密钥来自一个已有的 dsh home（默认 ~/.dsh）：settings.yaml 原样复制；.credentials.yaml 只在运行期间
复制进来，不读取、不打印，运行结束就删除（见 credentials()）。
"""
import contextlib
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PATCH = """# Loom 测试用：会话日志存成一行一个事件的普通 JSONL。
# patch 会整体替换这一行的 config，所以 root 等原有的键要一并写上。
- id: session-persistence-jsonl
  config:
    root: !!js dshHomePath('sessions')
    packChunks: false
    compression: none
    preparedSessionCacheSize: 5
    writeBatchMaxDelayMs: 200
"""
GIT_ID = {"GIT_AUTHOR_NAME": "loom-test", "GIT_AUTHOR_EMAIL": "loom-test@example.com",
          "GIT_COMMITTER_NAME": "loom-test", "GIT_COMMITTER_EMAIL": "loom-test@example.com"}


class RigError(Exception):
    pass


def dsh_command():
    """dsh 的启动命令。Windows 上 npm 装的是 .cmd 包装，经过 cmd.exe 时中文和引号容易出问题，所以直接用 node 跑入口文件。
    LOOM_TEST_DSH 可以指定别的可执行文件（例如虚拟环境里 SDK 自带的 dsh）。"""
    override = os.environ.get("LOOM_TEST_DSH")
    if override:
        return [override]
    found = shutil.which("dsh")
    if not found:
        raise RigError("找不到 dsh。先安装 @deepseek-ai/dsh，或用环境变量 LOOM_TEST_DSH 指定可执行文件。")
    entry = Path(found).parent / "node_modules" / "@deepseek-ai" / "dsh" / "lib" / "bin.js"
    return ["node", str(entry)] if entry.is_file() and shutil.which("node") else [found]


class Rig:
    def __init__(self, root, ref="HEAD", source_home=None):
        self.root = Path(root).resolve()
        self.ref = ref
        self.source_home = Path(source_home or os.environ.get("LOOM_TEST_DSH_HOME") or Path.home() / ".dsh")
        self.home, self.userhome, self.ws = self.root / "home", self.root / "userhome", self.root / "ws"
        self.patch = self.root / "loom-test.patch.yml"
        self.loom = self.userhome / ".agents" / "skills" / "loom"

    def build(self):
        for d in (self.home, self.userhome, self.ws):
            d.mkdir(parents=True, exist_ok=True)
        r = subprocess.run([sys.executable, str(REPO / "tools" / "deploy.py"), "--home", str(self.userhome),
                            "--agents", "claude", "--skip-tests", "--allow-dirty", "--ref", self.ref],
                           capture_output=True)
        if r.returncode != 0 or not (self.loom / "SKILL.md").is_file():
            raise RigError("部署被测的 Loom 失败：\n" + (r.stdout + r.stderr).decode("utf-8", "replace")[-1500:])
        settings = self.source_home / "settings.yaml"
        if not settings.is_file():
            raise RigError(f"{settings} 不存在：需要一个配置过模型的 dsh home（用 --dsh-home 或 LOOM_TEST_DSH_HOME 指定）。")
        shutil.copyfile(settings, self.home / "settings.yaml")
        self.patch.write_text(PATCH, encoding="utf-8")
        return self

    @property
    def version(self):
        return (self.loom / "VERSION").read_text(encoding="utf-8").strip()

    def env(self):
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("CLAUDE", "DSH_"))}
        env.update(GIT_ID, DSH_HOME=str(self.home), DSH_AGENTS_HOME=str(self.userhome / ".agents"),
                   DSH_PERMISSION_MODE="danger-full-access", DSH_TELEMETRY_MODE="DISABLED",
                   USERPROFILE=str(self.userhome), HOME=str(self.userhome), PYTHONUTF8="1")
        return env

    @contextlib.contextmanager
    def credentials(self):
        """运行期间把凭据文件原样复制进测试 home，结束后删除。内容不读取、不打印。"""
        src, dst = self.source_home / ".credentials.yaml", self.home / ".credentials.yaml"
        if src.is_file():
            shutil.copyfile(src, dst)
        try:
            yield
        finally:
            dst.unlink(missing_ok=True)

    def script(self, cwd, name, *args, stdin=b""):
        """运行被测 Loom 的脚本，返回（退出码，输出）。"""
        r = subprocess.run([sys.executable, str(self.loom / "scripts" / name), *args], cwd=cwd, env=self.env(),
                           capture_output=True, input=stdin)
        return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace").replace("\r\n", "\n")

    def git(self, cwd, *args):
        r = subprocess.run(["git", "-C", str(cwd), "-c", "core.quotepath=off", *args], env=self.env(), capture_output=True)
        return r.stdout.decode("utf-8", "replace").replace("\r\n", "\n").strip()

    def inject(self, workspace, on=True):
        """模拟 Claude Code 的会话开始注入：把两条 hook 命令的输出写进测试 home 的 AGENTS.md（dsh 的用户全局指令）。
        静态的：会话中途 hot.md 变了不会重新注入。"""
        target = self.home / "AGENTS.md"
        if not on:
            target.unlink(missing_ok=True)
            return 0
        text = self.script(workspace, "kb.py", "session-start")[1] + "\n" + self.script(workspace, "kb.py", "rules")[1]
        target.write_text(text, encoding="utf-8")
        return len(text)

    def run(self, cwd, prompt, timeout=900):
        """在 cwd 里跑一个一次性任务。返回 exit、seconds、answer、stderr、log（这次会话的日志路径）。"""
        before = set(self.home.glob("sessions/*/*/session.jsonl"))
        start = time.time()
        try:
            r = subprocess.run([*dsh_command(), "--profile", "headless", "--patch", str(self.patch), prompt],
                               cwd=cwd, env=self.env(), capture_output=True, timeout=timeout)
            code, out, err = r.returncode, r.stdout, r.stderr
        except subprocess.TimeoutExpired as e:
            code, out, err = -1, e.stdout or b"", (e.stderr or b"") + f"\n超时（{timeout} 秒）".encode("utf-8")
        logs = sorted(set(self.home.glob("sessions/*/*/session.jsonl")) - before, key=lambda p: p.stat().st_mtime)
        err_text = "\n".join(line for line in err.decode("utf-8", "replace").splitlines()
                             if "ExperimentalWarning" not in line and "trace-warnings" not in line)
        return {"exit": code, "seconds": round(time.time() - start, 1), "answer": out.decode("utf-8", "replace").strip(),
                "stderr": err_text.strip(), "log": logs[-1] if logs else None}
