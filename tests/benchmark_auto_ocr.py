"""Read-only benchmark: the same bound-window frame, no input or cloud requests."""
import json
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from autoskip.windows import WindowBinding
from autoskip.capture import WindowCapture
from autoskip.desktop import caption_fields
from autoskip.fast_ocr import FastOCR
from rapidocr_onnxruntime import RapidOCR
import numpy as np

binding=WindowBinding();binding.discover()
if not binding.target:raise SystemExit("No unambiguous Douyin window")
cap=WindowCapture()
try:image,_=cap.snapshot(binding.target[0])
finally:cap.close()
pixels=np.asarray(image)
print(json.dumps({"size":image.size}),flush=True)
results=[]
for name,params,options in [("existing",{"intra_op_num_threads":2,"inter_op_num_threads":1},{})]:
    model=RapidOCR(**params)
    for run in range(2):
        at=time.perf_counter();rows,timings=model(pixels,**options)
        text="\n".join(row[1] for row in rows or [] if row[2]>=.8)
        author,title=caption_fields(text)
        record={"name":name,"run":run,"seconds":round(time.perf_counter()-at,3),
              "stages":timings,"lines":len(rows or []),"author":bool(author),"title":bool(title)}
        results.append(record);print(json.dumps(record),flush=True)
fast=FastOCR()
for run in range(2):
    fast.last_digest=None  # Compare actual recognition, not identical-frame cache hits.
    at=time.perf_counter();text=fast.read(image);author,title=caption_fields(text)
    record={"name":fast.backend,"run":run,"seconds":round(time.perf_counter()-at,3),
            "lines":len(text.splitlines()),"author":bool(author),"title":bool(title)}
    results.append(record);print(json.dumps(record),flush=True)
(ROOT/".local"/"auto-performance.json").write_text(json.dumps({"size":image.size,"runs":results},indent=2),encoding="utf-8")
