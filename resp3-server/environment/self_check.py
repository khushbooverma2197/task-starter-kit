#!/usr/bin/env python3
"""Local baseline validation check for resp3-server.

Tests connection establishment, basic RESP3 wire framing, and standard operations.
Run this script while the server is active on 127.0.0.1:6379:
    python3 /app/self_check.py
"""

import socket
import sys
import time

def encode_resp_cmd(*args):
    out = [f"*{len(args)}\r\n".encode("utf-8")]
    for arg in args:
        data = str(arg).encode("utf-8")
        out.append(f"${len(data)}\r\n".encode("utf-8"))
        out.append(data + b"\r\n")
    return b"".join(out)

def read_response(s, timeout=2.0):
    s.settimeout(timeout)
    buf = b""
    while True:
        try:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
            # Check for completed simple frames
            if buf.endswith(b"\r\n"):
                break
        except socket.timeout:
            break
    return buf

def run_tests():
    print("[self_check] Connecting to 127.0.0.1:6379...")
    try:
        s = socket.create_connection(("127.0.0.1", 6379), timeout=3.0)
    except Exception as e:
        print(f"[self_check] FAILED: Could not connect to 127.0.0.1:6379: {e}")
        return False

    cases = [
        ("PING", encode_resp_cmd("PING"), b"+PONG\r\n"),
        ("ECHO", encode_resp_cmd("ECHO", "hello"), b"$5\r\nhello\r\n"),
        ("SET", encode_resp_cmd("SET", "sample_key", "sample_val"), b"+OK\r\n"),
        ("GET", encode_resp_cmd("GET", "sample_key"), b"$10\r\nsample_val\r\n"),
        ("GET_NONEXISTENT", encode_resp_cmd("GET", "nonexistent_key"), b"_\r\n"),
        ("INCR", encode_resp_cmd("INCR", "counter_key"), b":1\r\n"),
        ("DEL", encode_resp_cmd("DEL", "sample_key", "counter_key"), b":2\r\n"),
    ]

    passed = 0
    total = len(cases)

    for name, payload, expected in cases:
        try:
            s.sendall(payload)
            res = read_response(s)
            if res == expected:
                print(f"  [PASS] {name}")
                passed += 1
            else:
                print(f"  [FAIL] {name} - Expected {expected!r}, got {res!r}")
        except Exception as e:
            print(f"  [ERROR] {name} - Socket exception: {e}")

    s.close()
    print(f"\n[self_check] Result: {passed}/{total} self-checks passed.")
    return passed == total

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
