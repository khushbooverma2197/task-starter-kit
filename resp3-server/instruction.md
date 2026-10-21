# RESP3 Redis Protocol Server Implementation

Implement a standalone network daemon in Rust that communicates over TCP using the Redis Serialization Protocol Version 3 (RESP3) specification. The server must bind to `127.0.0.1:6379` and support core key-value storage, numeric arithmetic, hash operations, expiration, and multi-command pipelining over persistent connections.

## Workspace Layout

The root workspace is located in `/app`. It is organized as a standard Rust project:

```text
/app/
├── Cargo.toml          # Rust package manifest
├── src/
│   └── main.rs         # Server entry point and implementation
└── self_check.py       # Baseline validation script for local self-testing
```

You can compile the server at any time using:
```bash
cargo build --release
```
The resulting binary will be generated at `/app/target/release/resp3-server`.

To run the server manually:
```bash
/app/target/release/resp3-server
```
or directly via:
```bash
cargo run --release
```

The workspace is pre-configured with access to Rust's standard library. The evaluation environment operates fully offline (`allow_internet = false`), so all required functionality should be implemented using the standard library.

## Delivery Interface

When the evaluation suite executes, it launches `/app/target/release/resp3-server` as an unprivileged process. Your deliverable must satisfy the following runtime requirements:

* **Binding Address:** Listen on IPv4 address `127.0.0.1` on TCP port `6379`.
* **Connection Handling:** Support concurrent client connections. Handle connections sequentially or via multi-threading so that multiple simultaneous clients can issue queries.
* **Persistent Sessions & Pipelining:** Maintain open TCP connections across multiple commands until the client closes the socket. Support pipelining: multiple commands may be sent in a single TCP packet or stream buffer; each command must be parsed and answered in sequential order.
* **Command Case-Insensitivity:** Command verbs (e.g., `PING`, `ping`, `Ping`, `hgetall`) must be recognized case-insensitively. Keys and values are case-sensitive binary/string data.

## Protocol Specification (RESP3)

Requests sent from clients follow standard RESP array framing:
`*<num_args>\r\n$<arg1_len>\r\n<arg1>\r\n...`

Responses returned to clients must adhere to strict RESP3 wire types:
1. **Simple String:** `+<string>\r\n` (e.g., `+OK\r\n`, `+PONG\r\n`).
2. **Simple Error:** `-<error_string>\r\n` (e.g., `-ERR unknown command 'FOO'\r\n`).
3. **Integer:** `:<signed_64bit_integer>\r\n` (e.g., `:1\r\n`, `:0\r\n`, `:-5\r\n`).
4. **Bulk String:** `$<byte_length>\r\n<raw_bytes>\r\n` (e.g., `$5\r\nhello\r\n`). Empty string is `$0\r\n\r\n`.
5. **Null:** In RESP3, null values are represented by the underscore token: `_\r\n` (do NOT use RESP2 `$-1\r\n`).
6. **Array:** `*<element_count>\r\n<elements...>`
7. **Map:** `%<number_of_key_value_pairs>\r\n<key1><val1><key2><val2>...` where each key and value is a complete RESP item.

## Required Commands

Your server must implement the following commands with exact semantic behavior:

### 1. Connection & Diagnostic Commands
* `PING [message]`
  * If no arguments are provided, reply with Simple String `+PONG\r\n`.
  * If an argument is provided, reply with Bulk String containing the message: `$<len>\r\n<message>\r\n`.
* `ECHO <message>`
  * Reply with Bulk String containing `<message>`. Returns `-ERR wrong number of arguments for 'echo' command\r\n` if argument is missing.

### 2. Key-Value Storage Commands
* `SET <key> <value> [EX <seconds>]`
  * Stores `<value>` at `<key>`.
  * If `EX <seconds>` is provided (case-insensitive flag), the key expires after `<seconds>` seconds.
  * Overwrites any prior value or type associated with `<key>`.
  * Returns `+OK\r\n` on success.
* `GET <key>`
  * Returns the Bulk String value associated with `<key>`.
  * If `<key>` does not exist or has passed its expiration time, returns RESP3 Null `_\r\n`.
  * If the key holds a non-string value (e.g. a hash), returns `-WRONGTYPE Operation against a key holding the wrong kind of value\r\n`.
* `DEL <key> [key ...]`
  * Deletes one or more keys.
  * Returns Integer `:<num_deleted>\r\n` indicating the count of keys that were removed.
* `EXISTS <key> [key ...]`
  * Returns Integer `:<count>\r\n` indicating how many of the specified keys exist and are unexpired.

### 3. Numeric Arithmetic Commands
* `INCR <key>`
  * Increments the integer value of `<key>` by 1.
  * If `<key>` does not exist, it is initialized to `0` before the operation.
  * Returns the new value as Integer `:<new_val>\r\n`.
  * If the value contains non-numeric characters, returns `-ERR value is not an integer or out of range\r\n`.
* `INCRBY <key> <increment>`
  * Increments the integer value of `<key>` by `<increment>` (which may be negative).
  * Returns the new value as Integer `:<new_val>\r\n`.
  * If `<increment>` cannot be parsed as a 64-bit integer, returns `-ERR value is not an integer or out of range\r\n`.

### 4. Multi-Key Operations
* `MSET <key> <value> [<key> <value> ...]`
  * Sets the given keys to their respective values.
  * Returns `+OK\r\n`. If an odd number of arguments is given, returns `-ERR wrong number of arguments for 'mset' command\r\n`.
* `MGET <key> [key ...]`
  * Returns an Array `*<count>\r\n` where each item corresponds to the value of the requested key in order.
  * If a key does not exist or is expired, its entry in the array must be RESP3 Null `_\r\n`.

### 5. Hash Storage Commands
* `HSET <key> <field> <value> [<field> <value> ...]`
  * Sets the specified field(s) to their respective values in the hash stored at `<key>`.
  * Creates the hash if `<key>` does not exist.
  * Returns Integer `:<new_fields_count>\r\n` representing the number of new fields added (excluding fields that were updated with new values).
  * Returns `-WRONGTYPE Operation against a key holding the wrong kind of value\r\n` if `<key>` exists and is not a hash.
* `HGET <key> <field>`
  * Returns the Bulk String value stored at `<field>` in the hash.
  * If `<key>` or `<field>` does not exist, returns RESP3 Null `_\r\n`.
* `HGETALL <key>`
  * Returns a RESP3 Map `%<pair_count>\r\n` containing all field-value pairs in the hash.
  * If `<key>` does not exist, returns `%0\r\n`.

### 6. Unknown Commands & Argument Errors
* Any unrecognized command verb must respond with a Simple Error:
  `-ERR unknown command '<verb>'\r\n`
* If a command receives fewer or more arguments than expected, respond with:
  `-ERR wrong number of arguments for '<verb>' command\r\n`

## Scoring Contract

Grading is evaluated in two sequential stages:

1. **Hard Gates (Score = 0.0):**
   * **Compilation:** `/app/target/release/resp3-server` must compile without errors.
   * **Process Launch:** The server binary must start and bind to `127.0.0.1:6379` within 5 seconds.
   * **Anti-Cheat:** The grader environment and test harness are isolated. Modifying grading infrastructure results in immediate score forfeiture.

2. **Continuous Reward:**
   * After clearing hard gates, the test suite executes 25 sealed protocol tests.
   * Reward formula:
     $$\text{reward} = \frac{\text{cases\_passed}}{\text{cases\_total}}$$
   * Partial credit is granted proportionally. Passing 15 of 25 cases scores `0.60`.
   * A completely untouched workspace scores `0.00`. Passing all 25 cases achieves `1.00`.

## Local Self-Check

A validation script is provided in `/app/self_check.py`. It runs smoke tests against a running server to verify socket connectivity, ping/echo semantics, basic key-value operations, and RESP3 framing:

```bash
# In terminal 1:
cargo run --release

# In terminal 2:
python3 /app/self_check.py
```

The grading test suite tests additional edge cases including multi-client concurrency, pipelined buffers, TTL boundary expiration, and hash aggregate types.

## Time Budget & Pacing

Your time budget for this task is **8 hours**. 

The platform runs a background countdown daemon located at `/app/.timer`:
* Check remaining time at any point:
  ```bash
  cat /app/.timer/remaining_secs
  ```
* Milestone alert files are touched automatically as your budget elapses:
  * `/app/.timer/alert_30min` (30 minutes remaining)
  * `/app/.timer/alert_10min` (10 minutes remaining)
  * `/app/.timer/alert_5min` (5 minutes remaining)

Do not rely on host system clocks or timestamps; use `/app/.timer/remaining_secs` to pace long compilation or testing cycles.

## Operating Rules

* **Work Autonomously:** Do not stop to prompt for guidance or request external clarifications.
* **Keep the Build Green:** Always keep the codebase in a compilable state. Incomplete features that compile and pass partial tests score partial credit; broken code that fails compilation scores exactly zero.
* **Prioritize High-Yield Commands:** Implement core wire parsing and basic commands (`PING`, `ECHO`, `SET`, `GET`) first before moving to hashes, TTL expiration, and pipelining.
* **Test Incrementally:** Re-run `/app/self_check.py` frequently to guard against regressions as you add new command handlers.
