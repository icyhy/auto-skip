"""Live bound-window smoke check. Pass --wheel to verify one directed scroll."""
import sys
import time
import json
from pathlib import Path
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from autoskip import windows
from autoskip.desktop import DesktopReader

binding=windows.WindowBinding();binding.discover()
if not binding.target:raise SystemExit("No unambiguous Douyin window")
reader=DesktopReader(SimpleNamespace(hwnd=0,region=None,last_next=0))
config={"desktop_target":binding.target,"mode":"auto"}
with ThreadPoolExecutor(max_workers=1) as worker:
    try:
        started=time.perf_counter();before,before_image,_=worker.submit(reader.read,config).result(timeout=15)
        assert before and before.active and len(before.text.strip())>=10
        metrics={"backend":reader.fast_ocr.backend,"full_read_seconds":round(time.perf_counter()-started,3),
                 "ocr_ms":round(reader.fast_ocr.last_ms,1),"caption_found":bool(before.author and before.title)}
        if "--wheel" in sys.argv:
            foreground=windows.foreground()
            metrics["wheel_posted"]=windows.next_video(binding.target)
            config["video_switch_at"]=time.monotonic()
            time.sleep(1)
            after,after_image,_=worker.submit(reader.read,config).result(timeout=15)
            (ROOT/".local"/"auto-before.jpg").write_bytes(before_image)
            (ROOT/".local"/"auto-after.jpg").write_bytes(after_image)
            metrics["content_changed"]=bool(after and before.token!=after.token)
            metrics["focus_unchanged"]=windows.foreground()==foreground
            assert metrics["wheel_posted"] and metrics["content_changed"] and metrics["focus_unchanged"]
        print(json.dumps(metrics),flush=True)
    finally:worker.submit(reader.close).result(timeout=10)
