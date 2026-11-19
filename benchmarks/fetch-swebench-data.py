#!/usr/bin/env python3
"""Build the replay data directory from public sources.

Writes, under DATA_DIR (default ~/sandweaver-data):

- dataset/test.parquet: SWE-bench Multilingual test split from Hugging Face,
  checked against the sha256 recorded in swebench-ml-selection.json;
- trajs/<submission>/<instance>.traj.json: the mini-swe-agent trajectories
  of every selected task and submission, from the public SWE-bench submissions
  bucket (objects are readable, listing is not);
- analysis/<submission>.json: the submission's recorded verdicts, as a list of
  {"instance_id", "resolved"}, from per_instance_details.json in the
  SWE-bench/experiments repository.

Files that already exist are kept. A trajectory the bucket refuses is reported
and skipped. With --pull, the Docker image of every selected task is pulled too,
since replay-swebench.py inspects the image before it starts.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.error
import urllib.request

HERE = Path(__file__).resolve().parent
DATASET = ("https://huggingface.co/datasets/SWE-bench/SWE-bench_Multilingual/resolve/main/"
           "data/test-00000-of-00001.parquet")
TRAJ = "https://swe-bench-submissions.s3.amazonaws.com/multilingual/{sub}/trajs/{inst}/{inst}.traj.json"
VERDICTS = ("https://raw.githubusercontent.com/SWE-bench/experiments/main/evaluation/"
            "multilingual/{sub}/per_instance_details.json")


def fetch(url, path):
    """Download url to path unless it exists; return None or an error string."""
    if path.exists():
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(url, timeout=120) as response:
            data = response.read()
    except urllib.error.HTTPError as error:
        return f"{error.code} {url}"
    partial = path.with_suffix(path.suffix + ".part")
    partial.write_bytes(data)
    partial.rename(path)
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--selection", type=Path, default=HERE / "swebench-ml-selection.json")
    parser.add_argument("--data-dir", type=Path, default=Path.home() / "sandweaver-data")
    parser.add_argument("--pull", action="store_true", help="Also pull the task images")
    args = parser.parse_args()
    selection = json.loads(args.selection.read_text())
    instances = [t["instance_id"] for t in selection["tasks"]]
    submissions = selection["submissions"]

    parquet = args.data_dir / "dataset/test.parquet"
    error = fetch(DATASET, parquet)
    if error:
        raise SystemExit(f"Dataset download failed: {error}")
    expected = selection["dataset"].split("sha256")[-1].split()[0]
    actual = hashlib.sha256(parquet.read_bytes()).hexdigest()
    if actual != expected:
        raise SystemExit(f"{parquet} has sha256 {actual}, expected {expected}")
    print(f"dataset ok ({actual[:12]})")

    jobs = [(TRAJ.format(sub=sub, inst=inst), args.data_dir / "trajs" / sub / f"{inst}.traj.json")
            for sub in submissions for inst in instances]
    with ThreadPoolExecutor(16) as pool:
        errors = [e for e in pool.map(lambda job: fetch(*job), jobs) if e]
    print(f"trajectories: {len(jobs) - len(errors)}/{len(jobs)} present")
    for error in errors:
        print(f"  missing: {error}")

    for sub in submissions:
        path = args.data_dir / "analysis" / f"{sub}.json"
        if path.exists():
            continue
        try:
            with urllib.request.urlopen(VERDICTS.format(sub=sub), timeout=120) as response:
                details = json.load(response)
        except urllib.error.HTTPError as error:
            print(f"  no verdicts for {sub}: {error.code}")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([{"instance_id": k, "resolved": v.get("resolved")}
                                    for k, v in sorted(details.items())]))
    print("verdicts written")

    if args.pull:
        import pyarrow.parquet as pq
        rows = {r["instance_id"]: r for r in pq.read_table(parquet).to_pylist()}
        for inst in instances:
            image = rows[inst]["image"]
            image = image if "/" in image else "swebench/" + image  # as replay-swebench.py
            print(f"pull {image}", flush=True)
            subprocess.run(["docker", "pull", "-q", image], check=True)


if __name__ == "__main__":
    main()
