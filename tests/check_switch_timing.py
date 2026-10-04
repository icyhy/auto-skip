"""Exercise physical input signals, delayed metadata and timer dispatch offscreen."""
import os
import sys
import uuid
from pathlib import Path
from dataclasses import asdict, replace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ["QT_QPA_PLATFORM"]="offscreen"
os.environ["AUTOSKIP_DATA_DIR"]=str(ROOT/".local"/"switch-check"/uuid.uuid4().hex)
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
from autoskip.app import Overlay, Statistics
from autoskip.core import Snapshot

app=QApplication([])
QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"])/"Fonts"/"msyh.ttc"))
overlay=Overlay(preview=True);overlay.timer.stop();overlay.show();app.processEvents()
overlay.binding.target=(123,10,20);overlay.binding.title="抖音"
overlay.config["source"]="desktop"
now=100.0;overlay.engine.clock=lambda:now
overlay.engine.pause(False);overlay.refresh()
assert overlay.watch_duration.text()=="00:00:00"
assert overlay.watch_duration.accessibleName()=="当前视频观看时长"
assert overlay.watch_duration.x()>overlay.auto_skip_switch.geometry().right()
assert overlay.watch_duration.y()==overlay.auto_skip_switch.y()
initial_geometry=(overlay.size(),overlay.bind_button.pos(),overlay.watch_duration.geometry())
first=Snapshot("desktop","123:10:20","first",author="@初始作者",title="启动时的初始视频",active=True)
second=replace(first,token="second",author="@数码作者",title="手机数码评测")
third=replace(first,token="third",author="@美食作者",title="美食做饭")

with patch("autoskip.app.time.monotonic",side_effect=lambda:now),patch.object(overlay.binding,"matches",return_value=True):
    overlay.on_desktop((overlay.engine.epoch,0),first,None,"")
    now=104.9;overlay.refresh()
    assert overlay.watch_duration.text()=="00:00:04"
    assert not overlay.auto_skip_switch.isEnabled(),"The timer also works with automatic skipping disabled"
    now=105
    overlay.ui_input.key_event(True,123,now);app.processEvents()
    overlay.ui_input.key_event(False,123,now)
    assert overlay.engine.views.started==105
    assert overlay.store.statistics()["count"]==0
    overlay.refresh();assert overlay.watch_duration.text()=="00:00:00"
    # An old transition frame arrives before the new caption; do not lose the boundary.
    overlay.on_desktop((overlay.engine.epoch,105),None,None,"视频切换中")
    assert overlay.engine.views.started==105
    now=108
    overlay.on_desktop((overlay.engine.epoch,105),second,None,"")
    assert overlay.watch_duration.text()=="00:00:03","OCR delay must not restart the timer"
    now=115
    overlay.ui_input.key_event(True,123,now);app.processEvents()
    overlay.ui_input.key_event(False,123,now)
    assert overlay.store.statistics()["count"]==1
    assert overlay.store.statistics()["seconds"]==10
    overlay.refresh();assert overlay.watch_duration.text()=="00:00:00"
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
    overlay.refresh();assert overlay.watch_duration.text()=="00:00:00"
    assert overlay.store.statistics()["count"]==1
    assert overlay.store.statistics()["seconds"]==10

    # Restart and enable historical skipping. First video stays excluded from statistics.
    overlay.engine.pause(False);overlay.engine.set_features(auto=True,auto_skip=True)
    now=200
    overlay.on_desktop((overlay.engine.epoch,115),second,None,"")
    assert overlay.watch_duration.text()=="00:00:00"
    for now in range(201,210):
        overlay.on_desktop((overlay.engine.epoch,115),second,None,"")
    now=210
    with patch.object(overlay,"poll_binding"),patch("autoskip.windows.next_video",return_value=True) as next_video:
        overlay.tick();next_video.assert_called_once()
    assert overlay.watch_duration.text()=="00:00:00","Automatic navigation resets the display"
    assert overlay.engine.views.started==210
    assert overlay.store.statistics()["count"]==1
    now=213
    overlay.on_desktop((overlay.engine.epoch,115),third,None,"")
    assert overlay.watch_duration.text()=="00:00:03"
    now=220
    overlay.ui_input.key_event(True,123,now);app.processEvents()
    overlay.ui_input.key_event(False,123,now)
    assert overlay.store.statistics()["seconds"]==20
    assert overlay.store.statistics()["count"]==2
    now=220.3;overlay.on_navigation(overlay.binding.target,now);overlay.refresh()
    assert overlay.engine.views.started==220,"Duplicate inputs must not reset the timer"
    overlay.desktop_busy=True
    now=221.1
    with patch.object(overlay,"poll_binding"):
        overlay.tick()
    assert overlay.watch_duration.text()=="00:00:01","Timer ticks update while waiting for video metadata"
    overlay.desktop_busy=False

    # Web video identity changes reset the same display; formatting never wraps at 24 hours.
    overlay.engine.pause(True);overlay.config["source"]="chrome"
    overlay.engine.set_features(auto=False,auto_skip=False);overlay.engine.pause(False)
    web=replace(first,source="chrome",session="tab",token="web-first")
    now=1000
    with patch("autoskip.windows.process_name",return_value="chrome.exe"):
        overlay.on_message({**asdict(web),"type":"snapshot","sequence":1},lambda response:None)
        assert overlay.watch_duration.text()=="00:00:00"
        for seconds,expected in ((59.9,"00:00:59"),(60,"00:01:00"),(3599,"00:59:59"),(3600,"01:00:00"),(90061,"25:01:01")):
            now=1000+seconds;overlay.refresh()
            assert overlay.watch_duration.text()==expected
        app.processEvents()
        assert (overlay.size(),overlay.bind_button.pos(),overlay.watch_duration.geometry())==initial_geometry
        output=ROOT/".local"/"ui";output.mkdir(parents=True,exist_ok=True)
        assert overlay.grab().save(str(output/"watch-duration-overlay.png"))
        now+=1
        overlay.on_message({**asdict(replace(web,token="web-second")),"type":"snapshot","sequence":2},lambda response:None)
        assert overlay.watch_duration.text()=="00:00:00"
        now+=1
        with patch.object(overlay,"poll_binding"):
            overlay.tick()
        assert overlay.watch_duration.text()=="00:00:01"

overlay.engine.pause(True)
overlay.refresh();assert overlay.watch_duration.text()=="00:00:00"
overlay.desktop_executor.shutdown(wait=True);overlay.learning_executor.shutdown(wait=True)
overlay.store.db.close()
print("Desktop/web timer display, reset, formatting and complete switch intervals: PASS")
