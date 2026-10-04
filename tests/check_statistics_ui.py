"""Watch statistics and historical skip controls, without operating user apps."""
import os
import sys
import uuid
import json
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ["QT_QPA_PLATFORM"]="offscreen"
os.environ["AUTOSKIP_DATA_DIR"]=str(ROOT/".local"/"statistics-check"/uuid.uuid4().hex)
from PySide6.QtWidgets import QApplication, QPushButton, QMessageBox
from PySide6.QtGui import QFontDatabase
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from autoskip.app import Overlay, Statistics
from autoskip.core import Snapshot

app=QApplication([])
QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"])/"Fonts"/"msyh.ttc"))
overlay=Overlay(preview=True);overlay.timer.stop();overlay.show();app.processEvents()
assert not overlay.auto_skip_switch.isEnabled()
overlay.auto_switch.click();overlay.auto_skip_switch.click()
assert overlay.engine.auto_enabled and overlay.engine.auto_skip_enabled
overlay.auto_switch.click()
assert not overlay.auto_skip_switch.isEnabled() and overlay.auto_skip_switch.isChecked()
overlay.auto_switch.click()
assert overlay.auto_skip_switch.isEnabled() and overlay.auto_skip_switch.isChecked()
for title,seconds in (("手机数码评测",10),("手机数码评测",5),("家常美食做饭",12),("旅行风景",20),("短时跳过的手机视频",3)):
    overlay.store.save_watch(Snapshot("chrome","test",title,author="@测试作者",title=title),seconds)
dialog=Statistics(overlay);dialog.show();app.processEvents()
assert dialog.table.rowCount()==4
assert "全部观看：5 次" in dialog.summary.text()
assert "平均 10.0 秒" in dialog.summary.text()
assert "有效观看：3 次" in dialog.summary.text()
assert [dialog.table.item(0,i).text() for i in range(4)]==["跳过","1","3.0","3.0"]
output=ROOT/".local"/"ui";output.mkdir(parents=True,exist_ok=True)
assert dialog.grab().save(str(output/"statistics.png"))
assert overlay.grab().save(str(output/"statistics-overlay.png"))
overlay.store.set("threshold",12);dialog.refresh()
assert dialog.table.rowCount()==2
assert [dialog.table.item(0,i).text() for i in range(4)]==["跳过","3","18.0","6.0"]
assert dialog.table.item(1,0).text()=="旅行风景"

def click(text):
    control=next(button for button in dialog.findChildren(QPushButton) if button.text()==text)
    QTest.mouseClick(control,Qt.MouseButton.LeftButton);app.processEvents()

backup=Path(os.environ["AUTOSKIP_DATA_DIR"])/"观看记录.json"
before=overlay.store.export_watches()
with patch("autoskip.app.QFileDialog.getSaveFileName",return_value=(str(backup),"")), \
        patch("autoskip.app.QMessageBox.information") as info:
    click("导出记录");info.assert_called_once()
assert json.loads(backup.read_text(encoding="utf-8"))==before
with patch("autoskip.app.QFileDialog.getSaveFileName",return_value=("","")), \
        patch("autoskip.app.QFileDialog.getOpenFileName",return_value=("","")), \
        patch("autoskip.app.QMessageBox.information") as info:
    click("导出记录");click("导入记录");info.assert_not_called()
with patch("autoskip.app.QFileDialog.getSaveFileName",return_value=(str(backup.parent/"missing"/"backup.json"),"")), \
        patch("autoskip.app.QMessageBox.warning") as warning:
    click("导出记录");warning.assert_called_once()
assert json.loads(backup.read_text(encoding="utf-8"))==before

snap=Snapshot("chrome","test","current",author="@作者",title="手机数码评测",active=True)
overlay.store.save_filter("保留作者","","","or")
rules=overlay.store.rules()
overlay.engine.views.switch("chrome","test",100)
overlay.engine.views.observe(snap,102)
overlay.engine.budget=(10,"数码科技");overlay.engine.budget_identity=("cached",)
with patch("autoskip.app.QMessageBox.question",return_value=QMessageBox.StandardButton.No) as question:
    click("重置统计")
    assert question.call_args.args[-1]==QMessageBox.StandardButton.No
assert overlay.store.export_watches()==before
assert overlay.engine.views.started==100 and overlay.engine.budget==(10,"数码科技")
with patch("autoskip.app.QMessageBox.question",return_value=QMessageBox.StandardButton.Yes):click("重置统计")
assert "全部观看：0 次" in dialog.summary.text() and dialog.table.rowCount()==1
assert overlay.store.export_watches()["watches"]==[]
assert overlay.store.rules()==rules and overlay.store.get("threshold")==12
assert overlay.engine.views.started is None and overlay.engine.budget is None
assert overlay.engine.budget_identity is None and overlay.engine.auto_skip_enabled
# The abandoned interval must not reappear after a reset.
assert overlay.engine.views.switch("chrome","test",115)
assert overlay.store.statistics()["count"]==0
overlay.engine.views.observe(snap,116)
assert overlay.engine.views.switch("chrome","test",130)
assert overlay.store.statistics()["seconds"]==15

# UTF-8 BOM files remain usable; imports merge with new visits and are repeatable.
backup.write_text(json.dumps(before,ensure_ascii=False),encoding="utf-8-sig")
with patch("autoskip.app.QFileDialog.getOpenFileName",return_value=(str(backup),"")), \
        patch("autoskip.app.QMessageBox.information") as info:
    click("导入记录")
    assert "新增 5 条" in info.call_args.args[2]
    assert overlay.engine.views.started==130 and overlay.engine.budget is None
    click("导入记录")
    assert "新增 0 条" in info.call_args.args[2]
assert "全部观看：6 次" in dialog.summary.text()
assert "有效观看：2 次" in dialog.summary.text()
assert overlay.store.statistics()["seconds"]==65
assert overlay.store.rules()==rules and overlay.store.get("threshold")==12

invalid=backup.parent/"invalid.json"
merged=overlay.store.export_watches()
for content in ("{",json.dumps({**before,"watches":[before["watches"][0],{}]})):
    invalid.write_text(content,encoding="utf-8")
    with patch("autoskip.app.QFileDialog.getOpenFileName",return_value=(str(invalid),"")), \
            patch("autoskip.app.QMessageBox.warning") as warning:
        click("导入记录");warning.assert_called_once()
    assert overlay.store.export_watches()==merged
with patch("autoskip.app.QFileDialog.getOpenFileName",return_value=(str(backup.parent/"missing.json"),"")), \
        patch("autoskip.app.QMessageBox.warning") as warning:
    click("导入记录");warning.assert_called_once()
assert overlay.store.export_watches()==merged

dialog.close();overlay.close()
overlay.desktop_executor.shutdown(wait=True);overlay.learning_executor.shutdown(wait=True)
overlay.store.db.close()
print("Statistics, JSON export/import, merge deduplication, reset confirmation and interval discard: PASS")
