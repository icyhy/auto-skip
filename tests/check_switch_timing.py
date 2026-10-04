"""Exercise physical input signals, delayed metadata and timer dispatch offscreen."""
import os
import sys
import uuid
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ["QT_QPA_PLATFORM"]="offscreen"
os.environ["AUTOSKIP_DATA_DIR"]=str(ROOT/".local"/"switch-check"/uuid.uuid4().hex)
from PySide6.QtWidgets import QApplication
from autoskip.app import Overlay, Statistics
from autoskip.core import Snapshot

app=QApplication([])
overlay=Overlay(preview=True);overlay.timer.stop()
overlay.binding.target=(123,10,20);overlay.binding.title="抖音"
overlay.config["source"]="desktop"
now=100.0;overlay.engine.clock=lambda:now
overlay.engine.pause(False);overlay.refresh()
first=Snapshot("desktop","123:10:20","first",author="@初始作者",title="启动时的初始视频",active=True)
second=replace(first,token="second",author="@数码作者",title="手机数码评测")
third=replace(first,token="third",author="@美食作者",title="美食做饭")

with patch("autoskip.app.time.monotonic",side_effect=lambda:now),patch.object(overlay.binding,"matches",return_value=True):
    overlay.on_desktop((overlay.engine.epoch,0),first,None,"")
    now=105
    overlay.ui_input.key_event(True,123,now);app.processEvents()
    overlay.ui_input.key_event(False,123,now)
    assert overlay.engine.views.started==105
    assert overlay.store.statistics()["count"]==0
    # An old transition frame arrives before the new caption; do not lose the boundary.
    overlay.on_desktop((overlay.engine.epoch,105),None,None,"视频切换中")
    assert overlay.engine.views.started==105
    now=108
    overlay.on_desktop((overlay.engine.epoch,105),second,None,"")
    now=115
    overlay.ui_input.key_event(True,123,now);app.processEvents()
    overlay.ui_input.key_event(False,123,now)
    assert overlay.store.statistics()["count"]==1
    assert overlay.store.statistics()["seconds"]==10
    now=118
    overlay.on_desktop((overlay.engine.epoch,115),third,None,"")
    dialog=Statistics(overlay)
    assert "全部观看：1 次" in dialog.summary.text()
    assert dialog.table.item(0,0).text()=="跳过"
    assert dialog.table.item(0,1).text()=="0"
    assert dialog.table.item(1,0).text()=="数码科技"
    dialog.close()
    # Exit with a long open video. No exit-time flush or startup partial row.
    now=150;overlay.engine.pause(True)
    assert overlay.store.statistics()["count"]==1
    assert overlay.store.statistics()["seconds"]==10

    # Restart and enable historical skipping. First video stays excluded from statistics.
    overlay.engine.pause(False);overlay.engine.set_features(auto=True,auto_skip=True)
    now=200
    overlay.on_desktop((overlay.engine.epoch,115),second,None,"")
    for now in range(201,210):
        overlay.on_desktop((overlay.engine.epoch,115),second,None,"")
    now=210
    with patch.object(overlay,"poll_binding"),patch("autoskip.windows.next_video",return_value=True) as next_video:
        overlay.tick();next_video.assert_called_once()
    assert overlay.engine.views.started==210
    assert overlay.store.statistics()["count"]==1
    now=213
    overlay.on_desktop((overlay.engine.epoch,115),third,None,"")
    now=220
    overlay.ui_input.key_event(True,123,now);app.processEvents()
    overlay.ui_input.key_event(False,123,now)
    assert overlay.store.statistics()["seconds"]==20
    assert overlay.store.statistics()["count"]==2

overlay.engine.pause(True)
overlay.desktop_executor.shutdown(wait=True);overlay.learning_executor.shutdown(wait=True)
overlay.store.db.close()
print("Desktop input -> delayed OCR -> complete interval -> SQLite -> statistics -> timed dispatch: PASS")
