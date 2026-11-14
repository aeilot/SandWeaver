#!/usr/bin/env python3
"""Grade a replay's eval.log with the official SWE-bench log parser for that repo.

Usage: grade-swebench.py RUN_DIR [--data-dir DIR]. Reads RUN_DIR/result.json and
RUN_DIR/eval.log, writes the FAIL_TO_PASS / PASS_TO_PASS report back into
result.json. Needs the `swebench` package (kept out of the scheduler environment).
"""
import argparse
import json
from pathlib import Path

import pyarrow.parquet as pq
from swebench.harness.grading import get_eval_tests_report, get_logs_eval, get_resolution_status
from swebench.harness.utils import make_test_spec  # swebench 5.x layout


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run", type=Path)
    parser.add_argument("--data-dir", type=Path, default=Path.home() / "sandweaver-data")
    args = parser.parse_args()
    result = json.loads((args.run / "result.json").read_text())
    rows = pq.read_table(args.data_dir / "dataset/test.parquet").to_pylist()
    row = next(r for r in rows if r["instance_id"] == result["instance_id"])
    for key in ("FAIL_TO_PASS", "PASS_TO_PASS"):
        if isinstance(row[key], str):
            row[key] = json.loads(row[key])
    # The harness slices the log between its test-output markers and applies the
    # repo's registered parser, as in official grading.
    status_map, found = get_logs_eval(make_test_spec(row), str(args.run / "eval.log"))
    if not found:
        status_map = {}
    report = get_eval_tests_report(status_map, {"FAIL_TO_PASS": row["FAIL_TO_PASS"],
                                                "PASS_TO_PASS": row["PASS_TO_PASS"]})
    status = get_resolution_status(report)
    result["grade"] = {"status": status, "resolved": status == "RESOLVED_FULL",
                       "parsed_tests": len(status_map),
                       "counts": {group: {outcome: len(tests) for outcome, tests in outcomes.items()}
                                  for group, outcomes in report.items()}}
    (args.run / "result.json").write_text(json.dumps(result, indent=1))
    print(json.dumps(result["grade"]))


if __name__ == "__main__":
    main()
