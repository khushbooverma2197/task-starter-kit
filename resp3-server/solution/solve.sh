#!/usr/bin/env bash
# Reference solution: produces the deliverable in /app and nothing else.
# It never writes the grader's log directory or touches the sealed grader.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd /app

cp "$SRC/src/main.rs" /app/src/main.rs
cargo build --release
