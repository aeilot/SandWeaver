"""Opt-in timing and usage metadata for a local agent run."""
from contextlib import contextmanager
import json
import math
import os
import sys
import threading
import time
import uuid


class Trace:
    def __init__(self, path, session):
        self.path = path
        self.session = session
        self.origin = time.monotonic_ns()
        self.lock = threading.Lock()
        self.stream = None

    def __enter__(self):
        if self.path is not None:
            descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            self.stream = os.fdopen(descriptor, "w")
            self.emit("trace_started", wall_time_ns=time.time_ns())
        return self

    def __exit__(self, *_):
        if self.stream is not None:
            self.stream.close()

    def emit(self, event, **metadata):
        if self.stream is None:
            return
        with self.lock:
            record = {"session": self.session, "event": event,
                      "elapsed_ns": time.monotonic_ns() - self.origin, **metadata}
            try:
                self.stream.write(json.dumps(record) + "\n")
                self.stream.flush()
            except OSError:
                self.stream.close()
                self.stream = None
                print("Timing trace disabled after a write error", file=sys.stderr)

    @contextmanager
    def span(self, name):
        identifier = uuid.uuid4().hex
        self.emit("span_start", name=name, span=identifier)
        outcome = "ok"
        try:
            yield identifier
        except BaseException:
            outcome = "error"
            raise
        finally:
            self.emit("span_end", name=name, span=identifier, outcome=outcome)

    def model_usage(self, span, response):
        raw = response.raw_response
        usage = getattr(raw, "usage", None)
        details = getattr(usage, "prompt_tokens_details", None)
        if details is None:
            details = getattr(usage, "input_tokens_details", None)
        prompt = getattr(usage, "prompt_tokens", None)
        completion = getattr(usage, "completion_tokens", None)
        if prompt is None:
            prompt = getattr(usage, "input_tokens", None)
        if completion is None:
            completion = getattr(usage, "output_tokens", None)
        counters = {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "cache_read_tokens": getattr(details, "cached_tokens", None),
            "cache_write_tokens": getattr(details, "cache_write_tokens", None),
        }
        metadata = {key: value for key, value in counters.items()
                    if type(value) is int and value >= 0}
        cost = getattr(usage, "cost", None)
        if type(cost) in (int, float) and math.isfinite(cost) and cost >= 0:
            metadata["provider_cost_usd"] = cost
        self.emit("llm_usage", span=span, **metadata)

    def sdk_event(self, event):
        self.emit("sdk_event", event_type=type(event).__name__, event_id=str(event.id))


class TracedClient:
    def __init__(self, client, trace):
        self.client = client
        self.trace = trace

    def request(self, op, **fields):
        if self.trace.stream is None:
            return self.client.request(op, **fields)
        if op in ("claim", "exec"):
            fields["observe"] = True
        with self.trace.span(op) as span:
            response = self.client.request(op, **fields)
        timing = response.pop("timing", {})
        if timing:
            self.trace.emit("scheduler_timing", span=span, **timing)
        if op == "claim":
            self.trace.emit("lease_acquired", worker=response["worker"])
        elif op == "park":
            self.trace.emit("lease_parked")
        elif op == "release":
            self.trace.emit("lease_released")
        elif op == "exec":
            self.trace.emit("command_result", span=span, exit_code=response["exit_code"],
                            stdout_bytes=len(response["stdout"].encode("utf-8", errors="replace")),
                            stderr_bytes=len(response["stderr"].encode("utf-8", errors="replace")))
        return response
