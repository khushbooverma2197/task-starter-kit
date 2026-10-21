"""Evidence collection: build, run, anti-cheat. Never scores.

Writes one JSON object to --out on every path. compute_reward.py reads it.
Fields compute_reward.py expects:
  runtime_ok      false only when the runtime itself failed (not the agent's work)
  runtime_error   why, when runtime_ok is false
  build_ok        the deliverable built
  cheat_detected  an anti-cheat check fired
  gate_reason     why a gate failed
  cases_total     size of the fixed case set (implementation, optimization)
  cases_passed    cases whose output matched (implementation, optimization)
  speedup         measured speedup over the shipped baseline (optimization)
  constraints_ok  the artifact meets every stated constraint (research)
  metric          the raw metric on the cases the agent never saw (research)
"""

import argparse
import json
import os
import signal
import subprocess
import sys

RUN_AS = "runner"  # unprivileged account created in environment/Dockerfile


def run_untrusted(argv, timeout, cwd="/app"):
    """Run agent-built code as RUN_AS in its own process group; kill the group after."""
    proc = subprocess.Popen(
        ["runuser", "-u", RUN_AS, "--", *argv],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        out, err = proc.communicate(timeout=timeout)
        return proc.returncode, out, err
    except subprocess.TimeoutExpired:
        return None, b"", b"timed out"
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)  # by process group, never by name
        except ProcessLookupError:
            pass
        proc.wait()


# >>> gpu
def gpu_visible():
    """No visible GPU means the run cannot be measured (valid = 0), never a CPU score."""
    try:
        return subprocess.run(["nvidia-smi", "-L"], capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


# <<< gpu
def collect():
    ev = {
        "runtime_ok": True,
        "runtime_error": "",
        "build_ok": False,
        "cheat_detected": False,
        "gate_reason": "",
        "cases_total": 0,
        "cases_passed": 0,
    }
    # >>> gpu
    if not gpu_visible():
        ev["runtime_ok"] = False
        ev["runtime_error"] = "no GPU visible"
        return ev
    # <<< gpu
    # TODO(author): your evidence collection. Typical order:
    #   1. integrity: hash-check or restore anything you read from the agent's
    #      tree (harness files, fixed inputs); set cheat_detected on a mismatch.
    #   2. build the deliverable from source; set build_ok.
    #   3. run every case in your fixed case set (keep them under tests/cases/)
    #      with run_untrusted(); count passes against your frozen expected outputs.
    #   4. optimization: measure the speedup; research: compute the metric.
    #   5. set runtime_ok = False only when the runtime itself is broken, with
    #      runtime_error saying why. A wrong or missing deliverable is not that.
    ev["gate_reason"] = "evidence collection not implemented"
    return ev


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        ev = collect()
    except Exception as exc:  # a collector bug means nothing was measured: valid = 0
        ev = {"runtime_ok": False, "runtime_error": f"collector error: {type(exc).__name__}"}
    with open(args.out, "w") as fh:
        json.dump(ev, fh)
    return 0


if __name__ == "__main__":
    sys.exit(main())
