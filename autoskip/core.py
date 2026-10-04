"""Deterministic rules. Adapters provide observations; only this module decides."""
import re
import time
import hashlib
import unicodedata
from urllib.parse import urlsplit
from dataclasses import dataclass


INVALID_AUTHOR_IDS={"dy:author:self","dy:author:me"}


def author_name(value):
    value=unicodedata.normalize("NFKC",value or "")
    value=re.sub(r"[\u200b-\u200f\u2060\ufeff]","",value).strip().lstrip("@·•.。 \t")
    value=re.sub(r"(?<=[\u4e00-\u9fff])[ \t]+(?=[\u4e00-\u9fff])","",value)
    value=re.sub(r"(?:\s*[·•.。|]\s*|\s+)(?:\d+\s*(?:秒|分钟|小时|天|周|月|年)\s*前|\d{1,2}\s*月\s*\d{1,2}\s*日|刚刚|昨天|前天)\s*$","",value)
    value=re.sub(r"\s*\(\s*主页\s*\)\s*$","",value)
    value=re.sub(r"\s+","",value)
    return value


def author_name_key(value):
    name=author_name(value)
    if name in {"","作者","用户","我的","我","主页","发一条友好的弹幕吧"}:return ""
    return "dy:author-name:"+hashlib.sha256(name.encode()).hexdigest()


def author_matches(rule,snapshot):
    target=rule["target"]
    current_id=snapshot.author_id if snapshot.author_id not in INVALID_AUTHOR_IDS else ""
    if target.startswith("dy:author-name:"):
        return target==author_name_key(snapshot.author)
    if target not in INVALID_AUTHOR_IDS and current_id:
        return target==current_id  # Different known accounts must never match by nickname.
    expected=author_name_key(rule["label"])
    return bool(expected and expected==author_name_key(snapshot.author))


def caption_key(author, title):
    author=re.sub(r"\s+","",unicodedata.normalize("NFKC",author)).lstrip("@")
    title=re.sub(r"\s+","",unicodedata.normalize("NFKC",title))
    if not author or len(title)<5:return ""
    return "dy:caption:"+hashlib.sha256((author+"\n"+title).encode()).hexdigest()


def video_link(target):
    if target.startswith("dy:video:"):
        return "https://www.douyin.com/video/"+target.removeprefix("dy:video:")
    return target


def extract_links(text):
    return list(dict.fromkeys(value.rstrip(".,;!?，。；！？、)") for value in
        re.findall(r"(?:https?://|www\.)[^\s<>\"'，。；！？、（）]+",text)))


def link_key(value):
    value=value.strip().rstrip("/")
    if value.startswith("www."):value="https://"+value
    try:parts=urlsplit(value)
    except ValueError:return value
    if parts.hostname in {"douyin.com","www.douyin.com"} and re.fullmatch(r"/video/\d+/?",parts.path):
        return "dy:video:"+parts.path.strip("/").split("/")[1]
    return value


def rule_matches(rule,snap):
    author=rule["author"]
    if rule["kind"]=="author":
        author_hit=bool(author) and author_matches(rule,snap)
    else:
        author_hit=bool(author) and author_name(author)==author_name(snap.author)
    normalize=lambda text: re.sub(r"\s+","",unicodedata.normalize("NFKC",text)).casefold()
    keyword_hit=bool(rule["keyword"]) and normalize(rule["keyword"]) in normalize(snap.title+"\n"+snap.text)
    links=extract_links(snap.links+"\n"+snap.title+"\n"+snap.text)
    if snap.video_id:links.append(video_link(snap.video_id))
    # Keep exact identities for older screenshot-learned videos that have no URL.
    if rule["kind"]=="video":links.append(caption_key(snap.author,snap.title))
    link_hit=bool(rule["link"]) and link_key(rule["link"]) in {link_key(link) for link in links if link}
    matches=(author_hit,keyword_hit,link_hit)
    return all(matches) if rule["condition"]=="and" else any(matches)


def evidence_text(text):
    lines=[]
    for line in text.splitlines():
        line=re.sub(r"\d{1,2}\s*[:：]\s*\d{2}\s*/\s*\d{1,2}\s*[:：]\s*\d{2}","",line).strip()
        if not line or re.fullmatch(r"[\d.,万亿/\s:%]+",line):continue
        if line in {"首页","搜索","消息","点赞","评论","分享","发送","连播","自动","倍速","弹幕"}:continue
        lines.append(line)
    return "\n".join(lines)[:6000]


@dataclass(frozen=True)
class Snapshot:
    source: str
    session: str
    token: str
    video_id: str = ""
    author_id: str = ""
    title: str = ""
    author: str = ""
    text: str = ""
    active: bool = False
    playing: bool = False
    timing: bool = False
    ended: bool = False
    user_from: str = ""
    purchase: str = ""
    links: str = ""

    @classmethod
    def parse(cls, data):
        if not isinstance(data, dict):
            raise ValueError("无效的视频信息")
        values = {}
        for key, field in cls.__dataclass_fields__.items():
            value = data.get(key, field.default)
            if key in {"active", "playing", "timing", "ended"}:
                values[key] = value is True
            else:
                if not isinstance(value, str):
                    raise ValueError("字段类型不正确")
                values[key] = value[:8000 if key in {"text","links"} else 2000]
        if values["source"] not in {"chrome", "desktop"} or not values["session"] or not values["token"]:
            raise ValueError("缺少当前视频身份")
        return cls(**values)

    @property
    def key(self):
        return self.source, self.session, self.token


class Engine:
    def __init__(self, store, clock=time.monotonic):
        self.store, self.clock = store, clock
        self.listen_enabled = bool(store.get("listen_enabled"))
        self.auto_enabled = bool(store.get("auto_enabled"))
        self.auto_skip_enabled = bool(store.get("auto_skip_enabled"))
        self.paused = True  # Starting the program never starts input injection.
        self.current = None
        self.last_at = 0.0
        self.watched = 0.0
        from .statistics import WatchTracker
        self.views = WatchTracker(store)
        self.budget = None
        self.budget_identity = None
        self.pending = None
        self.undo_stack = []
        self.manual = None
        self.suppressed = None
        self.status = "已暂停，点击开始后打开抖音即可"
        self.epoch = 0

    def reset(self, preserve_watch=False):
        if not preserve_watch:self.views.discard()
        self.epoch += 1
        self.current, self.pending, self.manual = None, None, None
        self.watched, self.last_at = 0.0, 0.0
        self.budget = self.budget_identity = None

    def pause(self, value):
        self.paused = value
        self.reset()
        self.status = "已暂停" if value else "等待视频画面"

    def set_features(self, *, listen=None, auto=None, auto_skip=None):
        if any(value is not None and not isinstance(value,bool) for value in (listen,auto,auto_skip)):
            raise ValueError("功能开关必须为布尔值")
        old_listen,old_auto=self.listen_enabled,self.auto_enabled
        if listen is not None:self.listen_enabled=listen
        if auto is not None:self.auto_enabled=auto
        if auto_skip is not None:
            self.auto_skip_enabled=auto_skip
            self.budget = self.budget_identity = None
        self.store.set("listen_enabled",self.listen_enabled)
        self.store.set("auto_enabled",self.auto_enabled)
        self.store.set("auto_skip_enabled",self.auto_skip_enabled)
        if old_auto!=self.auto_enabled:self.reset(preserve_watch=True)
        elif old_listen!=self.listen_enabled:
            # Toggling learning must not cancel a pending automatic skip.
            self.last_at=self.clock() if self.current else 0.0

    def remember(self, kind, target, label, reason):
        change = self.store.add_rule(kind, target, label, reason)
        self.undo_stack.append(change)
        self.undo_stack = self.undo_stack[-30:]
        self.store.log("拉黑", label, reason)

    def undo(self):
        if not self.undo_stack:
            return "没有可撤销的拉黑记录"
        self.store.undo(self.undo_stack.pop())
        self.suppressed = self.current.key if self.current else None
        self.manual = None
        self.status = "已撤销最近一次拉黑"
        return self.status

    def manual_block(self, kind):
        snap = self.current
        if self.paused or not snap or not snap.active or self.clock() - self.last_at > 2:
            raise ValueError("请先开始，并确认目标窗口正在提供视频画面")
        target = snap.author_id if kind == "author" else snap.video_id
        if kind=="author" and (not target or target in INVALID_AUTHOR_IDS):target=author_name_key(snap.author)
        if not target:
            raise ValueError("当前未取得可靠的" + ("作者账号标识" if kind == "author" else "视频标识") + "，未执行拉黑")
        self.remember(kind, target, snap.author if kind == "author" else snap.title or target, "手动拉黑")
        self.manual = snap.key
        self.suppressed = None

    def match(self, snap):
        for rule in self.store.rules(enabled=True):
            if rule_matches(rule,snap):
                return {"video":"视频黑名单：","author":"作者黑名单：","filter":"黑名单："}[rule["kind"]]+rule["label"]
        return ""

    def update(self, snap):
        now, old = self.clock(), self.current
        if self.paused:
            return None
        if not snap.active:
            # A background interval breaks observation continuity, including learning.
            self.reset(preserve_watch=True)
            self.status = "等待返回目标视频"
            return None
        delta = now - self.last_at
        if old and old.key == snap.key and delta > 2:
            # A long observation gap breaks playback continuity for blacklist learning.
            self.reset(preserve_watch=True)
            old=None
        contiguous = old is not None and old.active and 0 <= delta <= 2
        if not self.pending or snap.key!=self.pending[0]:self.views.observe(snap,now)
        if contiguous and old.playing and old.timing:
            if not self.pending:
                self.watched += delta
        if not old or old.key != snap.key:
            self.epoch += 1
            threshold = float(self.store.get("threshold"))
            if (contiguous and old.source == snap.source and old.session == snap.session
                    and old.source != "desktop"
                    and snap.user_from == old.token and self.listen_enabled
                    and old.video_id and old.timing and not old.ended
                    and self.pending is None and 0 < self.watched < threshold):
                self.remember("video", old.video_id, old.title or old.video_id,
                              f"手动跳过，观察到播放 {self.watched:.1f} 秒")
                self.status = "已记住刚刚跳过的视频"
            self.watched = 0.0
            self.budget = self.budget_identity = None
            self.pending = self.manual = None
            self.suppressed = None
        self.current, self.last_at = snap, now
        if self.auto_enabled and self.auto_skip_enabled:
            from .statistics import identity
            metadata=(identity(snap),snap.author,snap.title)
            if metadata!=self.budget_identity:
                self.budget=self.store.historical_watch(snap)
                self.budget_identity=metadata
        if self.pending:
            if now - self.pending[1] > 3:
                self.paused = True
                self.status = "切换未确认，已暂停；请检查播放页面"
            return None
        if self.suppressed == snap.key:
            return None
        reason = "手动拉黑" if self.manual == snap.key else ""
        if not reason and self.auto_enabled:
            reason = self.match(snap) or ("视频播放完成" if snap.ended and snap.timing else "")
        if reason:
            return self.next_action(reason)
        action=self.timed_action()
        if action:return action
        if self.listen_enabled and not self.auto_enabled and not self.status.startswith("已记住"):
            self.status = f"监听中 · 切换间隔 {self.views.elapsed(now):.1f} 秒"
        elif self.auto_enabled:
            self.status = ("监听＋自动" if self.listen_enabled else "自动")+" · 继续观看"
            if self.auto_skip_enabled:
                self.status+=f" · {self.views.elapsed(now):.1f}/{self.budget[0]:.1f} 秒" if self.budget else " · 暂无有效历史时长"
        return None

    def timed_action(self):
        if self.current and self.suppressed==self.current.key:return None
        if self.auto_enabled and self.auto_skip_enabled and self.budget and self.views.elapsed(self.clock())>=self.budget[0]:
            return self.next_action(f"历史观看时长 {self.budget[0]:.1f} 秒（{self.budget[1]}）")
        return None

    def next_action(self, reason):
        snap = self.current
        if not snap or self.pending or self.paused or not snap.active:
            return None
        self.pending = (snap.key, self.clock())
        self.manual = None
        self.status = "跳过：" + reason
        self.store.log("请求跳过", snap.title or snap.author, reason)
        return {"action": "next", "token": snap.token, "session": snap.session, "reason": reason}

    def cloud_result(self, key, result, epoch=None):
        # Category decisions from older in-flight requests no longer filter videos.
        return None


def purchase_evidence(text):
    """Explicit invitations only; product names or prices alone never match."""
    for line in text.splitlines():
        if re.search(r"(?:不要|别|没有|拒绝|警惕|骗局|不建议|勿).{0,12}(?:下单|购买|链接|口令|小黄车)", line):
            continue
        match = re.search(r"(?:点击|点开|点进|戳).{0,6}(?:购物车|小黄车|链接).{0,8}(?:购买|下单|领券)|(?:复制|输入|搜索)\s*[\w￥$]{2,20}\s*(?:领券|优惠)|(?:点击|立即|赶紧)(?:下单|购买)", line)
        if match:
            return match.group(0)
    return ""
