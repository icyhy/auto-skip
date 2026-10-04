"""Real native-message framing and authenticated named-pipe round trip."""
import json
import os
import struct
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ["AUTOSKIP_DATA_DIR"]=str(ROOT/".local"/"bridge-check")
from autoskip.bridge import serve, read_frame

listener=serve(lambda data,reply:reply({"received":data["token"]}))
command=[sys.argv[1]] if len(sys.argv)>1 else [sys.executable,str(ROOT/"native_host.py")]
child=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=os.environ.copy())
try:
    payload=json.dumps({"token":"synthetic-video"}).encode()
    child.stdin.write(struct.pack("<I",len(payload))+payload);child.stdin.flush()
    try:response=json.loads(read_frame(child.stdout))
    except EOFError:
        raise RuntimeError(child.stderr.read().decode(errors="replace")) from None
    assert response=={"received":"synthetic-video"},response
    child.stdin.close()
    child.wait(timeout=5)
    assert child.returncode==0,child.stderr.read().decode(errors="replace")
    print("Native Messaging and named pipe: PASS")
finally:
    if child.poll() is None:child.kill();child.wait()
    listener.close()
