"""Every scoring decision, made from /logs/verifier/evidence.json.

Writes three files on every path, including a crash of this script:
  reward.txt    one float in [0, 1]
  reward.json   flat, numbers only: reward, score, valid, plus numeric components
  details.json  {"subscores": [...], "additional_data": {"reason": "..."}}

valid = 0 when the run could not be measured: the collector reports the
runtime failed, the evidence is missing or malformed, or this scorer is
misconfigured or crashes. A wrong answer, a failed build, a cheat and the
untouched starting state are measurable: valid = 1 with reward 0.

This is a skeleton. You align it with the exact reward formula your
instruction.md states, and only your own oracle and nop runs show that it
gives your reference its ceiling and the untouched state exactly 0.

Exit status follows the score: 0 when reward > 0, 1 otherwise.
"""

import json
import math
import sys
from pathlib import Path

OUT = Path("/logs/verifier")
EVIDENCE = OUT / "evidence.json"

# TODO(author): calibration constants, measured on your own reference solution.
# The scorer refuses to give credit while a constant it needs is None.
EXPECTED_CASES = None  # size of the fixed case set; crashed or skipped cases count as failed
REFERENCE_SPEEDUP = None  # optimization: speedup your reference measures (or a stretch target)
NOISE_MARGIN = 0.02  # optimization: measurement noise below which no credit is given
BASELINE_METRIC = None  # research: metric of the untouched starting artifact
TARGET_METRIC = None  # research: your reference's metric (capped), or a stretch target (uncapped)
HIGHER_IS_BETTER = True  # research: direction of the metric


def emit(reward, valid, reason, subscores):
    reward = float(reward)
    if not math.isfinite(reward):
        reward = 0.0
    reward = round(min(1.0, max(0.0, reward)), 6)
    flat = {"reward": reward, "score": reward, "valid": int(valid)}
    for name, value in subscores.items():
        flat[name] = round(float(value), 6)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "reward.json").write_text(json.dumps(flat))
    (OUT / "reward.txt").write_text(f"{reward}\n")
    (OUT / "details.json").write_text(
        json.dumps(
            {
                "subscores": [{"name": k, "score": round(float(v), 6)} for k, v in subscores.items()],
                "additional_data": {"reason": reason},
            }
        )
    )
    raise SystemExit(0 if reward > 0 else 1)


class Unmeasurable(Exception):
    """Evidence or calibration the scorer cannot trust: valid = 0, never a score."""


def number(ev, key):
    value = ev.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise Unmeasurable(f"evidence field {key!r} is missing or not a finite number")
    return float(value)


def flag(ev, key):
    value = ev.get(key)
    if not isinstance(value, bool):
        raise Unmeasurable(f"evidence field {key!r} is missing or not true/false")
    return value


def integer(ev, key):
    value = number(ev, key)
    if value != int(value):
        raise Unmeasurable(f"evidence field {key!r} is not a whole number")
    return int(value)


def correctness(ev):
    """Fraction of the fixed case set passed. Denominator is EXPECTED_CASES."""
    if isinstance(EXPECTED_CASES, bool) or not isinstance(EXPECTED_CASES, int) or EXPECTED_CASES <= 0:
        raise Unmeasurable("EXPECTED_CASES must be a positive whole number")
    total = integer(ev, "cases_total")
    passed = integer(ev, "cases_passed")
    if total != EXPECTED_CASES or not 0 <= passed <= total:
        raise Unmeasurable(f"case counts {passed}/{total} do not match the fixed set of {EXPECTED_CASES}")
    return passed / EXPECTED_CASES


# >>> class: implementation
def score_implementation(ev):
    c = correctness(ev)
    emit(c, 1, f"{c:.4f} of the case set passed", {"correctness": c})
# <<< class: implementation


# >>> class: optimization
def score_optimization(ev):
    # A calibration skeleton, not a formula that fits every task: replace the
    # measurement behind "speedup" with the one your task needs.
    c = correctness(ev)
    if c < 1.0:
        emit(0.0, 1, "outputs differ from the baseline", {"correctness": c})
    if not (isinstance(NOISE_MARGIN, (int, float)) and math.isfinite(NOISE_MARGIN) and NOISE_MARGIN >= 0):
        raise Unmeasurable("NOISE_MARGIN must be a finite number >= 0")
    if not (isinstance(REFERENCE_SPEEDUP, (int, float)) and math.isfinite(REFERENCE_SPEEDUP)
            and REFERENCE_SPEEDUP > 1 + NOISE_MARGIN):
        raise Unmeasurable("REFERENCE_SPEEDUP must be a finite number above 1 + NOISE_MARGIN")
    s = number(ev, "speedup")
    u = min(1.0, max(0.0, (s - 1 - NOISE_MARGIN) / (REFERENCE_SPEEDUP - 1 - NOISE_MARGIN)))
    emit(2**u - 1, 1, f"speedup {s:.3f}x", {"correctness": c, "speedup": s})
# <<< class: optimization


# >>> class: research
def score_research(ev):
    # A calibration skeleton, not a formula that fits every task: replace the
    # metric and constraints with the ones your task needs.
    if not flag(ev, "constraints_ok"):
        emit(0.0, 1, "artifact violates a stated constraint", {"constraints": 0.0})
    for name, value in (("BASELINE_METRIC", BASELINE_METRIC), ("TARGET_METRIC", TARGET_METRIC)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise Unmeasurable(f"{name} must be a finite number")
    span = (TARGET_METRIC - BASELINE_METRIC) if HIGHER_IS_BETTER else (BASELINE_METRIC - TARGET_METRIC)
    if span <= 0:
        raise Unmeasurable("TARGET_METRIC must be better than BASELINE_METRIC in the stated direction")
    m = number(ev, "metric")
    gain = (m - BASELINE_METRIC) if HIGHER_IS_BETTER else (BASELINE_METRIC - m)
    emit(gain / span, 1, f"metric {m:.6g}", {"constraints": 1.0, "metric": m})
# <<< class: research


def main():
    try:
        ev = json.loads(EVIDENCE.read_text())
        if not isinstance(ev, dict):
            raise ValueError("evidence.json is not an object")
    except (OSError, ValueError) as exc:
        emit(0.0, 0, f"evidence unreadable: {exc}", {})
    try:
        if not flag(ev, "runtime_ok"):
            emit(0.0, 0, "runtime unavailable: " + str(ev.get("runtime_error", "")), {})
        if flag(ev, "cheat_detected"):
            emit(0.0, 1, "anti-cheat: " + str(ev.get("gate_reason", "")), {"correctness": 0.0})
        if not flag(ev, "build_ok"):
            emit(0.0, 1, "build failed: " + str(ev.get("gate_reason", "")), {"correctness": 0.0})
        SCORE(ev)
    except Unmeasurable as exc:
        emit(0.0, 0, f"not measurable: {exc}", {})


SCORE = score_implementation  # `taskkit.py new` sets this to the class you choose

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # a scorer bug still leaves the three files
        emit(0.0, 0, f"scorer error: {type(exc).__name__}", {})
    sys.exit(1)
