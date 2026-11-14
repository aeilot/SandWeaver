"""Normalize public mini-swe-agent v2 trajectories into timed shell steps.

Chat-completions runs store model turns as role=assistant and outputs as role=tool;
Responses-API runs store model turns as object=response and outputs as
type=function_call_output. Both put the shell commands in extra.actions and
Unix timestamps in extra.timestamp. Model-turn timestamps mark when the response
arrived; output timestamps mark when that command finished.
"""
from dataclasses import dataclass, field
import json
from pathlib import Path


@dataclass
class Step:
    model_wait_s: float | None  # previous output (or prompt) -> this model response
    commands: list[str]
    exec_s: list[float] = field(default_factory=list)  # per command, sequential
    returncodes: list[int | None] = field(default_factory=list)


def is_model_turn(message):
    return message.get("role") == "assistant" or message.get("object") == "response"


def is_output(message):
    return message.get("role") == "tool" or message.get("type") == "function_call_output"


def load(path):
    traj = json.loads(Path(path).read_text())
    steps, last = [], None
    for message in traj["messages"]:
        extra = message.get("extra") or {}
        stamp = extra.get("timestamp")
        if is_model_turn(message):
            commands = [a.get("command", "") for a in extra.get("actions") or []]
            wait = stamp - last if stamp is not None and last is not None else None
            steps.append(Step(wait, commands))
            last = stamp
        elif is_output(message) and steps:
            if stamp is not None and last is not None:
                steps[-1].exec_s.append(stamp - last)
            steps[-1].returncodes.append(extra.get("returncode"))
            last = stamp if stamp is not None else last
        elif message.get("role") == "user" and stamp is not None:
            last = stamp
    return traj.get("info", {}), steps
