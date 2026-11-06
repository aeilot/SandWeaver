FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends util-linux mount \
    && rm -rf /var/lib/apt/lists/* \
    && python -m venv /project/.venv \
    && /project/.venv/bin/pip install --no-cache-dir humanize==4.12.3
