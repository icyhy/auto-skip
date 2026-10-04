import hashlib
import io
import re
import time
from dataclasses import replace

from .core import Snapshot, purchase_evidence, caption_key, evidence_text, author_name, extract_links
from .capture import WindowCapture
from .players import analysis_bounds
from . import windows


def parse_times(text):
    match = re.search(r"(?<!\d)(\d{1,2})\s*[:：]\s*(\d{2})\s*/\s*(\d{1,2})\s*[:：]\s*(\d{2})(?!\d)", text)
    if not match:return None
    a,b,c,d = map(int, match.groups())
    if b >= 60 or d >= 60:return None
    current,total = a*60+b,c*60+d
    return (current,total) if total>0 and current<=total else None


def read_controls(hwnd):
    import pythoncom
    pythoncom.CoInitialize()
    try:
        from pywinauto import Desktop
        controls=[]
        for element in Desktop(backend="uia").window(handle=hwnd).descendants()[:600]:
            try:
                info=element.element_info
                if not info.visible:continue
                control={"name":info.name or "", "kind":info.control_type,
                         "editing":info.control_type=="Edit" and element.has_keyboard_focus(), "link":"",
                         "rect":(info.rectangle.left,info.rectangle.top,info.rectangle.right,info.rectangle.bottom)}
                if info.control_type=="Hyperlink":
                    try:control["link"]=element.iface_value.CurrentValue
                    except Exception:control["link"]=control["name"]
                controls.append(control)
            except Exception:continue
        return controls
    finally:pythoncom.CoUninitialize()


def caption_fields(text):
    """Extract stable caption hints from whole-window text, without locating a player."""
    lines=[line.strip().lstrip("·•.。'\"“”‘’ ") for line in text.splitlines() if line.strip()]
    index=next((i for i,line in enumerate(lines) if line.startswith(("@","＠"))),None)
    if index is None:return "",""
    name=author_name(lines[index])
    author="@"+name[:199] if name else ""
    caption=[]
    for line in lines[index+1:index+5]:
        if parse_times(line) or line.startswith(("合集","作者声明","发一条","发送","搜索","评论")):break
        if len(line)>=5 and not re.fullmatch(r"[\d.万亿]+",line):caption.append(line)
    return author," ".join(caption)[:500]


class DesktopReader:
    def __init__(self,user_input):
        self.input=user_input
        self.capture=WindowCapture()
        self.ocr=None
        self.fast_ocr=None
        self.reset()

    def reset(self):
        self.input.hwnd,self.input.region=0,None
        # Keep the hook's monotonic navigation stamp; worker resets must not erase input.
        self.previous=self.times=self.window_context=None
        self.last_time=self.last_advance=0.0
        self.cached=None
        self.frame_size=None
        self.analysis_context=None
        self.switch_at=0.0
        self.departing_token=""

    def close(self):
        self.capture.close()
        self.reset()

    def read(self,config):
        target=config.get("desktop_target")
        if not windows.valid_target(target):
            self.close()
            return None,None,"等待绑定抖音窗口"
        hwnd=target[0]
        if windows.user32.IsIconic(hwnd) or not windows.user32.IsWindowVisible(hwnd):
            self.close()
            return None,None,"已绑定抖音窗口；窗口最小化或隐藏，等待恢复"
        if self.window_context!=tuple(target):
            self.close();self.window_context=tuple(target)
        # Start the frame stream before slow UI Automation / OCR so input hooks
        # can freeze a departing video while this worker is still analyzing.
        try:image,captured_at=self.capture.snapshot(hwnd)
        except ValueError:
            self.cached=None
            raise
        if self.frame_size!=image.size:
            self.cached=None;self.frame_size=image.size
        self.input.hwnd,self.input.region=hwnd,windows.client_rect(hwnd)
        statistics=config.get("statistics",False)
        if config.get("mode")=="listen" and not statistics:
            # Keep only the frame stream warm. No UIA, OCR or inference during viewing.
            self.cached=None
            return None,None,f"监听中 · 仅切换间隔小于 {config.get('threshold',5):g} 秒时解析"
        reparse=config.get("mode")=="reparse"
        automatic=config.get("mode")=="auto" or statistics or reparse
        switch_at=max(self.input.last_next,config.get("video_switch_at",0.0))
        if switch_at!=self.switch_at:
            self.departing_token=self.previous.token if self.previous else ""
            self.switch_at=switch_at;self.cached=None
        if not automatic:self.cached=None
        controls=[]
        if not automatic:
            try:controls=read_controls(hwnd)
            except Exception:controls=[]
            if windows.foreground()==hwnd and any(item["editing"] for item in controls):
                self.reset()
                return None,None,"正在编辑文字，已暂停客户端操作"
            image,captured_at=self.capture.snapshot(hwnd)
        if not windows.valid_target(target):
            self.close();return None,None,"绑定窗口已关闭，正在重新查找"
        self.input.hwnd,self.input.region=hwnd,windows.client_rect(hwnd)
        bounds=analysis_bounds(image.size,config)
        if self.analysis_context!=bounds:
            self.cached=None;self.analysis_context=bounds
        if automatic and self.cached and not reparse:
            # Keep checking window/frame health, but never OCR a known video again.
            # The cached time is not a fresh playback/end observation.
            snap,jpeg,note=self.cached
            return replace(snap,playing=False,timing=False,ended=False,user_from=""),jpeg,note
        if bounds!=(0,0,*image.size):
            window=windows.rect(hwnd)
            if window:
                sx=image.width/(window[2]-window[0]);sy=image.height/(window[3]-window[1])
                controls=[item for item in controls if item.get("rect") and
                    bounds[0]<=(item["rect"][0]-window[0])*sx<(item["rect"][2]-window[0])*sx<=bounds[2] and
                    bounds[1]<=(item["rect"][1]-window[1])*sy<(item["rect"][3]-window[1])*sy<=bounds[3]]
            else:controls=[]
            image=image.crop(bounds)
        texts=[item["name"] for item in controls if item["name"]]
        links=[item["link"] for item in controls if item["link"]]
        if automatic and not reparse:
            if self.fast_ocr is None:
                from .fast_ocr import FastOCR
                self.fast_ocr=FastOCR()
            ocr_text=self.fast_ocr.read(image)
        else:
            if self.ocr is None:
                from rapidocr_onnxruntime import RapidOCR
                self.ocr=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=1)
            import numpy as np
            result,_=self.ocr(np.asarray(image))
            ocr_text="\n".join(item[1] for item in result or [] if item[2]>=0.8)
        text="\n".join(dict.fromkeys(texts))+"\n"+ocr_text
        if not windows.valid_target(target) or windows.user32.IsIconic(hwnd):
            self.close();return None,None,"绑定窗口已关闭或最小化"
        urls="\n".join(links+texts+[ocr_text])
        video_ids=set(re.findall(r"(?:www\.)?douyin\.com/video/(\d+)",urls))
        video_id="dy:video:"+next(iter(video_ids)) if len(video_ids)==1 else ""
        author,title=caption_fields(ocr_text)
        if not author:author,title=caption_fields(text)
        if automatic and author and not reparse:
            author=self.fast_ocr.verify_author(image,author,config.get("blocked_authors",[]))
        # A whole-window profile link can belong to navigation or a recommendation.
        # Associate IDs only with a link explicitly named after the recognized author.
        author_links="\n".join(item["link"] for item in controls if item.get("kind")=="Hyperlink"
            and author and author_name(item["name"])==author_name(author))
        author_ids=set(re.findall(r"(?:www\.)?douyin\.com/user/([A-Za-z0-9_-]+)",author_links)) - {"self","me"}
        author_id="dy:author:"+next(iter(author_ids)) if len(author_ids)==1 else ""
        # OCR caption is a transient continuity hint, never a fabricated account ID.
        token=video_id or caption_key(author,title) or f"frame:{captured_at}"
        if automatic and not video_id and not caption_key(author,title) and evidence_text(text):
            token="text:"+hashlib.sha256(evidence_text(text).encode()).hexdigest()
        now=time.monotonic()
        times=parse_times(text)
        same=self.previous is not None and self.previous.token==token
        if same and times and self.times and times[1]==self.times[1] and times[0]>self.times[0]:
            self.last_advance=now
        playing=bool(same and times and now-self.last_advance<1.5)
        ended=bool(same and times and self.times and times[0]==times[1] and self.times[0]<times[0])
        user_from=self.previous.token if self.previous and not same and now-self.input.last_next<1.8 else ""
        snap=Snapshot("desktop",windows.target_session(target),token,video_id,author_id,title,author,text[:8000],
                      True,playing,bool(times),ended,user_from,purchase_evidence(ocr_text),"\n".join(extract_links(urls)))
        if reparse:snap=replace(snap,playing=False,timing=False,ended=False,user_from="")
        self.previous,self.times,self.last_time=snap,times,now
        waiting=automatic and token==self.departing_token and (
            config.get("pending_token")==token or now-switch_at<1.2)
        if waiting and config.get("pending_token")!=token:
            return None,None,"视频切换中，等待新作者"
        image.thumbnail((1280,1280))
        stream=io.BytesIO();image.convert("RGB").save(stream,"JPEG",quality=80)
        note="已绑定抖音窗口 · 整窗识别"
        if bounds!=(0,0,*self.frame_size):note="已绑定抖音窗口 · 已排除边缘区域"
        if automatic and not reparse:note=f"自动识别 · {self.fast_ocr.backend} {self.fast_ocr.last_ms:.0f} ms"
        if not author_id:note+=" · 按完整作者名匹配"
        if automatic and author and not waiting:
            note="已识别作者 · 等待视频切换"
            self.cached=(snap,stream.getvalue(),note)
        return snap,stream.getvalue(),note
