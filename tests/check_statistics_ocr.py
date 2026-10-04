"""Native metadata recognition without a timer, followed by switch statistics."""
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw, ImageFont
from autoskip.fast_ocr import FastOCR
from autoskip.desktop import caption_fields
from autoskip.core import Snapshot
from autoskip.store import Store
from autoskip.statistics import WatchTracker

font=ImageFont.truetype(str(Path(os.environ["WINDIR"])/"Fonts"/"msyh.ttc"),28)
image=Image.new("RGB",(800,400),"white")
ImageDraw.Draw(image).text((20,20),"@统计作者\n手机数码评测",font=font,fill="black")
ocr=FastOCR();author,title=caption_fields(ocr.read(image))
assert "统计作者" in author and "手机" in title,(author,title)
assert not hasattr(ocr,"read_timer")
store=Store(":memory:")
try:
    tracker=WatchTracker(store)
    snap=Snapshot("desktop","test","v",author=author,title=title)
    tracker.observe(snap,100);tracker.switch("desktop","test",105)
    tracker.observe(snap,108);tracker.switch("desktop","test",115)
    assert store.statistics()["count"]==1
    assert store.statistics()["seconds"]==10
    assert store.statistics()["categories"][0]["category"]=="数码科技"
finally:store.db.close()
print("Native OCR metadata with no playback timer -> 10-second switch statistics: PASS")
