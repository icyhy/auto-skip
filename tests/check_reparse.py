"""One-off author corrections with real Qt clicks and isolated watch records."""
import os
import sys
import time
import uuid
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ["QT_QPA_PLATFORM"]="offscreen"
os.environ["AUTOSKIP_DATA_DIR"]=str(ROOT/".local"/"reparse-check"/uuid.uuid4().hex)
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt
from autoskip.app import Overlay
from autoskip.core import Snapshot, author_name_key

app=QApplication([])
QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"])/"Fonts"/"msyh.ttc"))
overlay=Overlay(preview=True);overlay.timer.stop();overlay.show();app.processEvents()
overlay.desktop_executor.shutdown(wait=True)
jobs=[]
target=(123,10,20)
original=Snapshot("desktop","123:10:20","old",author="@错误作者",title="手机续航实测结果",active=True)
corrected=replace(original,token="corrected",author="@正确作者")

def click():
    QTest.mouseClick(overlay.reparse_button,Qt.MouseButton.LeftButton);app.processEvents()

with patch.object(overlay.desktop_executor,"submit",side_effect=lambda work:jobs.append(work)), \
        patch.object(overlay.binding,"matches",side_effect=lambda session:session=="123:10:20"), \
        patch("autoskip.windows.next_video") as send, \
        patch.object(overlay.reader,"read",return_value=(corrected,None,"ok")) as read:
    assert not overlay.reparse_button.isEnabled()
    assert not overlay.reparse_button.icon().isNull()
    assert overlay.reparse_button.accessibleName()=="重新解析当前视频"
    assert overlay.reparse_button.mapTo(overlay,overlay.reparse_button.rect().topLeft()).x()<overlay.subtitle.mapTo(overlay,overlay.subtitle.rect().topLeft()).x()
    overlay.binding.target=target;overlay.config["source"]="desktop"
    overlay.engine.pause(False);overlay.refresh()
    assert overlay.reparse_button.isEnabled()
    start=time.monotonic()-10
    overlay.engine.views.switch("desktop",original.session,start)
    overlay.engine.update(original)
    overlay.refresh()
    geometry=(overlay.size(),overlay.bind_button.pos(),overlay.subtitle.pos())
    epoch=overlay.engine.epoch
    click();click()
    assert len(jobs)==1 and overlay.manual_busy and not overlay.reparse_button.isEnabled()
    # Neither manual blacklist actions nor the timer may use the old author while parsing.
    overlay.block("author")
    overlay.engine.budget=(1,"数码科技")
    with patch.object(overlay,"poll_binding"),patch.object(overlay,"dispatch") as dispatch:
        overlay.tick();dispatch.assert_not_called()
    overlay.on_desktop((epoch,overlay.ui_input.last_next),original,None,"old result")
    jobs.pop()();app.processEvents()
    assert overlay.engine.current==corrected and overlay.engine.views.snap==corrected
    assert overlay.engine.views.started==start and overlay.engine.views.observed_at==start
    assert overlay.reparse_button.isEnabled() and not overlay.manual_busy
    assert "@正确作者" in overlay.subtitle.text()
    assert (overlay.size(),overlay.bind_button.pos(),overlay.subtitle.pos())==geometry
    assert read.call_args.args[0]["mode"]=="reparse"
    assert overlay.store.rules()==[] and overlay.store.statistics()["count"]==0
    send.assert_not_called()
    # The existing visit gets the corrected metadata at its actual end switch.
    overlay.engine.views.switch("desktop",original.session,start+20)
    record=overlay.store.export_watches()["watches"][0]
    assert record["author"]=="@正确作者" and record["seconds"]==20
    read.reset_mock()
    overlay.block("author")
    read.assert_not_called()
    assert overlay.store.rules()[0]["target"]==author_name_key("@正确作者")
    overlay.engine.manual=None
    # A missing author or capture failure preserves the displayed result and permits retry.
    for value in ((replace(corrected,author=""),None,"ok"),(None,None,"窗口最小化")):
        read.return_value=value
        click();jobs.pop()();app.processEvents()
        assert overlay.engine.current==corrected and overlay.reparse_button.isEnabled()
        assert "未能识别作者" in overlay.notice.text() or "窗口最小化" in overlay.notice.text()
    read.side_effect=ValueError("无法取得新画面")
    click();jobs.pop()();app.processEvents()
    assert overlay.engine.current==corrected and overlay.notice.text()=="无法取得新画面"
    read.side_effect=None;read.return_value=(corrected,None,"ok")
    # Pausing, rebinding and a navigation during OCR discard late results.
    for invalidate in (lambda:overlay.engine.pause(True),lambda:setattr(overlay.binding,"target",(456,10,20)),
            lambda:setattr(overlay.ui_input,"last_next",overlay.ui_input.last_next+1)):
        overlay.binding.target=target;overlay.engine.pause(False);overlay.engine.update(original);overlay.refresh()
        click();invalidate();jobs.pop()();app.processEvents()
        assert overlay.engine.current!=corrected and not overlay.manual_busy
    overlay.binding.target=target;overlay.engine.pause(False);overlay.engine.update(original);overlay.refresh()
    overlay.engine.next_action("切换中");overlay.refresh()
    assert not overlay.reparse_button.isEnabled()
    overlay.engine.pause(False);overlay.config["source"]="chrome";overlay.refresh()
    assert not overlay.reparse_button.isEnabled()
    send.assert_not_called()

overlay.config["source"]="desktop";overlay.engine.current=corrected;overlay.engine.status="监听中 · 继续观看"
overlay.show_notice("已重新解析当前视频");app.processEvents()
output=ROOT/".local"/"ui";output.mkdir(parents=True,exist_ok=True)
assert overlay.grab().save(str(output/"reparse-overlay.png"))
overlay.close();overlay.learning_executor.shutdown(wait=True);overlay.store.db.close()
print("One-off reparse, corrected blacklist/statistics, preserved timing and stale-result guards: PASS")
