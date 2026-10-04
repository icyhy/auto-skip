import ctypes
from copy import deepcopy
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import json
import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal, QObject, QPoint, QLockFile, QEvent
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap, QFont, QFontDatabase, QImage, QPen
from PySide6.QtWidgets import (
    QApplication, QWidget, QFrame, QLabel, QPushButton, QToolButton, QMenu,
    QHBoxLayout, QVBoxLayout, QFormLayout, QDialog, QTabWidget, QComboBox,
    QDoubleSpinBox, QSpinBox, QLineEdit, QCheckBox, QSlider, QDialogButtonBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QSystemTrayIcon, QAbstractItemView,
)
from . import windows, bridge
from .core import Engine, Snapshot, purchase_evidence
from .store import Store
from .desktop import DesktopReader
from .capture import capture_region
from .learning import QuickSkip, ScreenshotAnalyzer
from .players import DIRECTIONS, validate_profiles


STYLE = """
QWidget { font-family: 'Microsoft YaHei UI'; font-size: 12px; color: #e4ebf5; }
QDialog { background: #141c29; }
QFrame#panel { background: #182334; border: 1px solid #35445b; border-radius: 14px; }
QPushButton,QToolButton { background: #27354a; border: 0; border-radius: 7px; padding: 8px 12px; }
QPushButton:hover,QToolButton:hover { background: #344760; }
QPushButton#primary { background: #3fcaac; color: #092b25; font-weight: 600; }
QLabel#muted { color: #91a4bc; }
QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox { background: #1e2b3e; border: 1px solid #3d4e65; border-radius: 5px; padding: 6px; }
QComboBox QAbstractItemView { background: #1e2b3e; color: #e4ebf5; border: 1px solid #3d4e65; selection-background-color: #36516c; selection-color: #e4ebf5; outline: 0; }
QComboBox QAbstractItemView::item { min-height: 28px; padding: 4px 8px; }
QComboBox QAbstractItemView::item:hover,QComboBox QAbstractItemView::item:selected { background: #36516c; color: #e4ebf5; }
QTableWidget { background: #192537; gridline-color: #314055; alternate-background-color: #1e2c40; }
QHeaderView::section,QTableCornerButton::section { background: #27354a; padding: 8px; border: 0; }
QTabWidget::pane { border: 1px solid #34455e; padding: 12px; }
QTabBar::tab { background: #1c293b; padding: 10px 16px; }
QTabBar::tab:selected { background: #31445e; }
QMenu { background: #1e2b3e; border: 1px solid #41546c; padding: 5px; }
QMenu::item { padding: 7px 22px; }
QMenu::item:selected { background: #36516c; }
QCheckBox { spacing: 8px; }
"""


class Bus(QObject):
    message = Signal(object, object)
    desktop = Signal(object, object, object, object)
    captured = Signal(object, str)
    learned = Signal(object, object, str)
    manual = Signal(object, object, str)
    navigated = Signal(object, float)


def button(text, callback, primary=False):
    value = QPushButton(text)
    value.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    if primary:
        value.setObjectName("primary")
    value.clicked.connect(callback)
    return value


class PlayerRegionPreview(QWidget):
    def __init__(self,parent):
        super().__init__(parent,Qt.WindowType.ToolTip|Qt.WindowType.FramelessWindowHint|
            Qt.WindowType.WindowStaysOnTopHint|Qt.WindowType.WindowDoesNotAcceptFocus|Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.pixmap=QPixmap()

    def display(self,image,area):
        image=image.convert("RGB")
        self.pixmap=QPixmap.fromImage(QImage(image.tobytes(),image.width,image.height,image.width*3,QImage.Format.Format_RGB888).copy())
        self.show()
        # Use physical coordinates so negative monitor origins and DPI scaling agree with WGC.
        if not windows.user32.SetWindowPos(int(self.winId()),-1,area[0],area[1],area[2]-area[0],area[3]-area[1],0x10|0x40):
            self.hide();raise OSError("无法显示有效区域边框")
        self.update()

    def paintEvent(self,event):
        painter=QPainter(self);painter.drawPixmap(self.rect(),self.pixmap)
        painter.setPen(QPen(QColor("#00ff00"),3));painter.drawRect(self.rect().adjusted(1,1,-2,-2))


class Settings(QDialog):
    region_captured=Signal(int,object,object,str)

    def __init__(self, app):
        super().__init__(app)
        self.host=app
        self.setWindowTitle("Auto Skip · 设置")
        self.resize(680,650)
        self.region_preview=PlayerRegionPreview(self);self.region_request=0
        self.region_captured.connect(self.show_region)
        layout=QVBoxLayout(self)
        tabs=QTabWidget()
        layout.addWidget(tabs)
        general=QWidget();form=QFormLayout(general)
        self.source=QComboBox();self.source.addItem("自动识别（推荐）","auto");self.source.addItem("Chrome 网页版","chrome");self.source.addItem("抖音电脑客户端","desktop")
        self.source.setCurrentIndex(max(0,self.source.findData(app.store.get("source"))))
        form.addRow("观看入口",self.source)
        self.threshold=QDoubleSpinBox();self.threshold.setRange(0.5,60);self.threshold.setValue(app.store.get("threshold"));self.threshold.setSuffix(" 秒")
        form.addRow("快速跳过阈值",self.threshold)
        self.opacity=QSlider(Qt.Orientation.Horizontal);self.opacity.setRange(35,100);self.opacity.setValue(int(app.store.get("opacity")*100))
        form.addRow("浮窗透明度",self.opacity)
        self.hotkeys={}
        for name,label in [("pause","开始／暂停"),("block","拉黑作者"),("undo","撤销拉黑"),("auto","自动开关"),("listen","监听开关"),("show","显示浮窗／关闭穿透")]:
            field=QLineEdit(app.store.get("hotkeys")[name]);self.hotkeys[name]=field;form.addRow(label,field)
        note=QLabel("自动查找并绑定抖音窗口。切到其他软件后仍可识别；可在「播放器区域」中设置 OCR 排除区域。")
        note.setWordWrap(True);note.setObjectName("muted");form.addRow(note)
        tabs.addTab(general,"常规")
        chrome=QWidget();cf=QVBoxLayout(chrome)
        help_text=QLabel("1. Chrome 打开 chrome://extensions，开启开发者模式。\n2. 点击「加载已解压的扩展程序」，选择发布目录中的 extension 文件夹。\n3. 将扩展卡片上的 ID 粘贴到下方，点击注册。\n4. 回到抖音网页并刷新，在桌面浮窗点击开始。")
        help_text.setWordWrap(True);cf.addWidget(help_text)
        self.extension=QLineEdit(app.store.get("extension_id",""));self.extension.setPlaceholderText("32 位扩展 ID");cf.addWidget(self.extension)
        cf.addWidget(button("注册本机连接",self.register));cf.addStretch()
        tabs.addTab(chrome,"Chrome 连接")
        players=QWidget();pf=QVBoxLayout(players);fields=QFormLayout();pf.addLayout(fields)
        self.player_profiles=deepcopy(app.store.get("player_profiles"))
        self.player_type=QComboBox();self.player_type.addItems([p["name"] for p in self.player_profiles])
        self.player_type.setCurrentIndex(max(0,self.player_type.findText(app.store.get("player_type"))))
        fields.addRow("当前使用／编辑的播放器",self.player_type)
        self.player_name=QLineEdit();fields.addRow("类型名称",self.player_name)
        self.player_process=QLineEdit();self.player_process.setPlaceholderText("例如 douyin.exe")
        fields.addRow("窗口进程",self.player_process)
        type_actions=QHBoxLayout();pf.addLayout(type_actions)
        type_actions.addWidget(button("新增播放器类型",self.add_player))
        self.delete_player_button=button("删除播放器类型",self.delete_player);type_actions.addWidget(self.delete_player_button)
        self.regions=QTableWidget(0,2);self.regions.setHorizontalHeaderLabels(["排除方向","跨度（像素）"])
        self.regions.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.regions.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        pf.addWidget(self.regions)
        region_actions=QHBoxLayout();pf.addLayout(region_actions)
        region_actions.addWidget(button("添加排除区域",lambda:self.add_region()))
        region_actions.addWidget(button("删除所选区域",self.delete_region))
        self.verify_region=QPushButton("按住验证有效区域")
        self.verify_region.setToolTip("按住显示当前未保存配置的有效截图和绿色边框，松开取消")
        self.verify_region.pressed.connect(self.start_region_preview);self.verify_region.released.connect(self.stop_region_preview)
        pf.addWidget(self.verify_region)
        self.region_status=QLabel("按住验证，松开隐藏；无需先保存设置。")
        self.region_status.setWordWrap(True);self.region_status.setObjectName("muted");pf.addWidget(self.region_status)
        player_note=QLabel("从绑定播放窗口的边缘向内排除，跨度使用原始截图像素。下方 100 表示底部 100 像素不参与 OCR。\n每个类型可配置多个区域；同方向取最大跨度。删除全部区域可恢复整窗识别。\n当前选择的类型应用于桌面 OCR、作者复核和划走快照；Chrome 网页文字读取不使用此配置。")
        player_note.setWordWrap(True);player_note.setObjectName("muted");pf.addWidget(player_note)
        self.player_index=None;self.select_player(self.player_type.currentIndex())
        self.player_type.currentIndexChanged.connect(self.select_player)
        tabs.addTab(players,"播放器区域")
        tabs.currentChanged.connect(self.stop_region_preview)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.save);buttons.rejected.connect(self.reject);layout.addWidget(buttons)

    def stash_player(self):
        if self.player_index is None:return
        name=self.player_name.text().strip()
        self.player_profiles[self.player_index]={"name":name,"process":self.player_process.text().strip().lower(),"regions":[
            {"direction":self.regions.cellWidget(row,0).currentData(),"span":self.regions.cellWidget(row,1).value()}
            for row in range(self.regions.rowCount())]}
        self.player_type.setItemText(self.player_index,name)

    def select_player(self,index):
        self.stop_region_preview()
        self.stash_player();self.player_index=index
        profile=self.player_profiles[index]
        self.player_name.setText(profile["name"]);self.regions.setRowCount(0)
        self.player_process.setText(profile.get("process","douyin.exe"))
        for region in profile["regions"]:self.add_region(region)
        self.delete_player_button.setEnabled(len(self.player_profiles)>1)

    def add_player(self):
        self.stash_player()
        name="新播放器";number=2
        while name in {p["name"] for p in self.player_profiles}:
            name=f"新播放器 {number}";number+=1
        self.player_profiles.append({"name":name,"process":"douyin.exe","regions":[]})
        self.player_type.addItem(name);self.player_type.setCurrentIndex(len(self.player_profiles)-1)
        self.player_name.setFocus();self.player_name.selectAll()

    def delete_player(self):
        if len(self.player_profiles)<=1:return
        index=self.player_index;self.player_index=None
        del self.player_profiles[index]
        self.player_type.blockSignals(True);self.player_type.removeItem(index);self.player_type.blockSignals(False)
        self.select_player(self.player_type.currentIndex())

    def add_region(self,region=None):
        region=region or {"direction":"bottom","span":100}
        row=self.regions.rowCount();self.regions.insertRow(row)
        direction=QComboBox()
        for key,label in DIRECTIONS.items():direction.addItem(label,key)
        direction.setCurrentIndex(direction.findData(region["direction"]))
        span=QSpinBox();span.setRange(1,2147483647);span.setValue(region["span"]);span.setSuffix(" 像素")
        self.regions.setCellWidget(row,0,direction);self.regions.setCellWidget(row,1,span)
        self.regions.setRowHeight(row,42)

    def delete_region(self):
        for row in sorted({index.row() for index in self.regions.selectedIndexes()},reverse=True):
            self.regions.removeRow(row)

    def start_region_preview(self):
        self.stop_region_preview();request=self.region_request
        try:
            self.stash_player();profile=deepcopy(self.player_profiles[self.player_index])
            validate_profiles([profile],profile["name"])
        except ValueError as error:
            self.region_status.setText(str(error));return
        preferred=self.host.binding.target
        self.region_status.setText("正在查找窗口并截取有效区域…")
        def capture():
            try:
                target=windows.find_player_window(profile["process"],preferred)
                image,area=capture_region(target,{"player_type":profile["name"],"player_profiles":[profile]})
                error=""
            except (ValueError,OSError) as problem:image=area=None;error=str(problem)
            except Exception as problem:image=area=None;error="区域验证失败（"+type(problem).__name__+"）："+str(problem)[:500]
            self.region_captured.emit(request,image,area,error)
        self.host.desktop_executor.submit(capture)

    def show_region(self,request,image,area,error):
        if request!=self.region_request or not self.verify_region.isDown() or not self.isVisible():return
        if error:self.region_status.setText(error);return
        try:self.region_preview.display(image,area)
        except OSError as problem:self.region_status.setText(str(problem));return
        self.region_status.setText(f"绿色边框内为有效区域：{image.width} × {image.height} 像素；松开隐藏。")

    def stop_region_preview(self,*args):
        self.region_request+=1;self.region_preview.hide()

    def hideEvent(self,event):
        self.stop_region_preview();super().hideEvent(event)

    def changeEvent(self,event):
        if event.type()==QEvent.Type.ActivationChange and not self.isActiveWindow():self.stop_region_preview()
        super().changeEvent(event)

    def register(self):
        try:
            bridge.register_host(self.extension.text().strip())
            self.host.store.set("extension_id",self.extension.text().strip())
            QMessageBox.information(self,"已注册","请刷新抖音网页，或重新加载扩展。")
        except (ValueError,OSError) as error:
            QMessageBox.warning(self,"未注册",str(error))

    def save(self):
        try:
            keys={name:field.text().strip() for name,field in self.hotkeys.items()}
            parsed=[windows.hotkey_parts(value) for value in keys.values()]
            if len(set(parsed))!=len(parsed):
                raise ValueError("快捷键不能重复")
            self.stash_player()
            player_type=self.player_profiles[self.player_index]["name"]
            validate_profiles(self.player_profiles,player_type)
            for key,value in {"source":self.source.currentData(),"threshold":self.threshold.value(),
                "opacity":self.opacity.value()/100,"hotkeys":keys,
                "player_type":player_type,"player_profiles":self.player_profiles}.items():
                self.host.store.set(key,value)
            self.host.reload_settings()
            self.accept()
        except (ValueError,OSError) as error:
            QMessageBox.warning(self,"设置未保存",str(error))


class RuleEditor(QDialog):
    def __init__(self, host, rule=None, parent=None):
        super().__init__(parent or host);self.host=host;self.rule=rule
        self.setWindowTitle("编辑规则" if rule else "手动添加规则");self.resize(580,300)
        layout=QVBoxLayout(self);form=QFormLayout();layout.addLayout(form)
        self.author=QLineEdit();self.author.setPlaceholderText("完整作者名称，可带 @")
        self.keyword=QLineEdit();self.keyword.setPlaceholderText("在视频标题或解析文字中查找的关键词")
        self.link=QLineEdit();self.link.setPlaceholderText("https://www.douyin.com/video/…")
        self.condition=QComboBox();self.condition.addItem("或（任一项匹配）","or");self.condition.addItem("与（三项全部匹配）","and")
        for name,label in (("author","作者"),("keyword","关键词"),("link","链接")):
            field=getattr(self,name);field.setMaxLength(2000);form.addRow(label,field)
            if rule:field.setText(rule[name])
        if rule:
            self.condition.setCurrentIndex(self.condition.findData(rule["condition"]))
            if rule["kind"]=="video" and not rule["link"].startswith(("http://","https://","www.")):
                self.link.clear();self.link.setPlaceholderText("历史视频无可用链接；编辑后请填写新的匹配内容")
        form.addRow("过滤条件",self.condition)
        note=QLabel("或：至少填写一项，任一项匹配即可。\n与：作者、关键词、链接均需填写，并且三项全部匹配。\n作者按完整名称匹配；关键词按包含匹配；链接按完整地址匹配。")
        note.setWordWrap(True);note.setObjectName("muted");layout.addWidget(note)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.save);buttons.rejected.connect(self.reject);layout.addWidget(buttons)

    def save(self):
        try:
            change=self.host.store.save_filter(self.author.text(),self.keyword.text(),self.link.text(),self.condition.currentData(),
                                              self.rule["id"] if self.rule else None)
            if change:
                self.host.engine.undo_stack.append(change);self.host.engine.undo_stack=self.host.engine.undo_stack[-30:]
            else:
                self.host.engine.undo_stack=[c for c in self.host.engine.undo_stack if c["id"]!=self.rule["id"]]
            label=" / ".join(value for value in (self.author.text(),self.keyword.text(),self.link.text()) if value)
            self.host.store.log("编辑规则" if self.rule else "添加规则",label,"与" if self.condition.currentData()=="and" else "或")
            self.accept()
        except ValueError as error:QMessageBox.warning(self,"规则未保存",str(error))


class Rules(QDialog):
    def __init__(self, host):
        super().__init__(host);self.host=host
        self.setWindowTitle("Auto Skip · 黑名单与记录");self.resize(1000,520)
        layout=QVBoxLayout(self)
        self.search=QLineEdit();self.search.setPlaceholderText("搜索作者、关键词或链接");self.search.textChanged.connect(self.refresh);layout.addWidget(self.search)
        self.table=QTableWidget(0,6);self.table.setHorizontalHeaderLabels(["作者","关键词","链接","过滤条件","启用","添加时间"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        for column in range(3):self.table.horizontalHeader().setSectionResizeMode(column,QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        row=QHBoxLayout();layout.addLayout(row)
        row.addWidget(button("手动添加",self.add_rule));row.addWidget(button("编辑规则",self.edit_rule));row.addWidget(button("启用／停用",self.toggle));row.addWidget(button("删除规则",self.delete))
        row.addWidget(button("最近操作",self.history));row.addWidget(button("关闭",self.accept))
        self.refresh()

    def refresh(self):
        query=self.search.text().casefold()
        self.rows=[r for r in self.host.store.rules() if query in " ".join(r[key] for key in ("author","keyword","link","label","reason")).casefold()]
        self.table.setRowCount(len(self.rows))
        for i,r in enumerate(self.rows):
            link=r["link"]
            if r["kind"]=="video" and not link.startswith(("http://","https://","www.")):link="已学习视频："+r["label"]
            for j,value in enumerate([r["author"],r["keyword"],link,"与" if r["condition"]=="and" else "或","是" if r["enabled"] else "否",r["created"]]):
                item=QTableWidgetItem(value);item.setToolTip(value+"\n"+r["reason"]);self.table.setItem(i,j,item)

    def selected(self):
        index=self.table.currentRow()
        return self.rows[index] if 0<=index<len(self.rows) else None

    def toggle(self):
        r=self.selected()
        if r:self.host.store.enable(r["id"],not r["enabled"]);self.refresh()

    def delete(self):
        r=self.selected()
        if r:self.host.store.delete(r["id"]);self.refresh()

    def add_rule(self):
        if RuleEditor(self.host,parent=self).exec():self.refresh()

    def edit_rule(self):
        r=self.selected()
        if r and RuleEditor(self.host,r,parent=self).exec():self.refresh()

    def history(self):
        dialog=QDialog(self);dialog.setWindowTitle("最近操作（本机最多保存 300 条）");dialog.resize(720,400)
        from PySide6.QtWidgets import QPlainTextEdit
        box=QPlainTextEdit();box.setReadOnly(True)
        box.setPlainText("\n\n".join(f'{r["created"]} · {r["action"]}\n{r["label"]}\n{r["reason"]}' for r in self.host.store.history()))
        QVBoxLayout(dialog).addWidget(box);dialog.exec()


class Statistics(QDialog):
    def __init__(self, host):
        super().__init__(host);self.host=host
        self.setWindowTitle("Auto Skip · 观看统计");self.resize(760,520)
        layout=QVBoxLayout(self)
        self.summary=QLabel();self.summary.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(self.summary)
        self.note=QLabel();self.note.setWordWrap(True);self.note.setObjectName("muted");layout.addWidget(self.note)
        self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels(["类别","观看次数","总观看时长（秒）","平均观看时长（秒）"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        row=QHBoxLayout();layout.addLayout(row)
        row.addWidget(button("刷新统计",self.refresh));row.addWidget(button("关闭",self.accept))
        self.refresh()

    def refresh(self):
        stats=self.host.store.statistics()
        self.summary.setText(f"全部观看：{stats['count']} 次 · 总计 {stats['seconds']:.1f} 秒 · 平均 {stats['average']:.1f} 秒\n"
                             f"有效观看：{stats['valid_count']} 次 · 总计 {stats['valid_seconds']:.1f} 秒 · 平均 {stats['valid_average']:.1f} 秒")
        self.note.setText(f"小于 {self.host.store.get('threshold'):g} 秒归入「跳过」；严格大于阈值为有效观看。关键词分类和历史时长分析仅使用有效观看。"
                          "按标题及话题关键词分类，一条视频可归入多个类别，各类次数不相加。"
                          "时长为两次视频切换的时间间隔；启动时的第一条和退出时的最后一条不统计。首次切换只建立起点，第二次切换开始产生统计记录。")
        rows=[stats["skipped"],*stats["categories"]]
        self.table.setRowCount(len(rows))
        for i,group in enumerate(rows):
            for j,value in enumerate((group["category"],str(group["count"]),f"{group['seconds']:.1f}",f"{group['average']:.1f}")):
                item=QTableWidgetItem(value);item.setToolTip(value);self.table.setItem(i,j,item)


class Overlay(QWidget):
    def __init__(self, preview=False):
        super().__init__()
        self.preview=preview
        self.setWindowTitle("Auto Skip")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowStaysOnTopHint|Qt.WindowType.Tool|Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.store=Store(windows.data_dir()/"autoskip.db")
        self.engine=Engine(self.store)
        self.desktop_executor=ThreadPoolExecutor(max_workers=1)
        self.learning_executor=ThreadPoolExecutor(max_workers=1)
        self.bus=Bus();self.bus.message.connect(self.on_message);self.bus.desktop.connect(self.on_desktop)
        self.desktop_busy=False;self.reply_context=None;self.auto_input_at=0.0
        self.ui_input=windows.UserInput();self.reader=DesktopReader(self.ui_input)
        self.quick_skip=QuickSkip(self.reader.capture.freeze,self.bus.captured.emit)
        self.screenshot_analyzer=ScreenshotAnalyzer()
        self.bus.captured.connect(self.on_captured);self.bus.learned.connect(self.on_learned)
        self.bus.manual.connect(self.on_manual);self.manual_busy=False
        self.bus.navigated.connect(self.on_navigation)
        def navigation(kind,at,frame=None):
            self.quick_skip.navigation(kind,at,frame)
            self.bus.navigated.emit(self.binding.target,at)
        self.ui_input.on_navigation=navigation
        self.ui_input.on_drag_start=self.quick_skip.drag_frame
        self.notice_until=0.0
        self.binding=windows.WindowBinding();self.picking_at=0.0;self.discovered_at=0.0;self.desktop_next_at=0.0
        self.desktop_switch_at=0.0
        self.listener=None;self.dialog_open=False;self.folded=False;self.drag_start=None;self.passthrough=False
        self.last_sequence={}
        outer=QVBoxLayout(self);outer.setContentsMargins(0,0,0,0)
        panel=QFrame();panel.setObjectName("panel");outer.addWidget(panel)
        layout=QVBoxLayout(panel);layout.setContentsMargins(15,12,15,12)
        top=QHBoxLayout();layout.addLayout(top)
        self.brand=QLabel("●  AUTO SKIP");self.brand.setStyleSheet("color:#73e2c2;font-size:13px;font-weight:700;letter-spacing:1px")
        top.addWidget(self.brand);top.addStretch()
        self.listen_switch=QCheckBox("监听");self.listen_switch.setToolTip("根据用户快速切换学习视频黑名单，可与自动同时开启")
        self.listen_switch.toggled.connect(self.set_listening);top.addWidget(self.listen_switch)
        self.auto_switch=QCheckBox("自动");self.auto_switch.setToolTip("根据黑名单自动跳过，可与监听同时开启")
        self.auto_switch.toggled.connect(self.set_automatic);top.addWidget(self.auto_switch)
        self.pause_button=button("开始",self.toggle_pause,True);top.addWidget(self.pause_button)
        self.fold_button=button("−",self.fold);self.fold_button.setToolTip("隐藏解析文字")
        self.fold_button.setAccessibleName("隐藏解析文字");top.addWidget(self.fold_button)
        self.details=QWidget();detail=QVBoxLayout(self.details);detail.setContentsMargins(0,0,0,0);layout.addWidget(self.details)
        self.status=QLabel();detail.addWidget(self.status)
        self.notice=QLabel();self.notice.setStyleSheet("color:#73e2c2");detail.addWidget(self.notice)
        self.subtitle=QLabel("自动识别观看窗口 · 本地优先");self.subtitle.setObjectName("muted");detail.addWidget(self.subtitle)
        self.auto_skip_switch=QCheckBox("按历史时长自动跳过")
        self.auto_skip_switch.setToolTip("启用自动后可选择。优先使用同一视频的有效平均观看时长，其次使用匹配关键词类别的平均时长；无有效历史时继续观看。")
        self.auto_skip_switch.toggled.connect(lambda enabled:self.set_auto_skip(enabled));layout.addWidget(self.auto_skip_switch)
        target_row=QHBoxLayout();layout.addLayout(target_row)
        self.target_label=QLabel("自动查找抖音窗口");self.target_label.setObjectName("muted");target_row.addWidget(self.target_label,1)
        self.bind_button=button("绑定窗口",self.pick_window);target_row.addWidget(self.bind_button)
        actions=QHBoxLayout();layout.addLayout(actions)
        block=QToolButton();block.setText("拉黑作者");block.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        block.clicked.connect(lambda:self.block("author"));menu=QMenu(block)
        menu.addAction("拉黑当前视频",lambda:self.block("video"));menu.addAction("拉黑作者",lambda:self.block("author"));menu.addAction("手动添加规则",self.new_rule)
        block.setMenu(menu);actions.addWidget(block)
        actions.addWidget(button("黑名单",self.open_rules))
        actions.addWidget(button("观看统计",self.open_statistics))
        more=QToolButton();more.setText("···");more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup);moremenu=QMenu(more)
        moremenu.addAction("设置",self.open_settings);moremenu.addAction("鼠标穿透（快捷键恢复）",self.enable_passthrough)
        moremenu.addAction("重新自动查找窗口",self.rediscover_window)
        moremenu.addAction("收起到托盘",self.hide);moremenu.addAction("退出",self.quit);more.setMenu(moremenu);actions.addWidget(more)
        self.setStyleSheet(STYLE);self.setFixedWidth(460);self.ensurePolished()
        line_height=self.status.fontMetrics().lineSpacing()
        for field in (self.status,self.notice,self.subtitle):
            field.setTextFormat(Qt.TextFormat.PlainText)
            field.setWordWrap(True);field.setMaximumWidth(430)
            field.setAlignment(Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignTop)
            field.setFixedHeight(line_height*2+4)
        self.layout().activate()
        self.expanded_height=max(244,self.sizeHint().height())
        self.collapsed_height=self.expanded_height-self.details.sizeHint().height()-layout.spacing()
        self.setFixedHeight(self.expanded_height)
        self.icon=self.make_icon();self.setWindowIcon(self.icon)
        self.tray=QSystemTrayIcon(self.icon,self);self.tray.setToolTip("Auto Skip · 双击显示")
        traymenu=QMenu();traymenu.addAction("显示浮窗",self.restore);traymenu.addAction("开始／暂停",self.toggle_pause)
        traymenu.addAction("设置",self.open_settings);traymenu.addAction("退出",self.quit);self.tray.setContextMenu(traymenu)
        self.tray.activated.connect(lambda reason:self.restore() if reason==QSystemTrayIcon.ActivationReason.DoubleClick else None)
        self.reload_settings()
        pos=self.store.get("position",[40,80]);self.move(*pos)
        screen=QApplication.primaryScreen().availableGeometry()
        if not screen.intersects(self.geometry()):self.move(screen.topLeft()+QPoint(40,80))
        self.timer=QTimer(self);self.timer.timeout.connect(self.tick);self.timer.start(150)
        if not preview:
            try:self.listener=bridge.serve(lambda data,reply:self.bus.message.emit(data,reply))
            except OSError:self.engine.status="本地连接启动失败；请检查是否已启动另一份程序"
            self.ui_input.start();self.tray.show()
        self.refresh()

    def make_icon(self):
        pix=QPixmap(64,64);pix.fill(Qt.GlobalColor.transparent);p=QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setBrush(QColor("#182334"));p.setPen(Qt.PenStyle.NoPen);p.drawRoundedRect(0,0,64,64,15,15)
        p.setPen(QColor("#64dfbd"));p.setFont(QFont("Segoe UI",30,QFont.Weight.Bold));p.drawText(pix.rect(),Qt.AlignmentFlag.AlignCenter,"»");p.end();return QIcon(pix)

    def reload_settings(self):
        self.config={key:self.store.get(key) for key in ("source","player_type","player_profiles")}
        self.setWindowOpacity(self.store.get("opacity"))
        self.engine.reset(preserve_watch=True)
        self.desktop_executor.submit(self.reader.close)
        if self.preview:return
        self.register_hotkeys()

    def register_hotkeys(self):
        if self.preview:return
        conflicts=[];self.registered=set()
        hotkeys=self.store.get("hotkeys")
        for i in range(1,max(getattr(self,"hotkey_count",0),len(hotkeys))+1):windows.unregister_hotkey(int(self.winId()),i)
        self.hotkey_count=len(hotkeys)
        for i,(name,key) in enumerate(hotkeys.items(),1):
            if not windows.register_hotkey(int(self.winId()),i,key):conflicts.append(key)
            else:self.registered.add(name)
        if conflicts:self.engine.status="快捷键冲突："+"、".join(conflicts)

    def nativeEvent(self,event_type,message):
        from ctypes import wintypes
        msg=wintypes.MSG.from_address(int(message))
        if msg.message==0x312:
            names=list(self.store.get("hotkeys"))
            index=int(msg.wParam)-1
            if 0<=index<len(names):
                {"pause":self.toggle_pause,"block":lambda:self.block("author"),"undo":self.undo,
                 "auto":lambda:self.set_automatic(not self.engine.auto_enabled),
                 "listen":lambda:self.set_listening(not self.engine.listen_enabled),"show":self.restore}[names[index]]()
            return True,0
        return super().nativeEvent(event_type,message)

    def refresh(self):
        self.sync_learning()
        if time.monotonic()>=self.notice_until:self.notice.clear();self.notice.setToolTip("")
        self.status.setText(self.engine.status)
        self.status.setToolTip(self.engine.status)
        for switch,enabled in ((self.listen_switch,self.engine.listen_enabled),(self.auto_switch,self.engine.auto_enabled)):
            switch.blockSignals(True);switch.setChecked(enabled);switch.blockSignals(False)
        self.auto_skip_switch.blockSignals(True);self.auto_skip_switch.setChecked(self.engine.auto_skip_enabled);self.auto_skip_switch.blockSignals(False)
        self.auto_skip_switch.setEnabled(self.engine.auto_enabled)
        self.pause_button.setText("开始" if self.engine.paused else "暂停")
        snap=self.engine.current
        text=(snap.author+" · "+snap.title).strip(" ·") if snap else {"auto":"自动识别观看窗口","chrome":"Chrome 网页版","desktop":"抖音电脑客户端"}[self.config["source"]]
        self.subtitle.setText((text or "正在读取视频信息")+" · 本地优先");self.subtitle.setToolTip(text)
        target=self.binding.target
        self.target_label.setText("请点击抖音窗口…" if self.picking_at else ("已绑定："+self.binding.title[:22] if target else "自动查找抖音窗口"))
        self.target_label.setToolTip(f"HWND: 0x{target[0]:X} · PID: {target[1]}" if target else "发现多个抖音窗口时，点击绑定窗口后选择要观看的窗口")
        self.bind_button.setText("取消绑定" if self.picking_at else "绑定窗口")

    def sync_learning(self):
        active=not self.engine.paused and not self.dialog_open and not self.picking_at and self.accepts_source("desktop") and (self.engine.listen_enabled or self.engine.auto_enabled)
        target=self.binding.target if active else None
        self.quick_skip.configure(target,active and self.engine.listen_enabled,float(self.store.get("threshold")))
        hwnd=target[0] if target else 0
        if self.ui_input.hwnd!=hwnd:self.ui_input.drag=None;self.ui_input.down_pressed=False
        self.ui_input.hwnd=hwnd

    def show_notice(self,text):
        self.notice.setText(text);self.notice.setToolTip(text);self.notice_until=time.monotonic()+8;self.refresh()

    def on_captured(self,event,message):
        if event is None:self.show_notice(message);return
        if not self.quick_skip.qualifies(event):
            self.quick_skip.slots.release();return
        self.show_notice(message)
        config=deepcopy(self.config)
        def analyze():
            try:
                if not self.quick_skip.qualifies(event):raise ValueError("观看间隔已达到阈值，已取消后台解析")
                result=self.screenshot_analyzer.analyze(event,config);error=""
            except ValueError as problem:result=None;error=str(problem)
            except Exception as problem:result=None;error="截图解析失败，本次未加入黑名单（"+type(problem).__name__+"）"
            self.bus.learned.emit(event,result,error)
        self.learning_executor.submit(analyze)

    def on_learned(self,event,result,error):
        try:
            if not self.quick_skip.qualifies(event):
                self.show_notice("观看间隔已达到阈值，未加入黑名单");return
            if error:self.show_notice(error);return
            label=result["author"]+" "+result["title"]
            self.engine.remember("video",result["target"],label,
                f"快速切换：{event.kind}，间隔 {event.elapsed:.3f} 秒，触发阈值 {event.threshold:g} 秒；划走前截图识别")
            self.show_notice(label+f" 视频被加入黑名单（切换间隔 {event.elapsed:.3f} 秒）")
        finally:self.quick_skip.slots.release()

    def toggle_pause(self):
        self.engine.pause(not self.engine.paused);self.refresh()
        if self.engine.paused:self.desktop_executor.submit(self.reader.close)

    def set_listening(self,enabled):
        self.engine.set_features(listen=enabled);self.refresh()
        if not self.engine.listen_enabled and not self.engine.auto_enabled:self.desktop_executor.submit(self.reader.close)

    def set_automatic(self,enabled):
        self.engine.set_features(auto=enabled);self.refresh()
        if not self.engine.listen_enabled and not self.engine.auto_enabled:self.desktop_executor.submit(self.reader.close)

    def set_auto_skip(self,enabled):
        self.engine.set_features(auto_skip=enabled);self.refresh()

    def block(self,kind):
        if not self.engine.auto_enabled and self.accepts_source("desktop") and self.binding.target and not self.engine.paused:
            if self.manual_busy:return
            self.manual_busy=True
            request=(self.binding.target,kind,self.engine.epoch)
            config={**self.config,"desktop_target":self.binding.target,"mode":"manual"}
            self.show_notice("正在处理你手动指定的拉黑操作…")
            def analyze_manual():
                try:snap,_,note=self.reader.read(config)
                except Exception as error:snap,note=None,"手动读取失败："+type(error).__name__
                self.bus.manual.emit(request,snap,note)
            self.desktop_executor.submit(analyze_manual)
            return
        snap=self.engine.current
        hwnd=windows.foreground()
        if not snap or (snap.source=="chrome" and windows.process_name(hwnd)!="chrome.exe") or (snap.source=="desktop" and not self.binding.matches(snap.session)):
            self.engine.status="请确认已绑定的视频窗口正在提供画面";self.refresh();return
        try:self.engine.manual_block(kind)
        except ValueError as error:self.engine.status=str(error)
        self.refresh()

    def on_manual(self,request,snap,note):
        self.manual_busy=False
        target,kind,epoch=request
        if self.engine.paused or epoch!=self.engine.epoch or target!=self.binding.target:return
        if not snap:self.show_notice(note);return
        if not self.binding.matches(snap.session):return
        self.engine.update(snap)
        try:
            self.engine.manual_block(kind)
            self.dispatch(self.engine.update(snap))
        except ValueError as error:self.show_notice(str(error))
        self.refresh()

    def undo(self):self.engine.undo();self.refresh()

    def fold(self):
        # Resize while hidden so Windows updates the translucent window's bounds.
        visible=self.isVisible();self.hide();self.drag_start=None
        self.folded=not self.folded;self.details.setVisible(not self.folded)
        self.fold_button.setText("+" if self.folded else "−")
        label="显示解析文字" if self.folded else "隐藏解析文字"
        self.fold_button.setToolTip(label);self.fold_button.setAccessibleName(label)
        self.layout().activate()
        self.setFixedHeight(self.collapsed_height if self.folded else self.expanded_height)
        if visible:self.show()

    def restore(self):
        self.passthrough=False;self.setWindowFlag(Qt.WindowType.WindowTransparentForInput,False);self.show();self.register_hotkeys()
        if self.folded:self.fold()

    def enable_passthrough(self):
        # Do not strand the user if the restore hotkey could not be registered.
        if "show" not in getattr(self,"registered",set()):
            self.engine.status="恢复快捷键不可用，请先在设置中更换快捷键";self.refresh();return
        self.engine.status="鼠标穿透中；使用 "+self.store.get("hotkeys")["show"]+" 或托盘恢复"
        self.refresh();self.passthrough=True;self.setWindowFlag(Qt.WindowType.WindowTransparentForInput,True);self.show();self.register_hotkeys()

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:self.drag_start=event.globalPosition().toPoint()-self.pos()

    def mouseMoveEvent(self,event):
        if self.drag_start is not None and event.buttons() & Qt.MouseButton.LeftButton:self.move(event.globalPosition().toPoint()-self.drag_start)

    def mouseReleaseEvent(self,event):
        if self.drag_start is not None:self.store.set("position",[self.x(),self.y()]);self.drag_start=None

    def dialog(self,kind):
        self.dialog_open=True;self.engine.reset(preserve_watch=True)
        self.desktop_executor.submit(self.reader.close)
        try:kind(self).exec()
        finally:self.dialog_open=False;self.engine.reset(preserve_watch=True);self.refresh()

    def open_settings(self):self.dialog(Settings)
    def open_rules(self):self.dialog(Rules)
    def open_statistics(self):self.dialog(Statistics)

    def new_rule(self):
        self.dialog_open=True;self.engine.reset(preserve_watch=True)
        try:
            RuleEditor(self).exec()
        finally:self.dialog_open=False;self.engine.reset(preserve_watch=True)

    def accepts_source(self, source):
        if self.config["source"] != "auto":
            return self.config["source"] == source
        # An established desktop binding survives focus changes, including Chrome.
        if source=="desktop":return self.binding.target is not None
        return self.binding.target is None and windows.process_name(windows.foreground())=="chrome.exe"

    def pick_window(self):
        if self.picking_at:
            self.picking_at=0;self.engine.status="已取消点选，保留原窗口绑定"
        else:
            self.picking_at=time.monotonic();self.engine.pause(True)
            self.desktop_executor.submit(self.reader.close)
            self.engine.status="请点击要观看的抖音窗口，完成后点击开始"
        self.refresh()

    def rediscover_window(self):
        self.picking_at=0;self.binding.target=None;self.binding.title="";self.discovered_at=0
        self.engine.reset();self.desktop_executor.submit(self.reader.close)
        self.refresh()

    def poll_binding(self):
        now=time.monotonic()
        if self.picking_at:
            clicked_at,hwnd=self.ui_input.last_click
            if clicked_at>self.picking_at:
                self.picking_at=now
                try:
                    self.binding.bind(hwnd)
                    self.picking_at=0;self.config["source"]="desktop";self.store.set("source","desktop")
                    self.engine.reset()
                    self.engine.status="窗口已绑定；点击开始，切到其他软件也会继续识别"
                except ValueError:self.engine.status="这不是抖音窗口，请重新点击；可按取消绑定结束"
            return
        if now-self.discovered_at>=1 and self.config["source"]!="chrome":
            before=self.binding.target
            self.binding.discover();self.discovered_at=now
            if before!=self.binding.target:
                self.engine.reset();self.desktop_executor.submit(self.reader.close)

    def on_message(self,data,reply):
        if not self.accepts_source("chrome"):return
        if data.get("type")!="snapshot":return
        try:
            snap=Snapshot.parse(data)
            sequence=data.get("sequence",0)
            if type(sequence) is not int or sequence<=self.last_sequence.get(snap.session,-1):return
            self.last_sequence[snap.session]=sequence
            if len(self.last_sequence)>100:self.last_sequence={snap.session:sequence}
        except (ValueError,TypeError):return
        if self.dialog_open:return
        if snap.source!="chrome":return
        active=snap.active and windows.process_name(windows.foreground())=="chrome.exe"
        snap=replace(snap,active=active,purchase=snap.purchase or purchase_evidence(snap.title))
        self.reply_context=(data,reply)
        action=self.engine.update(snap)
        response={"request":data.get("request"),"sequence":sequence,"status":self.engine.status}
        if action:response.update(action)
        reply(response)
        self.refresh()

    def dispatch(self,action):
        if not action:return
        snap=self.engine.current
        if not snap:return
        if snap.source=="chrome" and self.reply_context:
            data,reply=self.reply_context
            if data.get("token")==snap.token and data.get("session")==snap.session and windows.process_name(windows.foreground())=="chrome.exe":
                reply({**action,"request":data.get("request"),"sequence":data.get("sequence"),"status":self.engine.status})
        elif snap.source=="desktop":
            if not self.binding.matches(snap.session) or not windows.next_video(self.binding.target):
                self.engine.pause(True);self.engine.status="绑定窗口不可用，未发送下一条操作"
            else:
                at=time.monotonic();self.desktop_next_at=at+.35
                self.desktop_switch_at=at
                self.engine.views.switch(snap.source,snap.session,at)
                self.quick_skip.automatic_transition(at)

    def on_navigation(self,target,at):
        if not target or target!=self.binding.target or self.engine.paused or self.dialog_open or not self.accepts_source("desktop"):
            return
        if not self.engine.listen_enabled and not self.engine.auto_enabled:return
        self.auto_input_at=max(self.auto_input_at,at)
        if self.engine.views.switch("desktop",windows.target_session(target),at,manual=True):
            self.engine.reset(preserve_watch=True)
            self.desktop_switch_at=at
            self.desktop_next_at=max(self.desktop_next_at,at+.35)

    def tick(self):
        self.poll_binding()
        if self.engine.paused or self.dialog_open:self.refresh();return
        if not self.engine.listen_enabled and not self.engine.auto_enabled:
            self.engine.status="监听和自动均已关闭";self.refresh();return
        if self.accepts_source("desktop") and self.ui_input.last_next>self.auto_input_at:
            self.on_navigation(self.binding.target,self.ui_input.last_next)
        if self.engine.current and not self.engine.pending and not self.desktop_busy and not self.manual_busy and time.monotonic()-self.engine.last_at>2.5:
            self.engine.reset();self.engine.status="视频连接中断，等待重新识别"
        if self.accepts_source("desktop"):self.dispatch(self.engine.timed_action())
        if self.accepts_source("desktop") and not self.desktop_busy and not self.manual_busy and time.monotonic()>=self.desktop_next_at:
            self.desktop_busy=True;context=(self.engine.epoch,self.ui_input.last_next);config={**self.config,"desktop_target":self.binding.target,
                "mode":"auto" if self.engine.auto_enabled else "listen","threshold":float(self.store.get("threshold")),
                "statistics":True,
                "video_switch_at":max(self.desktop_switch_at,self.ui_input.last_next),
                "pending_token":self.engine.pending[0][2] if self.engine.pending else "",
                "blocked_authors":[r["author"] for r in self.store.rules(enabled=True) if r["author"]]}
            def run():
                try:snap,image,note=self.reader.read(config)
                except ValueError as error:snap,image,note=None,None,str(error)
                except Exception as error:snap,image,note=None,None,"客户端识别失败："+type(error).__name__
                self.bus.desktop.emit(context,snap,image,note)
            self.desktop_executor.submit(run)
        self.refresh()

    def on_desktop(self,context,snap,image,note):
        epoch,input_at=context
        self.desktop_busy=False
        interval=1 if snap and snap.author and not self.engine.pending else .35
        self.desktop_next_at=time.monotonic()+interval
        if self.engine.paused or self.dialog_open or not self.accepts_source("desktop") or epoch!=self.engine.epoch:return
        if self.ui_input.last_next>input_at:return
        if snap is None:
            self.engine.reset(preserve_watch=True)
            self.engine.status=note;self.refresh();return
        if not self.binding.matches(snap.session):self.engine.reset();return
        action=self.engine.update(snap)
        if not action and not self.engine.pending and not self.engine.paused and not snap.author:self.engine.status=note
        self.dispatch(action);self.refresh()

    def quit(self):
        self.engine.pause(True)
        self.sync_learning()
        for i in range(1,getattr(self,"hotkey_count",0)+1):windows.unregister_hotkey(int(self.winId()),i)
        self.tray.hide()
        self.desktop_executor.submit(self.reader.close);self.desktop_executor.shutdown(wait=False)
        self.learning_executor.shutdown(wait=False,cancel_futures=True)
        if self.listener:self.listener.close()
        QApplication.quit()

    def closeEvent(self,event):
        if self.preview:event.accept()
        else:self.hide();event.ignore()


def main():
    try:windows.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError,OSError):pass
    app=QApplication(sys.argv);app.setQuitOnLastWindowClosed(False)
    # The offscreen Windows Qt plugin does not discover system fonts itself.
    if app.platformName()=="offscreen":
        import os
        font=Path(os.environ.get("WINDIR",r"C:\Windows"))/"Fonts"/"msyh.ttc"
        if font.exists():QFontDatabase.addApplicationFont(str(font))
    preview="--preview" in sys.argv
    lock=QLockFile(str(windows.data_dir()/"running.lock"))
    if not preview and not lock.tryLock(0):
        QMessageBox.information(None,"Auto Skip","程序已经运行，请使用托盘图标显示浮窗。")
        return 0
    overlay=Overlay(preview);overlay.show()
    if preview:
        output=Path(sys.argv[sys.argv.index("--preview")+1]);output.parent.mkdir(parents=True,exist_ok=True)
        def render():
            overlay.grab().save(str(output))
            if "--check-ocr" in sys.argv:
                try:
                    import os
                    from PIL import Image,ImageDraw,ImageFont
                    from .fast_ocr import FastOCR
                    sample=Image.new("RGB",(700,150),"white")
                    face=ImageFont.truetype(str(Path(os.environ["WINDIR"])/"Fonts"/"msyh.ttc"),28)
                    ImageDraw.Draw(sample).text((20,20),"@测试作者\n数码客观评测",font=face,fill="black")
                    reader=FastOCR();text=reader.read(sample)
                    report={"ok":"测试作者" in text and "数码客观评测" in text,"backend":reader.backend,"ms":reader.last_ms}
                except Exception as problem:report={"ok":False,"error":type(problem).__name__+": "+str(problem)}
                output.with_suffix(".ocr.json").write_text(json.dumps(report,ensure_ascii=False),encoding="utf-8")
            overlay.desktop_executor.shutdown(wait=False);overlay.learning_executor.shutdown(wait=False);app.quit()
        QTimer.singleShot(300,render)
    return app.exec()
