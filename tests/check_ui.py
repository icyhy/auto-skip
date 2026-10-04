"""Render our own UI without touching the user's desktop or video app."""
import os
import sys
import time
import uuid
from unittest.mock import patch
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ["QT_QPA_PLATFORM"]="offscreen"
os.environ["AUTOSKIP_DATA_DIR"]=str(ROOT/".local"/"ui-check"/uuid.uuid4().hex)
from PySide6.QtWidgets import QApplication, QPushButton, QTabWidget
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtGui import QFontDatabase
from autoskip.app import Overlay, Settings, Rules, RuleEditor
from autoskip.core import Snapshot
from autoskip.core import caption_key
from autoskip.learning import SkipEvent

app=QApplication([])
QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"])/"Fonts"/"msyh.ttc"))
overlay=Overlay(preview=True)
overlay.show();app.processEvents()
destination=ROOT/".local"/"ui"
destination.mkdir(parents=True,exist_ok=True)
assert overlay.grab().save(str(destination/"overlay.png"))
settings=Settings(overlay);settings.show();app.processEvents()
assert settings.source.itemData(0)=="auto"
assert not any("校准" in button.text() for button in settings.findChildren(QPushButton))
assert settings.grab().save(str(destination/"settings.png"))
settings.findChild(QTabWidget).setCurrentIndex(1);app.processEvents()
assert settings.grab().save(str(destination/"chrome-settings.png"))
settings.close()
# Multiple player types retain independent regions; cancel leaves stored settings intact.
settings=Settings(overlay);tabs=settings.findChild(QTabWidget);tabs.setCurrentIndex(2)
assert settings.player_name.text()=="抖音桌面版 Windows"
assert settings.regions.cellWidget(0,0).currentData()=="bottom"
assert settings.regions.cellWidget(0,1).value()==100
settings.add_region({"direction":"left","span":35})
settings.add_player();settings.player_name.setText("其他播放器")
settings.add_region({"direction":"top","span":20})
settings.player_type.setCurrentIndex(0)
assert settings.regions.rowCount()==2
settings.show();app.processEvents()
assert settings.grab().save(str(destination/"player-settings.png"))
# Press/release uses unsaved fields, discards late frames and cleans up on page/close changes.
from PIL import Image
overlay.timer.stop()
pending=[]
with patch.object(overlay.desktop_executor,"submit",side_effect=lambda work:pending.append(work)),\
     patch("autoskip.windows.find_player_window",return_value=(123,10,20)) as find,\
     patch("autoskip.app.capture_region",return_value=(Image.new("RGB",(865,500),"blue"),(35,0,900,500))) as capture,\
     patch("autoskip.windows.user32.SetWindowPos",return_value=True):
    settings.player_process.setText("example.exe")
    QTest.mousePress(settings.verify_region,Qt.MouseButton.LeftButton)
    assert settings.verify_region.isDown() and len(pending)==1
    QTest.mouseRelease(settings.verify_region,Qt.MouseButton.LeftButton)
    pending.pop()();app.processEvents()
    assert not settings.region_preview.isVisible()
    QTest.mousePress(settings.verify_region,Qt.MouseButton.LeftButton)
    pending.pop()();app.processEvents()
    assert settings.region_preview.isVisible()
    assert capture.call_args.args[1]["player_profiles"][0]["process"]=="example.exe"
    assert len(capture.call_args.args[1]["player_profiles"][0]["regions"])==2
    assert find.call_args.args[0]=="example.exe"
    assert overlay.store.get("player_profiles")[0].get("process","douyin.exe")=="douyin.exe"
    rendered=settings.region_preview.grab().toImage()
    assert rendered.pixelColor(1,1).name()=="#00ff00"
    QTest.mouseRelease(settings.verify_region,Qt.MouseButton.LeftButton)
    assert not settings.region_preview.isVisible()
    # Errors are inline so they do not trap the mouse release in a modal dialog.
    find.side_effect=ValueError("未找到播放器")
    QTest.mousePress(settings.verify_region,Qt.MouseButton.LeftButton)
    pending.pop()();app.processEvents()
    assert settings.region_status.text()=="未找到播放器" and not settings.region_preview.isVisible()
    QTest.mouseRelease(settings.verify_region,Qt.MouseButton.LeftButton)
    find.side_effect=None
    QTest.mousePress(settings.verify_region,Qt.MouseButton.LeftButton)
    pending.pop()();app.processEvents()
    assert settings.region_preview.isVisible()
    tabs.setCurrentIndex(0);assert not settings.region_preview.isVisible()
    QTest.mouseRelease(settings.verify_region,Qt.MouseButton.LeftButton)
    tabs.setCurrentIndex(2)
    QTest.mousePress(settings.verify_region,Qt.MouseButton.LeftButton)
    settings.close();pending.pop()();app.processEvents()
    assert not settings.region_preview.isVisible()
    QTest.mouseRelease(settings.verify_region,Qt.MouseButton.LeftButton)
settings.player_process.setText("douyin.exe")
settings.show();app.processEvents();overlay.timer.start(150)
settings.save();assert settings.result()==1
assert overlay.config["player_type"]=="抖音桌面版 Windows"
assert len(overlay.config["player_profiles"])==2
settings=Settings(overlay);settings.player_type.setCurrentIndex(1)
assert settings.player_name.text()=="其他播放器" and settings.regions.cellWidget(0,1).value()==20
settings.player_name.setText("抖音桌面版 Windows")
with patch("autoskip.app.QMessageBox.warning") as warning:
    settings.save();warning.assert_called_once()
assert settings.result()==0
settings.player_name.setText("其他播放器");settings.save()
assert overlay.config["player_type"]=="其他播放器"
settings=Settings(overlay);settings.delete_player()
assert settings.player_type.count()==1
settings.regions.selectRow(0);settings.delete_region()
assert settings.regions.rowCount()==1
settings.regions.selectRow(0);settings.delete_region()
assert settings.regions.rowCount()==0
settings.reject()
assert len(overlay.store.get("player_profiles"))==2
# Return this isolated UI run to the default profile.
settings=Settings(overlay);settings.player_type.setCurrentIndex(0);settings.save()
overlay.config["source"]="auto"
overlay.binding.target=(123,10,20);overlay.binding.title="抖音"
with patch("autoskip.windows.foreground",return_value=123),patch("autoskip.windows.process_name",return_value="douyin.exe"):
    assert overlay.accepts_source("desktop") and not overlay.accepts_source("chrome")
with patch("autoskip.windows.foreground",return_value=456),patch("autoskip.windows.process_name",return_value="chrome.exe"):
    assert overlay.accepts_source("desktop") and not overlay.accepts_source("chrome")
with patch("autoskip.windows.foreground",return_value=789),patch("autoskip.windows.process_name",return_value="notepad.exe"):
    assert overlay.accepts_source("desktop") and not overlay.accepts_source("chrome")
overlay.binding.target=None
with patch("autoskip.windows.foreground",return_value=456),patch("autoskip.windows.process_name",return_value="chrome.exe"):
    assert overlay.accepts_source("chrome") and not overlay.accepts_source("desktop")
overlay.store.add_rule("author","test-author","示例作者","测试数据")
rules=Rules(overlay);rules.show();app.processEvents()
assert [rules.table.horizontalHeaderItem(i).text() for i in range(6)]==["作者","关键词","链接","过滤条件","启用","添加时间"]
editor=RuleEditor(overlay,parent=rules)
editor.author.setText("摄影作者");editor.keyword.setText("摄影教程")
editor.condition.setCurrentIndex(1)
with patch("autoskip.app.QMessageBox.warning") as warning:
    editor.save();warning.assert_called_once()
assert editor.result()==0
editor.link.setText("https://www.douyin.com/video/999")
editor.show();app.processEvents()
assert editor.grab().save(str(destination/"rule-editor.png"))
editor.save();assert editor.result()==1
rules.refresh();rule=rules.rows[0]
assert rule["condition"]=="and" and rule["author"]=="摄影作者"
rules.search.setText("摄影教程");assert rules.table.rowCount()==1
rules.table.selectRow(0);rules.toggle();assert not rules.rows[0]["enabled"]
edit=RuleEditor(overlay,rules.rows[0],rules)
edit.condition.setCurrentIndex(0);edit.author.clear();edit.link.clear();edit.save()
rules.refresh();assert rules.rows[0]["condition"]=="or" and not rules.rows[0]["enabled"]
rules.table.selectRow(0);rules.toggle()
assert overlay.engine.match(Snapshot("chrome","test","photo",title="摄影教程"))
assert not overlay.engine.match(Snapshot("chrome","test","photo",author="摄影作者"))
rules.search.clear();app.processEvents()
assert rules.grab().save(str(destination/"rules.png"))
rules.search.setText("摄影教程");rules.table.selectRow(0);rules.delete()
assert not rules.rows
rules.close()

overlay.engine.pause(False)
overlay.engine.update(Snapshot("chrome","test","v1","video-1","author-1",title="示例数码评测",author="@测试作者",active=True,playing=True,timing=True))
with patch("autoskip.windows.foreground",return_value=123),patch("autoskip.windows.process_name",return_value="chrome.exe"):
    overlay.block("author")
assert overlay.engine.manual is not None
snapshot=overlay.engine.current
overlay.engine.reset(preserve_watch=True)
rules=Rules(overlay)
index=next(i for i,rule in enumerate(rules.rows) if rule["author"]=="@测试作者")
rules.table.selectRow(index);rules.delete();rules.close()
assert not overlay.engine.match(snapshot)
overlay.engine.update(snapshot)
with patch("autoskip.windows.foreground",return_value=456),patch("autoskip.windows.process_name",return_value="notepad.exe"):
    overlay.block("author")
assert overlay.engine.manual is None
# Chrome messages keep all parsed fields through video blocking and rule editing.
message={"type":"snapshot","source":"chrome","session":"chrome-metadata","token":"metadata-video",
         "video_id":"dy:video:1234567890123456789","author_id":"dy:author:metadata",
         "author":"@网页作者","title":"手机续航实测 #数码","active":True,"playing":True,"timing":True,"sequence":1}
with patch("autoskip.windows.foreground",return_value=123),patch("autoskip.windows.process_name",return_value="chrome.exe"):
    overlay.on_message(message,lambda response:None)
    overlay.block("video")
snapshot=overlay.engine.current
rules=Rules(overlay);rules.show();app.processEvents()
index=next(i for i,rule in enumerate(rules.rows) if rule["target"]==message["video_id"])
assert [rules.table.item(index,column).text() for column in (0,1,2,3)]==[
    message["author"],message["title"],"https://www.douyin.com/video/1234567890123456789","仅视频"]
rules.search.setText("网页作者");assert rules.table.rowCount()==1
rule=rules.rows[0];editor=RuleEditor(overlay,rule,rules);editor.show();app.processEvents()
assert editor.author.text()==message["author"] and editor.keyword.text()==message["title"]
assert editor.condition.currentData()=="video" and editor.author.isReadOnly()
assert editor.grab().save(str(destination/"video-rule-editor.png"))
editor.save();assert overlay.store.rules()[0]["kind"]=="video"
assert not overlay.engine.match(Snapshot("chrome","test","other","dy:video:999",author=message["author"],title=message["title"]))
assert rules.grab().save(str(destination/"chrome-video-rule.png"))
# Changing the condition explicitly converts the saved details into a filter.
editor=RuleEditor(overlay,rule,rules);editor.condition.setCurrentIndex(editor.condition.findData("or"))
assert not editor.author.isReadOnly();editor.author.clear();editor.link.clear();editor.save()
assert overlay.store.rules()[0]["kind"]=="filter" and overlay.engine.match(snapshot)
overlay.store.delete(rule["id"]);rules.close();overlay.engine.reset(preserve_watch=True)
overlay.fold();assert overlay.details.isHidden()
overlay.fold();assert not overlay.details.isHidden()
overlay.pick_window();assert overlay.engine.paused and overlay.picking_at
overlay.pick_window();assert not overlay.picking_at
overlay.pick_window()
overlay.ui_input.last_click=(time.monotonic()+1,123)
def bind_click(hwnd):
    assert hwnd==123
    overlay.binding.target=(123,10,20);overlay.binding.title="抖音"
with patch.object(overlay.binding,"bind",side_effect=bind_click):overlay.poll_binding()
assert not overlay.picking_at and overlay.config["source"]=="desktop"
assert overlay.binding.target==(123,10,20)
overlay.binding.target=(123,10,20)
overlay.engine.pause(False)
overlay.engine.set_features(listen=False,auto=True)
overlay.engine.update(Snapshot("desktop","123:10:20","v1","video-1","author-1",author="@桌面作者",active=True))
with patch.object(overlay.binding,"matches",return_value=True),patch("autoskip.windows.foreground",return_value=789):
    overlay.block("author")
assert overlay.engine.manual is not None
with patch.object(overlay.binding,"matches",return_value=True),patch("autoskip.windows.next_video",return_value=True) as send:
    overlay.dispatch({"action":"next"})
    send.assert_called_once_with((123,10,20))
# Manual user requests still get a one-off read after passive OCR is removed.
overlay.engine.set_features(listen=True,auto=False)
manual_snap=Snapshot("desktop","123:10:20","manual-v","manual-video","manual-author",author="@手动作者",active=True)
with patch.object(overlay.reader,"read",return_value=(manual_snap,None,"ok")) as read,patch.object(overlay.desktop_executor,"submit",side_effect=lambda work:work()),patch.object(overlay.binding,"matches",return_value=True),patch("autoskip.windows.next_video",return_value=True):
    overlay.block("author")
    read.assert_called_once()
    assert read.call_args.args[0]["mode"]=="manual"
    assert overlay.engine.match(manual_snap)
# Missing authors cancel manual requests before saving a rule or sending input.
for kind in ("author","video"):
    overlay.engine.reset(preserve_watch=True)
    missing=Snapshot("desktop","123:10:20","missing-v","missing-video","missing-author",active=True)
    before=len(overlay.store.rules());undo=list(overlay.engine.undo_stack)
    with patch.object(overlay.reader,"read",return_value=(missing,None,"ok")),patch.object(overlay.desktop_executor,"submit",side_effect=lambda work:work()),patch.object(overlay.binding,"matches",return_value=True),patch("autoskip.windows.next_video") as send:
        overlay.block(kind)
        send.assert_not_called()
    assert len(overlay.store.rules())==before and overlay.engine.undo_stack==undo
    assert "未能识别作者" in overlay.notice.text()
    assert not overlay.engine.manual
# An ineligible queued result must neither run OCR nor enter SQLite.
overlay.store.set("threshold",4);overlay.refresh()
expired=SkipEvent((123,10,20),100,4.5,"wheel",(None,99.9),5)
assert overlay.quick_skip.slots.acquire(blocking=False)
with patch.object(overlay.learning_executor,"submit") as submit:
    overlay.on_captured(expired,"queued")
    submit.assert_not_called()
assert overlay.quick_skip.slots.acquire(blocking=False)
with patch.object(overlay.engine,"remember") as remember:
    overlay.on_learned(expired,{"target":"bad","author":"@不应拉黑","title":"超过阈值的视频"},"")
    remember.assert_not_called()
queued=SkipEvent((123,10,20),100,3.5,"wheel",(None,99.9),4)
assert overlay.quick_skip.slots.acquire(blocking=False)
with patch.object(overlay.learning_executor,"submit") as submit:
    overlay.on_captured(queued,"queued")
    work=submit.call_args.args[0]
overlay.store.set("threshold",3);overlay.refresh()
with patch.object(overlay.screenshot_analyzer,"analyze") as parse:
    work()
    parse.assert_not_called()
overlay.store.set("threshold",4);overlay.refresh()
# A result from a departing video must survive advancing, pausing and rebinding.
overlay.engine.pause(True)
overlay.binding.target=(456,30,40)
event=SkipEvent((123,10,20),100,3,"wheel",(None,99.9))
for author in (""," \t\u200b","＠ ·"):
    assert overlay.quick_skip.slots.acquire(blocking=False)
    before=len(overlay.store.rules());undo=list(overlay.engine.undo_stack)
    overlay.on_learned(event,{"target":"missing-author-target","author":author,"title":"有标题但没有作者"},"")
    assert len(overlay.store.rules())==before and overlay.engine.undo_stack==undo
    assert "未能识别作者" in overlay.notice.text()
# Each rejected result must release its queue slot.
for _ in range(8):assert overlay.quick_skip.slots.acquire(blocking=False)
assert not overlay.quick_skip.slots.acquire(blocking=False)
for _ in range(8):overlay.quick_skip.slots.release()
assert overlay.quick_skip.slots.acquire(blocking=False)
overlay.on_learned(event,{"target":caption_key("@示例视频作者","三秒内划走的数码评测"),"author":"@示例视频作者","title":"三秒内划走的数码评测"},"")
overlay.refresh()
assert "@示例视频作者 三秒内划走的数码评测 视频被加入黑名单（切换间隔 3.000 秒）"==overlay.notice.text()
assert not overlay.notice.isHidden()
assert overlay.engine.match(Snapshot("desktop","test","v2",author="@示例视频作者",title="三秒内划走的数码评测"))
assert not overlay.engine.match(Snapshot("desktop","test","v3",author="@示例视频作者",title="另一个完全不同的视频"))
learned=overlay.store.rules()[0]
assert (learned["author"],learned["keyword"])==("@示例视频作者","三秒内划走的数码评测")
overlay.grab().save(str(destination/"learned-notice.png"))

# Local rules never need a cloud service, including old configured keys.
assert not any(r["kind"]=="category" for r in overlay.store.rules())
# The reported author rule must trigger the real UI-to-wheel path without JEV.
overlay.store.add_rule("author","dy:author:self","@红衣大叔周鸿祎","手动拉黑")
overlay.engine.reset();overlay.engine.pause(False);overlay.engine.set_features(listen=False,auto=True)
overlay.ui_input.last_next=0;overlay.binding.target=(123,10,20)
blocked=Snapshot("desktop","123:10:20","zhou-video",author="@红衣大叔周鸿祎",title="另一个视频",active=True)
with patch.object(overlay.binding,"matches",return_value=True),patch("autoskip.windows.next_video",return_value=True) as wheel:
    overlay.on_desktop((overlay.engine.epoch,0),blocked,None,"作者已读取")
    wheel.assert_called_once_with((123,10,20))
    assert "作者黑名单" in overlay.engine.status
overlay.desktop_executor.shutdown(wait=True)
overlay.learning_executor.shutdown(wait=True)
overlay.store.db.close()
print("UI render and interaction checks: PASS")
