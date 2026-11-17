#!/usr/bin/env python3
"""Classify OSWorld tasks by whether a non-GUI path can reach the evaluated end state.

For each task with a trajectory under TRAJ_DIR, read its config from the OSWorld
checkout and classify it from the evaluator (what end state is checked) plus
manual decisions recorded below. Tiers:

  no_gui     the checked end state is a file, config or system setting that a
             documented library, CLI, config edit or app scripting API can produce
  browser    needs web content or browser state; reachable through a browser
             protocol (DevTools) or HTTP, without a desktop
  session    needs a running desktop session or open windows, not visual perception
  gui        the evaluator reads live UI state, or the task asks for a visual
             artifact of the GUI
  infeasible OSWorld marks the task as impossible; excluded from shares

'perception' marks no_gui tasks whose non-GUI path still has to interpret image
or video content. The classification says a path exists, not that an agent finds
it or that it reproduces GUI output exactly; OSWorld tasks are also biased toward
end states a script can check. Manual decisions are the author's judgement.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re

BROWSER_RESULTS = {"active_url_from_accessTree", "active_tab_html_parse", "active_tab_url_parse",
                   "active_tab_url_and_body_text", "active_tab_info", "open_tabs_info", "bookmarks",
                   "history", "url_path_parse", "url_dashPart", "page_info", "cookie_data",
                   "new_startup_page"}
GUI_RESULTS = {"accessibility_tree", "vlc_playing_info"}
# Manual decisions after reading each flagged task (task id prefix -> tier).
MANUAL = {
    **dict.fromkeys(["15c3b339", "7b1e1ff9", "f5c13cdd", "02ce9a50", "ef9d12bd", "7aeae0e2"], "gui"),
    **dict.fromkeys(["716a6079", "48c46dc7", "8d9fd4e2"], "session"),
    **dict.fromkeys(["da52d699", "5990457f", "0e5303d4", "deec51c9", "d1acdb87", "e1e75309", "788b3701",
                     "f8369178", "c7c1e4c3", "26660ad1", "74d5859f", "da922383", "67890eb6", "3e3fc409",
                     "6f4073b8", "dd60633f", "236833a3", "7ff48d5b", "7e287123", "68a25bd4", "873cafdd",
                     "a74b607e", "e135df7c", "a82b78bb", "36037439", "f8cfa149", "58565672", "7a5a7856",
                     "06fe7178", "121ba48f"], "browser"),
    # VLC launched from the CLI; Chrome settings, history, bookmarks and cookies live in profile files.
    **dict.fromkeys(["bba3381f", "59f21cfb", "3299584d", "44ee5668", "2ad9387a", "7b6c7e24", "030eeff7",
                     "93eabf48", "9656a811", "4c26e3f3"], "no_gui"),
}
PERCEPTION = {"d68204bf", "09a37c51", "2a729ded", "e8172110", "ce2b64a2", "82e3c869", "869de13e",
              "4c26e3f3", "7a4deb26", "47f7c0ce"}


def as_list(value):
    return value if isinstance(value, list) else [value]


def classify(config):
    evaluator = config.get("evaluator", {})
    funcs = as_list(evaluator.get("func"))
    results = {r.get("type") for r in as_list(evaluator.get("result")) if isinstance(r, dict)}
    if "infeasible" in funcs:
        return "infeasible", funcs, results
    if results & GUI_RESULTS:
        return "gui", funcs, results
    if results & BROWSER_RESULTS:
        return "browser", funcs, results
    return "no_gui", funcs, results


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("traj_dir", type=Path, help="Directory searched for traj.jsonl")
    parser.add_argument("--osworld", type=Path, default=Path.home() / "agent-experiments/OSWorld")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    examples = args.osworld / "evaluation_examples/examples"
    tasks = []
    for traj in sorted(args.traj_dir.rglob("traj.jsonl")):
        domain, task_id = traj.parent.parent.name, traj.parent.name
        path = examples / domain / f"{task_id}.json"
        if not path.exists():
            continue
        tier, funcs, results = classify(json.loads(path.read_text()))
        if tier != "infeasible":
            tier = MANUAL.get(task_id[:8], tier)
        tasks.append({"domain": domain, "id": task_id, "tier": tier,
                      "perception": task_id[:8] in PERCEPTION,
                      "evaluator": funcs, "result_types": sorted(t for t in results if t)})
    counts = Counter(t["tier"] for t in tasks)
    feasible = sum(v for k, v in counts.items() if k != "infeasible")
    summary = {"tasks": len(tasks), "infeasible": counts["infeasible"], "feasible": feasible,
               "share_of_feasible": {k: round(counts[k] / feasible, 4)
                                     for k in ("no_gui", "browser", "session", "gui")},
               "counts": dict(counts),
               "no_gui_with_perception": sum(t["perception"] and t["tier"] == "no_gui" for t in tasks)}
    text = json.dumps({"summary": summary, "tasks": tasks}, indent=1)
    if args.output:
        args.output.write_text(text)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
