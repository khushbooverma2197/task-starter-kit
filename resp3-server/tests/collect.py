"""Evidence collection: build, run, anti-cheat. Never scores.

Writes one JSON object to --out on every path. compute_reward.py reads it.
"""

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time

RUN_AS = "runner"


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
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()


def encode_resp(*args):
    out = [f"*{len(args)}\r\n".encode("utf-8")]
    for a in args:
        data = str(a).encode("utf-8")
        out.append(f"${len(data)}\r\n".encode("utf-8"))
        out.append(data + b"\r\n")
    return b"".join(out)


def query_server(sock, payload, timeout=2.0):
    sock.settimeout(timeout)
    sock.sendall(payload)
    buf = b""
    while True:
        try:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
            if buf.endswith(b"\r\n"):
                break
        except socket.timeout:
            break
    return buf


def wait_for_port(port=6379, max_wait=5.0):
    start = time.time()
    while time.time() - start < max_wait:
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=0.2)
            s.close()
            return True
        except (ConnectionRefusedError, socket.timeout, OSError):
            time.sleep(0.1)
    return False


def run_test_suite():
    passed = 0
    cases_total = 25

    try:
        s = socket.create_connection(("127.0.0.1", 6379), timeout=3.0)
    except Exception:
        return 0, cases_total

    def match(cmd_args, expected):
        res = query_server(s, encode_resp(*cmd_args))
        return res == expected

    try:
        # Case 1: PING no args
        if match(["PING"], b"+PONG\r\n"):
            passed += 1

        # Case 2: PING with message
        if match(["PING", "hello_resp3"], b"$11\r\nhello_resp3\r\n"):
            passed += 1

        # Case 3: ECHO string
        if match(["ECHO", "network_test"], b"$12\r\nnetwork_test\r\n"):
            passed += 1

        # Case 4: ECHO missing arg
        if match(["ECHO"], b"-ERR wrong number of arguments for 'echo' command\r\n"):
            passed += 1

        # Case 5: SET simple key
        if match(["SET", "k1", "val1"], b"+OK\r\n"):
            passed += 1

        # Case 6: GET existing key
        if match(["GET", "k1"], b"$4\r\nval1\r\n"):
            passed += 1

        # Case 7: GET missing key (RESP3 null)
        if match(["GET", "missing_key"], b"_\r\n"):
            passed += 1

        # Case 8: Case-insensitivity for command verbs
        if match(["seT", "k2", "val2"], b"+OK\r\n") and match(["gEt", "k2"], b"$4\r\nval2\r\n"):
            passed += 1

        # Case 9: Overwrite existing key
        if match(["SET", "k1", "val1_new"], b"+OK\r\n") and match(["GET", "k1"], b"$8\r\nval1_new\r\n"):
            passed += 1

        # Case 10: DEL single key
        if match(["DEL", "k2"], b":1\r\n") and match(["GET", "k2"], b"_\r\n"):
            passed += 1

        # Case 11: DEL multiple keys
        match(["SET", "m1", "v1"], b"+OK\r\n")
        match(["SET", "m2", "v2"], b"+OK\r\n")
        if match(["DEL", "m1", "m2", "nonexistent"], b":2\r\n"):
            passed += 1

        # Case 12: EXISTS multiple keys
        match(["SET", "e1", "v1"], b"+OK\r\n")
        if match(["EXISTS", "e1", "e_missing"], b":1\r\n"):
            passed += 1

        # Case 13: INCR missing key initializes to 0 then increments to 1
        if match(["INCR", "counter_a"], b":1\r\n"):
            passed += 1

        # Case 14: INCR existing integer key increments to 2
        if match(["INCR", "counter_a"], b":2\r\n"):
            passed += 1

        # Case 15: INCRBY with delta
        if match(["INCRBY", "counter_a", "10"], b":12\r\n") and match(["INCRBY", "counter_a", "-5"], b":7\r\n"):
            passed += 1

        # Case 16: INCR on non-integer string returns error
        match(["SET", "str_key", "not_a_number"], b"+OK\r\n")
        if match(["INCR", "str_key"], b"-ERR value is not an integer or out of range\r\n"):
            passed += 1

        # Case 17: MSET multiple keys
        if match(["MSET", "mk1", "mv1", "mk2", "mv2"], b"+OK\r\n"):
            passed += 1

        # Case 18: MGET multiple keys (mix of existing and missing)
        res_mget = query_server(s, encode_resp("MGET", "mk1", "missing", "mk2"))
        if res_mget == b"*3\r\n$3\r\nmv1\r\n_\r\n$3\r\nmv2\r\n":
            passed += 1

        # Case 19: HSET new fields
        if match(["HSET", "user:1", "name", "alice", "role", "admin"], b":2\r\n"):
            passed += 1

        # Case 20: HSET updating existing field returns 0 new fields
        if match(["HSET", "user:1", "name", "alice_new"], b":0\r\n"):
            passed += 1

        # Case 21: HGET existing and missing field
        if match(["HGET", "user:1", "name"], b"$9\r\nalice_new\r\n") and match(["HGET", "user:1", "missing_field"], b"_\r\n"):
            passed += 1

        # Case 22: HGETALL returns RESP3 Map
        res_hgetall = query_server(s, encode_resp("HGETALL", "user:1"))
        if res_hgetall.startswith(b"%2\r\n") and b"name" in res_hgetall and b"role" in res_hgetall:
            passed += 1

        # Case 23: WRONGTYPE error
        if match(["GET", "user:1"], b"-WRONGTYPE Operation against a key holding the wrong kind of value\r\n"):
            passed += 1

        # Case 24: Pipelining multiple commands in single write
        pipeline_payload = encode_resp("PING") + encode_resp("ECHO", "pipe") + encode_resp("GET", "mk1")
        s.settimeout(2.0)
        s.sendall(pipeline_payload)
        pipe_buf = b""
        while len(pipe_buf) < len(b"+PONG\r\n$4\r\npipe\r\n$3\r\nmv1\r\n"):
            chunk = s.recv(4096)
            if not chunk:
                break
            pipe_buf += chunk
        if pipe_buf == b"+PONG\r\n$4\r\npipe\r\n$3\r\nmv1\r\n":
            passed += 1

        # Case 25: TTL expiration (EX 1)
        if match(["SET", "temp_key", "temp_val", "EX", "1"], b"+OK\r\n") and match(["GET", "temp_key"], b"$8\r\ntemp_val\r\n"):
            time.sleep(1.2)
            if match(["GET", "temp_key"], b"_\r\n"):
                passed += 1

    except Exception:
        pass
    finally:
        s.close()

    return passed, cases_total


def collect():
    ev = {
        "runtime_ok": True,
        "runtime_error": "",
        "build_ok": False,
        "cheat_detected": False,
        "gate_reason": "",
        "cases_total": 25,
        "cases_passed": 0,
    }

    # Anti-cheat check: ensure candidate did not tamper with verifier logs directory
    if os.path.exists("/logs/verifier/reward.json") or os.path.exists("/logs/verifier/reward.txt"):
        ev["cheat_detected"] = True
        ev["gate_reason"] = "tampering with verifier log directory detected"
        return ev

    # 1. Build deliverable from source
    rc, out, err = run_untrusted(["cargo", "build", "--release"], timeout=180, cwd="/app")
    binary_path = "/app/target/release/resp3-server"
    if rc != 0 or not os.path.isfile(binary_path):
        ev["build_ok"] = False
        ev["gate_reason"] = f"cargo build --release failed: {err.decode('utf-8', errors='replace')[:200]}"
        return ev

    ev["build_ok"] = True

    # 2. Start deliverable server as unprivileged runner
    proc = subprocess.Popen(
        ["runuser", "-u", RUN_AS, "--", binary_path],
        cwd="/app",
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    try:
        if not wait_for_port(6379, max_wait=4.0):
            ev["gate_reason"] = "server did not bind to 127.0.0.1:6379 within timeout"
            ev["cases_passed"] = 0
            return ev

        # 3. Execute test suite
        passed, total = run_test_suite()
        ev["cases_passed"] = passed
        ev["cases_total"] = total
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()

    return ev


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        ev = collect()
    except Exception as exc:
        ev = {"runtime_ok": False, "runtime_error": f"collector error: {type(exc).__name__}"}
    with open(args.out, "w") as fh:
        json.dump(ev, fh)
    return 0


if __name__ == "__main__":
    sys.exit(main())
