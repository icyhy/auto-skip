import json
import math
import sqlite3
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from .core import INVALID_AUTHOR_IDS,author_name,author_name_key,video_link
from .players import DEFAULT_PLAYER


DEFAULTS = {
    "auto_skip_enabled": False,
    "listen_enabled": True, "auto_enabled": False, "threshold": 5.0, "opacity": 0.82,
    "source": "auto", "cloud_enabled": False,
    "player_type": DEFAULT_PLAYER,
    "player_profiles": [{"name": DEFAULT_PLAYER, "process": "douyin.exe", "regions": [{"direction": "bottom", "span": 100}]}],
    "base_url": "https://api.deepseek.com", "model": "deepseek-flash",
    "vision": False, "daily_limit": 50, "cloud_interval": 5,
    "jev_enabled": True, "jev_model": "jev-latest", "jev_confidence": 0.9,
    "hotkeys": {"pause": "Ctrl+Alt+P", "block": "Ctrl+Alt+B",
                "undo": "Ctrl+Alt+Z", "auto": "Ctrl+Alt+M", "listen": "Ctrl+Alt+L", "show": "Ctrl+Alt+O"},
}

WATCH_FIELDS = ("created", "video_key", "caption_key", "author", "title", "source", "seconds", "duration_basis")


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS rules (
          id INTEGER PRIMARY KEY, kind TEXT NOT NULL, target TEXT NOT NULL,
          label TEXT NOT NULL, reason TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
          created TEXT NOT NULL DEFAULT (datetime('now','localtime')), UNIQUE(kind,target));
        CREATE TABLE IF NOT EXISTS history (
          id INTEGER PRIMARY KEY, created TEXT DEFAULT (datetime('now','localtime')),
          action TEXT, label TEXT, reason TEXT);
        CREATE TABLE IF NOT EXISTS usage (day TEXT PRIMARY KEY, calls INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS watches (
          id INTEGER PRIMARY KEY, created TEXT DEFAULT (datetime('now','localtime')),
          video_key TEXT NOT NULL, caption_key TEXT NOT NULL, author TEXT NOT NULL,
          title TEXT NOT NULL, source TEXT NOT NULL, seconds REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS watches_video ON watches(video_key);
        CREATE INDEX IF NOT EXISTS watches_caption ON watches(caption_key);
        """)
        if "duration_basis" not in {row["name"] for row in self.db.execute("PRAGMA table_info(watches)")}:
            with self.db:
                self.db.execute("ALTER TABLE watches ADD COLUMN duration_basis TEXT NOT NULL DEFAULT 'legacy'")
        columns={row["name"] for row in self.db.execute("PRAGMA table_info(rules)")}
        with self.db:
            for name,default in (("author",""),("keyword",""),("link",""),("condition","or")):
                if name not in columns:
                    self.db.execute(f"ALTER TABLE rules ADD COLUMN {name} TEXT NOT NULL DEFAULT '{default}'")
            if "condition" not in columns:
                self.db.execute("UPDATE rules SET author=CASE WHEN label='' THEN target ELSE label END WHERE kind='author'")
                for row in self.db.execute("SELECT id,target FROM rules WHERE kind='video'").fetchall():
                    self.db.execute("UPDATE rules SET link=? WHERE id=?",(video_link(row["target"]),row["id"]))
        if not self.get("automatic_window_v1", False):
            # Upgrade the old mandatory calibration flow to foreground detection.
            with self.db:
                self.db.execute("DELETE FROM settings WHERE key='desktop_roi'")
                self.db.execute("INSERT OR REPLACE INTO settings VALUES ('source','\"auto\"')")
                self.db.execute("INSERT OR REPLACE INTO settings VALUES ('automatic_window_v1','true')")
        self.repair_author_rules()
        self.repair_video_rules()
        legacy_mode=self.get("mode","listen")
        with self.db:
            for key,value in (("listen_enabled",legacy_mode!="auto"),("auto_enabled",legacy_mode=="auto")):
                self.db.execute("INSERT OR IGNORE INTO settings VALUES (?,?)",(key,json.dumps(value)))
            self.db.execute("DELETE FROM settings WHERE key='mode'")
        keys=dict(self.get("hotkeys"))
        legacy_shortcut=keys.pop("mode",None)
        if legacy_shortcut is not None:keys.setdefault("auto",legacy_shortcut)
        self.set("hotkeys",{key:keys.get(key,value) for key,value in DEFAULTS["hotkeys"].items()})

    def repair_author_rules(self):
        with self.db:
            self.db.execute("UPDATE rules SET author=CASE WHEN label='' THEN target ELSE label END WHERE kind='author' AND author=''")
            for row in self.db.execute("SELECT id,target,label FROM rules WHERE kind='author'").fetchall():
                if row["target"] not in INVALID_AUTHOR_IDS:continue
                replacement=author_name_key(row["label"])
                if not replacement:
                    self.db.execute("UPDATE rules SET enabled=0 WHERE id=?",(row["id"],));continue
                duplicate=self.db.execute("SELECT id FROM rules WHERE kind='author' AND target=?",(replacement,)).fetchone()
                if duplicate:
                    self.db.execute("UPDATE rules SET enabled=0 WHERE id=?",(row["id"],))
                else:
                    self.db.execute("UPDATE rules SET target=?,reason=reason||'；已修复无效账号标识，按完整作者名匹配' WHERE id=?",(replacement,row["id"]))

    def get(self, key, fallback=None):
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else DEFAULTS.get(key, fallback)

    def repair_video_rules(self):
        # Recover only recorded metadata tied to the same persistent video identity.
        with self.db:
            for rule in self.db.execute("SELECT * FROM rules WHERE kind='video' AND (author='' OR keyword='')").fetchall():
                watch=self.db.execute("SELECT author,title FROM watches WHERE (video_key=? OR caption_key=?) "
                                      "AND author!='' ORDER BY id DESC LIMIT 1",(rule["target"],rule["target"])).fetchone()
                author=rule["author"] or (watch["author"] if watch else "")
                keyword=rule["keyword"] or (watch["title"] if watch else "")
                if not keyword and rule["target"].startswith("dy:video:") and rule["label"]!=rule["target"]:
                    keyword=rule["label"]
                if (author,keyword)!=(rule["author"],rule["keyword"]):
                    self.db.execute("UPDATE rules SET author=?,keyword=? WHERE id=?",(author[:2000],keyword[:2000],rule["id"]))

    def set(self, key, value):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value)))

    def add_rule(self, kind, target, label, reason, *, author="", keyword=""):
        if kind=="author" and target in INVALID_AUTHOR_IDS:target=author_name_key(label)
        if kind not in {"video", "author"} or not target or len(target) > 2000:
            raise ValueError("缺少可靠的屏蔽对象")
        old = self.db.execute("SELECT * FROM rules WHERE kind=? AND target=?", (kind, target)).fetchone()
        author=(author or label or target) if kind=="author" else author
        with self.db:
            if old:
                self.db.execute("UPDATE rules SET enabled=1,author=CASE WHEN author='' THEN ? ELSE author END,"
                                "keyword=CASE WHEN keyword='' THEN ? ELSE keyword END WHERE id=?",
                                (author[:2000],keyword[:2000],old["id"]))
                return {"id": old["id"], "old_enabled": old["enabled"]}
            cur = self.db.execute("INSERT INTO rules(kind,target,label,reason,author,keyword,link) VALUES (?,?,?,?,?,?,?)",
                                  (kind,target,label[:500],reason[:1000],author[:2000],keyword[:2000],video_link(target) if kind=="video" else ""))
            return {"id": cur.lastrowid, "old_enabled": None}

    def save_filter(self, author, keyword, link, condition, rule_id=None):
        values=(author,keyword,link)
        if any(not isinstance(value,str) or len(value)>2000 for value in values):
            raise ValueError("每项最多输入 2000 个字符")
        author,keyword,link=(value.strip() for value in values)
        if author and not author_name(author):raise ValueError("请输入有效的作者名称")
        if condition not in {"or","and"}:raise ValueError("请选择或、与过滤条件")
        if not any((author,keyword,link)):raise ValueError("作者、关键词、链接至少填写一项")
        if condition=="and" and not all((author,keyword,link)):
            raise ValueError("与条件需要填写作者、关键词和链接三项")
        if link:
            from urllib.parse import urlsplit
            try:
                parts=urlsplit(link if not link.startswith("www.") else "https://"+link)
                if parts.scheme not in {"http","https"} or not parts.hostname or any(c.isspace() for c in link):raise ValueError
            except ValueError:raise ValueError("请输入完整的 http:// 或 https:// 链接") from None
        target=json.dumps([author,keyword,link,condition],ensure_ascii=False)
        label=(" 或 " if condition=="or" else " 与 ").join(value for value in (author,keyword,link) if value)[:500]
        duplicate=self.db.execute("SELECT id,enabled FROM rules WHERE kind='filter' AND target=?",(target,)).fetchone()
        if duplicate and rule_id is not None and duplicate["id"]!=rule_id:raise ValueError("已存在相同规则")
        with self.db:
            if rule_id is not None:
                self.db.execute("UPDATE rules SET kind='filter',target=?,label=?,author=?,keyword=?,link=?,condition=? WHERE id=?",
                                (target,label,author,keyword,link,condition,rule_id))
                return None
            if duplicate:
                self.db.execute("UPDATE rules SET enabled=1 WHERE id=?",(duplicate["id"],))
                return {"id":duplicate["id"],"old_enabled":duplicate["enabled"]}
            cur=self.db.execute("INSERT INTO rules(kind,target,label,reason,author,keyword,link,condition) VALUES ('filter',?,?,'手动添加',?,?,?,?)",
                                (target,label,author,keyword,link,condition))
            return {"id":cur.lastrowid,"old_enabled":None}

    def undo(self, change):
        with self.db:
            if change["old_enabled"] is None:
                self.db.execute("DELETE FROM rules WHERE id=?", (change["id"],))
            else:
                self.db.execute("UPDATE rules SET enabled=? WHERE id=?", (change["old_enabled"], change["id"]))

    def rules(self, enabled=False):
        return [dict(r) for r in self.db.execute("SELECT * FROM rules WHERE kind!='category'" + (" AND enabled=1" if enabled else "") + " ORDER BY id DESC")]

    def enable(self, rule_id, enabled):
        with self.db:
            self.db.execute("UPDATE rules SET enabled=? WHERE id=?", (int(enabled), rule_id))

    def delete(self, rule_id):
        with self.db:
            self.db.execute("DELETE FROM rules WHERE id=?", (rule_id,))

    def log(self, action, label, reason):
        with self.db:
            self.db.execute("INSERT INTO history(action,label,reason) VALUES (?,?,?)", (action, label[:500], reason[:1000]))
            self.db.execute("DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY id DESC LIMIT 300)")

    def history(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM history ORDER BY id DESC LIMIT 100")]

    def save_watch(self, snap, seconds, watch_id=None):
        from .statistics import identity
        from .core import caption_key
        if not math.isfinite(seconds) or seconds<=0:return watch_id
        values=(identity(snap),caption_key(snap.author,snap.title),snap.author,snap.title,snap.source,seconds)
        with self.db:
            if watch_id is None:
                return self.db.execute("INSERT INTO watches(video_key,caption_key,author,title,source,seconds,duration_basis) VALUES (?,?,?,?,?,?,'switch')",values).lastrowid
            self.db.execute("UPDATE watches SET video_key=?,caption_key=?,author=?,title=?,source=?,seconds=?,duration_basis='switch' WHERE id=?",(*values,watch_id))
        return watch_id

    def export_watches(self):
        rows=self.db.execute(f"SELECT {','.join(WATCH_FIELDS)} FROM watches ORDER BY id").fetchall()
        return {"format":"autoskip-watches","version":1,"watches":[dict(row) for row in rows]}

    def import_watches(self, data):
        if (not isinstance(data,dict) or data.get("format")!="autoskip-watches"
                or type(data.get("version")) is not int or data["version"]!=1 or not isinstance(data.get("watches"),list)):
            raise ValueError("请选择 Auto Skip 导出的观看记录 JSON 文件（版本 1）")
        records=[]
        for index,row in enumerate(data["watches"],1):
            try:
                if not isinstance(row,dict):raise ValueError
                if any(not isinstance(row[field],str) for field in WATCH_FIELDS if field!="seconds"):raise ValueError
                datetime.strptime(row["created"],"%Y-%m-%d %H:%M:%S")
                if row["source"] not in {"chrome","desktop"} or row["duration_basis"] not in {"switch","legacy"}:raise ValueError
                if type(row["seconds"]) not in {int,float}:raise ValueError
                seconds=float(row["seconds"])
                if not math.isfinite(seconds) or seconds<=0:raise ValueError
                values=tuple(seconds if field=="seconds" else row[field] for field in WATCH_FIELDS)
            except (KeyError,ValueError,OverflowError):
                raise ValueError(f"第 {index} 条观看记录无效，未导入任何记录") from None
            records.append(values)
        # Match occurrence counts so a backup can retain genuinely identical visits.
        existing=Counter(tuple(row[field] for field in WATCH_FIELDS) for row in self.export_watches()["watches"])
        added=0
        with self.db:
            for values in records:
                if existing[values]:
                    existing[values]-=1
                    continue
                self.db.execute(f"INSERT INTO watches({','.join(WATCH_FIELDS)}) VALUES ({','.join('?' for _ in WATCH_FIELDS)})",values)
                added+=1
        return added

    def reset_watches(self):
        with self.db:
            self.db.execute("DELETE FROM watches")

    def statistics(self, exclude=None):
        from .statistics import categories
        threshold=float(self.get("threshold"))
        rows=self.db.execute("SELECT * FROM watches WHERE duration_basis='switch' AND id!=?",(exclude or -1,)).fetchall()
        valid=[row for row in rows if row["seconds"]>threshold]
        skipped=[row for row in rows if row["seconds"]<threshold]
        skipped_seconds=sum(row["seconds"] for row in skipped)
        groups={}
        for row in valid:
            for category in categories(row["title"]):
                group=groups.setdefault(category,{"category":category,"count":0,"seconds":0.0})
                group["count"]+=1;group["seconds"]+=row["seconds"]
        for group in groups.values():group["average"]=group["seconds"]/group["count"]
        total=sum(row["seconds"] for row in rows)
        effective=sum(row["seconds"] for row in valid)
        return {"count":len(rows),"seconds":total,"average":total/len(rows) if rows else 0.0,
                "skipped":{"category":"跳过","count":len(skipped),"seconds":skipped_seconds,
                           "average":skipped_seconds/len(skipped) if skipped else 0.0},
                "valid_count":len(valid),"valid_seconds":effective,"valid_average":effective/len(valid) if valid else 0.0,
                "categories":sorted(groups.values(),key=lambda group:(-group["count"],group["category"]))}

    def historical_watch(self, snap, exclude=None):
        from .statistics import identity, categories
        from .core import caption_key
        key,caption=identity(snap),caption_key(snap.author,snap.title)
        if not key:return None
        row=self.db.execute("""SELECT AVG(seconds) FROM watches WHERE duration_basis='switch' AND seconds>? AND id!=? AND
                            (video_key=? OR (?!='' AND caption_key=? AND
                            (video_key NOT LIKE 'dy:video:%' OR ? NOT LIKE 'dy:video:%')))""",
                            (float(self.get("threshold")),exclude or -1,key,caption,caption,key)).fetchone()
        if row[0] is not None:return (row[0],"同一视频")
        stats=self.statistics(exclude)
        matches=[g for g in stats["categories"] if g["category"]!="未分类" and g["category"] in categories(snap.title)]
        if matches:
            # Multiple matching topics use the most sampled category, without double counting.
            group=max(matches,key=lambda g:g["count"])
            return (group["average"],group["category"])
        return None

    def calls(self):
        row = self.db.execute("SELECT calls FROM usage WHERE day=?", (date.today().isoformat(),)).fetchone()
        return row[0] if row else 0

    def reserve_call(self, limit):
        if self.calls() >= limit:
            return False
        with self.db:
            self.db.execute("INSERT INTO usage VALUES (?,1) ON CONFLICT(day) DO UPDATE SET calls=calls+1", (date.today().isoformat(),))
        return True
