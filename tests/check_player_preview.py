"""Native hold-to-preview check using only an isolated window owned by this test."""
import ctypes
import os
from pathlib import Path
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ.pop("QT_QPA_PLATFORM",None)
os.environ["AUTOSKIP_DATA_DIR"]=str(ROOT/".local"/"player-preview-check"/uuid.uuid4().hex)
from autoskip import windows
windows.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor,QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QWidget,QTabWidget
from autoskip.app import Overlay,Settings


class SamplePlayer(QWidget):
    def paintEvent(self,event):
        painter=QPainter(self);painter.fillRect(self.rect(),QColor("#204080"))
        painter.fillRect(0,self.height()-100,self.width(),100,QColor("#ff0000"))


app=QApplication([])
player=SamplePlayer();player.setWindowTitle("AutoSkip region test player")
player.setWindowFlags(Qt.WindowType.FramelessWindowHint);player.setGeometry(60,60,900,600);player.show()
overlay=Overlay(preview=True);overlay.timer.stop()
settings=Settings(overlay);settings.findChild(QTabWidget).setCurrentIndex(2)
settings.move(100,100);settings.show();QTest.qWait(200)
target=windows.window_identity(int(player.winId()),windows.process_name(int(player.winId())))
overlay.binding.target=target
settings.player_process.setText(windows.process_name(int(player.winId())))
# Test fresh unsaved exclusions on all four sides.
settings.regions.setRowCount(0)
for direction,span in [("left",30),("right",40),("top",20),("bottom",100)]:
    settings.add_region({"direction":direction,"span":span})

try:
    original=windows.rect(int(player.winId()))
    QTest.mousePress(settings.verify_region,Qt.MouseButton.LeftButton)
    deadline=time.monotonic()+8
    while not settings.region_preview.isVisible() and time.monotonic()<deadline:
        QTest.qWait(20);time.sleep(0.01)  # Let the Python capture worker run between Qt test waits.
    assert settings.region_preview.isVisible(),settings.region_status.text()
    assert settings.verify_region.isDown(),"Preview stole activation or released the button"
    scale=player.devicePixelRatioF()
    expected=(original[0]+30,original[1]+20,original[2]-40,original[3]-100)
    actual=windows.rect(int(settings.region_preview.winId()))
    assert actual==expected,(actual,expected,scale)
    # Rendering must contain the captured effective image and the requested green border.
    image=settings.region_preview.grab().toImage()
    edge=round(scale)
    assert image.pixelColor(edge,edge).name()=="#00ff00"
    assert image.pixelColor(image.width()//2,image.height()//2).name()=="#204080"
    output=ROOT/".local"/"ui";output.mkdir(parents=True,exist_ok=True)
    image.save(str(output/"native-player-preview.png"))
    point=settings.verify_region.mapToGlobal(settings.verify_region.rect().center())
    button_scale=settings.devicePixelRatioF()
    assert windows.window_at(round(point.x()*button_scale),round(point.y()*button_scale))!=int(settings.region_preview.winId()),"Preview intercepts input"
    QTest.mouseRelease(settings.verify_region,Qt.MouseButton.LeftButton);QTest.qWait(50)
    assert not settings.region_preview.isVisible()
    assert not windows.user32.IsWindowVisible(int(settings.region_preview.winId()))
    QTest.mousePress(settings.verify_region,Qt.MouseButton.LeftButton)
    QTest.mouseRelease(settings.verify_region,Qt.MouseButton.LeftButton)
    deadline=time.monotonic()+1.2
    while time.monotonic()<deadline:QTest.qWait(20);time.sleep(0.01)
    assert not settings.region_preview.isVisible(),"A late capture resurrected the preview"
    print("Native capture, physical bounds, green frame, click-through and release: PASS",actual)
finally:
    settings.close();player.close();overlay.close()
    overlay.desktop_executor.shutdown(wait=True);overlay.learning_executor.shutdown(wait=True)
    overlay.store.db.close()
