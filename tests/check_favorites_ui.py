"""Exercise favorite controls and clipboard using an isolated offscreen UI."""
import os
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ["QT_QPA_PLATFORM"]="offscreen"
os.environ["AUTOSKIP_DATA_DIR"]=str(ROOT/".local"/"favorites-ui"/uuid.uuid4().hex)
from PySide6.QtWidgets import QApplication, QPushButton, QMessageBox
from PySide6.QtCore import Qt, QItemSelectionModel
from PySide6.QtTest import QTest
from PySide6.QtGui import QFontDatabase
from autoskip.app import Overlay, Settings, Favorites, FavoriteEditor
from autoskip.core import Snapshot

app=QApplication([])
QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"])/"Fonts"/"msyh.ttc"))
host=Overlay(preview=True);host.timer.stop();host.show();app.processEvents()
assert host.favorite_switch.isChecked()
host.listen_switch.click();assert not host.engine.listen_enabled
assert not host.engine.auto_enabled and host.favorite_switch.isEnabled()
host.favorite_switch.click();assert not host.store.get("favorites_enabled")
host.favorite_switch.click();assert host.engine.favorites_enabled
settings=Settings(host);assert settings.favorite_threshold.value()==5
settings.favorite_threshold.setValue(2.5);settings.save()
assert host.store.get("favorite_threshold")==150

first=Snapshot("chrome","tab","one","dy:video:123",author="@作者",title="手机数码实测")
second=Snapshot("chrome","tab","two","dy:video:456",author="@厨师",title="美食做饭")
missing=Snapshot("desktop","window","three",author="@旅人",title="旅行风景 #徒步")
for snap in (first,second,missing):host.store.add_favorite(snap,301)
dialog=Favorites(host);dialog.show();app.processEvents()
assert dialog.table.rowCount()==3 and not dialog.table.cellWidget(0,6).isEnabled()
QTest.mouseClick(dialog.table.cellWidget(1,6),Qt.MouseButton.LeftButton)
assert app.clipboard().text()=="https://www.douyin.com/video/456"
dialog.search.setText("数码");assert dialog.table.rowCount()==1
assert dialog.table.item(0,0).text()=="@作者"
dialog.search.setText("旅行");dialog.table.selectRow(0)
editor=FavoriteEditor(host,dialog.rows[0],dialog)
editor.category.setText("我的旅行");editor.link.setText("https://example.com/trip");editor.save();dialog.refresh()
assert dialog.table.item(0,2).text()=="我的旅行"
assert dialog.table.cellWidget(0,6).isEnabled()
dialog.search.clear();app.processEvents()
for row in (0,1):
    dialog.table.selectionModel().select(dialog.table.model().index(row,0),QItemSelectionModel.SelectionFlag.Select|QItemSelectionModel.SelectionFlag.Rows)
dialog.copy_selected()
assert app.clipboard().text()=="https://example.com/trip\nhttps://www.douyin.com/video/456"
with patch("autoskip.app.QMessageBox.question",return_value=QMessageBox.StandardButton.No):dialog.delete()
assert len(host.store.favorites())==3
with patch("autoskip.app.QMessageBox.question",return_value=QMessageBox.StandardButton.Yes):dialog.delete()
assert len(host.store.favorites())==1
dialog.copy_links([]);assert "没有可复制" in dialog.note.text()
with patch("autoskip.app.QMessageBox.question",return_value=QMessageBox.StandardButton.No):dialog.clear()
assert len(host.store.favorites())==1

# Keep screenshots of populated views for layout review.
for snap in (second,missing):host.store.add_favorite(snap,301)
dialog.refresh();app.processEvents()
output=ROOT/".local"/"ui";output.mkdir(parents=True,exist_ok=True)
assert dialog.grab().save(str(output/"favorites.png"))
assert host.grab().save(str(output/"favorites-overlay.png"))
settings=Settings(host);settings.show();app.processEvents()
assert settings.grab().save(str(output/"favorites-settings.png"))
settings.close()
with patch("autoskip.app.QMessageBox.question",return_value=QMessageBox.StandardButton.Yes):dialog.clear()
assert not host.store.favorites()
dialog.close();host.close();host.desktop_executor.shutdown(wait=True);host.learning_executor.shutdown(wait=True)
host.store.db.close()
print("Favorite settings, independent switch, search, editing, row/batch copy and confirmed deletion: PASS")
