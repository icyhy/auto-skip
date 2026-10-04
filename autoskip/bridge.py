"""Chrome Native Messaging <-> authenticated, per-user Windows named pipe."""
import json
import os
import re
import struct
import sys
import threading
import uuid
from multiprocessing.connection import Listener, Client
from pathlib import Path

HOST = "com.autoskip.bridge"
LIMIT = 1_000_000


def pipe_settings(create=False):
    from .windows import data_dir, load_secret, save_secret
    path = data_dir() / "bridge.json"
    if create and not path.exists():
        save_secret("bridge", os.urandom(32))
        path.write_text(json.dumps({"pipe": r"\\.\pipe\AutoSkip-" + uuid.uuid4().hex}), encoding="utf-8")
    data = json.loads(path.read_text(encoding="utf-8"))
    key = load_secret("bridge")
    if len(key) != 32 or not data["pipe"].startswith(r"\\.\pipe\AutoSkip-"):
        raise ValueError("无效的本地连接配置")
    return data["pipe"], key


def serve(on_message):
    address, authkey = pipe_settings(True)
    listener = Listener(address, family="AF_PIPE", authkey=authkey)
    def client_loop(conn):
        send_lock = threading.Lock()
        def reply(message):
            try:
                raw = json.dumps(message, ensure_ascii=False).encode("utf-8")
                with send_lock:
                    conn.send_bytes(raw)
            except (OSError, EOFError):
                pass
        try:
            while True:
                data = json.loads(conn.recv_bytes(LIMIT))
                if isinstance(data, dict):
                    on_message(data, reply)
        except (OSError, EOFError, ValueError):
            pass
        finally:
            conn.close()
    def accept():
        while True:
            try:
                conn = listener.accept()
                threading.Thread(target=client_loop, args=(conn,), daemon=True).start()
            except (OSError, EOFError):
                break
            except Exception:
                continue
    threading.Thread(target=accept, daemon=True).start()
    return listener


def read_exact(stream, size):
    chunks = bytearray()
    while len(chunks) < size:
        part = stream.read(size - len(chunks))
        if not part:
            raise EOFError()
        chunks.extend(part)
    return bytes(chunks)


def read_frame(stream):
    length, = struct.unpack("<I", read_exact(stream, 4))
    if not 0 < length <= LIMIT:
        raise ValueError("Native message exceeds limit")
    raw = read_exact(stream, length)
    if not isinstance(json.loads(raw), dict):
        raise ValueError("Expected object")
    return raw


def native_main():
    import msvcrt
    msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
    msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    try:
        address, key = pipe_settings()
        conn = Client(address, family="AF_PIPE", authkey=key)
    except (OSError, ValueError) as error:
        print("Auto Skip local connection unavailable: " + type(error).__name__, file=sys.stderr)
        return 1
    def output():
        try:
            while True:
                data = conn.recv_bytes(LIMIT)
                sys.stdout.buffer.write(struct.pack("<I", len(data)) + data)
                sys.stdout.buffer.flush()
        except (OSError, EOFError):
            os._exit(0)
    threading.Thread(target=output, daemon=True).start()
    try:
        while True:
            conn.send_bytes(read_frame(sys.stdin.buffer))
    except (OSError, EOFError, ValueError):
        conn.close()
    return 0


def register_host(extension_id):
    import winreg
    from .windows import data_dir
    if not re.fullmatch("[a-p]{32}", extension_id):
        raise ValueError("扩展 ID 应为 32 位 a-p 字母")
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).parent / "bridge" / "AutoSkipBridge.exe"
        if not executable.exists():
            raise ValueError("找不到 AutoSkipBridge.exe，请保持发布目录完整")
    else:
        # Chrome accepts a Windows batch launcher for development native hosts.
        executable = data_dir() / "native-host.cmd"
        entry = Path(__file__).resolve().parents[1] / "native_host.py"
        executable.write_text(f'@echo off\r\n"{sys.executable}" "{entry}"\r\n', encoding="utf-8")
    manifest = data_dir() / "native-host.json"
    manifest.write_text(json.dumps({"name": HOST, "description": "Auto Skip 本地连接",
        "path": str(executable), "type": "stdio", "allowed_origins": [f"chrome-extension://{extension_id}/"]},
        ensure_ascii=False), encoding="utf-8")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Software\\Google\\Chrome\\NativeMessagingHosts\\" + HOST) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(manifest))
