#!/usr/bin/env python3
"""Run an external OpenHands SDK agent on local SandWeaver workers."""
import argparse
import os
from pathlib import Path
from threading import Lock
import uuid
from typing import Callable, ClassVar
from pydantic import PrivateAttr

from openhands.sdk import Agent, Conversation, LLM, Tool
from openhands.sdk.tool import Action, Observation, ToolDefinition, ToolExecutor, register_tool

from sandweaver.scheduler import connect
from sandweaver.trace import Trace, TracedClient


class ObservedLLM(LLM):
    _trace: Trace = PrivateAttr()
    _before_model: Callable[[], None] | None = PrivateAttr(default=None)

    def completion(self, *args, **kwargs):
        if self._before_model is not None:
            self._before_model()
        with self._trace.span("llm_call") as span:
            response = super().completion(*args, **kwargs)
            self._trace.model_usage(span, response)
            return response

    async def acompletion(self, *args, **kwargs):
        if self._before_model is not None:
            self._before_model()
        with self._trace.span("llm_call") as span:
            response = await super().acompletion(*args, **kwargs)
            self._trace.model_usage(span, response)
            return response

    def responses(self, *args, **kwargs):
        if self._before_model is not None:
            self._before_model()
        with self._trace.span("llm_call") as span:
            response = super().responses(*args, **kwargs)
            self._trace.model_usage(span, response)
            return response

    async def aresponses(self, *args, **kwargs):
        if self._before_model is not None:
            self._before_model()
        with self._trace.span("llm_call") as span:
            response = await super().aresponses(*args, **kwargs)
            self._trace.model_usage(span, response)
            return response


class ShellCommand(Action):
    command: str


class ShellResult(Observation):
    exit_code: int


class RemoteShell(ToolExecutor[ShellCommand, ShellResult]):
    def __init__(self, client, workspace, lease_policy, inspect=False):
        self.client = client
        self.lock = Lock()
        self.lease_policy = lease_policy
        self.inspect = inspect
        self.leased = lease_policy == "session"
        self.parked = False
        self.last_worker = None
        if self.leased:
            self.last_worker = self.client.request("claim", workspace=str(workspace))["worker"]
        else:
            self.client.request("reserve", workspace=str(workspace))

    def __call__(self, action, conversation=None):
        with self.lock:
            if not self.leased:
                self.last_worker = self.client.request("claim")["worker"]
                self.leased = True
                self.parked = False
            result = self.client.request("exec", command=action.command)
        output = result["stdout"] + result["stderr"]
        code = result["exit_code"]
        return ShellResult.from_text(output, is_error=code != 0, exit_code=code)

    def record_state(self):
        # Call with the lock held and a worker leased, before it is parked or reset.
        if self.inspect:
            self.client.request("inspect")

    def pause(self):
        with self.lock:
            if self.leased:
                self.record_state()
                self.leased = False
                self.parked = self.lease_policy == "demand"
                self.client.request("park" if self.parked else "release")

    def release(self):
        with self.lock:
            if self.leased or self.parked:
                if self.leased:
                    self.record_state()
                self.leased = self.parked = False
                self.client.request("release")



EXECUTORS = {}


class SandWeaverShell(ToolDefinition[ShellCommand, ShellResult]):
    name: ClassVar[str] = "sandweaver_shell"

    @classmethod
    def create(cls, conv_state, binding):
        return [cls(description="Run a shell command in the leased SandWeaver workspace.",
                    action_type=ShellCommand, observation_type=ShellResult,
                    executor=EXECUTORS[binding])]


register_tool("SandWeaverShell", SandWeaverShell)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prompt")
    mode.add_argument("--smoke-command", action="append")
    parser.add_argument("--state-dir", type=Path,
                        default=Path.home() / ".local/state/sandweaver")
    parser.add_argument("--observe", action="store_true", help="Save timing metadata in the session state directory")
    policy = parser.add_mutually_exclusive_group()
    policy.add_argument("--batch-leases", dest="lease_policy", action="store_const", const="batch",
                        help="Release workers between tool batches for file-backed tasks without live processes")
    policy.add_argument("--demand-leases", dest="lease_policy", action="store_const", const="demand",
                        help="Allow parked workers to be reclaimed when a file-backed task is waiting")
    parser.set_defaults(lease_policy="session")
    parser.add_argument("--max-iterations", type=int, default=12)
    parser.add_argument("--max-output-tokens", type=int)
    parser.add_argument("--llm-attempts", type=int, default=5)
    args = parser.parse_args()
    if args.max_iterations < 1 or args.llm_attempts < 1 or (args.max_output_tokens is not None and args.max_output_tokens < 1):
        parser.error("Model limits must be positive")
    model, key = os.getenv("LLM_MODEL"), os.getenv("LLM_API_KEY")
    if args.prompt and not (model and key):
        parser.error("--prompt requires LLM_MODEL and LLM_API_KEY")
    binding = uuid.uuid4().hex
    state = args.state_dir / binding
    host = state / "host"
    host.mkdir(parents=True, exist_ok=True)
    trace_path = state / "trace.jsonl" if args.observe else None
    with Trace(trace_path, binding) as trace, connect(args.socket) as connection:
        client = TracedClient(connection, trace)
        trace.emit("run_mode", mode="fixed_tools" if args.smoke_command else "model")
        shell = RemoteShell(client, args.workspace.resolve(), args.lease_policy,
                            inspect=args.observe)
        EXECUTORS[binding] = shell
        conversation = None
        try:
            batch_leases = args.lease_policy != "session"
            llm_class = ObservedLLM if args.observe or batch_leases else LLM
            llm = llm_class(model=model or "openai/gpt-4o-mini", api_key=key or "unused",
                            base_url=os.getenv("LLM_BASE_URL"),
                            max_output_tokens=args.max_output_tokens, num_retries=args.llm_attempts)
            if isinstance(llm, ObservedLLM):
                llm._trace = trace
                if batch_leases:
                    llm._before_model = shell.pause
            agent = Agent(llm=llm,
                          tools=[Tool(name="SandWeaverShell", params={"binding": binding})],
                          include_default_tools=["FinishTool"])
            conversation = Conversation(agent=agent, workspace=host, persistence_dir=state / "sessions",
                                        max_iteration_per_run=args.max_iterations, visualizer=None,
                                        callbacks=[trace.sdk_event] if args.observe else None)
            trace.emit("conversation_ready", conversation_id=str(conversation.id))
            if args.smoke_command:
                for command in args.smoke_command:
                    if batch_leases:
                        shell.pause()
                    result = conversation.execute_tool(
                        "sandweaver_shell", ShellCommand(command=command))
                    print(result.text)
                    if result.exit_code:
                        raise SystemExit(result.exit_code)
            else:
                conversation.send_message(args.prompt)
                with trace.span("conversation_run"):
                    conversation.run()
            print(f"Conversation: {conversation.id}; worker: {shell.last_worker}")
        finally:
            try:
                if conversation is not None:
                    conversation.close()
            finally:
                EXECUTORS.pop(binding, None)
                shell.release()
    if trace_path is not None:
        print(f"Trace: {trace_path}")


if __name__ == "__main__":
    main()
