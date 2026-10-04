"""Fixed geometry and independent controls, without touching user apps."""
import os
import sys
import time
import uuid
from pathlib import Path
from unittest.mock import patch
from copy import deepcopy
import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ["QT_QPA_PLATFORM"]="offscreen"
os.environ["AUTOSKIP_DATA_DIR"]=str(ROOT/".local"/"control-check"/uuid.uuid4().hex)
from PySide6.QtWidgets import QApplication,QPushButton,QToolButton
from PySide6.QtGui import QFontDatabase
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from autoskip.app import Overlay
from autoskip.core import Snapshot

app=QApplication([])
QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"])/"Fonts"/"msyh.ttc"))
overlay=Overlay(preview=True);overlay.timer.stop();overlay.show();app.processEvents()
buttons=overlay.findChildren(QPushButton)+overlay.findChildren(QToolButton)
assert not any(b.text()=="撤销" for b in buttons)
def geometry():
    return (overlay.size().width(),overlay.size().height(),
        [(b.text(),b.mapTo(overlay,b.rect().topLeft()).x(),b.mapTo(overlay,b.rect().topLeft()).y(),b.width(),b.height()) for b in buttons])
initial=geometry()
# The main preview is an icon immediately before Start, usable while paused.
top=overlay.pause_button.parentWidget().layout().itemAt(0).layout()
assert top.indexOf(overlay.region_button)+1==top.indexOf(overlay.pause_button)
assert not overlay.region_button.icon().isNull() and overlay.region_button.accessibleName()
QTest.mouseClick(overlay.pause_button,Qt.MouseButton.LeftButton)
assert not overlay.engine.paused and not overlay.region_preview.isVisible()
QTest.mouseClick(overlay.pause_button,Qt.MouseButton.LeftButton)
saved_config=deepcopy(overlay.config);pending=[]
profile={"name":"测试播放器","process":"player.exe","regions":[{"direction":"left","span":30},{"direction":"bottom","span":100}]}
overlay.config["player_profiles"].append(profile);overlay.config["player_type"]=profile["name"]
with patch.object(overlay.desktop_executor,"submit",side_effect=lambda work:pending.append(work)),\
     patch("autoskip.windows.find_player_window",return_value=(123,10,20)) as find,\
     patch("autoskip.app.capture_region",return_value=(Image.new("RGB",(870,500),"blue"),(30,0,900,500))) as capture,\
     patch("autoskip.windows.user32.SetWindowPos",return_value=True):
    QTest.mouseClick(overlay.region_button,Qt.MouseButton.RightButton)
    assert not pending and not overlay.region_preview.isVisible()
    QTest.mousePress(overlay.region_button,Qt.MouseButton.LeftButton)
    request=overlay.region_request;pending.pop()();app.processEvents()
    assert overlay.engine.paused and overlay.region_preview.isVisible()
    assert find.call_args.args[0]=="player.exe"
    assert capture.call_args.args[1]=={"player_type":profile["name"],"player_profiles":[profile]}
    rendered=overlay.region_preview.grab().toImage()
    assert rendered.pixelColor(1,1).name()=="#00ff00"
    assert rendered.pixelColor(rendered.width()//2,rendered.height()//2).alpha()==0
    QTest.mouseRelease(overlay.region_button,Qt.MouseButton.LeftButton)
    assert not overlay.region_preview.isVisible()
    overlay.region_captured.emit(request,(30,0,900,500),"")
    assert not overlay.region_preview.isVisible(),"A late frame must not resurrect the border"
    QTest.mousePress(overlay.region_button,Qt.MouseButton.LeftButton)
    QTest.mouseRelease(overlay.region_button,Qt.MouseButton.LeftButton)
    capture.reset_mock();pending.pop()();capture.assert_not_called()
    find.side_effect=ValueError("未找到播放器")
    QTest.mousePress(overlay.region_button,Qt.MouseButton.LeftButton);pending.pop()()
    assert overlay.notice.text()=="未找到播放器" and not overlay.region_preview.isVisible()
    QTest.mouseRelease(overlay.region_button,Qt.MouseButton.LeftButton);find.side_effect=None
    QTest.mousePress(overlay.region_button,Qt.MouseButton.LeftButton);pending.pop()()
    assert overlay.region_preview.isVisible()
    overlay.hide();assert not overlay.region_preview.isVisible()
    QTest.mouseRelease(overlay.region_button,Qt.MouseButton.LeftButton);overlay.show();app.processEvents()
    QTest.mousePress(overlay.region_button,Qt.MouseButton.LeftButton);request=overlay.region_request
    overlay.reload_settings();pending.pop(0)()
    overlay.region_captured.emit(request,(30,0,900,500),"")
    assert not overlay.region_preview.isVisible(),"Changed settings must invalidate old bounds"
    QTest.mouseRelease(overlay.region_button,Qt.MouseButton.LeftButton)
overlay.config=saved_config;overlay.notice_until=0;overlay.refresh();pending.clear()
for text in ["短", "很长的识别内容"*100, "第一行\n第二行\n第三行\n"*30, ""]:
    overlay.engine.status=text
    overlay.engine.current=Snapshot("desktop","test","v",author="@作者",title=text)
    overlay.show_notice(text);app.processEvents()
    assert geometry()==initial,"Content must not move the action buttons"
    overlay.notice_until=0;overlay.refresh();app.processEvents()
    assert geometry()==initial,"Expiring notices must retain their space"
    assert overlay.subtitle.toolTip().startswith("@作者")
QTest.mouseClick(overlay.fold_button,Qt.MouseButton.LeftButton);app.processEvents()
assert overlay.details.isHidden() and overlay.height()<initial[1]
assert overlay.fold_button.text()=="+" and overlay.fold_button.toolTip()=="显示解析文字"
assert overlay.auto_skip_switch.isVisible() and overlay.bind_button.isVisible()
assert all(b.isVisible() for b in buttons if b is not overlay.reparse_button)
assert not overlay.reparse_button.isVisible()
overlay.engine.status="折叠后的长内容"*100;overlay.refresh();app.processEvents()
assert overlay.details.isHidden() and overlay.height()==overlay.collapsed_height
QTest.mouseClick(overlay.fold_button,Qt.MouseButton.LeftButton);app.processEvents()
assert not overlay.details.isHidden() and geometry()==initial
assert overlay.fold_button.toolTip()=="隐藏解析文字"

# Restoring from the tray also brings the parsed text back.
overlay.fold_button.click();overlay.restore();app.processEvents()
assert not overlay.details.isHidden() and geometry()==initial

overlay.binding.target=(123,10,20);overlay.binding.title="抖音"
overlay.config["source"]="desktop";overlay.engine.pause(False)
overlay.refresh()
assert overlay.listen_switch.isChecked() and not overlay.auto_switch.isChecked()
overlay.auto_switch.click()
assert overlay.engine.listen_enabled and overlay.engine.auto_enabled and overlay.quick_skip.enabled
overlay.listen_switch.click()
assert not overlay.engine.listen_enabled and overlay.engine.auto_enabled and not overlay.quick_skip.enabled
overlay.listen_switch.click();overlay.auto_switch.click()
assert overlay.engine.listen_enabled and not overlay.engine.auto_enabled and overlay.quick_skip.enabled
overlay.listen_switch.click()
with patch.object(overlay.desktop_executor,"submit") as submit,patch.object(overlay,"poll_binding"):
    overlay.tick();submit.assert_not_called()
assert not overlay.engine.listen_enabled and not overlay.engine.auto_enabled and not overlay.quick_skip.enabled
overlay.listen_switch.click();overlay.auto_switch.click()
assert overlay.engine.listen_enabled and overlay.engine.auto_enabled

# An actual automatic dispatch never schedules a learning job; the following
# user's quick skip can still learn while automatic filtering remains enabled.
overlay.engine.update(Snapshot("desktop","123:10:20","v",author="@作者",title="视频标题",active=True))
with patch.object(overlay.binding,"matches",return_value=True),patch("autoskip.windows.next_video",return_value=True),patch.object(overlay.learning_executor,"submit") as analyze:
    overlay.dispatch({"action":"next"});analyze.assert_not_called()
    baseline=overlay.quick_skip.previous
    assert baseline is not None
    assert overlay.desktop_switch_at==baseline
    frame=(np.zeros((20,20,3),dtype=np.uint8),baseline+2.9)
    with patch.object(overlay.quick_skip,"freeze",return_value=frame):
        overlay.quick_skip.navigation("key",baseline+3)
    analyze.assert_called_once()
    overlay.quick_skip.slots.release()

# Tool navigation reaches the reader even though window messages do not generate
# physical input hooks; the pending video must not be locked into the OCR cache.
pending_token=overlay.engine.current.token
overlay.engine.next_action("测试切换")
overlay.desktop_next_at=0
with patch.object(overlay,"poll_binding"),patch.object(overlay.reader,"read",return_value=(None,None,"等待新视频")) as read,patch.object(overlay.desktop_executor,"submit",side_effect=lambda work:work()):
    overlay.tick()
    assert read.call_args.args[0]["video_switch_at"]==baseline
    assert read.call_args.args[0]["pending_token"]==pending_token

overlay.engine.pause(True);overlay.refresh()
assert overlay.listen_switch.isChecked() and overlay.auto_switch.isChecked() and not overlay.quick_skip.enabled
overlay.engine.status="监听与自动可同时开启"
overlay.engine.current=Snapshot("desktop","test","v",author="@示例作者",title="识别内容在固定区域内更新，长文字不会推动下方按钮")
overlay.show_notice("@示例作者 某条视频被加入黑名单（切换间隔 3.000 秒）")
app.processEvents()
destination=ROOT/".local"/"ui";destination.mkdir(parents=True,exist_ok=True)
assert overlay.grab().save(str(destination/"independent-switches.png"))
overlay.fold_button.click();app.processEvents()
assert overlay.grab().save(str(destination/"collapsed-overlay.png"))
overlay.fold_button.click()
overlay.desktop_executor.shutdown(wait=True);overlay.learning_executor.shutdown(wait=True)
overlay.store.db.close()
print("Stable window/button geometry, independent switches and combined operation: PASS",initial[:2])
