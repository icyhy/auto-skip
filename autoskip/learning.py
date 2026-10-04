"""Input timing -> immutable pre-switch frame -> asynchronous video blacklist."""
import threading
import math
from dataclasses import dataclass

from .core import caption_key
from .desktop import caption_fields
from .players import analysis_bounds


@dataclass(frozen=True)
class SkipEvent:
    target: tuple
    at: float
    elapsed: float
    kind: str
    frame: tuple
    threshold: float = 5.0


def qualifies(event, threshold=None):
    if not math.isfinite(event.threshold) or (threshold is not None and not math.isfinite(threshold)):return False
    limit=min(event.threshold,threshold) if threshold is not None else event.threshold
    return math.isfinite(event.elapsed) and math.isfinite(limit) and 0<event.elapsed<limit


class QuickSkip:
    def __init__(self,freeze,emit):
        self.freeze,self.emit=freeze,emit
        self.lock=threading.Lock()
        self.slots=threading.BoundedSemaphore(8)
        self.target=None
        self.enabled=False
        self.threshold=5.0
        self.previous=None
        self.last_wheel=None
        self.last_input=None

    def configure(self,target,enabled,threshold):
        target=tuple(target) if target else None
        with self.lock:
            if self.target!=target or self.enabled!=enabled:
                self.previous=self.last_wheel=self.last_input=None
            self.target,self.enabled,self.threshold=target,enabled,threshold

    def drag_frame(self,at):
        with self.lock:
            # Long views do not retain an extra drag screenshot either.
            target=self.target if self.enabled and self.previous is not None and 0<round(at-self.previous,3)<self.threshold else None
        return self.freeze(target[0],at) if target else None

    def automatic_transition(self,at):
        """A tool-driven switch starts the next view's clock but never learns a rule."""
        with self.lock:
            if not self.enabled:return
            self.previous=at
            self.last_input=at
            self.last_wheel=None

    def navigation(self,kind,at,seed=None):
        with self.lock:
            if not self.enabled or not self.target:return
            if self.last_input is not None and at<=self.last_input:return
            self.last_input=at
            if kind=="wheel":
                last,self.last_wheel=self.last_wheel,at
                if last is not None and at-last<0.7:return
            # Different devices can report the same transition. Keep the original
            # switch time; duplicates must not restart the video's clock.
            if self.previous is not None and at-self.previous<0.7:return
            previous,self.previous=self.previous,at
            target=self.target
            elapsed=round(at-previous,3) if previous is not None else None
            if elapsed is None or not 0<elapsed<self.threshold:return
            frame=seed if kind=="drag" else self.freeze(target[0],at)
            event=None
            if frame is None:
                message="未取得划走前的新画面，本次未加入黑名单"
            elif not self.slots.acquire(blocking=False):
                message="截图解析队列已满，本次未加入黑名单"
            else:
                event=SkipEvent(target,at,elapsed,kind,frame,self.threshold)
                message="已保存划走前画面，正在后台识别…"
        self.emit(event,message)

    def qualifies(self,event):
        with self.lock:return qualifies(event,self.threshold)


class ScreenshotAnalyzer:
    def __init__(self):self.ocr=None

    def analyze(self,event,config=None):
        if not qualifies(event):raise ValueError("观看间隔已达到阈值，不解析、不加入黑名单")
        image=event.frame[0]
        left,top,right,bottom=analysis_bounds((image.shape[1],image.shape[0]),config or {})
        image=image[top:bottom,left:right]
        if self.ocr is None:
            from rapidocr_onnxruntime import RapidOCR
            self.ocr=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=1)
        result,_=self.ocr(image)
        text="\n".join(row[1] for row in result or [] if row[2]>=0.8)
        author,title=caption_fields(text)
        key=caption_key(author,title)
        if not key:raise ValueError("未能从划走前画面识别作者和标题，本次未加入黑名单")
        return {"target":key,"author":author,"title":title}
