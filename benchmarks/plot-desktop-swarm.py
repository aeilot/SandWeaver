#!/usr/bin/env python3
"""Draw the characterization charts for the desktop swarm and VM baseline.

Reads the raw runs that desktop-swarm.py and osworld-replay.py wrote (the
layout of docs/results/raw/desktop-swarm-2026-11-19) and the summary JSON two
directories up, and writes seven PNG charts. Needs matplotlib, which the
scheduler does not depend on, and a CJK font (Hiragino Sans GB on macOS;
pass another with --font).

Usage: plot-desktop-swarm.py RAW_DIR OUT_DIR [--font PATH]
"""
import glob
import json
import math
import statistics as st
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Patch

import argparse

parser = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("raw", type=Path)
parser.add_argument("out", type=Path)
parser.add_argument("--font", default="/System/Library/Fonts/Hiragino Sans GB.ttc")
args = parser.parse_args()
R, OUT = args.raw, args.out
OUT.mkdir(parents=True, exist_ok=True)
font = args.font
font_manager.fontManager.addfont(font)
plt.rcParams.update({
    "font.family": font_manager.FontProperties(fname=font).get_name(),
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
    "grid.color": "#e1e0d9", "grid.linewidth": 0.8, "axes.edgecolor": "#c3c2b7",
    "axes.labelcolor": "#52514e", "xtick.color": "#898781", "ytick.color": "#898781",
    "axes.titlesize": 13, "axes.titleweight": "medium", "figure.dpi": 150,
    "axes.unicode_minus": False})
BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN, VIOLET, RED = (
    "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948")
GRAY = "#b4b2a9"
POL = {"always": ("一直运行", BLUE, "-"), "freeze": ("冻结", ORANGE, "--"),
       "freeze-reclaim": ("冻结+回收", AQUA, ":")}


def load(path):
    return json.loads(Path(path).read_text())


def samples(path):
    return [json.loads(l) for l in Path(path).read_text().splitlines()]


def save(fig, name):
    fig.tight_layout()
    fig.savefig(OUT / name, bbox_inches="tight")
    plt.close(fig)


# 1. Step-gap CDF -------------------------------------------------------------
gaps = sorted(s["recorded_gap_s"] for f in glob.glob(str(R / "phase1/*/result.json"))
              for s in load(f)["steps"] if s.get("recorded_gap_s"))
n = len(gaps)
fig, ax = plt.subplots(figsize=(7.5, 4))
ax.step(gaps, [(i + 1) / n for i in range(n)], where="post", color=BLUE, lw=2,
        label=f"9 条回放轨迹的步间隔（{n} 个）")
for q, v in ((0.1, 9.5), (0.5, 24.3), (0.9, 48.5)):
    ax.plot(v, q, "o", color=ORANGE, ms=7, mec="white", mew=1.5)
ax.plot([], [], "o", color=ORANGE, label="全部 353 条轨迹的 p10 / p50 / p90")
short = sum(g < 12 for g in gaps) / n
ax.axvspan(0, 12, color=YELLOW, alpha=0.12)
ax.axvline(12, color=YELLOW, lw=1.5)
ax.text(12.8, 0.08, f"< 12 s：余波 10 s + 最短冻结 2 s 放不下\n{short:.0%} 的步间隔无法冻结",
        color="#854F0B", fontsize=9)
ax.set_xscale("log")
ax.set_xticks([5, 10, 20, 50, 100, 200])
ax.get_xaxis().set_major_formatter(matplotlib.ticker.ScalarFormatter())
ax.set_xlim(5, 250)
ax.set_xlabel("步间隔（s，对数轴）")
ax.set_ylabel("累计比例")
ax.set_title("步间隔分布：大部分时间在等模型")
ax.legend(loc="lower right", frameon=False, fontsize=9)
save(fig, "1-gap-cdf.png")

# 2. Timeline of N=16 under the freeze policy ---------------------------------
res = load(R / "swarm/n16-freeze/result.json")
colors = {"boot": "#d3d1c7", "a": RED, "s": YELLOW, "f": BLUE, "w": "#888780"}
fig, ax = plt.subplots(figsize=(11, 6))
labels = []
end_all = max(i["end_ns"] for i in res["instances"]) / 1e9
for row, inst in enumerate(res["instances"]):
    y = len(res["instances"]) - 1 - row
    labels.append(f"{row:2d} {inst['domain'].replace('libreoffice_', '')}")
    rb = inst["replay_begin_ns"] / 1e9
    b0 = rb - (inst["boot_ns"] + inst.get("setup_ns", 0)) / 1e9
    bars = {k: [] for k in colors}
    bars["boot"].append((b0, rb - b0))
    steps = inst["steps"]
    for i, s in enumerate(steps):
        a = s["action_begin_ns"] / 1e9
        d = a + (s["exec_ns"] + s["shot_ns"]) / 1e9
        nxt = steps[i + 1]["action_begin_ns"] / 1e9 if i + 1 < len(steps) else inst["end_ns"] / 1e9
        bars["a"].append((a, d - a))
        if "frozen_at_ns" in s:
            fa, th = s["frozen_at_ns"] / 1e9, s["thawed_at_ns"] / 1e9
            bars["s"].append((d, fa - d))
            bars["f"].append((fa, th - fa))
            if nxt > th:
                bars["w"].append((th, nxt - th))
        else:
            bars["s"].append((d, nxt - d))
    for key, spans in bars.items():
        ax.broken_barh(spans, (y - 0.38, 0.76), facecolors=colors[key], lw=0)
    ax.broken_barh([(inst["end_ns"] / 1e9, end_all - inst["end_ns"] / 1e9)], (y - 0.12, 0.24),
                   facecolors="#ecebe6", lw=0)
ax.set_yticks(range(len(labels)))
ax.set_yticklabels(labels[::-1], fontsize=9)
ax.grid(axis="y", visible=False)
ax.set_xlim(0, end_all + 5)
ax.set_xlabel("自第一台启动起（s）")
ax.set_title("16 个容器桌面的时间线（冻结策略）：冻结只占每个实例约 44%")
ax.legend(handles=[Patch(color=colors["boot"], label="启动+初始化"),
                   Patch(color=colors["a"], label="动作+截图"),
                   Patch(color=colors["s"], label="余波（不冻结）"),
                   Patch(color=colors["f"], label="冻结"),
                   Patch(color="#ecebe6", label="回放结束、容器仍在")],
          loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=5, frameon=False, fontsize=9)
save(fig, "2-timeline-n16-freeze.png")

# 3. Memory per desktop: VM composition vs container --------------------------
fig, ax = plt.subplots(figsize=(7.5, 4.2))
vm = [("客户机页缓存", 1719, "#85B7EB"), ("客户机进程匿名内存", 1107, BLUE),
      ("客户机内核（slab 等）", 200, "#0C447C"), ("已触及的空闲页", 789, "#d3d1c7")]
pss, private = 0.83 * 1024, 0.73 * 1024
ct = [("容器私有内存", private, ORANGE), ("共享页摊到本桌面的部分", pss - private, "#F5C4B3")]
for x, parts in ((0, vm), (1, ct)):
    bottom = 0
    for name, v, c in parts:
        ax.bar(x, v, bottom=bottom, color=c, width=0.55, edgecolor="white", lw=1.5, label=name)
        if v > 300:
            ax.text(x, bottom + v / 2, f"{name}\n{v:.0f} MiB", ha="center", va="center",
                    fontsize=8.5, color="white" if c in (BLUE, "#0C447C", ORANGE) else "#2C2C2A")
        bottom += v
    ax.text(x, bottom + 60, f"{bottom / 1024:.2f} GiB", ha="center", fontsize=11)
ax.annotate("客户机内核（slab 等）200 MiB", (0.28, 2930), (0.45, 2600), fontsize=8.5,
            arrowprops=dict(arrowstyle="-", color="#888780", lw=0.8))
ax.annotate(f"共享页摊到本桌面的部分 {pss - private:.0f} MiB", (1.28, private + (pss - private) / 2),
            (1.05, 1500), fontsize=8.5, ha="center",
            arrowprops=dict(arrowstyle="-", color="#888780", lw=0.8))
ax.set_xticks([0, 1])
ax.set_xticklabels(["虚拟机（calc 第 13 步快照）", "容器桌面（N=16，PSS 中位数）"])
ax.set_ylabel("MiB")
ax.set_ylim(0, 4300)
ax.grid(axis="x", visible=False)
ax.set_title("每个桌面的内存构成")
save(fig, "3-memory-composition.png")

# 4. Execution latency CDF, N=16 ----------------------------------------------
fig, ax = plt.subplots(figsize=(7.5, 4))
for pol, (name, c, ls) in POL.items():
    r = load(R / f"swarm/n16-{pol}/result.json")
    e = sorted(s["exec_ns"] / 1e6 for i in r["instances"] for s in i["steps"]
               if s.get("kind") == "command")
    ax.plot(e, [(k + 1) / len(e) for k in range(len(e))], color=c, ls=ls, lw=2,
            label=f"{name}（p50 {e[len(e) // 2]:.0f} ms）")
ax.set_xlim(0, 2000)
ax.set_xlabel("执行一步动作的耗时（ms）")
ax.set_ylabel("累计比例")
ax.set_title("执行延迟分布（N=16）：回收让整条曲线右移")
ax.legend(frameon=False, loc="lower right")
save(fig, "4-exec-latency-cdf.png")

# 5. Reclaimed memory vs next-step latency -------------------------------------
fig, ax = plt.subplots(figsize=(7.5, 4.2))
xs, ys = [], []
for N, c in ((4, BLUE), (8, ORANGE), (16, AQUA)):
    r = load(R / f"swarm/n{N}-freeze-reclaim/result.json")
    pts = [((a["reclaim"]["before"] - a["reclaim"]["after"]) / 2**20, b["exec_ns"] / 1e6)
           for i in r["instances"] for a, b in zip(i["steps"], i["steps"][1:])
           if "reclaim" in a and b.get("kind") == "command"]
    ax.scatter(*zip(*pts), s=16, color=c, alpha=0.65, lw=0, label=f"N={N}")
    xs += [p[0] for p in pts]
    ys += [p[1] for p in pts]
mx, my = st.mean(xs), st.mean(ys)
corr = (sum((a - mx) * (b - my) for a, b in zip(xs, ys))
        / math.sqrt(sum((a - mx) ** 2 for a in xs) * sum((b - my) ** 2 for b in ys)))
base = []
for N in (4, 8, 16):
    r = load(R / f"swarm/n{N}-freeze/result.json")
    base += [s["exec_ns"] / 1e6 for i in r["instances"] for s in i["steps"]
             if s.get("kind") == "command"]
ax.axhline(st.median(base), color=GRAY, lw=1.5, ls="--")
ax.text(max(xs), st.median(base) + 25,
        "只冻结时执行耗时中位数", ha="right", fontsize=8.5, color="#5F5E5A")
ax.set_ylim(0, 2000)
ax.set_xlabel("这次回收释放的内存（MiB）")
ax.set_ylabel("解冻后下一步的执行耗时（ms）")
ax.set_title(f"回收量与下一步变慢：相关性弱（r = {corr:.2f}）")
ax.legend(frameon=False, loc="upper right", markerscale=2, bbox_to_anchor=(1, 0.95))
save(fig, "5-reclaim-vs-next-step.png")

# 6. Density: memory and CPU vs N -----------------------------------------------
fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.2))
Ns = [4, 8, 16]
used = [load(R / "../../desktop-swarm-summary.json")[i]["host_used_gib_mean"] for i in (0, 3, 6)]
slope = (used[2] - used[0]) / 12
icpt = used[0] - slope * 4
grid_n = list(range(0, 61))
host = 31.3
a1.plot(grid_n, [3.54 * k for k in grid_n], color=VIOLET, lw=2, label="虚拟机（每台 3.54 GiB）")
a1.plot(grid_n, [icpt + slope * k for k in grid_n], color=ORANGE, lw=2, ls="--",
        label=f"容器（拟合：{icpt:.1f} + {slope:.2f}×N GiB）")
a1.plot(Ns, used, "o", color=ORANGE, mec="white", mew=1.5, ms=8, label="容器实测")
a1.axhline(host, color=RED, lw=1.2)
a1.text(22, host + 0.8, "宿主内存 31.3 GiB", color=RED, fontsize=9)
for k, c in ((host / 3.54, VIOLET), ((host - icpt) / slope, ORANGE)):
    a1.axvline(k, color=c, lw=0.8, ls=":")
    a1.text(k + 0.5, 3, f"≈{k:.0f}", color=c, fontsize=10)
a1.set_ylim(0, 40)
a1.set_xlim(0, 60)
a1.set_xlabel("桌面数 N")
a1.set_ylabel("宿主已用内存（GiB）")
a1.set_title("内存：一台 32 GB 机器能放多少个")
a1.legend(frameon=False, fontsize=8.5, loc="upper left", bbox_to_anchor=(0.15, 0.78))
boot_cpu, steady_cpu = [], []
for N in Ns:
    r = load(R / f"swarm/n{N}-always/result.json")
    lo = max(i["replay_begin_ns"] for i in r["instances"])
    hi = max(i["end_ns"] for i in r["instances"])
    S = samples(R / f"swarm/n{N}-always/samples.jsonl")
    e = S[0]["t_ns"]
    def cores(win):
        return ((win[-1]["cpu"]["busy_ticks"] - win[0]["cpu"]["busy_ticks"])
                / (win[-1]["cpu"]["total_ticks"] - win[0]["cpu"]["total_ticks"]) * 4)
    boot_cpu.append(cores([s for s in S if s["t_ns"] - e <= lo]))
    steady_cpu.append(cores([s for s in S if lo <= s["t_ns"] - e <= hi]))
w = 0.35
a2.bar([i - w / 2 for i in range(3)], boot_cpu, w, color=GRAY, label="启动阶段（有实例在启动）")
a2.bar([i + w / 2 for i in range(3)], steady_cpu, w, color=BLUE, label="全部启动后（回放 + 空闲）")
for i in range(3):
    a2.text(i - w / 2, boot_cpu[i] + 0.05, f"{boot_cpu[i]:.2f}", ha="center", fontsize=9)
    a2.text(i + w / 2, steady_cpu[i] + 0.05, f"{steady_cpu[i]:.2f}\n({steady_cpu[i] / Ns[i]:.3f}/个)",
            ha="center", fontsize=8.5)
a2.axhline(4, color=RED, lw=1.2)
a2.text(-0.45, 3.85, "4 核上限", color=RED, fontsize=9, va="top")
a2.set_xticks(range(3))
a2.set_xticklabels([f"N={k}" for k in Ns])
a2.set_ylim(0, 4.3)
a2.grid(axis="x", visible=False)
a2.set_ylabel("宿主 CPU 均值（核）")
a2.set_title("CPU：启动贵，稳态便宜（一直运行策略）")
a2.legend(frameon=False, fontsize=8.5, loc="upper left", bbox_to_anchor=(0, 0.8))
save(fig, "6-density.png")

# 7. Pressure timeline at N=16 --------------------------------------------------
fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 5.5), sharex=True)
r = load(R / "swarm/n16-always/result.json")
lo = max(i["replay_begin_ns"] for i in r["instances"]) / 1e9
for pol, (name, c, ls) in POL.items():
    S = samples(R / f"swarm/n16-{pol}/samples.jsonl")
    e = S[0]["t_ns"]
    t, cpu, psi = [], [], []
    for a, b in zip(S[::5], S[5::5]):
        t.append((a["t_ns"] - e) / 1e9)
        cpu.append((b["cpu"]["busy_ticks"] - a["cpu"]["busy_ticks"])
                   / (b["cpu"]["total_ticks"] - a["cpu"]["total_ticks"]) * 4)
        psi.append(b["psi_cpu"]["some"]["avg10"])
    a1.plot(t, cpu, color=c, ls=ls, lw=1.4, label=name)
    a2.plot(t, psi, color=c, ls=ls, lw=1.4, label=name)
for ax in (a1, a2):
    ax.axvspan(0, lo, color=GRAY, alpha=0.18, lw=0)
    for i in r["instances"]:
        ax.axvline((i["replay_begin_ns"] - i["boot_ns"] - i.get("setup_ns", 0)) / 1e9,
                   color=GRAY, lw=0.5)
a1.text(5, 3.6, "启动阶段：每 20 s 启动一台（灰线）", fontsize=9, color="#5F5E5A")
a1.set_ylabel("宿主 CPU（核，5 s 均值）")
a1.set_ylim(0, 4)
a2.set_ylabel("CPU 压力 some avg10（%）")
a2.set_xlabel("自第一台启动起（s）")
a1.set_title("N=16 的 CPU 和 CPU 压力随时间变化：高峰都在启动阶段")
a1.legend(frameon=False, ncol=3, loc="upper right", fontsize=9)
save(fig, "7-pressure-timeline-n16.png")
print("done", sorted(p.name for p in OUT.iterdir()))
