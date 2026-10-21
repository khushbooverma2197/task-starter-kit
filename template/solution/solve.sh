#!/usr/bin/env bash
# Reference solution: produces the deliverable in /app and nothing else.
# It never writes the grader's log directory or touches the sealed grader.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd /app

# TODO(author): apply your reference. Ship it as source files next to this
# script (for example solution/src/...), not as an archive, then copy or patch
# them into /app and build exactly as the agent would. solution/ must carry at
# least 150 non-blank lines of real code across its code files.
#   cp -r "$SRC/src/." /app/
#   make -C /app
