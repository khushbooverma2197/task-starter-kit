use std::net::TcpListener;

fn main() {
    let listener = match TcpListener::bind("127.0.0.1:6379") {
        Ok(l) => l,
        Err(e) => {
            eprintln!("Failed to bind to 127.0.0.1:6379: {}", e);
            std::process::exit(1);
        }
    };

    println!("RESP3 Server starting on 127.0.0.1:6379");

    for stream in listener.incoming() {
        match stream {
            Ok(_socket) => {
                // Skeleton stub: socket connection accepted, protocol handler not yet implemented.
            }
            Err(e) => {
                eprintln!("Connection failed: {}", e);
            }
        }
    }
}
