#!/usr/bin/env python3
"""Compare aShare-inspired EDF and parked leases in a fixed-capacity event replay."""
import argparse
from collections import deque
from dataclasses import dataclass, field
import heapq
from itertools import count
import json
from pathlib import Path
import random
import statistics


@dataclass
class Batch:
    session: int
    index: int
    ready: int
    duration: int
    deadline: int


@dataclass
class Worker:
    parked: int | None = None
    available: int = 0
    queue: list[Batch] = field(default_factory=list)


def replay(policy, capacity, sessions, jitter, seed, reset=46, setup=107):
    rng = random.Random(seed)
    # Second-batch gaps start at first-tool completion. These are synthetic
    # file-backed commands, with identical mounted-cache behavior in both arms.
    durations = [(rng.choice((30, 60, 140)), rng.choice((30, 60, 140)))
                 for _ in range(sessions)]
    arrivals = [rng.randrange(0, 121) for _ in range(sessions)]
    gaps = [150 + rng.randrange(jitter + 1) for _ in range(sessions)]
    workers = [Worker() for _ in range(capacity)]
    pending = deque()
    parked = {}
    events = []
    order = count()
    rows = []
    reclaims = 0
    retained = 0
    infeasible = 0

    def event(at, kind, payload):
        heapq.heappush(events, (at, next(order), kind, payload))

    def ready(session, index, now):
        # A shared tool-batch budget, measured from readiness to tool completion.
        event(now, "ready", Batch(session, index, now, durations[session][index], now + 300))

    def run(worker, batch, now, transition):
        finish = now + transition + batch.duration
        worker.available = finish + (reset if policy == "edf" else 0)
        event(finish, "done", (worker, batch))
        rows.append({"session": batch.session, "batch": batch.index, "ready_ms": batch.ready,
                     "finish_ms": finish, "admission_to_dispatch_ms": now - batch.ready,
                     "deadline_missed": finish > batch.deadline})

    def enqueue_edf(batch, now):
        nonlocal infeasible
        options = []
        for worker in workers:
            queue = sorted([*worker.queue, batch], key=lambda item: item.deadline)
            finish = max(now, worker.available)
            lateness = []
            for index, item in enumerate(queue):
                finish += setup + item.duration + (reset if index else 0)
                lateness.append(max(0, finish - item.deadline))
            if not any(lateness):
                worker.queue = queue
                return
            options.append((sum(lateness), finish, worker, queue))
        # The paper would request expansion here. Under the fixed cap, admit
        # to the queue with the smallest predicted aggregate tardiness.
        infeasible += 1
        _, _, worker, queue = min(options, key=lambda option: option[:2])
        worker.queue = queue

    for session, now in enumerate(arrivals):
        ready(session, 0, now)
    while events:
        now, _, kind, payload = heapq.heappop(events)
        if kind == "done":
            worker, batch = payload
            if batch.index == 0:
                ready(batch.session, 1, now + gaps[batch.session])
            if policy == "demand" and batch.index == 0:
                worker.parked = batch.session
                parked[batch.session] = worker
            else:
                worker.available = now + reset
                event(worker.available, "wake", None)
        elif kind == "ready":
            if policy == "edf":
                enqueue_edf(payload, now)
            else:
                pending.append(payload)

        # Handle all completions and arrivals at this timestamp before dispatch.
        if events and events[0][0] == now:
            continue
        if policy == "edf":
            for worker in workers:
                if worker.available <= now and worker.queue:
                    run(worker, worker.queue.pop(0), now, setup)
            continue

        for batch in list(pending):
            if batch.session in parked:
                worker = parked.pop(batch.session)
                worker.parked = None
                pending.remove(batch)
                retained += 1
                run(worker, batch, now, 0)
        while pending:
            worker = next((w for w in workers if w.available <= now and w.parked is None), None)
            transition = setup
            if worker is None and parked:
                worker = next(iter(parked.values()))
                del parked[worker.parked]
                worker.parked = None
                reclaims += 1
                transition += reset
            if worker is None:
                break
            run(worker, pending.popleft(), now, transition)

    assert len(rows) == sessions * 2
    return {"batches": rows, "reclaims": reclaims, "retained": retained,
            "edf_infeasible_admissions": infeasible,
            "session_completion_ms": [row["finish_ms"] - arrivals[row["session"]]
                                      for row in rows if row["batch"] == 1]}


def p95(values):
    ordered = sorted(values)
    return ordered[(95 * len(ordered) + 99) // 100 - 1]


def summary(trials):
    rows = [row for trial in trials for row in trial["batches"]]
    return {
        "first_batch_p95_ms": p95([row["finish_ms"] - row["ready_ms"] for row in rows if row["batch"] == 0]),
        "resume_p95_ms": p95([row["finish_ms"] - row["ready_ms"] for row in rows if row["batch"] == 1]),
        "session_p95_ms": p95([value for trial in trials for value in trial["session_completion_ms"]]),
        "deadline_miss_percent": round(100 * statistics.mean(row["deadline_missed"] for row in rows), 2),
        **{key: sum(trial[key] for trial in trials)
           for key in ("reclaims", "retained", "edf_infeasible_admissions")},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    scenarios = []
    for capacity, sessions, jitter in ((2, 2, 0), (2, 4, 0), (4, 8, 0), (4, 8, 450)):
        policies = {}
        for policy in ("eager_fifo", "edf", "demand"):
            trials = [replay(policy, capacity, sessions, jitter, seed) for seed in range(100)]
            policies[policy] = {"summary": summary(trials), "trials": trials}
        scenarios.append({"workers": capacity, "sessions": sessions, "wait_jitter_ms": jitter,
                       "policies": policies})
    args.output.write_text(json.dumps({"reset_ms": 46, "setup_ms": 107, "deadline_budget_ms": 300,
                                      "seeds": list(range(100)), "scenarios": scenarios}) + "\n")
    for scenario in scenarios:
        print({key: value for key, value in scenario.items() if key != "policies"},
              {key: value["summary"] for key, value in scenario["policies"].items()})
