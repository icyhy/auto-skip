"""Verify actual Windows bounds and hit regions, without using user data."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ.pop("QT_QPA_PLATFORM",None)
os.environ["AUTOSKIP_DATA_DIR"]=str(ROOT/".local"/"native-overlay-check"/uuid.uuid4().hex)
from autoskip import windows
windows.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QPushButton,QToolButton
from autoskip.app import Overlay

app=QApplication([])
overlay=Overlay(preview=True);overlay.timer.stop();overlay.move(80,80);overlay.show()
QTest.qWait(200)
handle=int(overlay.winId());origin=overlay.pos()
scale=overlay.devicePixelRatioF()
heights=[]

def verify_bounds():
    rect=wintypes.RECT()
    assert windows.user32.GetWindowRect(handle,ctypes.byref(rect))
    size=(rect.right-rect.left,rect.bottom-rect.top)
    expected=(round(overlay.width()*scale),round(overlay.height()*scale))
    assert size==expected,("Windows/Qt bounds differ",size,expected)
    assert overlay.pos()==origin,"Folding must not move the window"
    assert (rect.left,rect.top)==(round(origin.x()*scale),round(origin.y()*scale))
    for control in overlay.findChildren(QPushButton)+overlay.findChildren(QToolButton):
        if not control.isVisible() or not control.isEnabled():continue
        point=control.mapToGlobal(control.rect().center())
        assert QApplication.widgetAt(point)==control,("Qt hit region",control.text())
        assert windows.window_at(round(point.x()*scale),round(point.y()*scale))==handle,("Windows hit region",control.text())
    heights.append(size[1])

try:
    verify_bounds()
    for _ in range(3):
        QTest.mouseClick(overlay.fold_button,Qt.MouseButton.LeftButton);QTest.qWait(150)
        assert overlay.details.isHidden()
        verify_bounds()
        assert heights[-1]<heights[0]
        enabled=overlay.engine.listen_enabled
        QTest.mouseClick(overlay.listen_switch,Qt.MouseButton.LeftButton)
        assert overlay.engine.listen_enabled!=enabled
        QTest.mouseClick(overlay.listen_switch,Qt.MouseButton.LeftButton)
        QTest.mouseClick(overlay.bind_button,Qt.MouseButton.LeftButton)
        assert overlay.picking_at
        QTest.mouseClick(overlay.bind_button,Qt.MouseButton.LeftButton)
        assert not overlay.picking_at
        overlay.engine.status="隐藏期间更新文字"*50;overlay.refresh();QTest.qWait(50)
        assert overlay.details.isHidden()
        verify_bounds()
        QTest.mouseClick(overlay.fold_button,Qt.MouseButton.LeftButton);QTest.qWait(150)
        assert not overlay.details.isHidden()
        verify_bounds()
        assert heights[-1]==heights[0]
    print("Native Windows bounds, fixed position and button hit regions: PASS",heights)
finally:
    overlay.close()
    overlay.desktop_executor.shutdown(wait=True);overlay.learning_executor.shutdown(wait=True)
    overlay.store.db.close()
