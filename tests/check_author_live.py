"""Verify a requested author against actual saved rules; --scroll sends one next."""
import json
import os
import sqlite3
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from autoskip import windows
from autoskip.core import Engine,author_name
from autoskip.store import Store
from autoskip.desktop import DesktopReader

expected="红衣大叔周鸿祎"
production=sqlite3.connect((windows.data_dir()/"autoskip.db").as_uri()+"?mode=ro",uri=True)
production.row_factory=sqlite3.Row
rules=[dict(row) for row in production.execute("SELECT * FROM rules WHERE kind='author' AND enabled=1")
       if author_name(row["label"])==expected]
production.close()
assert rules,"Requested author rule is not enabled"
local=Store(ROOT/".local"/("author-check-"+uuid.uuid4().hex+".db"))
for rule in rules:local.add_rule(rule["kind"],rule["target"],rule["label"],rule["reason"])
engine=Engine(local);engine.set_features(listen=False,auto=True);engine.pause(False)
binding=windows.WindowBinding();binding.discover();assert binding.target
reader=DesktopReader(SimpleNamespace(hwnd=0,region=None,last_next=0))
config={"mode":"auto","desktop_target":binding.target,"blocked_authors":[r["label"] for r in rules]}
with ThreadPoolExecutor(max_workers=1) as worker:
    try:
        started=time.perf_counter();snap,_,_=worker.submit(reader.read,config).result(timeout=30)
        report={"recognized_author":snap.author if snap else None,"read_ms":round((time.perf_counter()-started)*1000,1),
                "secondary_ocr":bool(reader.fast_ocr and reader.fast_ocr.fallback)}
        if not snap or author_name(snap.author)!=expected:
            print(json.dumps(report,ensure_ascii=True),flush=True)
            raise AssertionError("Current video author not confirmed; no scrolling performed")
        action=engine.update(snap)
        assert action and "作者黑名单" in action["reason"]
        report["matched"]=True
        if "--scroll" in sys.argv:
            focused=windows.foreground()
            report["scroll_sent"]=windows.next_video(binding.target)
            config["video_switch_at"]=time.monotonic()
            time.sleep(1)
            after,_,_=worker.submit(reader.read,config).result(timeout=30)
            report["next_author"]=after.author if after else None
            report["video_changed"]=bool(after and after.token!=snap.token)
            report["focus_unchanged"]=windows.foreground()==focused
            assert report["scroll_sent"] and report["video_changed"] and report["focus_unchanged"]
        print(json.dumps(report,ensure_ascii=True),flush=True)
    finally:
        worker.submit(reader.close).result(timeout=10)
        local.db.close()
