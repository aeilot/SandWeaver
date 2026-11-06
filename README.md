# SandWeaver

SandWeaver is a local scheduler for reusable Docker workers. An external client or OpenHands agent holds an exclusive workspace lease over a Unix socket. A warm worker starts each lease with a private OverlayFS writable layer and PID namespace. Closing the lease discards those task resources and returns the worker to the pool. The bind-mounted workspace persists.

The pool prewarms to its configured minimum, grows on demand up to the maximum, and retires excess idle workers after a timeout. A worker that fails to reset is retired. Each scheduler manages one image. Use separate scheduler instances and disjoint workspace roots for separate environments.

## Quick start

Requires Python 3.11+ (Python 3.12 for the tested agent setup) and a Docker daemon whose Linux kernel supports OverlayFS and PID and mount namespaces.

From the project root:

```sh
python -m pip install -e .
docker build -t sandweaver-demo:local .
mkdir -p /tmp/sandweaver-workspaces/demo
sandweaver --socket /tmp/sandweaver.sock serve \
  --workspace-root /tmp/sandweaver-workspaces --min 1 --max 4 --idle-seconds 30
```

In another terminal using the same Python environment:

```sh
sandweaver --socket /tmp/sandweaver.sock status
sandweaver --socket /tmp/sandweaver.sock run /tmp/sandweaver-workspaces/demo \
  '/project/.venv/bin/python -c "import humanize; print(humanize.intcomma(1000))"'
```

Use `serve --image IMAGE` to select an already available compatible image with a Debian-style userspace and the mount and namespace utilities. Stop the scheduler with Ctrl-C to remove its workers.

## OpenHands

```sh
python -m pip install -e '.[agent]'
sandweaver-agent --socket /tmp/sandweaver.sock --workspace /tmp/sandweaver-workspaces/demo \
  --prompt "Inspect this workspace and report what is present"
```

Set `LLM_MODEL` and `LLM_API_KEY` in the client environment first. `LLM_BASE_URL` is optional. Use `--smoke-command` for deterministic SDK tool calls without a model. Run the integration check with `python tests/smoke.py` after installing the agent extra and building the demo image.

## Scope

This research prototype is for trusted local tasks and images. Workers require extra mount privileges, and the prototype has not been validated for hostile multi-tenant workloads. Use a dedicated workspace root. The worker has no external network. The included benchmark and JSON are the earlier single-worker handoff experiment, separate from the scheduler integration check.
