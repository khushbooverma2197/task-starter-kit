# Task starter kit

This kit sets up the parts of a task bundle that are the same for every task:
the timer daemon, the Dockerfile skeleton, the `task.toml` wiring, the
two-stage grader (evidence, then scoring) and a script that checks and zips the
bundle, so you avoid mechanical setup mistakes.

It does **not** write the task. You still write the instruction, the
provenance, the environment, the reference solution (at least 150 lines of real
code), the hidden cases and the evidence collection, and you calibrate the
score. A bundle made from this kit without that work fails the upload check,
as it should.

This README is not part of your bundle. Only the folder `taskkit.py new`
creates gets zipped.

## Requirements

- Python 3.11 or newer for `taskkit.py`. If `python3 --version` shows an older
  version, use [uv](https://docs.astral.sh/uv/):
  `uv run --python 3.11 taskkit.py ...`
- Docker and `harbor` for the local runs in step 4.

## Steps

```bash
# 1. Create the task folder. Pick a class the upload form currently shows as open.
python3 taskkit.py new my-task --name my-task --class implementation --language rust
#    options: --class implementation|performance|research   --budget-hours 2|4|8|20 (default 8)
#             --gpu (one H100)   --reward-cap capped|uncapped (research only, required)
#             --language is repeatable: --language rust --language python

# 2. Write the task. Search for TODO(author) and {{...}} and replace every one.
grep -rn "TODO(author)\|{{" my-task

# 3. Pre-check. Use the same name and class you will enter on the upload form.
python3 taskkit.py check my-task --name my-task --class implementation

# 4. Run it locally, with Docker running.
(cd my-task && harbor run -p . -a nop -e docker -k 1)      # untouched state: reward exactly 0
(cd my-task && harbor run -p . -a oracle -e docker -k 2)   # reference: its ceiling, same score both runs

# 5. Package. Writes my-task-YYYYMMDD.zip next to the task folder; upload that file.
python3 taskkit.py package my-task --name my-task --class implementation
```

The upload form's class "performance" is written `paradigm = "optimization"`
in `task.toml`. `new` handles this for you.

## What is done and what you write

| File | Done by the kit | You write |
|---|---|---|
| `task.toml` | name, class, compute, languages, budget tier, matching `TASK_BUDGET_SECS`, `allow_internet = false`, GPU pin, `reward_cap` | `description`, `category`, `tags`; `cpus`, `memory_mb` and `[verifier] timeout_sec` sized to your task |
| `instruction.md` | section headings and the budget number | the whole contract, in your own words (250 words minimum; strong ones run 700 to 3,350) |
| `PROVENANCE.md` | headings | the real source and how you extracted the task (80 words minimum) |
| `environment/timer.sh` | the canonical daemon | nothing. Do not edit it. |
| `environment/Dockerfile` | pinned base, pager settings, agent CLI install, an unprivileged `runner` account, the timer tail | your workspace and every dependency. Pin the base by digest. |
| `tests/test.sh` | environment reset, locked log directory, evidence step, scorer, crash fallback | usually nothing |
| `tests/collect.py` | `run_untrusted()` (runs code as `runner` in its own process group and kills the group), GPU check with `--gpu` | the build, the cases, anti-cheat, the measurement |
| `tests/compute_reward.py` | the three reward files on every path, hard gates, fail-closed handling, one scoring block for your class | the calibration constants, and any change to the formula your instruction states |
| `solution/solve.sh` | a wrapper that runs from `/app` | the reference solution, as source files next to it |

Put the hidden cases and frozen expected outputs under `tests/cases/` (or
another data folder: `fixtures/`, `expected/`, `data/`).

## The contracts the kit wires up

**Timer.** The platform starts `/app/timer.sh` in the sandbox with
`TASK_BUDGET_SECS` set from `[agent] timeout_sec`. The daemon writes
`/app/.timer/remaining_secs`, `elapsed_secs` and the `alert_30min`,
`alert_10min`, `alert_5min` files. Never start it from the image (no
`ENV BASH_ENV`, no entrypoint). For a local run, start it yourself inside the
task container (not on your machine) with your task's budget, for example
`TASK_BUDGET_SECS=28800 /app/timer.sh &` for the default 8-hour tier. Your instruction must state the
budget in hours and point at `/app/.timer`.

**Budget.** `[agent] timeout_sec` is one of 7200, 14400, 28800 or 72000.
`[environment.env] TASK_BUDGET_SECS` is the same number as a string. To change
the budget, change both (or re-run `new`) and update the instruction.

**Evidence, then score.** `test.sh` runs `collect.py`, which writes
`/logs/verifier/evidence.json`. Then `compute_reward.py` reads it and writes
`reward.txt`, a flat numbers-only `reward.json` (`reward`, `score`, `valid`,
plus components) and `details.json` (`subscores`, `additional_data.reason`).
`test.sh` exits 0 when the reward is above 0 and 1 otherwise.

Evidence fields `compute_reward.py` reads:

| Field | Type | Meaning |
|---|---|---|
| `runtime_ok` | bool, required | `false` only when the runtime itself failed (for example, no GPU visible) |
| `runtime_error` | string | why, when `runtime_ok` is false |
| `build_ok` | bool, required | the deliverable built |
| `cheat_detected` | bool, required | an anti-cheat check fired |
| `gate_reason` | string | why a gate failed |
| `cases_total`, `cases_passed` | whole numbers | implementation and performance: the fixed case set |
| `speedup` | number | performance |
| `constraints_ok`, `metric` | bool, number | research |

**valid.** `valid = 1` means the run was measured, including every zero the
work earned: a failed build, a wrong answer, a cheat, the untouched starting
state. `valid = 0` means nothing was measured: the runtime failed, the evidence
is missing or malformed, the calibration constants are unset or inconsistent,
or the collector or scorer crashed. A `valid = 0` run is retried, not graded,
so set your constants before you upload or every run comes back invalid.

## Scoring by class

The scoring blocks are starting points, not formulas that fit every task. Make
`compute_reward.py` compute exactly what `instruction.md` promises; the quality
review fails a task whose grader contradicts its instruction. Only your own
nop and oracle runs show that the untouched state scores exactly 0 and your
reference reaches its ceiling.

- **implementation**: reward = cases passed / `EXPECTED_CASES`. The fixed
  case set must cover the contract your instruction states, and your reference
  must pass every case, so it scores exactly 1. If it fails a case, fix the
  reference or the case; never drop required cases to reach 1. Hard gates:
  build and anti-cheat.
- **performance**: outputs must match the baseline on every case (any
  mismatch scores 0), then `u = clamp((s − 1 − d) / (S − 1 − d), 0, 1)`,
  reward = `2^u − 1`, with `s` the measured speedup, `S = REFERENCE_SPEEDUP`
  (what your reference measures, or a higher stretch target as long as your
  reference still scores at least 0.5) and `d = NOISE_MARGIN`. Measure with
  repeated runs and take the median, never a single sample.
- **research**: reward = `clamp((metric − BASELINE_METRIC) / (TARGET_METRIC −
  BASELINE_METRIC), 0, 1)`, flipped when `HIGHER_IS_BETTER = False`. For
  `reward_cap = "capped"`, `TARGET_METRIC` is your reference's metric. For
  `"uncapped"`, use a stretch target beyond your reference in the improving
  direction (below it when lower is better). Run your reference
  end to end before you claim its number.

## GPU tasks (`--gpu`)

`new --gpu` sets `gpus = 1`, `gpu_types = ["H100"]` and `compute = "gpu"`, and
adds a check to `collect.py` that reports `runtime_ok = false` when no GPU is
visible. You still need a CUDA base image and, if you use torch, a CUDA build
pinned as `torch==X.Y.Z+cuNNN` from the matching
`https://download.pytorch.org/whl/cuNNN` index. Detect the GPU at run time; do
not hard-code a model.

## What `check` covers, and what it cannot tell you

`check` is a partial pre-check. It looks for:

- unfilled `TODO(author)` and `{{...}}` markers
- a missing required file; a changed `timer.sh`; a missing timer tail or agent CLI install in the Dockerfile
- `task.toml`: name format and match with `--name`, description, budget tier, `TASK_BUDGET_SECS`, `allow_internet`, `docker_image`, class (with `--class`), compute, languages, GPU type, `reward_cap`
- the word floors (instruction 250, provenance 80) and 150 code lines in `solution/`
- symlinks, non-regular files, unsafe or duplicate paths, size limits, and grader or reference files under `environment/`

`package` runs the same check, writes the zip and reads it back the way the
upload does.

A clean `check` does **not** mean the upload will pass. The upload check is
authoritative, and only the platform can decide:

- whether your task name is free
- the current settings: which classes are open, the current limits and floors
- the full list of blocked terms. Keep every file free of references to this
  platform, its clients or any public benchmark, and avoid evaluation jargon
  such as "the solver", "held-out" or "reward hacking". The organisation name
  belongs only in `[task] name`.
- the full verifier-hygiene and image-hygiene rules (for example, a verifier
  that kills processes by name)
- similarity to existing tasks, the quality review, oracle and nop runs,
  the adversarial and difficulty runs, and human review

Two warnings are expected on a kit bundle and do not block an upload:
`base-image-not-digest` (fix it by pinning the digest) and
`codex-cli-not-baked` (an optional second agent CLI).

## Keep your task your own

Every task is compared with existing tasks. The Dockerfile skeleton and
`timer.sh` are meant to be shared; everything else should be your own work: don't paste this README or the kit's comments into your
instruction, and write the operating rules in your own voice.
