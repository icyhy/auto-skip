"""Capture a bound HWND through Windows Graphics Capture, even when occluded."""
import threading
import time
from PIL import Image


def capture_region(target, config):
    from . import windows
    from .players import analysis_bounds
    process=config["player_profiles"][0].get("process","douyin.exe")
    capture=WindowCapture()
    try:
        if not windows.valid_target(target,process):raise ValueError("播放器窗口已关闭，请重新验证")
        area=windows.rect(target[0])
        image,_=capture.snapshot(target[0])
        if not windows.valid_target(target,process) or windows.rect(target[0])!=area:
            raise ValueError("播放器窗口位置或大小已变化，请重新按住验证")
        if not area or windows.user32.IsIconic(target[0]) or not windows.user32.IsWindowVisible(target[0]):
            raise ValueError("播放器窗口不可见，请恢复窗口后验证")
        bounds=analysis_bounds(image.size,config)
        # Map original capture pixels to physical screen pixels, including HiDPI.
        screen=tuple(round(area[i%2]+bounds[i]*(area[i%2+2]-area[i%2])/image.size[i%2]) for i in range(4))
        return image.crop(bounds),screen
    finally:capture.close()


class WindowCapture:
    def __init__(self):
        self.hwnd=0
        self.control=None
        self.capture=None
        self.frame=None
        self.lock=threading.Lock()
        self.ready=threading.Event()
        self.generation=0

    def close(self):
        self.generation+=1
        control,self.control=self.control,None
        if control and not control.is_finished():control.stop()
        self.capture=None;self.hwnd=0
        with self.lock:self.frame=None
        self.ready.clear()

    def freeze(self, hwnd, at):
        """O(1) pre-input snapshot; never wait for a future (possibly next-video) frame."""
        if self.hwnd!=hwnd:return None
        with self.lock:frame=self.frame
        if not frame or not 0<=at-frame[1]<=0.6:return None
        return frame  # Frame arrays are immutable and owned, safe after capture advances.

    def snapshot(self, hwnd):
        if self.hwnd!=hwnd or not self.control or self.control.is_finished():
            self.close()
            from windows_capture import WindowsCapture
            generation=self.generation
            capture=WindowsCapture(window_hwnd=hwnd,cursor_capture=False)
            @capture.event
            def on_frame_arrived(frame,control):
                if generation!=self.generation:
                    control.stop();return
                now=time.monotonic()
                with self.lock:
                    if self.frame and now-self.frame[1]<0.1:return
                pixels=frame.frame_buffer[:,:,:3][:,:,::-1].copy()
                pixels.flags.writeable=False
                with self.lock:self.frame=(pixels,now)
                self.ready.set()
            @capture.event
            def on_closed():
                if generation==self.generation:
                    with self.lock:self.frame=None
                    self.ready.set()
            self.capture=capture;self.hwnd=hwnd
            self.control=capture.start_free_threaded()
        self.ready.wait(2)
        with self.lock:frame=self.frame
        if not frame or time.monotonic()-frame[1]>2:
            raise ValueError("绑定窗口暂无新画面，请确认窗口未最小化且视频正在显示")
        return Image.fromarray(frame[0]),frame[1]
