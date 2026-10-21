use std::collections::HashMap;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

#[derive(Clone)]
enum Value {
    Str(String),
    Hash(HashMap<String, String>),
}

struct Entry {
    value: Value,
    expires_at: Option<Instant>,
}

impl Entry {
    fn is_expired(&self) -> bool {
        if let Some(exp) = self.expires_at {
            Instant::now() >= exp
        } else {
            false
        }
    }
}

type Store = Arc<Mutex<HashMap<String, Entry>>>;

fn main() {
    let listener = match TcpListener::bind("127.0.0.1:6379") {
        Ok(l) => l,
        Err(e) => {
            eprintln!("Failed to bind to 127.0.0.1:6379: {}", e);
            std::process::exit(1);
        }
    };

    println!("RESP3 Server listening on 127.0.0.1:6379");
    let store: Store = Arc::new(Mutex::new(HashMap::new()));

    for stream in listener.incoming() {
        match stream {
            Ok(stream) => {
                let store_clone = Arc::clone(&store);
                thread::spawn(move || {
                    handle_client(stream, store_clone);
                });
            }
            Err(e) => {
                eprintln!("Connection failed: {}", e);
            }
        }
    }
}

fn handle_client(mut stream: TcpStream, store: Store) {
    let mut buffer = Vec::new();
    let mut temp = [0u8; 4096];

    loop {
        let bytes_read = match stream.read(&mut temp) {
            Ok(0) => break, // Connection closed by client
            Ok(n) => n,
            Err(_) => break,
        };

        buffer.extend_from_slice(&temp[..bytes_read]);

        while !buffer.is_empty() {
            let mut cursor = 0;
            match parse_resp_command(&buffer, &mut cursor) {
                Some(args) => {
                    let response = execute_command(&args, &store);
                    if stream.write_all(&response).is_err() {
                        return;
                    }
                    let _ = stream.flush();
                    buffer.drain(..cursor);
                }
                None => {
                    // Need more data from client
                    break;
                }
            }
        }
    }
}

fn parse_resp_command(buffer: &[u8], cursor: &mut usize) -> Option<Vec<String>> {
    if buffer.is_empty() {
        return None;
    }

    if buffer[0] == b'*' {
        // Array framing: *<count>\r\n
        let line_end = find_crlf(buffer, 0)?;
        let count_str = std::str::from_utf8(&buffer[1..line_end]).ok()?;
        let num_args: usize = count_str.parse().ok()?;
        let mut pos = line_end + 2;

        let mut args = Vec::with_capacity(num_args);
        for _ in 0..num_args {
            if pos >= buffer.len() || buffer[pos] != b'$' {
                return None;
            }
            let len_end = find_crlf(buffer, pos)?;
            let len_str = std::str::from_utf8(&buffer[pos + 1..len_end]).ok()?;
            let arg_len: usize = len_str.parse().ok()?;

            pos = len_end + 2;
            if pos + arg_len + 2 > buffer.len() {
                return None;
            }

            let arg_bytes = &buffer[pos..pos + arg_len];
            let arg = String::from_utf8_lossy(arg_bytes).to_string();
            args.push(arg);

            pos += arg_len + 2; // skip arg and \r\n
        }

        *cursor = pos;
        Some(args)
    } else {
        // Simple inline command format (e.g. PING\r\n)
        let line_end = find_crlf(buffer, 0)?;
        let line = std::str::from_utf8(&buffer[0..line_end]).ok()?;
        *cursor = line_end + 2;
        let args: Vec<String> = line.split_whitespace().map(|s| s.to_string()).collect();
        if args.is_empty() {
            None
        } else {
            Some(args)
        }
    }
}

fn find_crlf(buf: &[u8], start: usize) -> Option<usize> {
    if start >= buf.len() {
        return None;
    }
    for i in start..buf.len().saturating_sub(1) {
        if buf[i] == b'\r' && buf[i + 1] == b'\n' {
            return Some(i);
        }
    }
    None
}

fn execute_command(args: &[String], store: &Store) -> Vec<u8> {
    if args.is_empty() {
        return b"-ERR empty command\r\n".to_vec();
    }

    let cmd = args[0].to_uppercase();
    let rest = &args[1..];

    match cmd.as_str() {
        "PING" => {
            if rest.is_empty() {
                b"+PONG\r\n".to_vec()
            } else if rest.len() == 1 {
                format_bulk_string(&rest[0])
            } else {
                b"-ERR wrong number of arguments for 'ping' command\r\n".to_vec()
            }
        }
        "ECHO" => {
            if rest.len() == 1 {
                format_bulk_string(&rest[0])
            } else {
                b"-ERR wrong number of arguments for 'echo' command\r\n".to_vec()
            }
        }
        "SET" => {
            if rest.len() < 2 {
                return b"-ERR wrong number of arguments for 'set' command\r\n".to_vec();
            }
            let key = &rest[0];
            let val = &rest[1];
            let mut expires_at = None;

            if rest.len() >= 4 && rest[2].to_uppercase() == "EX" {
                if let Ok(secs) = rest[3].parse::<u64>() {
                    expires_at = Some(Instant::now() + Duration::from_secs(secs));
                } else {
                    return b"-ERR value is not an integer or out of range\r\n".to_vec();
                }
            }

            let mut map = store.lock().unwrap();
            map.insert(
                key.clone(),
                Entry {
                    value: Value::Str(val.clone()),
                    expires_at,
                },
            );
            b"+OK\r\n".to_vec()
        }
        "GET" => {
            if rest.len() != 1 {
                return b"-ERR wrong number of arguments for 'get' command\r\n".to_vec();
            }
            let key = &rest[0];
            let mut map = store.lock().unwrap();
            if let Some(entry) = map.get(key) {
                if entry.is_expired() {
                    map.remove(key);
                    b"_\r\n".to_vec()
                } else {
                    match &entry.value {
                        Value::Str(s) => format_bulk_string(s),
                        Value::Hash(_) => {
                            b"-WRONGTYPE Operation against a key holding the wrong kind of value\r\n".to_vec()
                        }
                    }
                }
            } else {
                b"_\r\n".to_vec()
            }
        }
        "DEL" => {
            if rest.is_empty() {
                return b"-ERR wrong number of arguments for 'del' command\r\n".to_vec();
            }
            let mut map = store.lock().unwrap();
            let mut count = 0;
            for key in rest {
                if let Some(entry) = map.get(key) {
                    if !entry.is_expired() {
                        count += 1;
                    }
                    map.remove(key);
                }
            }
            format!(":{}\r\n", count).into_bytes()
        }
        "EXISTS" => {
            if rest.is_empty() {
                return b"-ERR wrong number of arguments for 'exists' command\r\n".to_vec();
            }
            let mut map = store.lock().unwrap();
            let mut count = 0;
            for key in rest {
                if let Some(entry) = map.get(key) {
                    if entry.is_expired() {
                        map.remove(key);
                    } else {
                        count += 1;
                    }
                }
            }
            format!(":{}\r\n", count).into_bytes()
        }
        "INCR" => {
            if rest.len() != 1 {
                return b"-ERR wrong number of arguments for 'incr' command\r\n".to_vec();
            }
            incr_by(store, &rest[0], 1)
        }
        "INCRBY" => {
            if rest.len() != 2 {
                return b"-ERR wrong number of arguments for 'incrby' command\r\n".to_vec();
            }
            match rest[1].parse::<i64>() {
                Ok(delta) => incr_by(store, &rest[0], delta),
                Err(_) => b"-ERR value is not an integer or out of range\r\n".to_vec(),
            }
        }
        "MSET" => {
            if rest.is_empty() || rest.len() % 2 != 0 {
                return b"-ERR wrong number of arguments for 'mset' command\r\n".to_vec();
            }
            let mut map = store.lock().unwrap();
            for chunk in rest.chunks(2) {
                map.insert(
                    chunk[0].clone(),
                    Entry {
                        value: Value::Str(chunk[1].clone()),
                        expires_at: None,
                    },
                );
            }
            b"+OK\r\n".to_vec()
        }
        "MGET" => {
            if rest.is_empty() {
                return b"-ERR wrong number of arguments for 'mget' command\r\n".to_vec();
            }
            let mut map = store.lock().unwrap();
            let mut out = format!("*{}\r\n", rest.len()).into_bytes();
            for key in rest {
                let mut found = None;
                if let Some(entry) = map.get(key) {
                    if entry.is_expired() {
                        map.remove(key);
                    } else if let Value::Str(s) = &entry.value {
                        found = Some(s.clone());
                    }
                }
                match found {
                    Some(s) => out.extend_from_slice(&format_bulk_string(&s)),
                    None => out.extend_from_slice(b"_\r\n"),
                }
            }
            out
        }
        "HSET" => {
            if rest.len() < 3 || (rest.len() - 1) % 2 != 0 {
                return b"-ERR wrong number of arguments for 'hset' command\r\n".to_vec();
            }
            let key = &rest[0];
            let mut map = store.lock().unwrap();

            let mut hash_map = match map.get(key) {
                Some(entry) => {
                    if entry.is_expired() {
                        HashMap::new()
                    } else {
                        match &entry.value {
                            Value::Hash(h) => h.clone(),
                            _ => {
                                return b"-WRONGTYPE Operation against a key holding the wrong kind of value\r\n".to_vec();
                            }
                        }
                    }
                }
                None => HashMap::new(),
            };

            let mut new_fields = 0;
            for chunk in rest[1..].chunks(2) {
                let field = &chunk[0];
                let val = &chunk[1];
                if !hash_map.contains_key(field) {
                    new_fields += 1;
                }
                hash_map.insert(field.clone(), val.clone());
            }

            map.insert(
                key.clone(),
                Entry {
                    value: Value::Hash(hash_map),
                    expires_at: None,
                },
            );
            format!(":{}\r\n", new_fields).into_bytes()
        }
        "HGET" => {
            if rest.len() != 2 {
                return b"-ERR wrong number of arguments for 'hget' command\r\n".to_vec();
            }
            let key = &rest[0];
            let field = &rest[1];
            let mut map = store.lock().unwrap();

            if let Some(entry) = map.get(key) {
                if entry.is_expired() {
                    map.remove(key);
                    b"_\r\n".to_vec()
                } else {
                    match &entry.value {
                        Value::Hash(h) => match h.get(field) {
                            Some(v) => format_bulk_string(v),
                            None => b"_\r\n".to_vec(),
                        },
                        _ => {
                            b"-WRONGTYPE Operation against a key holding the wrong kind of value\r\n".to_vec()
                        }
                    }
                }
            } else {
                b"_\r\n".to_vec()
            }
        }
        "HGETALL" => {
            if rest.len() != 1 {
                return b"-ERR wrong number of arguments for 'hgetall' command\r\n".to_vec();
            }
            let key = &rest[0];
            let mut map = store.lock().unwrap();

            if let Some(entry) = map.get(key) {
                if entry.is_expired() {
                    map.remove(key);
                    b"%0\r\n".to_vec()
                } else {
                    match &entry.value {
                        Value::Hash(h) => {
                            let mut out = format!("%{}\r\n", h.len()).into_bytes();
                            for (k, v) in h {
                                out.extend_from_slice(&format_bulk_string(k));
                                out.extend_from_slice(&format_bulk_string(v));
                            }
                            out
                        }
                        _ => {
                            b"-WRONGTYPE Operation against a key holding the wrong kind of value\r\n".to_vec()
                        }
                    }
                }
            } else {
                b"%0\r\n".to_vec()
            }
        }
        _ => format!("-ERR unknown command '{}'\r\n", args[0]).into_bytes(),
    }
}

fn incr_by(store: &Store, key: &str, delta: i64) -> Vec<u8> {
    let mut map = store.lock().unwrap();
    let current_val = match map.get(key) {
        Some(entry) => {
            if entry.is_expired() {
                0i64
            } else {
                match &entry.value {
                    Value::Str(s) => match s.parse::<i64>() {
                        Ok(n) => n,
                        Err(_) => {
                            return b"-ERR value is not an integer or out of range\r\n".to_vec();
                        }
                    },
                    _ => {
                        return b"-WRONGTYPE Operation against a key holding the wrong kind of value\r\n".to_vec();
                    }
                }
            }
        }
        None => 0i64,
    };

    let new_val = match current_val.checked_add(delta) {
        Some(v) => v,
        None => return b"-ERR increment or decrement would overflow\r\n".to_vec(),
    };

    map.insert(
        key.to_string(),
        Entry {
            value: Value::Str(new_val.to_string()),
            expires_at: None,
        },
    );

    format!(":{}\r\n", new_val).into_bytes()
}

fn format_bulk_string(s: &str) -> Vec<u8> {
    let bytes = s.as_bytes();
    format!("${}\r\n{}\r\n", bytes.len(), s).into_bytes()
}
