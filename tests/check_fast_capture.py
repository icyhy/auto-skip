"""Read-only live capture timing check. Does not install hooks or send input."""
import json
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from autoskip.windows import WindowBinding
from autoskip.capture import WindowCapture
from autoskip.learning import QuickSkip, ScreenshotAnalyzer

binding=WindowBinding();binding.discover()
if not binding.target:raise SystemExit("No unambiguous Douyin window available")
capture=WindowCapture()
try:
    capture.snapshot(binding.target[0])
    events=[]
    gate=QuickSkip(capture.freeze,lambda event,text:events.append((event,text)))
    gate.configure(binding.target,True,5)
    at=time.monotonic()
    gate.navigation("wheel",at-3)
    started=time.perf_counter()
    gate.navigation("wheel",at)
    freeze_ms=(time.perf_counter()-started)*1000
    event,message=events[-1]
    assert event is not None,message
    image_at=event.frame[1]
    started=time.perf_counter()
    analyzer=ScreenshotAnalyzer()
    result=analyzer.analyze(event)
    cold_seconds=time.perf_counter()-started
    started=time.perf_counter()
    analyzer.analyze(event)
    print(json.dumps({"freeze_ms":round(freeze_ms,3),"frame_age_ms":round((at-image_at)*1000,1),
        "first_parse_seconds":round(cold_seconds,2),"warm_parse_seconds":round(time.perf_counter()-started,2),"author_found":bool(result["author"]),
        "title_found":bool(result["title"]),"video_key_created":result["target"].startswith("dy:caption:")}),flush=True)
finally:capture.close()
