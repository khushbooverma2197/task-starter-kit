# environment/ is the build context and becomes the agent's /app.
# Version-pinned base with digest.
FROM python:3.12.7-slim-bookworm@sha256:60d9996b6a8a3689d36db740b49f4327be3be09a21122bd02fb8895abb38b50d

ENV DEBIAN_FRONTEND=noninteractive \
    PAGER=cat \
    GIT_PAGER=cat \
    GIT_TERMINAL_PROMPT=0 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        procps \
        build-essential \
        cargo \
        rustc \
        netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# The coding agent runs from inside this image, and the image has no network at
# run time, so its CLI is installed here.
RUN curl -fsSL https://claude.ai/install.sh | bash \
    && ln -sf /root/.local/bin/claude /usr/local/bin/claude

# Unprivileged account the grader uses to run the deliverable, so the code it
# grades never runs with the rights that write the score.
RUN useradd --create-home --shell /bin/bash runner

WORKDIR /app

# Build workspace environment
COPY Cargo.toml /app/Cargo.toml
COPY src/ /app/src/
COPY self_check.py /app/self_check.py

# Pre-compile the starter workspace and set runner permissions
RUN cargo build --release \
    && chown -R runner:runner /app \
    && chmod +x /app/self_check.py

# --- task timer (append at the end of environment/Dockerfile) ---
# COPY only — never auto-start it from the image (no ENV BASH_ENV, no shell
# profile hooks). The platform arms /app/timer.sh in the task sandbox with the
# real TASK_BUDGET_SECS. An image-side autostart also fires inside the image
# BUILD container and stalls the build until the timer's budget expires.
COPY timer.sh /app/timer.sh
RUN chmod +x /app/timer.sh && mkdir -p /app/.timer
