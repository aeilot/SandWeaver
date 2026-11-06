# Test guidance

- smoke.py is an integration check requiring Docker, the demo image, and the optional agent dependencies.
- Use temporary workspaces and sockets. Always stop the scheduler and remove test workers.
- Use fixed SDK tool calls by default so smoke checks do not need model credentials.
- Verify same-worker handoff, private state removal, workspace persistence, and pool resizing when changing lifecycle behavior.
