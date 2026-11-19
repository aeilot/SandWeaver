#!/bin/sh
# Prepare a fresh Ubuntu 24.04 Compute Engine VM for the SWE-bench replays.
# Run as the login user from a checkout of this repository:
#   sh benchmarks/gce-setup.sh
# It installs Docker and a Python venv, checks cgroup v2, fetches the replay
# data and pulls the task images. Log out and back in afterwards so the docker
# group membership applies.
set -eu
repo=$(cd "$(dirname "$0")/.." && pwd)

test "$(stat -fc %T /sys/fs/cgroup)" = cgroup2fs || {
    echo "cgroup v2 is required; this host mounts $(stat -fc %T /sys/fs/cgroup)" >&2
    exit 1
}
sudo apt-get update -q
sudo apt-get install -yq docker.io python3-venv python3-dev git tmux
sudo usermod -aG docker "$USER"

python3 -m venv "$HOME/sandweaver-venv"
"$HOME/sandweaver-venv/bin/pip" install -q --upgrade pip
"$HOME/sandweaver-venv/bin/pip" install -q -e "$repo" pyarrow swebench

# The current shell is not yet in the docker group, so pull through sudo.
sudo "$HOME/sandweaver-venv/bin/python" "$repo/benchmarks/fetch-swebench-data.py" \
    --data-dir "$HOME/sandweaver-data" --pull
sudo chown -R "$USER" "$HOME/sandweaver-data"
nproc
free -h
df -h "$HOME"
