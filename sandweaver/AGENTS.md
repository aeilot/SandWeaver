# Implementation guidance

- Keep scheduler.py independent of the optional OpenHands SDK. The agent is a socket client.
- Keep workspace validation, leasing, and task isolation at the scheduler boundary. A worker with uncertain cleanup must be retired.
- Preserve command exit codes and stdout/stderr. Test multi-command state and cross-lease reset when touching execution.
- Treat Docker mount privileges as part of the local trusted prototype. Document changes to the isolation boundary.
