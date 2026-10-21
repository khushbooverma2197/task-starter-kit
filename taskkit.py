#!/usr/bin/env python3
"""Task starter kit: scaffold, pre-check and package a task bundle.

  taskkit.py new <dir> --name <task-name> --language <lang> [options]
  taskkit.py check <dir-or-zip> [--name <task-name>] [--class <class>]
  taskkit.py package <dir> [--name <task-name>] [--class <class>] [--out-dir <dir>]

`check` is a PARTIAL pre-check. It catches the mistakes that most often fail
the upload structure check (unfilled scaffold fields, task.toml identity and
budget wiring, a changed timer, missing files, unsafe paths, the size floors)
and nothing more. The upload page runs the full check and stays
authoritative; README.md lists what only the upload can decide.

Standard library only. Needs Python 3.11 or newer.
"""

import sys

if sys.version_info < (3, 11):
    sys.exit(
        f"taskkit.py needs Python 3.11 or newer (this is {sys.version.split()[0]}).\n"
        "Run it with a newer interpreter, for example:  uv run --python 3.11 taskkit.py ..."
    )

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import stat
import tomllib
import zipfile
from pathlib import Path

TEMPLATE_DIR = Path(__file__).resolve().parent / "template"

MAX_ZIP_BYTES = 250 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
MAX_FILES = 20_000
MAX_CONTROL_FILE_BYTES = 512 * 1024
BUDGET_TIERS_SEC = (7200, 14400, 28800, 72000)
MIN_INSTRUCTION_WORDS = 250
MIN_PROVENANCE_WORDS = 80
MIN_SOLUTION_LINES = 150
NAME_PREFIX = "afterquery/"
CLASS_TO_PARADIGM = {"implementation": "implementation", "performance": "optimization", "research": "research"}
TIMER_SHA256 = "39efae1f67c5f37b5dcbf5454f348a9a08469e96398f7b760f476b4cbadfdccd"

REQUIRED_FILES = (
    "task.toml",
    "instruction.md",
    "PROVENANCE.md",
    "environment/Dockerfile",
    "environment/timer.sh",
    "tests/test.sh",
    "tests/compute_reward.py",
    "solution/solve.sh",
)
TEXT_SUFFIXES = {".md", ".toml", ".sh", ".py", ".txt", ".json", ".yaml", ".yml", ""}
JUNK_DIRS = {"__MACOSX", ".git", "node_modules", "__pycache__", ".venv", ".pytest_cache"}
# Counted toward the solution floor: files with a code extension or a shebang.
CODE_SUFFIX_RE = re.compile(
    r"\.(sh|bash|py|rs|zig|hs|c|h|cc|cpp|hpp|cu|cuh|go|ts|tsx|js|jsx|mjs|java|kt|scala|ml|rb|lua|jl|swift|cs|"
    r"sql|nim|v|sv|f90|r|php|pl|lean|cmake|mk|patch|diff)$|(^|/)(Makefile|CMakeLists\.txt)$",
    re.I,
)
SLUG_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")


class Report:
    def __init__(self):
        self.errors, self.warnings = [], []

    def error(self, code, msg, path=None):
        self.errors.append((code, msg, path))

    def warning(self, code, msg, path=None):
        self.warnings.append((code, msg, path))

    def print(self, label):
        for level, rows in (("ERROR", self.errors), ("WARNING", self.warnings)):
            for code, msg, path in rows:
                print(f"{level:7} {code}{f' [{path}]' if path else ''}: {msg}")
        print(f"\n{label}: {len(self.errors)} error(s), {len(self.warnings)} warning(s).")
        if not self.errors:
            print("Nothing blocking that this partial pre-check covers. The upload check is authoritative.")
        return not self.errors


# ── Reading a bundle (directory or zip), with the upload's path rules ─────────


def unsafe_path(path: str) -> bool:
    return path.startswith("/") or "\\" in path or ".." in path or "\0" in path


def read_dir(root: Path, rep: Report) -> dict[str, bytes]:
    files, total = {}, 0
    for dirpath, dirnames, filenames in os.walk(root):
        rel = Path(dirpath).relative_to(root)
        for d in list(dirnames):
            if (Path(dirpath) / d).is_symlink():
                rep.error("symlink", "Symlinks are not allowed in a bundle.", (rel / d).as_posix())
                dirnames.remove(d)
            elif d in JUNK_DIRS:
                dirnames.remove(d)
        for name in filenames:
            p = Path(dirpath) / name
            path = (rel / name).as_posix()
            if name == ".DS_Store":
                continue
            if p.is_symlink():
                rep.error("symlink", "Symlinks are not allowed in a bundle.", path)
                continue
            st = p.stat()
            if not stat.S_ISREG(st.st_mode):
                rep.error("not-a-file", "Only regular files can go in a bundle.", path)
                continue
            if unsafe_path(path):
                rep.error("unsafe-path", "Path the upload refuses (.., backslash).", path)
                continue
            total += st.st_size
            if len(files) >= MAX_FILES or total > MAX_UNCOMPRESSED_BYTES:
                rep.error("too-large", f"More than {MAX_FILES} files or 2GB; stopped reading.")
                return files
            files[path] = p.read_bytes()
    return files


def read_zip(zip_path: Path, rep: Report) -> dict[str, bytes]:
    """Drop macOS junk and unwrap one top-level folder, as the upload does."""
    if zip_path.stat().st_size > MAX_ZIP_BYTES:
        rep.error("zip-too-large", "The zip is over 250MB.")
        return {}
    with zipfile.ZipFile(zip_path) as zf:
        infos = []
        for i in zf.infolist():
            if stat.S_ISLNK(i.external_attr >> 16):
                rep.error("symlink", "Symlinks are not allowed in a bundle.", i.filename)
            elif not i.is_dir() and not i.filename.startswith("__MACOSX/") and not i.filename.endswith(".DS_Store"):
                infos.append(i)
        names = [i.filename for i in infos]
        for n in sorted({n for n in names if names.count(n) > 1}):
            rep.error("duplicate-bundle-path", "The zip has more than one entry for this path.", n)
        for n in names:
            if unsafe_path(n):
                rep.error("unsafe-path", "Path the upload refuses (absolute, .., backslash).", n)
        if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_UNCOMPRESSED_BYTES:
            rep.error("too-large", f"More than {MAX_FILES} files or 2GB uncompressed; not read.")
            return {}
        if rep.errors:
            return {}
        tops = {n.split("/")[0] for n in names}
        wrapper = next(iter(tops)) + "/" if len(tops) == 1 and all("/" in n for n in names) else ""
        return {i.filename[len(wrapper):]: zf.read(i) for i in infos if i.filename[len(wrapper):]}


def text_of(path: str, data: bytes) -> str | None:
    textual = Path(path).suffix.lower() in TEXT_SUFFIXES or path.endswith("Dockerfile") or CODE_SUFFIX_RE.search(path)
    if b"\0" in data[:4096] or not textual:
        return None
    return data.decode("utf-8", errors="replace")


# ── The pre-check ─────────────────────────────────────────────────────────────


def check_files(files: dict[str, bytes], name: str | None, task_class: str | None, rep: Report) -> None:
    if len(files) > MAX_FILES:
        rep.error("too-many-files", f"{len(files)} files (max {MAX_FILES}).")
    for path in files:
        if path.startswith("/") or "\\" in path or any(s in ("", ".", "..") for s in path.split("/")):
            rep.error("noncanonical-bundle-path", "Path is not canonical.", path)
    for req in REQUIRED_FILES:
        if req not in files:
            rep.error("missing-file", "Required file is missing.", req)
        elif len(files[req]) > MAX_CONTROL_FILE_BYTES or b"\0" in files[req][:4096]:
            rep.error("control-file-not-inspectable", "Must be a text file of at most 512KB.", req)
    texts = {p: t for p, d in files.items() if (t := text_of(p, d)) is not None}

    for path, t in texts.items():
        if "TODO(author)" in t:
            rep.error("kit-todo-left", "Unfinished TODO(author) section: write it, then delete the marker.", path)
        if re.search(r"\{\{[A-Z_]+\}\}", t):
            rep.error("kit-token-left", "Unfilled {{...}} field.", path)
        if path != "task.toml" and NAME_PREFIX.rstrip("/") in t.lower():
            rep.error("kit-org-name", "The organisation name may appear only in task.toml's [task] name.", path)
    for path in files:
        if path.startswith("cheat/") or re.match(r"^environment/(solution/|(tests/)?solve\.sh$|([^/]+/)?compute_reward[^/]*\.py$)", path):
            rep.error("grader-in-bundle", "Grader, reference or exploit material in the wrong place.", path)

    timer = files.get("environment/timer.sh")
    if timer is not None and hashlib.sha256(timer).hexdigest() != TIMER_SHA256:
        rep.error("kit-timer-modified", "Differs from the canonical timer daemon; restore it from the kit template.", "environment/timer.sh")
    docker = texts.get("environment/Dockerfile", "")
    if docker and ("COPY timer.sh /app/timer.sh" not in docker or re.search(r"^\s*ENV\s+BASH_ENV\b", docker, re.I | re.M)):
        rep.error("timer-not-bootstrapped", "Keep the timer tail (COPY timer.sh, chmod) and never autostart it.", "environment/Dockerfile")
    if docker and not re.search(r"claude\.ai/install\.sh|@anthropic-ai/claude-code", docker):
        rep.error("agent-cli-not-baked", "The Dockerfile must install the Claude Code CLI.", "environment/Dockerfile")
    if docker and not re.search(r"^\s*FROM\s+\S+@sha256:[0-9a-f]{64}", docker, re.I | re.M):
        rep.warning("base-image-not-digest", "Pin the base image by digest before you submit.", "environment/Dockerfile")

    budget = None
    toml_text = texts.get("task.toml")
    if toml_text is not None:
        try:
            t = tomllib.loads(toml_text)
        except tomllib.TOMLDecodeError as exc:
            rep.error("toml-parse", f"task.toml does not parse: {exc}", "task.toml")
            t = None
        if t is not None:
            budget = check_toml(t, name, task_class, rep)

    ins = texts.get("instruction.md", "")
    if ins:
        words = len(ins.split())
        if words < MIN_INSTRUCTION_WORDS:
            rep.error("instruction-too-thin", f"{words} words; at least {MIN_INSTRUCTION_WORDS} are required.", "instruction.md")
        if "/app/.timer" not in ins:
            rep.error("no-timer-reference", "Point the agent at /app/.timer.", "instruction.md")
        if budget in BUDGET_TIERS_SEC and not re.search(rf"\b{budget // 3600}\s*(?:-\s*)?(?:h\b|hrs?\b|hours?\b)", ins, re.I):
            rep.warning("budget-not-stated", f'State the budget as "{budget // 3600} hours" (other spellings may also pass).', "instruction.md")
    prov = texts.get("PROVENANCE.md", "")
    if prov and len(prov.split()) < MIN_PROVENANCE_WORDS:
        rep.error("provenance-thin", f"At least {MIN_PROVENANCE_WORDS} words naming the real source and the extraction.", "PROVENANCE.md")
    lines = sum(
        sum(1 for ln in t.split("\n") if ln.strip())
        for p, t in texts.items()
        if p.startswith("solution/") and (CODE_SUFFIX_RE.search(p) or t.startswith("#!"))
    )
    if "solution/solve.sh" in files and lines < MIN_SOLUTION_LINES:
        rep.error("solution-too-small", f"solution/ has {lines} non-blank code lines; at least {MIN_SOLUTION_LINES}.", "solution/")


def check_toml(t: dict, name: str | None, task_class: str | None, rep: Report) -> int | None:
    tables = {}
    for key in ("task", "metadata", "agent", "environment"):
        value = t.get(key, {})
        if not isinstance(value, dict):
            rep.error("toml-shape", f"[{key}] must be a table.", "task.toml")
            value = {}
        tables[key] = value
    task, meta, agent, env = tables["task"], tables["metadata"], tables["agent"], tables["environment"]
    pkg = task.get("name")
    if not isinstance(pkg, str) or not pkg.startswith(NAME_PREFIX) or not SLUG_RE.match(pkg[len(NAME_PREFIX):]) or ".." in pkg:
        rep.error("task-name-org", f'[task] name must be "{NAME_PREFIX}<task-name>".', "task.toml")
    elif name is not None and pkg[len(NAME_PREFIX):] != name:
        rep.error("task-name-mismatch", f"[task] name does not match --name {name}.", "task.toml")
    if not str(task.get("description", "")).strip():
        rep.error("no-task-description", "[task] description is required.", "task.toml")

    budget = agent.get("timeout_sec")
    if budget not in BUDGET_TIERS_SEC or isinstance(budget, bool):
        rep.error("agent-timeout-off-tier", f"[agent] timeout_sec must be one of {BUDGET_TIERS_SEC}.", "task.toml")
        budget = None
    declared = env.get("env", {}).get("TASK_BUDGET_SECS") if isinstance(env.get("env"), dict) else None
    if budget is not None and declared != str(budget):
        rep.error("budget-env-mismatch", f'[environment.env] TASK_BUDGET_SECS must be the string "{budget}".', "task.toml")
    if env.get("allow_internet") is not False:
        rep.error("internet-enabled", "[environment] allow_internet must be false.", "task.toml")
    if "docker_image" in env:
        rep.error("docker-image-not-allowed", "Remove [environment] docker_image.", "task.toml")

    paradigm = meta.get("paradigm")
    if paradigm not in CLASS_TO_PARADIGM.values():
        rep.error("metadata-paradigm-missing", "[metadata] paradigm must be implementation, optimization or research.", "task.toml")
    elif task_class and CLASS_TO_PARADIGM[task_class] != paradigm:
        rep.error("metadata-paradigm-mismatch", f'--class {task_class} is paradigm "{CLASS_TO_PARADIGM[task_class]}".', "task.toml")
    gpus = env.get("gpus", 0)
    if meta.get("compute") != ("gpu" if gpus else "cpu"):
        rep.error("metadata-compute-mismatch", "[metadata] compute must be gpu when gpus > 0, else cpu.", "task.toml")
    if gpus and env.get("gpu_types") != ["H100"]:
        rep.error("gpu-type-not-h100", 'GPU tasks set gpu_types = ["H100"].', "task.toml")
    if not meta.get("languages"):
        rep.error("metadata-languages-missing", "[metadata] languages is required.", "task.toml")
    if paradigm == "research" and meta.get("reward_cap") not in ("capped", "uncapped"):
        rep.error("metadata-reward-cap-missing", 'Research tasks set reward_cap = "capped" or "uncapped".', "task.toml")
    return budget


# ── Commands ──────────────────────────────────────────────────────────────────


def cmd_new(a) -> int:
    dest = Path(a.dir)
    if dest.exists() and any(dest.iterdir()):
        sys.exit(f"{dest} exists and is not empty.")
    if not SLUG_RE.match(a.name) or ".." in a.name:
        sys.exit("--name: start with a letter or digit; then letters, digits, '.', '_' or '-'.")
    if (a.task_class == "research") != (a.reward_cap is not None):
        sys.exit("--reward-cap is required for research tasks and only allowed there.")
    paradigm = CLASS_TO_PARADIGM[a.task_class]
    budget = a.budget_hours * 3600
    shutil.copytree(TEMPLATE_DIR, dest, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"))

    p = dest / "task.toml"
    s = p.read_text()
    s = s.replace("{{TASK_NAME}}", a.name).replace("{{PARADIGM}}", paradigm)
    s = s.replace('["{{LANGUAGE}}"]', "[" + ", ".join(json.dumps(x) for x in a.language) + "]")
    s = s.replace("timeout_sec = 28800", f"timeout_sec = {budget}")
    s = s.replace('TASK_BUDGET_SECS = "28800"', f'TASK_BUDGET_SECS = "{budget}"')
    if a.reward_cap:
        s = s.replace('difficulty = "frontier"\n', f'difficulty = "frontier"\nreward_cap = "{a.reward_cap}"\n')
    if a.gpu:
        s = s.replace('compute = "cpu"', 'compute = "gpu"').replace("gpus = 0", 'gpus = 1\ngpu_types = ["H100"]')
    p.write_text(s)

    p = dest / "instruction.md"
    p.write_text(p.read_text().replace("{{BUDGET_HOURS}}", str(a.budget_hours)))

    p = dest / "tests" / "compute_reward.py"
    s = p.read_text()
    for other in set(CLASS_TO_PARADIGM.values()) - {paradigm}:
        s = re.sub(rf"# >>> class: {other}\n.*?# <<< class: {other}\n\n\n", "", s, flags=re.S)
    s = re.sub(r"# (?:>>>|<<<) class: \w+\n", "", s)
    p.write_text(s.replace("SCORE = score_implementation", f"SCORE = score_{paradigm}"))

    p = dest / "tests" / "collect.py"
    s = p.read_text()
    s = re.sub(r"[ \t]*# (?:>>>|<<<) gpu\n", "", s) if a.gpu else re.sub(r"[ \t]*# >>> gpu\n.*?# <<< gpu\n", "", s, flags=re.S)
    p.write_text(s)

    print(f"Created {dest}: {a.task_class}, {a.budget_hours}-hour budget, {'1x H100' if a.gpu else 'CPU'}.")
    print(f"Fill every TODO(author) and {{{{...}}}} field, then:  taskkit.py check {dest} --name {a.name} --class {a.task_class}")
    return 0


def run_check(source: Path, name, task_class) -> tuple[Report, dict[str, bytes]]:
    rep = Report()
    files = read_zip(source, rep) if source.is_file() and source.suffix == ".zip" else read_dir(source, rep)
    check_files(files, name, task_class, rep)
    return rep, files


def cmd_check(a) -> int:
    rep, _ = run_check(Path(a.dir), a.name, a.task_class)
    return 0 if rep.print(a.dir) else 1


def cmd_package(a) -> int:
    root = Path(a.dir)
    rep, files = run_check(root, a.name, a.task_class)
    if not rep.print(a.dir):
        print("Not packaged: fix the errors first.")
        return 1
    slug = tomllib.loads(files["task.toml"].decode())["task"]["name"][len(NAME_PREFIX):]
    out_dir = Path(a.out_dir).resolve() if a.out_dir else root.resolve().parent
    if out_dir == root.resolve() or root.resolve() in out_dir.parents:
        print("--out-dir must be outside the task directory, or the zip would package itself.")
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{slug}-{datetime.date.today():%Y%m%d}.zip"
    if out.exists():
        print(f"{out} already exists; move it away or pick another --out-dir.")
        return 1
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(files):
            info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            mode = 0o755 if os.access(root / path, os.X_OK) else 0o644
            info.external_attr = (stat.S_IFREG | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, files[path])
    back, back_files = run_check(out, a.name, a.task_class)
    if back.errors or back_files != files:
        back.print(str(out))
        out.unlink()
        print("The zip did not read back identically; removed it.")
        return 1
    print(f"Wrote {out} ({len(files)} files). Upload this file.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new", help="create a task directory from the template")
    n.add_argument("dir")
    n.add_argument("--name", required=True, help="the task name you will type on the upload form")
    n.add_argument("--class", dest="task_class", choices=sorted(CLASS_TO_PARADIGM), default="implementation")
    n.add_argument("--budget-hours", type=int, choices=[2, 4, 8, 20], default=8)
    n.add_argument("--language", action="append", required=True, help="a language the agent writes; repeatable")
    n.add_argument("--gpu", action="store_true", help="one H100")
    n.add_argument("--reward-cap", choices=["capped", "uncapped"], help="research only")
    for cmd, helptext in (("check", "partial pre-check of a directory or zip"), ("package", "pre-check, then write <task-name>-YYYYMMDD.zip")):
        c = sub.add_parser(cmd, help=helptext)
        c.add_argument("dir")
        c.add_argument("--name", help="the task name you will type on the upload form")
        c.add_argument("--class", dest="task_class", choices=sorted(CLASS_TO_PARADIGM), help="the class you will pick on the upload form")
        if cmd == "package":
            c.add_argument("--out-dir")
    a = ap.parse_args(argv)
    return {"new": cmd_new, "check": cmd_check, "package": cmd_package}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
