import unittest
from dataclasses import replace
from pathlib import Path
import shutil
import uuid

from autoskip.core import Engine, Snapshot
from autoskip.store import Store


class Favorites(unittest.TestCase):
    def setUp(self):
        self.store=Store(":memory:");self.addCleanup(self.store.db.close)
        self.now=100.0
        self.engine=Engine(self.store,lambda:self.now);self.engine.pause(False)
        self.video=Snapshot("chrome","tab","one","dy:video:123",author="@作者",
                            title="手机续航实测 #数码",active=True,playing=True)

    def watch(self,seconds,snap=None):
        snap=snap or self.video
        while seconds>0:
            step=min(1,seconds);self.now+=step;seconds-=step;self.engine.update(snap)

    def test_strict_default_threshold_saves_current_video_without_switch(self):
        self.engine.update(self.video);self.watch(300)
        self.assertEqual(self.store.favorites(),[])
        self.watch(.01)
        row=self.store.favorites()[0]
        self.assertEqual((row["author"],row["category"],row["link"]),
                         ("@作者","数码科技","https://www.douyin.com/video/123"))
        self.assertEqual(self.store.statistics()["count"],0)
        self.watch(10);self.assertEqual(len(self.store.favorites()),1)

    def test_independent_switch_configurable_threshold_and_pending_skip(self):
        self.store.set("favorite_threshold",6)
        self.engine.set_features(listen=False,auto=False,favorites=False)
        self.engine.update(self.video);self.watch(7)
        self.assertEqual(self.store.favorites(),[])
        self.engine.set_features(favorites=True)
        self.watch(1);self.assertEqual(len(self.store.favorites()),1)
        with self.assertRaises(ValueError):self.engine.set_features(favorites="yes")
        self.engine.pause(True);self.engine.pause(False);self.engine.update(replace(self.video,video_id="dy:video:456"))
        self.engine.next_action("跳过");self.watch(2,replace(self.video,video_id="dy:video:456"))
        self.assertEqual(len(self.store.favorites()),1)

    def test_pause_background_and_connection_gaps_are_excluded(self):
        self.store.set("favorite_threshold",6)
        self.engine.update(self.video);self.watch(3)
        self.watch(1,replace(self.video,playing=False));self.watch(20,replace(self.video,playing=False))
        self.assertEqual(self.store.favorites(),[])
        self.engine.update(replace(self.video,active=False));self.now+=1000
        self.engine.update(self.video);self.watch(2)
        self.assertEqual(self.store.favorites(),[])
        self.now+=1000;self.engine.update(self.video)
        self.assertEqual(self.store.favorites(),[])
        self.watch(.1);self.assertEqual(len(self.store.favorites()),1)
        self.engine.pause(True);self.now+=1000
        self.assertFalse(self.engine.collect_favorite())

    def test_switch_boundary_collects_departing_video_and_resets_new_video(self):
        self.store.set("favorite_threshold",6)
        self.engine.update(self.video);self.watch(6)
        self.now+=.1
        second=replace(self.video,token="two",video_id="dy:video:456",author="@下一位",title="旅行风景")
        self.engine.update(second)
        self.assertEqual([row["video_key"] for row in self.store.favorites()],["dy:video:123"])
        self.watch(6,second);self.assertEqual(len(self.store.favorites()),1)
        self.watch(.1,second);self.assertEqual(len(self.store.favorites()),2)

    def test_desktop_counts_available_window_and_collects_at_navigation(self):
        self.store.set("favorite_threshold",6)
        video=replace(self.video,source="desktop",playing=False)
        self.engine.update(video);self.watch(6,video)
        self.now+=.1;self.engine.views.switch(video.source,video.session,self.now,manual=True)
        self.assertEqual(self.store.favorites()[0]["video_key"],video.video_id)
        self.engine.reset(preserve_watch=True)
        self.assertIsNone(self.engine.views.snap)

    def test_duplicate_enrichment_known_ids_and_user_edits(self):
        no_link=replace(self.video,source="desktop",video_id="",links="https://www.douyin.com/user/creator")
        self.assertTrue(self.store.add_favorite(no_link,301))
        row=self.store.favorites()[0];self.assertEqual(row["link"],"")
        self.store.edit_favorite(row["id"],"自定义作者","自定义标题","自定义类型","")
        self.assertFalse(self.store.add_favorite(self.video,310))
        saved=self.store.favorites()[0]
        self.assertEqual((saved["id"],saved["author"],saved["title"],saved["category"],saved["video_key"]),
                         (row["id"],"自定义作者","自定义标题","自定义类型","dy:video:123"))
        self.assertEqual(saved["link"],"https://www.douyin.com/video/123")
        self.assertTrue(self.store.add_favorite(replace(self.video,video_id="dy:video:456"),301))
        self.assertEqual(len(self.store.favorites()),2)

    def test_unknown_identity_is_not_saved_and_profile_links_are_not_video_links(self):
        self.assertFalse(self.store.add_favorite(replace(self.video,video_id="",author="",title=""),301))
        for seconds in (0,-1,float("nan"),float("inf")):
            self.assertFalse(self.store.add_favorite(self.video,seconds))
        self.assertTrue(self.store.add_favorite(replace(self.video,video_id="",links="https://www.douyin.com/user/a"),301))
        self.assertEqual(self.store.favorites()[0]["link"],"")

    def test_delete_does_not_readd_during_same_visit_and_edit_validates_links(self):
        self.store.set("favorite_threshold",6)
        self.engine.update(self.video);self.watch(7)
        row=self.store.favorites()[0]
        for link in ("javascript:alert(1)","https://", "https://example.com/with space"):
            with self.assertRaises(ValueError):self.store.edit_favorite(row["id"],"作者","标题","类型",link)
        self.store.delete_favorites([row["id"]]);self.watch(10)
        self.assertEqual(self.store.favorites(),[])
        other=replace(self.video,token="two",video_id="dy:video:456")
        self.engine.update(other);self.now+=1;self.engine.update(self.video);self.watch(7)
        self.assertEqual(len(self.store.favorites()),1)

    def test_restart_retains_favorites_preferences_and_other_data(self):
        root=Path(__file__).resolve().parents[1]/".local"/"favorites-tests";root.mkdir(parents=True,exist_ok=True)
        folder=root/uuid.uuid4().hex;folder.mkdir()
        try:
            path=folder/"data.db"
            store=Store(path);store.add_favorite(self.video,301);store.set("favorite_threshold",120)
            store.set("favorites_enabled",False);store.save_watch(self.video,10)
            store.add_rule("author","dy:author:a","作者","手动");store.db.close()
            store=Store(path)
            try:
                self.assertEqual(len(store.favorites()),1)
                self.assertEqual(store.get("favorite_threshold"),120)
                self.assertFalse(Engine(store).favorites_enabled)
                store.reset_watches();self.assertEqual(len(store.favorites()),1)
                store.delete_favorites([row["id"] for row in store.favorites()])
                self.assertEqual(len(store.rules()),1)
            finally:store.db.close()
        finally:
            assert folder.resolve().is_relative_to(root.resolve())
            shutil.rmtree(folder)


if __name__=="__main__":unittest.main()
