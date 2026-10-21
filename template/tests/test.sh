#!/usr/bin/env bash
# Evidence and anti-cheat only; compute_reward.py makes every scoring decision.
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONUSERBASE LD_PRELOAD LD_AUDIT LD_LIBRARY_PATH BASH_ENV ENV CDPATH

OUT=/logs/verifier
mkdir -p "$OUT"
chmod 700 "$OUT"
rm -f "$OUT/evidence.json" "$OUT/reward.txt" "$OUT/reward.json" "$OUT/details.json"

# Collect evidence (build, run, anti-cheat) into evidence.json.
python3 -E -s /tests/collect.py --out "$OUT/evidence.json"

# Score it. Exit status: 0 when the reward is above 0, 1 otherwise.
python3 -E -s /tests/compute_reward.py
status=$?

# Crash fallback: if the scorer died before writing all three files, the run
# was not measured (valid 0); still leave all three files.
if [ ! -s "$OUT/reward.txt" ] || [ ! -s "$OUT/reward.json" ] || [ ! -s "$OUT/details.json" ]; then
    printf '0\n' > "$OUT/reward.txt"
    printf '{"reward": 0, "score": 0, "valid": 0}\n' > "$OUT/reward.json"
    printf '{"subscores": [], "additional_data": {"reason": "scorer exited %s without writing the reward files"}}\n' "$status" > "$OUT/details.json"
    status=1
fi
exit "$status"
