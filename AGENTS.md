# Repository guidance

SandWeaver is a local Docker worker scheduler. The OpenHands agent runs outside the worker. Keep the scheduler usable without the optional OpenHands dependency.

- Read the nearest AGENTS.md before changing a directory. The documentation index is in docs/README.md.
- Preserve exclusive workspace leases and fail closed on worker reset errors.
- Keep secrets, real workspaces, local sockets, and generated session data out of Git.
- For lifecycle changes, run the Docker integration smoke test with the demo image. For docs changes, verify local links and claims against the implementation.
- Distinguish measured behavior, design proposals, and unverified security properties.
- Use DeepSeek Flash through OpenRouter for model-backed research runs unless the user explicitly selects another model. Do not silently substitute another model.
