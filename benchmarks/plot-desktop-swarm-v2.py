#!/usr/bin/env python3
"""Draw the per-process and thaw-cost charts for the second desktop swarm run.

Reads the raw runs of docs/results/raw/desktop-swarm-v2-2026-11-20 (written by
desktop-swarm.py with --process-interval and osworld-replay.py with
--guest-procs) and writes four PNG charts, numbered after the seven of
plot-desktop-swarm.py. Uses summarize-procs.py and summarize-thaw-cost.py for
the numbers. Needs matplotlib and a CJK font (Hiragino Sans GB on macOS; pass
another with --font).

Usage: plot-desktop-swarm-v2.py RAW_DIR OUT_DIR [--font PATH]
"""
import argparse
import collections
import importlib.util
import json
from pathlib import Path
import re
import statistics as st

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

HERE = Path(__file__).resolve().parent


def module(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


procs = module("summarize-procs")
thaw = module("summarize-thaw-cost")

parser = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("raw", type=Path)
parser.add_argument("out", type=Path)
parser.add_argument("--font", default="/System/Library/Fonts/Hiragino Sans GB.ttc")
args = parser.parse_args()
R, OUT = args.raw, args.out
OUT.mkdir(parents=True, exist_ok=True)
font_manager.fontManager.addfont(args.font)
plt.rcParams.update({
    "font.family": font_manager.FontProperties(fname=args.font).get_name(),
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
    "grid.color": "#e1e0d9", "grid.linewidth": 0.8, "axes.edgecolor": "#c3c2b7",
    "axes.labelcolor": "#52514e", "xtick.color": "#898781", "ytick.color": "#898781",
    "axes.titlesize": 13, "axes.titleweight": "medium", "figure.dpi": 150,
    "axes.unicode_minus": False})
BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN, VIOLET, RED = (
    "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948")
GRAY = "#b4b2a9"
POL = {"always": ("一直运行", BLUE), "freeze": ("冻结", ORANGE),
       "freeze-reclaim": ("冻结+回收", AQUA)}
# Ubuntu background services that check for or apply updates.
UPDATERS = {"packagekitd", "snap-store", "store", "cnf-update-db", "apt-check", "snapd",
            "fwupd", "gnome-software", "update-notifier", "unattended-upgr", "mandb",
            "decompose", "http", "gpgv", "fstrim"}
# Colour per process group; everything else is grey.
PROC_COLORS = {"gnome-shell": BLUE, "Xvnc": VIOLET, "Xorg": VIOLET, "python": ORANGE,
               "chrome": AQUA, "soffice.bin": GREEN, "code": MAGENTA, "updaters": RED,
               "sw-procs": YELLOW}
PROC_LABELS = {"python": "OSWorld 服务（python）", "updaters": "更新服务",
               "sw-procs": "采样脚本", "Xvnc": "X 服务器", "Xorg": "X 服务器"}


def save(fig, name):
    fig.tight_layout()
    fig.savefig(OUT / name, bbox_inches="tight")
    plt.close(fig)


def bucket(name):
    return "updaters" if name in UPDATERS else name


# 8. CPU by process and phase: containers (N=16 always) vs VMs ----------------
def phase_cpu(results, top=40):
    """{phase: Counter(group -> cores per instance)} pooled over runs, weighted by seconds."""
    cpu = collections.defaultdict(collections.Counter)
    secs = collections.Counter()
    for res in results:
        for phase, row in res["phases"].items():
            secs[phase] += row["seconds"]
            for name, cores, _, _ in row["top"]:
                cpu[phase][bucket(name)] += cores * row["seconds"]
            other = row["cores"] * row["seconds"] - sum(c * row["seconds"] for _, c, _, _ in row["top"])
            cpu[phase]["其他"] += max(other, 0)
    return {p: {k: v / secs[p] for k, v in c.items()} for p, c in cpu.items()}, secs


swarm16 = procs.summarize(R / "swarm/n16-always", 40)
vms = [procs.summarize(d, 60) for d in sorted((R / "phase1").iterdir()) if d.is_dir()]
cont, _ = phase_cpu([swarm16])
vm, _ = phase_cpu(vms)
phases = [("action", "动作+截图"), ("wait 0-10s", "余波（动作后 10 s）"),
          ("wait >10s", "之后的等待"), ("idle tail", "回放后空闲")]
groups = ["gnome-shell", "Xvnc", "Xorg", "python", "chrome", "soffice.bin", "code",
          "updaters", "sw-procs"]
fig, axes = plt.subplots(1, 2, figsize=(12, 4.6), sharex=True)
for ax, data, title in ((axes[0], cont, "容器桌面（N=16，一直运行）"),
                        (axes[1], vm, "虚拟机（9 台，客户机内）")):
    rows = [(lab, data[p]) for p, lab in phases if p in data]
    for y, (lab, c) in enumerate(rows[::-1]):
        left = 0
        for g in groups + ["rest"]:
            v = c.get(g, 0) if g != "rest" else sum(v for k, v in c.items() if k not in groups)
            if v <= 0:
                continue
            ax.barh(y, v, left=left, color=PROC_COLORS.get(g, GRAY), height=0.62,
                    edgecolor="white", lw=0.6)
            left += v
        ax.text(left + 0.01, y, f"{left:.2f}", va="center", fontsize=9, color="#52514e")
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([lab for lab, _ in rows[::-1]])
    ax.grid(axis="y", visible=False)
    ax.set_title(title)
    ax.set_xlabel("每个实例的 CPU（核）")
seen = []
for g in groups + ["rest"]:
    lab = PROC_LABELS.get(g, g) if g != "rest" else "其他"
    if lab in [s[0] for s in seen]:
        continue
    seen.append((lab, PROC_COLORS.get(g, GRAY)))
fig.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=c) for _, c in seen],
           labels=[l for l, _ in seen], loc="lower center", ncol=len(seen), frameon=False,
           fontsize=9, bbox_to_anchor=(0.5, -0.06))
fig.suptitle("CPU 花在哪些进程上：虚拟机余波中近一半是更新服务", fontsize=13)
save(fig, "8-cpu-by-process.png")

# 9. Cost of the first action after a thaw ------------------------------------
runs = {}
for d in sorted((R / "swarm").iterdir()):
    if d.is_dir():
        res = thaw.summarize(d)
        runs[(res["n"], res["policy"])] = res
metrics = [("majflt_p50", "主缺页（p50）", "次"), ("read_mib_mean", "从磁盘读回（均值）", "MiB"),
           ("io_stall_ms_mean", "IO 等待（均值）", "ms"), ("exec_ms_p50", "执行耗时（p50）", "ms")]
fig, axes = plt.subplots(1, 4, figsize=(13, 3.8))
ns = [4, 8, 16]
for ax, (key, title, unit) in zip(axes, metrics):
    width = 0.27
    for k, pol in enumerate(["always", "freeze", "freeze-reclaim"]):
        vals = []
        for n in ns:
            g = runs[(n, pol)]["groups"]
            vals.append((g.get("after_thaw") or g["other"])[key])
        xs = [i + (k - 1) * width for i in range(len(ns))]
        ax.bar(xs, vals, width, color=POL[pol][1], label=POL[pol][0])
    ax.set_xticks(range(len(ns)))
    ax.set_xticklabels([f"N={n}" for n in ns])
    ax.set_title(title, fontsize=11)
    ax.set_ylabel(unit)
    ax.grid(axis="x", visible=False)
fig.legend(*axes[0].get_legend_handles_labels(), loc="lower center", ncol=3, frameon=False,
           fontsize=9, bbox_to_anchor=(0.5, -0.07))
fig.suptitle("解冻后第一步：回收清掉的页要从磁盘读回来（一直运行策略取全部步骤）", fontsize=13)
save(fig, "9-thaw-cost.png")

# 10. IO stall vs execution time of the step after a thaw ----------------------
fig, ax = plt.subplots(figsize=(7.5, 4.6))
for pol, marker in (("freeze", "o"), ("freeze-reclaim", "o")):
    xs, ys = [], []
    for n in ns:
        _, rows = thaw.steps(R / f"swarm/n{n}-{pol}")
        for r in rows:
            if r["after_thaw"]:
                xs.append(r["io_stall_ms"])
                ys.append(r["exec_ms"])
    ax.scatter(xs, ys, s=14, alpha=0.55, color=POL[pol][1], label=f"{POL[pol][0]}（{len(xs)} 步）",
               edgecolors="none")
ax.set_xscale("symlog", linthresh=10)
ax.set_xlabel("这一步期间容器的 IO 等待（ms，对数轴）")
ax.set_ylabel("执行耗时（ms）")
ax.set_ylim(0, 2500)
corr = {n: runs[(n, "freeze-reclaim")]["corr_exec_after_thaw"]["io_stall_ms"] for n in ns}
ax.set_title("解冻后第一步：回收之后多出 IO 等待，慢步多在右侧")
ax.text(0.02, 0.97, "冻结+回收下的相关系数 r：" + "，".join(f"N={n} {corr[n]}" for n in ns),
        transform=ax.transAxes, va="top", fontsize=9, color="#52514e")
ax.legend(frameon=False, fontsize=9, loc="upper right")
save(fig, "10-iostall-vs-exec.png")

# 11. Guest CPU per minute in the VMs, updaters vs the rest --------------------
def guest_minutes(run):
    lines = procs.read_text(run / "guest-procs.jsonl").splitlines()
    header = json.loads(lines[0])
    hz = header["clk_tck"]
    last, t0 = {}, None
    bins = collections.defaultdict(collections.Counter)
    for line in lines[1:]:
        tick = json.loads(line)
        t0 = t0 or tick["wall_ns"]
        b = int((tick["wall_ns"] - t0) / 60e9)
        for pid, row in tick["procs"].items():
            key = (pid, row[6])
            if key in last:
                name = procs.group(row[0])
                kind = ("updaters" if name in UPDATERS else
                        "sw-procs" if name == "sw-procs" else "rest")
                bins[b][kind] += (row[1] + row[2] - last[key][1] - last[key][2]) / hz
            last[key] = row
    return [{k: v / 60 for k, v in bins[b].items()} for b in range(max(bins) + 1)]


per_vm = {d.name: guest_minutes(d) for d in sorted((R / "phase1").iterdir()) if d.is_dir()}
length = max(len(v) for v in per_vm.values())
fig, ax = plt.subplots(figsize=(9, 4.4))
bottom = [0.0] * length
for kind, label, color in (("updaters", "更新服务", RED), ("rest", "其他进程", BLUE),
                           ("sw-procs", "采样脚本", YELLOW)):
    vals = []
    for m in range(length):
        xs = [v[m].get(kind, 0) for v in per_vm.values() if m < len(v)]
        vals.append(st.fmean(xs) if xs else 0)
    ax.bar(range(length), vals, bottom=bottom, color=color, label=label, width=0.75)
    bottom = [b + v for b, v in zip(bottom, vals)]
counts = [sum(m < len(v) for v in per_vm.values()) for m in range(length)]
for m, c in enumerate(counts):
    if c < len(per_vm):
        ax.text(m, bottom[m] + 0.01, f"{c} 台", ha="center", fontsize=8, color="#898781")
ax.set_xticks(range(length))
ax.set_xlabel("客户机采样开始后第几分钟（含回放与 120 s 空闲尾段）")
ax.set_ylabel("客户机 CPU（核，9 台平均）")
ax.set_title("虚拟机客户机 CPU：第一分钟一半是更新服务")
ax.grid(axis="x", visible=False)
ax.legend(frameon=False, fontsize=9)
save(fig, "11-vm-guest-cpu-minutes.png")
print("wrote", sorted(p.name for p in OUT.glob("*.png")))
