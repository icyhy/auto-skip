"""Local keyword categories shared by statistics and historical watch budgets."""
import re
import math
import unicodedata

from .core import caption_key, link_key, extract_links


CATEGORIES = {
    "数码科技": "数码 科技 手机 电脑 芯片 人工智能 AI 编程 软件 机器人 摄影 相机",
    "美食": "美食 做饭 烹饪 菜谱 食谱 厨房 探店 小吃 火锅 烧烤",
    "运动健身": "运动 健身 减脂 瑜伽 跑步 篮球 足球 游泳 马拉松",
    "旅行风景": "旅行 旅游 风景 景点 自驾 徒步 露营 山水",
    "知识教育": "知识 科普 教育 学习 教程 数学 英语 历史 物理 课堂",
    "财经商业": "财经 股票 基金 投资 经济 商业 创业 职场 理财",
    "汽车": "汽车 新能源 试驾 电动车 摩托 车评",
    "影视娱乐": "影视 电影 电视剧 明星 综艺 搞笑 喜剧 相声 段子",
    "音乐舞蹈": "音乐 唱歌 歌曲 演唱 跳舞 舞蹈 吉他 钢琴",
    "游戏": "游戏 电竞 王者荣耀 原神 我的世界 英雄联盟",
    "宠物动物": "宠物 猫咪 狗狗 小猫 小狗 动物 萌宠",
    "生活情感": "生活 情感 家庭 婚姻 育儿 宝宝 家居 装修 穿搭 美妆",
}


def categories(title):
    # ponytail: local keyword matching; extend this vocabulary when new topics matter.
    text=unicodedata.normalize("NFKC",title).casefold()
    found=[]
    for category,words in CATEGORIES.items():
        if any((bool(re.search(r"(?<![a-z0-9])"+re.escape(word.casefold())+r"(?![a-z0-9])",text))
                if word.isascii() else word in text) for word in words.split()):
            found.append(category)
    # Keep unknown parsed hashtags useful as their own categories.
    tags=re.findall(r"#([^\s#，。！？,!?]+)",text)
    return found or list(dict.fromkeys(tags))[:8] or ["未分类"]


def identity(snap):
    links=extract_links(snap.links)
    video_id=snap.video_id or next((link_key(link) for link in links if link_key(link).startswith("dy:video:")),"")
    return video_id or caption_key(snap.author,snap.title)


class WatchTracker:
    """Only persist visits with both a start switch and an end switch."""
    def __init__(self,store):
        self.store=store
        self.discard()

    def discard(self):
        self.context=self.snap=self.started=self.observed_at=self.last_switch=None
        self.favorite_saved=False
        self.favorite_seconds=0.0
        self.favorite_at=None

    def suspend_favorite(self):
        self.favorite_at=None

    def advance_favorite(self,at):
        if self.snap and self.favorite_at is not None:
            delta=at-self.favorite_at
            if 0<delta<=2 and self.snap.active and (self.snap.source=="desktop" or self.snap.playing):
                # ponytail: desktop has no continuous pause signal; count available-window intervals.
                self.favorite_seconds+=delta
        self.favorite_at=at

    def collect(self,at):
        self.advance_favorite(at)
        if self.favorite_saved or not self.snap or not self.store.get("favorites_enabled"):return False
        seconds=self.favorite_seconds
        if seconds<=float(self.store.get("favorite_threshold")) or not identity(self.snap):return False
        added=self.store.add_favorite(self.snap,seconds)
        self.favorite_saved=True
        return added

    def switch(self,source,session,at,manual=False):
        if not math.isfinite(at):return False
        context=(source,session)
        if self.context!=context:
            self.discard();self.context=context
        if self.last_switch is not None and (at<=self.last_switch or (manual and at-self.last_switch<.7)):
            return False
        self.collect(at)
        if self.started is not None and at>self.started:
            from .core import Snapshot
            snap=self.snap or Snapshot(source,session,"unknown")
            self.store.save_watch(snap,at-self.started)
        self.started=self.observed_at=self.last_switch=at
        self.snap=None
        self.favorite_saved=False
        self.favorite_seconds=0.0
        self.favorite_at=at
        return True

    def observe(self,snap,at):
        self.advance_favorite(at)
        context=(snap.source,snap.session)
        if self.context!=context:
            self.discard();self.context=context
        if snap.source=="chrome" and self.snap and self.snap.key!=snap.key:
            self.switch(snap.source,snap.session,at)
        if self.observed_at is None:self.observed_at=at
        self.snap=snap

    def elapsed(self,at):
        return max(0,at-self.observed_at) if self.observed_at is not None else 0.0
