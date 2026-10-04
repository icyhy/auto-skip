import os
from pathlib import Path
import subprocess
import json
import sys

root=Path(__file__).resolve().parents[1]
output=root/".local"/"frozen-overlay.png"
if output.exists():output.unlink()
output.with_suffix(".ocr.json").unlink(missing_ok=True)
env=dict(os.environ,QT_QPA_PLATFORM="offscreen",AUTOSKIP_DATA_DIR=str(root/".local"/"frozen-preview"))
startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
executable=Path(sys.argv[1]) if len(sys.argv)>1 else root/"dist"/"AutoSkip"/"AutoSkip.exe"
result=subprocess.run([str(executable),"--preview",str(output),"--check-ocr"],
                      env=env,startupinfo=startup,capture_output=True,timeout=20)
assert result.returncode==0,result.stderr.decode(errors="replace")
assert output.exists() and output.stat().st_size>1000
report=json.loads(output.with_suffix(".ocr.json").read_text(encoding="utf-8"))
assert report["ok"] and report["backend"]=="Windows OCR",report
print("Packaged Windows OCR: PASS",round(report["ms"],1),"ms")
print("Standalone executable startup and render: PASS")
