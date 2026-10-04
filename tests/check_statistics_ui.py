"""Watch statistics and historical skip controls, without operating user apps."""
import os
import sys
import uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ["QT_QPA_PLATFORM"]="offscreen"
os.environ["AUTOSKIP_DATA_DIR"]=str(ROOT/".local"/"statistics-check"/uuid.uuid4().hex)
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
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
dialog.close();overlay.close()
overlay.desktop_executor.shutdown(wait=True);overlay.learning_executor.shutdown(wait=True)
overlay.store.db.close()
print("Statistics summary, keyword categories, strict threshold and independent skip controls: PASS")
