#!/usr/bin/env python3
"""Run an external OpenHands SDK agent on one local scheduler lease."""
import argparse
import os
from pathlib import Path
import uuid
from typing import ClassVar

from openhands.sdk import Agent, Conversation, LLM, Tool
from openhands.sdk.tool import Action, Observation, ToolDefinition, ToolExecutor, register_tool

from sandweaver.scheduler import connect


class ShellCommand(Action):
    command: str


class ShellResult(Observation):
    exit_code: int


class RemoteShell(ToolExecutor[ShellCommand, ShellResult]):
    def __init__(self, client):
        self.client = client

    def __call__(self, action, conversation=None):
        result = self.client.request("exec", command=action.command)
        output = result["stdout"] + result["stderr"]
        code = result["exit_code"]
        return ShellResult.from_text(output, is_error=code != 0, exit_code=code)



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
    args = parser.parse_args()
    model, key = os.getenv("LLM_MODEL"), os.getenv("LLM_API_KEY")
    if args.prompt and not (model and key):
        parser.error("--prompt requires LLM_MODEL and LLM_API_KEY")
    binding = uuid.uuid4().hex
    state = args.state_dir / binding
    host = state / "host"
    host.mkdir(parents=True, exist_ok=True)
    with connect(args.socket) as client:
        claim = client.request("claim", workspace=str(args.workspace.resolve()))
        EXECUTORS[binding] = RemoteShell(client)
        conversation = None
        try:
            agent = Agent(llm=LLM(model=model or "openai/gpt-4o-mini", api_key=key or "unused",
                                  base_url=os.getenv("LLM_BASE_URL")),
                          tools=[Tool(name="SandWeaverShell", params={"binding": binding})],
                          include_default_tools=["FinishTool"])
            conversation = Conversation(agent=agent, workspace=host, persistence_dir=state / "sessions",
                                        max_iteration_per_run=12, visualizer=None)
            if args.smoke_command:
                for command in args.smoke_command:
                    result = conversation.execute_tool(
                        "sandweaver_shell", ShellCommand(command=command))
                    print(result.text)
                    if result.exit_code:
                        raise SystemExit(result.exit_code)
            else:
                conversation.send_message(args.prompt)
                conversation.run()
            print(f"Conversation: {conversation.id}; worker: {claim['worker']}")
        finally:
            try:
                if conversation is not None:
                    conversation.close()
            finally:
                EXECUTORS.pop(binding, None)
                client.request("release")


if __name__ == "__main__":
    main()
