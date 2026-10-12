"""在 DeepSeek Harness（dsh）里跑 Loom 的行为测试，并报告每一步有什么进了上下文。

用法（在 Loom 源码仓库中运行）：
  python tests/agent/run.py [--scenario s1,s3] [--repeat 3] [--inject] [--ref HEAD]
                            [--dsh-home ~/.dsh] [--out <目录>] [--timeout 900] [--keep]
  python tests/agent/run.py --list

  --scenario  要跑的场景，逗号分隔；缺省跑全部（见 scenarios.py）
  --repeat    每个场景跑几次。模型的输出不确定，看的是次数
  --inject    模拟 Claude Code 的会话开始注入（把 hot.md、提醒和通用规则放进第一步的上下文）
  --ref       被测的 Loom 版本（tag 或 commit），缺省 HEAD。测的是已提交的内容
  --dsh-home  一个配置过模型的 dsh home，从它复制模型设置和凭据文件；缺省 ~/.dsh
  --out       报告目录，缺省 tests/agent/.runs/<时间>/
  --keep      保留临时的运行环境（缺省跑完删除）

需要本机装有 dsh 和可用的模型凭据，会产生模型调用费用，所以不进 CI。夹具内容是虚构的；
运行环境在临时目录里，不动日常的 dsh home。模型在其中不受沙箱限制（danger-full-access），不要在夹具里放真实内容。
"""
import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ctxtrace  # noqa: E402
from rig import REPO, Rig, RigError, dsh_command  # noqa: E402
from scenarios import SCENARIOS, Check, commit_fixture  # noqa: E402


def run_once(rig, key, index, inject, timeout):
    sc = SCENARIOS[key]
    ws = sc["fixture"](rig, rig.ws / f"{key}{'-inj' if inject else ''}-{index}")
    head = "" if sc.get("no_commit") else commit_fixture(rig, ws, *sc.get("exclude", ()))
    cwd = ws / sc["cwd"] if sc.get("cwd") else ws
    injected = rig.inject(ws, inject and not sc.get("no_commit"))
    res = rig.run(cwd, sc["prompt"], timeout)
    events = ctxtrace.load(res["log"]) if res["log"] else []
    trace = ctxtrace.analyze(events, ws) if events else \
        {"baseline": {}, "steps": [], "actions": [], "totals": {}, "answer": "", "end": None}
    trace["answer"] = res["answer"] or trace["answer"]
    trace["injected"] = "--- 00-Hub/hot.md ---" if injected else ""
    check = Check()
    check.must("任务正常结束", res["exit"] == 0 and trace["end"] == "completed", f"exit={res['exit']} end={trace['end']} {res['stderr'][:200]}")
    if trace["actions"] or trace["answer"]:
        try:
            sc["check"](rig, ws, head, trace, check)
        except Exception as e:  # 检查本身出错不能丢掉这次运行的记录
            check.must("检查脚本运行出错", False, f"{type(e).__name__}: {e}")
    return {"scenario": key, "title": sc["title"], "inject": inject, "index": index, "prompt": sc["prompt"],
            "exit": res["exit"], "seconds": res["seconds"], "stderr": res["stderr"][:500], "injected_chars": injected,
            "steps": len(trace["steps"]), "peak_prompt_tokens": max((s["prompt_tokens"] for s in trace["steps"]), default=0),
            "output_tokens": sum(s["output_tokens"] for s in trace["steps"]),
            "checks": check.items, "trace": trace,
            # 留一份去掉流式分片的日志：以后改了分析器，可以不重跑模型就重新分析（ctxtrace.py 直接读它）
            "events": [e for e in events if e.get("type") != "assistant/chunk"]}


def report_run(r):
    label = f"{r['scenario']}（{r['title']}）{'，带注入' if r['inject'] else ''} 第 {r['index']} 次"
    out = [f"# {label}", "", f"- 提示：{r['prompt']}",
           f"- 用时 {r['seconds']} 秒，{r['steps']} 步，提示词最多 {r['peak_prompt_tokens']} token，输出共 {r['output_tokens']} token",
           *([f"- 模拟注入 {r['injected_chars']} 字符"] if r["inject"] else []), "", "## 检查", ""]
    mark = {"pass": "✅", "fail": "❌", "info": "·"}
    for c in r["checks"]:
        value = "" if c["status"] != "info" else f"：{c['value']}"
        detail = f"（{c['detail']}）" if c["detail"] and c["status"] != "pass" else ""
        out.append(f"- {mark[c['status']]} {c['name']}{value}{detail}")
    out += ["", ctxtrace.render(r["trace"]), "## 最后的回答", "", r["trace"]["answer"] or "（没有）", ""]
    return "\n".join(out)


def summarize(results, meta):
    out = ["# Loom 行为测试汇总", "",
           f"- Loom：{meta['loom']}（{meta['ref']}）；dsh：{meta['dsh']}；模型路由：见 dsh home 的默认设置",
           f"- 时间：{meta['time']}；共 {len(results)} 次运行", "",
           "硬性检查写成：通过次数/运行次数。标 · 的是观察项，写的是出现的次数。", ""]
    groups = {}
    for r in results:
        groups.setdefault((r["scenario"], r["inject"]), []).append(r)
    for (key, inject), runs in groups.items():
        n = len(runs)
        out += [f"## {key}：{runs[0]['title']}{'（带注入）' if inject else ''}", "",
                f"{n} 次运行；平均 {sum(r['seconds'] for r in runs) / n:.0f} 秒、{sum(r['steps'] for r in runs) / n:.1f} 步；"
                f"提示词峰值平均 {sum(r['peak_prompt_tokens'] for r in runs) / n:.0f} token", ""]
        names = []
        for r in runs:
            names += [c["name"] for c in r["checks"] if c["name"] not in names]
        for name in names:
            items = [c for r in runs for c in r["checks"] if c["name"] == name]
            if items[0]["status"] == "info":
                values = [c["value"] for c in items]
                shown = f"{sum(1 for v in values if v is True)}/{len(values)}" if all(isinstance(v, bool) for v in values) \
                    else "；".join(str(v) for v in values)
                out.append(f"- · {name}：{shown}")
            else:
                ok = sum(1 for c in items if c["status"] == "pass")
                fails = "；".join(c["detail"] for c in items if c["status"] == "fail" and c["detail"])[:300]
                out.append(f"- {'✅' if ok == len(items) else '❌'} {name}：{ok}/{len(items)}" + (f"（{fails}）" if fails else ""))
        totals = {}
        for r in runs:
            for k, v in r["trace"]["totals"].items():
                totals[k] = totals.get(k, 0) + v
        if totals:
            out += ["", "Loom 带进上下文的内容（平均字符数）：" + "；".join(f"{k} {v / n:.0f}" for k, v in sorted(totals.items(), key=lambda x: -x[1]))]
        out.append("")
    return "\n".join(out)


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description="在 dsh 里跑 Loom 的行为测试")
    p.add_argument("--scenario")
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--inject", action="store_true")
    p.add_argument("--ref", default="HEAD")
    p.add_argument("--dsh-home")
    p.add_argument("--out")
    p.add_argument("--timeout", type=int, default=900)
    p.add_argument("--keep", action="store_true")
    p.add_argument("--list", action="store_true")
    args = p.parse_args()
    if args.list:
        for k, s in SCENARIOS.items():
            print(f"{k:12} {s['title']}：{s['prompt'][:60]}")
        return
    keys = [k.strip() for k in (args.scenario or ",".join(SCENARIOS)).split(",") if k.strip()]
    unknown = [k for k in keys if k not in SCENARIOS]
    if unknown:
        sys.exit(f"没有这些场景：{', '.join(unknown)}。可用的：{', '.join(SCENARIOS)}")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out) if args.out else Path(__file__).resolve().parent / ".runs" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    # 以前的运行如果被强行终止，凭据文件的副本可能还留在临时目录里：清掉三小时以前的（更新的可能属于正在跑的另一次）
    for stale in Path(tempfile.gettempdir()).glob("loom-agent-test-*/home/.credentials.yaml"):
        if time.time() - stale.stat().st_mtime > 3 * 3600:
            stale.unlink(missing_ok=True)
    root = Path(tempfile.mkdtemp(prefix="loom-agent-test-"))
    results = []
    try:
        rig = Rig(root, args.ref, args.dsh_home).build()
        import subprocess
        dsh_version = subprocess.run([*dsh_command(), "--version"], capture_output=True).stdout.decode().strip()
        commit = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", args.ref], capture_output=True).stdout.decode().strip()
        meta = {"loom": rig.version, "ref": commit, "dsh": dsh_version, "time": time.strftime("%Y-%m-%d %H:%M")}
        print(f"被测的 Loom {meta['loom']}（{commit}），dsh {dsh_version}，运行环境 {root}")
        with rig.credentials():
            for key in keys:
                for i in range(1, args.repeat + 1):
                    r = run_once(rig, key, i, args.inject, args.timeout)
                    results.append(r)
                    name = f"{key}{'-inj' if args.inject else ''}-{i}"
                    (out_dir / f"{name}.md").write_text(report_run(r), encoding="utf-8")
                    (out_dir / f"{name}.session.jsonl").write_text(
                        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in r.pop("events")), encoding="utf-8")
                    hard = [c for c in r["checks"] if c["status"] != "info"]
                    failed = [c["name"] for c in hard if c["status"] == "fail"]
                    print(f"  {name}: {r['seconds']} 秒，{r['steps']} 步，硬性检查 {len(hard) - len(failed)}/{len(hard)}"
                          + (f"，未通过：{'；'.join(failed)}" if failed else ""))
        (out_dir / "summary.md").write_text(summarize(results, meta), encoding="utf-8")
        slim = [{k: v for k, v in r.items() if k != "trace"} | {"totals": r["trace"]["totals"], "baseline": r["trace"]["baseline"]}
                for r in results]
        (out_dir / "results.json").write_text(json.dumps({"meta": meta, "runs": slim}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"报告：{out_dir / 'summary.md'}")
    except RigError as e:
        sys.exit(f"❌ {e}")
    finally:
        if args.keep:
            print(f"运行环境保留在 {root}（凭据文件已删除）")
        else:
            shutil.rmtree(root, ignore_errors=True)
    if any(c["status"] == "fail" for r in results for c in r["checks"]):
        sys.exit(1)


if __name__ == "__main__":
    main()
