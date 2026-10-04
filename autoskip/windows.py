"""Windows boundary: identity, credentials, hotkeys and guarded input."""
import ctypes as c
from ctypes import wintypes as w
import os
import time
from pathlib import Path

user32 = c.WinDLL("user32", use_last_error=True)
kernel32 = c.WinDLL("kernel32", use_last_error=True)
user32.GetForegroundWindow.restype = w.HWND
user32.GetAncestor.argtypes = [w.HWND, w.UINT]
user32.GetAncestor.restype = w.HWND
user32.GetWindowThreadProcessId.argtypes = [w.HWND, c.POINTER(w.DWORD)]
kernel32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
kernel32.OpenProcess.restype = w.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, c.POINTER(w.DWORD)]
kernel32.CloseHandle.argtypes = [w.HANDLE]
user32.GetWindowRect.argtypes = [w.HWND, c.POINTER(w.RECT)]
user32.GetClientRect.argtypes = [w.HWND, c.POINTER(w.RECT)]
user32.ClientToScreen.argtypes = [w.HWND, c.POINTER(w.POINT)]
user32.IsIconic.argtypes = [w.HWND]
user32.IsWindowVisible.argtypes = [w.HWND]
user32.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, c.c_int]
user32.GetWindowTextLengthW.argtypes = [w.HWND]
user32.IsWindow.argtypes = [w.HWND]
user32.WindowFromPoint.argtypes = [w.POINT]
user32.WindowFromPoint.restype = w.HWND
user32.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
user32.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, c.c_int]
user32.EnumChildWindows.argtypes = [w.HWND,c.c_void_p,w.LPARAM]
user32.EnumWindows.argtypes = [c.c_void_p,w.LPARAM]
user32.MapVirtualKeyW.argtypes = [w.UINT,w.UINT]
user32.SetWindowPos.argtypes = [w.HWND,w.HWND,c.c_int,c.c_int,c.c_int,c.c_int,w.UINT]
kernel32.GetTickCount64.restype = c.c_ulonglong
_input_clock_offset = None


def input_time(milliseconds):
    """Use the OS event time, not when a busy Python thread processes its callback."""
    global _input_clock_offset
    ticks=kernel32.GetTickCount64()
    if _input_clock_offset is None:_input_clock_offset=time.monotonic()-ticks/1000
    age=(ticks-milliseconds)&0xffffffff
    return _input_clock_offset+(ticks-age)/1000


def process_name(hwnd):
    pid = w.DWORD()
    user32.GetWindowThreadProcessId(hwnd, c.byref(pid))
    handle = kernel32.OpenProcess(0x1000, False, pid.value)
    if not handle:
        return ""
    try:
        buf, size = c.create_unicode_buffer(32768), w.DWORD(32768)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, c.byref(size)):
            return Path(buf.value).name.lower()
        return ""
    finally:
        kernel32.CloseHandle(handle)


def foreground():
    return int(user32.GetForegroundWindow() or 0)


def window_at(x, y):
    hwnd = user32.WindowFromPoint(w.POINT(x,y))
    return int(user32.GetAncestor(hwnd,2) or 0) if hwnd else 0


def window_identity(hwnd, process="douyin.exe"):
    """Check HWND ownership as well as process lifetime; never persist raw HWNDs."""
    if not hwnd or not user32.IsWindow(hwnd) or process_name(hwnd) != process.lower():
        return None
    pid = w.DWORD()
    user32.GetWindowThreadProcessId(hwnd,c.byref(pid))
    handle = kernel32.OpenProcess(0x1000,False,pid.value)
    if not handle:return None
    try:
        created,exited,kernel,user = w.FILETIME(),w.FILETIME(),w.FILETIME(),w.FILETIME()
        kernel32.GetProcessTimes.argtypes=[w.HANDLE]+[c.POINTER(w.FILETIME)]*4
        if not kernel32.GetProcessTimes(handle,c.byref(created),c.byref(exited),c.byref(kernel),c.byref(user)):
            return None
        return (int(hwnd),pid.value,(created.dwHighDateTime<<32)|created.dwLowDateTime)
    finally:kernel32.CloseHandle(handle)


def valid_target(target, process="douyin.exe"):
    return bool(target and window_identity(target[0],process) == tuple(target))


def target_session(target):
    return ":".join(map(str,target))


class WindowBinding:
    def __init__(self):
        self.target = None
        self.title = ""

    def bind(self, hwnd):
        identity = window_identity(hwnd)
        if not identity:raise ValueError("请点击抖音客户端窗口")
        self.target = identity
        buf=c.create_unicode_buffer(user32.GetWindowTextLengthW(hwnd)+1)
        user32.GetWindowTextW(hwnd,buf,len(buf))
        self.title=buf.value or "抖音"

    def discover(self):
        if valid_target(self.target):return self.target
        self.target=None;self.title=""
        choices=windows()
        if len(choices)==1:
            try:self.bind(choices[0][0])
            except ValueError:pass
        return self.target

    def matches(self, session):
        return bool(self.target and target_session(self.target)==session and valid_target(self.target))


def rect(hwnd):
    value = w.RECT()
    if not user32.GetWindowRect(hwnd, c.byref(value)):
        return None
    return value.left, value.top, value.right, value.bottom


def client_rect(hwnd):
    """Current content bounds in physical screen coordinates, excluding the frame."""
    value = w.RECT()
    if not user32.GetClientRect(hwnd, c.byref(value)):
        return None
    start, end = w.POINT(value.left, value.top), w.POINT(value.right, value.bottom)
    if not user32.ClientToScreen(hwnd, c.byref(start)) or not user32.ClientToScreen(hwnd, c.byref(end)):
        return None
    if end.x <= start.x or end.y <= start.y:
        return None
    return start.x, start.y, end.x, end.y


def windows(process="douyin.exe"):
    result = []
    callback_type = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    def visit(hwnd, _):
        if user32.IsWindowVisible(hwnd) and process_name(hwnd) == process.lower():
            buf = c.create_unicode_buffer(user32.GetWindowTextLengthW(hwnd) + 1)
            user32.GetWindowTextW(hwnd, buf, len(buf))
            area = rect(hwnd)
            if area and area[2] - area[0] > 300 and area[3] - area[1] > 200:
                result.append((int(hwnd), buf.value or "抖音"))
        return True
    user32.EnumWindows(callback_type(visit), 0)
    return result


def find_player_window(process, preferred=None):
    if valid_target(preferred,process):
        target=tuple(preferred)
    else:
        choices=[hwnd for hwnd,_ in windows(process) if not user32.IsIconic(hwnd)]
        if not choices:raise ValueError(f"未找到 {process} 的可见窗口，请先打开播放器并恢复窗口")
        if len(choices)>1:raise ValueError("找到多个播放器窗口，请先绑定要验证的窗口，或关闭多余窗口")
        target=window_identity(choices[0],process)
    if not target or user32.IsIconic(target[0]) or not user32.IsWindowVisible(target[0]):
        raise ValueError("播放器窗口已关闭、隐藏或最小化，请恢复窗口后验证")
    return target


class Blob(c.Structure):
    _fields_ = [("length", w.DWORD), ("data", c.POINTER(c.c_ubyte))]


def protect(data, decrypt=False):
    crypt32 = c.WinDLL("crypt32", use_last_error=True)
    raw = (c.c_ubyte * len(data)).from_buffer_copy(data)
    source, output = Blob(len(data), raw), Blob()
    if decrypt:
        ok = crypt32.CryptUnprotectData(c.byref(source), None, None, None, None, 1, c.byref(output))
    else:
        ok = crypt32.CryptProtectData(c.byref(source), "Auto Skip", None, None, None, 1, c.byref(output))
    if not ok:
        raise c.WinError(c.get_last_error())
    try:
        return c.string_at(output.data, output.length)
    finally:
        kernel32.LocalFree.argtypes = [w.HLOCAL]
        kernel32.LocalFree(output.data)


def data_dir():
    path = Path(os.environ.get("AUTOSKIP_DATA_DIR", str(Path(os.environ["LOCALAPPDATA"]) / "AutoSkip")))
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_secret(name):
    path = data_dir() / (name + ".protected")
    return protect(path.read_bytes(), True) if path.exists() else b""


def save_secret(name, value):
    path = data_dir() / (name + ".protected")
    temp = path.with_suffix(".tmp")
    temp.write_bytes(protect(value))
    temp.replace(path)


def hotkey_parts(text):
    pieces = text.upper().split("+")
    key, modifiers = pieces[-1], 0x4000
    for name in pieces[:-1]:
        if name not in {"CTRL", "ALT", "SHIFT"}:
            raise ValueError("快捷键只支持 Ctrl、Alt、Shift 加字母或功能键")
        modifiers |= {"CTRL": 2, "ALT": 1, "SHIFT": 4}[name]
    if not modifiers & 7:
        raise ValueError("快捷键需包含 Ctrl、Alt 或 Shift")
    if len(key) == 1 and key.isascii() and key.isalnum():
        return modifiers, ord(key)
    if key.startswith("F") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        return modifiers, 0x70 + int(key[1:]) - 1
    raise ValueError("不支持的快捷键")


def register_hotkey(hwnd, identity, value):
    modifiers, key = hotkey_parts(value)
    user32.RegisterHotKey.argtypes = [w.HWND, c.c_int, w.UINT, w.UINT]
    return bool(user32.RegisterHotKey(hwnd, identity, modifiers, key))


def unregister_hotkey(hwnd, identity):
    user32.UnregisterHotKey.argtypes = [w.HWND, c.c_int]
    user32.UnregisterHotKey(hwnd, identity)


def message_target(hwnd):
    # Chromium receives key messages in its renderer child, when exposed.
    children=[]
    callback_type=c.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
    def visit(child,_):
        name=c.create_unicode_buffer(256)
        user32.GetClassNameW(child,name,len(name))
        if name.value=="Chrome_RenderWidgetHostHWND" and user32.IsWindowVisible(child):
            children.append(int(child))
        return True
    user32.EnumChildWindows(hwnd,callback_type(visit),0)
    return children[0] if len(children)==1 else hwnd


def next_video(target):
    if not valid_target(target) or user32.IsIconic(target[0]):return False
    hwnd=message_target(target[0])
    if not valid_target(target):return False
    bounds=client_rect(target[0])
    if not bounds:return False
    x=(bounds[0]+bounds[2])//2;y=(bounds[1]+bounds[3])//2
    # WM_MOUSEWHEEL uses screen coordinates and a signed wheel delta in HIWORD.
    # Post to the bound renderer; never move the cursor or scroll the foreground app.
    return bool(user32.PostMessageW(hwnd,0x20A,(-120&0xffff)<<16,(x&0xffff)|((y&0xffff)<<16)))


class UserInput:
    """Only record navigation intent in the selected video rectangle; never log keys."""
    def __init__(self):
        self.hwnd = 0
        self.region = None
        self.last_next = 0.0
        self.hooks = []
        self.callbacks = []
        self.last_click = (0.0,0)
        self.on_navigation=lambda kind,at,frame:None
        self.on_drag_start=lambda at:None
        self.down_pressed=False
        self.drag=None

    def key_event(self,down,hwnd,at,injected=False):
        if injected:return
        if not down:self.down_pressed=False;return
        if self.down_pressed:return
        self.down_pressed=True
        if self.hwnd and hwnd==self.hwnd:
            self.last_next=at;self.on_navigation("key",at,None)

    def mouse_event(self,kind,hwnd,x,y,at,delta=0,injected=False):
        if injected:return
        if kind=="down":
            self.last_click=(at,hwnd)
            self.drag=(hwnd,x,y,self.on_drag_start(at)) if self.hwnd and hwnd==self.hwnd else None
        elif kind=="up":self.drag=None
        elif kind=="wheel" and self.hwnd and hwnd==self.hwnd and delta<0:
            self.last_next=at;self.on_navigation("wheel",at,None)
        elif kind=="move" and self.drag:
            origin,dx,dy,frame=self.drag
            if hwnd!=origin or self.hwnd!=origin:self.drag=None;return
            if abs(y-dy)>=40 and abs(y-dy)>abs(x-dx)*1.5:
                self.drag=None
                self.last_next=at;self.on_navigation("drag",at,frame)

    def start(self):
        import threading
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        callback_type = c.WINFUNCTYPE(c.c_ssize_t, c.c_int, w.WPARAM, w.LPARAM)
        user32.SetWindowsHookExW.argtypes = [c.c_int, callback_type, w.HINSTANCE, w.DWORD]
        user32.SetWindowsHookExW.restype = w.HHOOK
        user32.CallNextHookEx.argtypes = [w.HHOOK, c.c_int, w.WPARAM, w.LPARAM]
        user32.CallNextHookEx.restype = c.c_ssize_t
        class Keyboard(c.Structure):
            _fields_ = [("vk", w.DWORD), ("scan", w.DWORD), ("flags", w.DWORD), ("time", w.DWORD), ("extra", c.c_size_t)]
        class Mouse(c.Structure):
            _fields_ = [("point", w.POINT), ("data", w.DWORD), ("flags", w.DWORD), ("time", w.DWORD), ("extra", c.c_size_t)]
        def key(code, message, address):
            if code >= 0 and message in {0x100,0x101}:
                item = c.cast(address, c.POINTER(Keyboard)).contents
                if item.vk==0x28:
                    self.key_event(message==0x100,foreground(),input_time(item.time),bool(item.flags&0x10))
            return user32.CallNextHookEx(None, code, message, address)
        def mouse(code, message, address):
            if code >= 0 and message in {0x201,0x202,0x20A,0x200}:
                item = c.cast(address, c.POINTER(Mouse)).contents
                if message!=0x200 or self.drag:
                    self.mouse_event({0x201:"down",0x202:"up",0x20A:"wheel",0x200:"move"}[message],
                        window_at(item.point.x,item.point.y),item.point.x,item.point.y,input_time(item.time),
                        c.c_short(item.data>>16).value,bool(item.flags&1))
            return user32.CallNextHookEx(None, code, message, address)
        self.callbacks = [callback_type(key), callback_type(mouse)]
        kernel32.GetModuleHandleW.argtypes=[w.LPCWSTR]
        kernel32.GetModuleHandleW.restype=w.HMODULE
        module=kernel32.GetModuleHandleW(None)
        self.hooks = [user32.SetWindowsHookExW(kind, cb, module, 0) for kind,cb in zip((13,14), self.callbacks)]
        msg = w.MSG()
        while user32.GetMessageW(c.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(c.byref(msg))
            user32.DispatchMessageW(c.byref(msg))
