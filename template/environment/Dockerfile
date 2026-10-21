# environment/ is the build context and becomes the agent's /app.
# The image builder rejects COPY flags (--chown, --chmod, --link) and $VARIABLES
# in COPY sources: copy plainly, then chown/chmod in a RUN step.

# Version-pinned base. Pin it by digest as well before you submit:
#   docker buildx imagetools inspect python:3.12.7-slim-bookworm
# then write FROM python:3.12.7-slim-bookworm@sha256:<digest>.
FROM python:3.12.7-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PAGER=cat \
    GIT_PAGER=cat \
    GIT_TERMINAL_PROMPT=0 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git procps build-essential \
    && rm -rf /var/lib/apt/lists/*

# The coding agent runs from inside this image, and the image has no network at
# run time, so its CLI is installed here.
RUN curl -fsSL https://claude.ai/install.sh | bash \
    && ln -sf /root/.local/bin/claude /usr/local/bin/claude

# Unprivileged account the grader uses to run the deliverable, so the code it
# grades never runs with the rights that write the score.
RUN useradd --create-home --shell /bin/bash runner

WORKDIR /app

# TODO(author): build the workspace the agent starts from. COPY your sources,
# visible examples and a self-check script that never reads the sealed grader;
# install every build-time and grading-time dependency here, since nothing can
# be downloaded at run time. Example:
#   COPY workspace/ /app/
#   RUN cd /app && make

# --- task timer (append at the end of environment/Dockerfile) ---
# COPY only — never auto-start it from the image (no ENV BASH_ENV, no shell
# profile hooks). The platform arms /app/timer.sh in the task sandbox with the
# real TASK_BUDGET_SECS. An image-side autostart also fires inside the image
# BUILD container and stalls the build until the timer's budget expires.
COPY timer.sh /app/timer.sh
RUN chmod +x /app/timer.sh && mkdir -p /app/.timer
