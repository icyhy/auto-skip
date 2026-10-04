"""Video blacklist metadata must survive without broadening video matches."""
import sqlite3
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from autoskip.core import Engine, Snapshot, caption_key
from autoskip.store import Store


class VideoRules(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.addCleanup(lambda: self.store.db.close())
        self.now = 100.0
        self.engine = Engine(self.store, lambda: self.now)
        self.engine.pause(False)
        self.video = Snapshot("chrome", "tab", "one", "dy:video:123",
                              "dy:author:creator", "手机续航实测 #数码", "@测试作者",
                              active=True, playing=True, timing=True)

    def test_manual_video_keeps_metadata_and_exact_video_identity(self):
        self.engine.update(self.video)
        self.engine.manual_block("video")
        rule = self.store.rules()[0]
        self.assertEqual((rule["author"], rule["keyword"], rule["link"]),
                         (self.video.author, self.video.title, "https://www.douyin.com/video/123"))
        self.assertTrue(self.engine.match(replace(self.video, author="改名", title="新标题")))
        self.assertFalse(self.engine.match(replace(self.video, token="two", video_id="dy:video:456")))
        self.assertTrue(self.engine.match(replace(self.video, video_id="", links=rule["link"] + "?from=share")))

    def test_chrome_learning_keeps_departing_video_metadata(self):
        self.engine.update(self.video)
        self.now += 1
        self.engine.update(self.video)
        self.now += 1
        self.engine.update(replace(self.video, token="two", video_id="dy:video:456",
                                   author="@下一位作者", title="下一条视频", user_from="one"))
        rule = self.store.rules()[0]
        self.assertEqual((rule["target"], rule["author"], rule["keyword"]),
                         (self.video.video_id, self.video.author, self.video.title))
        self.assertFalse(self.engine.match(replace(self.video, video_id="dy:video:456")))

    def test_screenshot_video_keeps_metadata_without_matching_other_titles(self):
        target = caption_key(self.video.author, self.video.title)
        self.engine.remember("video", target, self.video.author + " " + self.video.title,
                             "划走前截图识别", author=self.video.author, title=self.video.title)
        rule = self.store.rules()[0]
        self.assertEqual((rule["author"], rule["keyword"]), (self.video.author, self.video.title))
        self.assertTrue(self.engine.match(replace(self.video, source="desktop", video_id="")))
        self.assertFalse(self.engine.match(replace(self.video, source="desktop", video_id="", title="其他手机评测")))

    def test_duplicate_video_enriches_missing_fields_and_undo_preserves_disabled_state(self):
        old = self.store.add_rule("video", self.video.video_id, self.video.title, "旧记录")
        self.store.enable(old["id"], False)
        self.engine.update(self.video)
        self.engine.manual_block("video")
        rule = self.store.rules()[0]
        self.assertEqual((rule["id"], rule["author"], rule["keyword"]),
                         (old["id"], self.video.author, self.video.title))
        self.engine.undo()
        self.assertEqual(len(self.store.rules()), 1)
        self.assertFalse(self.store.rules()[0]["enabled"])

    def test_missing_title_keeps_author_without_using_unrelated_page_text(self):
        self.engine.update(replace(self.video, title="", text="侧栏文字 评论内容"))
        self.engine.manual_block("video")
        rule = self.store.rules()[0]
        self.assertEqual((rule["author"], rule["keyword"]), (self.video.author, ""))
        self.assertFalse(self.engine.match(replace(self.video, video_id="dy:video:456")))

    def test_upgrade_recovers_metadata_by_video_identity_and_preserves_rule_state(self):
        self.store.add_rule("video", self.video.video_id, self.video.title, "旧记录")
        self.store.add_rule("video", "dy:video:789", "只有旧标题", "旧记录")
        self.store.add_rule("video", "dy:video:999", "dy:video:999", "无标题")
        self.store.save_watch(self.video, 3)
        self.store.save_watch(replace(self.video, video_id="dy:video:456", author="@别的作者"), 3)
        original = next(r for r in self.store.rules() if r["target"] == self.video.video_id)
        self.store.enable(original["id"], False)
        with TemporaryDirectory() as folder:
            path=Path(folder)/"upgrade.db"
            with sqlite3.connect(path) as backup:self.store.db.backup(backup)
            backup.close()
            for _ in range(2):
                restored=Store(path)
                try:
                    rules = {r["target"]: r for r in restored.rules()}
                    rule = rules[self.video.video_id]
                    self.assertEqual((rule["author"], rule["keyword"], rule["enabled"], rule["created"]),
                                     (self.video.author, self.video.title, 0, original["created"]))
                    self.assertEqual((rules["dy:video:789"]["author"], rules["dy:video:789"]["keyword"]),
                                     ("", "只有旧标题"))
                    self.assertEqual(rules["dy:video:999"]["keyword"], "")
                finally:restored.db.close()
