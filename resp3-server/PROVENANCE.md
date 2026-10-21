# Provenance

## Source

This task is derived directly from the official Redis RESP3 specification hosted in the Redis specifications repository (https://github.com/redis/redis-specifications/blob/master/protocol/RESP3.md, commit `1444bf485e94b29bbecf0b48f9d0c24c25f4639d`) and the protocol compliance tests in the official Redis server repository (https://github.com/redis/redis, tag `7.2.4`). RESP3 is the modern revision of the Redis serialization protocol, introducing distinct semantic wire types for nulls, booleans, maps, sets, and error responses.

## Extraction

The environment provides a clean Rust workspace in `/app` containing a cargo package manifest and a stub binary skeleton that binds to a TCP socket without implementing protocol parsing. The sealed test harness under `tests/` contains a comprehensive differential test suite executing 25 distinct protocol verification scenarios. These scenarios test client connection handling, CRLF token framing, multi-byte bulk strings, aggregate types (RESP3 maps and arrays), null return values (`_\r\n`), TTL expiration (`EX`), multi-key operations (`MGET`/`MSET`), and hash operations (`HSET`/`HGETALL`). The reference solution in `solution/` provides a complete, self-contained server written using Rust's standard library networking primitives.

## Why it is real work

Building protocol-conforming network servers against published wire specifications is a staple systems engineering task. In production systems, engineers frequently implement lightweight, protocol-compatible proxies, in-memory caches, or mock daemons that speak the Redis wire protocol without the overhead of running a full Redis cluster. Doing so requires handling subtle stream framing rules, pipelined network requests over persistent connections, command parsing, and accurate type serialization according to spec.
