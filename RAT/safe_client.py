import getpass
import socket
import random
import time
import subprocess
import platform
import os

lHost = ""
port = 5050

def send(msg):
    s.send(msg.encode("UTF-8"))

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
            try:
                send("This feature was removed for safety.")
            except:
                pass

        elif Command.startswith("cd "):
            try:
                send("This feature was removed for safety.")
            except:
                pass

        elif Command.startswith("cat "):
            try:
                send("This feature was removed for safety.")
            except:
                pass

        elif Command.startswith("download "):
            try:
                send("This feature was removed for safety.")
            except:
                pass

        elif Command.startswith("exec "):
            try:
                send("This feature was removed for safety.")
            except:
                pass

        else:
            try:
                send("[?]")
            except:
                pass

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

host = socket.gethostname()

connected = False

while connected == False:
    try:
        s.connect((host, port))
        connected = True
    except:
        sleepTime = random.randint(20, 30)
        time.sleep(sleepTime)

getCommand()
