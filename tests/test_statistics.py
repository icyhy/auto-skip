import unittest
import json
import sqlite3
from copy import deepcopy
from dataclasses import replace
from unittest.mock import patch, Mock

from autoskip.core import Engine, Snapshot
from autoskip.store import Store
from autoskip.statistics import categories
import test_desktop


class WatchStatistics(unittest.TestCase):
    def setUp(self):
        self.store=Store(":memory:")
        self.addCleanup(self.store.db.close)
        self.now=100
        self.engine=Engine(self.store,lambda:self.now)
        self.engine.pause(False)
        self.video=Snapshot("chrome","tab","one","dy:video:1",title="手机续航实测 #数码",author="@作者",active=True,playing=True,timing=True)

    def tick(self,snap=None):
        self.now+=1
        return self.engine.update(snap or self.video)

    def test_all_average_and_strict_valid_average_recalculate_after_threshold_change(self):
        for seconds in (3,5,10,20):self.store.save_watch(self.video,seconds)
        self.store.save_watch(replace(self.video,title="做饭美食"),12)
        stats=self.store.statistics()
        self.assertEqual(stats["count"],5)
        self.assertEqual(stats["average"],10)
        self.assertEqual(stats["valid_count"],3)
        self.assertEqual(stats["valid_average"],14)
        self.assertEqual({g["category"]:g["average"] for g in stats["categories"]},{"数码科技":15,"美食":12})
        self.store.set("threshold",12)
        stats=self.store.statistics()
        self.assertEqual(stats["valid_count"],1)
        self.assertEqual(stats["categories"][0]["average"],20)

    def test_first_and_last_visits_are_excluded_and_duration_needs_no_progress(self):
        first=replace(self.video,playing=False,timing=False)
        second=replace(first,token="second",video_id="dy:video:2")
        third=replace(first,token="third",video_id="dy:video:3")
        self.engine.update(first)
        self.now=107;self.engine.update(second)
        self.assertEqual(self.store.statistics()["count"],0)
        self.now=117;self.engine.update(third)
        self.assertEqual(self.store.statistics()["count"],1)
        self.assertEqual(self.store.statistics()["seconds"],10)
        self.now=140;self.engine.update(third)
        self.engine.pause(True)
        self.assertEqual(self.store.statistics()["seconds"],10)
        self.assertEqual(self.store.db.execute("SELECT video_key FROM watches").fetchone()[0],"dy:video:2")

    def test_skipped_category_uses_strict_threshold_and_is_excluded_from_prediction(self):
        self.assertEqual(self.store.statistics()["skipped"],{"category":"跳过","count":0,"seconds":0,"average":0})
        for seconds in (2,4,5,10):self.store.save_watch(self.video,seconds)
        stats=self.store.statistics()
        self.assertEqual(stats["skipped"],{"category":"跳过","count":2,"seconds":6,"average":3})
        self.assertEqual(stats["count"],4)
        self.assertEqual(stats["valid_count"],1)
        self.assertEqual(self.store.historical_watch(self.video),(10,"同一视频"))
        self.assertEqual(self.store.historical_watch(replace(self.video,video_id="dy:video:99",title="电脑评测")),(10,"数码科技"))
        self.store.set("threshold",4)
        self.assertEqual(self.store.statistics()["skipped"]["count"],1)
        self.assertEqual(self.store.statistics()["skipped"]["average"],2)
        self.store.set("threshold",2)
        self.assertEqual(self.store.statistics()["skipped"]["count"],0)

    def test_historical_countdown_works_without_progress_and_does_not_save_last_view(self):
        self.store.save_watch(self.video,10)
        self.engine.set_features(auto=True,auto_skip=True)
        snap=replace(self.video,playing=False,timing=False)
        self.engine.update(snap)
        for _ in range(9):self.assertIsNone(self.tick(snap))
        action=self.tick(snap)
        self.assertEqual(action["action"],"next")
        self.assertIn("10.0",action["reason"])
        self.assertEqual(self.store.statistics()["count"],1)
        self.assertEqual(self.store.rules(),[])

    def test_no_history_short_history_and_unclassified_do_not_set_budget(self):
        self.store.save_watch(self.video,5)
        self.engine.set_features(auto=True,auto_skip=True)
        self.engine.update(self.video)
        for _ in range(12):self.assertIsNone(self.tick())
        self.assertIsNone(self.engine.budget)
        self.assertIsNone(self.store.historical_watch(replace(self.video,video_id="dy:video:8",title="无话题标题")))

    def test_exact_video_precedes_category_and_different_known_ids_use_category(self):
        self.store.save_watch(self.video,10)
        self.store.save_watch(replace(self.video,video_id="dy:video:2",title="电脑评测"),20)
        self.assertEqual(self.store.historical_watch(self.video),(10,"同一视频"))
        other=replace(self.video,video_id="dy:video:3")
        self.assertEqual(self.store.historical_watch(other),(15,"数码科技"))
        self.assertEqual(self.store.historical_watch(replace(self.video,video_id="")),(10,"同一视频"))

    def test_switches_pause_and_background_do_not_trigger_or_accumulate(self):
        self.store.save_watch(self.video,10)
        self.engine.set_features(auto_skip=True)
        self.engine.update(self.video)
        for _ in range(11):self.assertIsNone(self.tick())
        self.engine.pause(True)
        seconds=self.store.statistics()["seconds"]
        for _ in range(10):self.tick()
        self.assertEqual(self.store.statistics()["seconds"],seconds)
        self.engine.pause(False);self.engine.set_features(auto=True,auto_skip=False)
        self.engine.update(replace(self.video,playing=False))
        for _ in range(12):self.assertIsNone(self.tick(replace(self.video,playing=False)))
        self.assertEqual(self.store.statistics()["seconds"],seconds)
        self.tick(replace(self.video,active=False))
        self.assertIsNone(self.engine.current)

    def test_budget_survives_learning_toggle_and_cancels_when_skip_disabled(self):
        self.store.save_watch(self.video,10)
        self.engine.set_features(auto=True,auto_skip=True)
        self.engine.update(self.video)
        for _ in range(8):self.tick()
        self.engine.set_features(listen=False)
        self.assertEqual(self.engine.watched,8)
        self.engine.set_features(auto_skip=False)
        for _ in range(4):self.assertIsNone(self.tick())
        with self.assertRaises(ValueError):self.engine.set_features(auto_skip="yes")

    def test_invalid_durations_and_unknown_keywords(self):
        for duration in (0,-1,float('nan'),float('inf')):self.assertIsNone(self.store.save_watch(self.video,duration))
        self.assertEqual(self.store.statistics()["count"],0)
        self.assertEqual(categories("#陶艺 #手作"),["陶艺","手作"])
        self.assertEqual(categories("train railway"),["未分类"])
        self.assertEqual(categories("AI 编程与做饭"),["数码科技","美食"])

    def test_switch_clock_survives_dialog_reset_and_does_not_use_current_view_for_prediction(self):
        self.engine.update(self.video)
        second=replace(self.video,token="second",video_id="dy:video:2")
        self.now=105;self.engine.update(second)
        self.now=110;self.engine.reset(preserve_watch=True)
        self.engine.set_features(auto=True,auto_skip=True)
        self.engine.update(second)
        self.assertIsNone(self.engine.budget)
        self.now=115;self.engine.update(replace(self.video,token="third",video_id="dy:video:3"))
        self.assertEqual(self.store.statistics()["count"],1)
        self.assertEqual(self.store.statistics()["seconds"],10)

    def test_legacy_partial_records_are_preserved_but_excluded(self):
        self.store.db.execute("INSERT INTO watches(video_key,caption_key,author,title,source,seconds) VALUES (?,?,?,?,?,?)",
                              ("dy:video:1","","@作者","手机续航实测 #数码","chrome",30))
        self.store.db.commit()
        self.assertEqual(self.store.statistics()["count"],0)
        self.assertIsNone(self.store.historical_watch(self.video))
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM watches").fetchone()[0],1)

    def test_restart_discards_the_previous_open_visit(self):
        self.engine.update(self.video)
        second=replace(self.video,token="second",video_id="dy:video:2")
        self.now=105;self.engine.update(second)
        self.now=115
        self.engine=Engine(self.store,lambda:self.now);self.engine.pause(False)
        self.engine.update(second)
        self.now=120;self.engine.update(replace(self.video,token="third",video_id="dy:video:3"))
        self.assertEqual(self.store.statistics()["count"],0)

    def test_records_and_preferences_survive_restart(self):
        from pathlib import Path
        import uuid
        import shutil
        root=Path(__file__).resolve().parents[1]/".local"/"statistics-tests"
        folder=root/uuid.uuid4().hex;folder.mkdir(parents=True)
        try:
            path=folder/"history.db"
            store=Store(path);store.save_watch(self.video,10);store.set("auto_skip_enabled",True);store.db.close()
            store=Store(path)
            try:
                self.assertEqual(store.statistics()["valid_average"],10)
                self.assertEqual(store.historical_watch(self.video),(10,"同一视频"))
                self.assertTrue(Engine(store).auto_skip_enabled)
            finally:store.db.close()
        finally:
            assert folder.resolve().is_relative_to(root.resolve())
            shutil.rmtree(folder)

    def test_record_backup_roundtrip_retains_legacy_metadata_and_identical_visits(self):
        for seconds in (3,5,10,10):self.store.save_watch(self.video,seconds)
        self.store.save_watch(replace(self.video,source="desktop",video_id="",title="",author=""),8)
        self.store.db.execute("UPDATE watches SET duration_basis='legacy' WHERE id=1")
        backup=json.loads(json.dumps(self.store.export_watches(),ensure_ascii=False))
        self.assertEqual(len(backup["watches"]),5)
        self.assertNotIn("id",backup["watches"][0])
        restored=Store(":memory:");self.addCleanup(restored.db.close)
        self.assertEqual(restored.import_watches(backup),5)
        self.assertEqual(restored.export_watches(),backup)
        self.assertEqual(restored.statistics(),self.store.statistics())
        self.assertEqual(restored.historical_watch(self.video),self.store.historical_watch(self.video))
        self.assertEqual(restored.import_watches(backup),0)
        self.assertEqual(restored.statistics()["count"],4)
        restored.set("threshold",10)
        self.assertEqual(restored.statistics()["valid_count"],0)

    def test_record_import_merges_existing_visits_and_preserves_repeated_occurrences(self):
        self.store.save_watch(self.video,10)
        backup=self.store.export_watches()
        backup["watches"]*=2
        backup["watches"].append({**backup["watches"][0],"seconds":20})
        self.store.save_watch(replace(self.video,title="旅行风景"),30)
        self.assertEqual(self.store.import_watches(backup),2)
        self.assertEqual(self.store.statistics()["count"],4)
        self.assertEqual(self.store.statistics()["seconds"],70)
        self.assertEqual(self.store.import_watches(backup),0)

    def test_invalid_backups_leave_all_records_unchanged(self):
        self.store.save_watch(self.video,10)
        before=self.store.export_watches()
        good={**before["watches"][0],"seconds":20}
        for data in (None,[],{}, {**before,"format":"other"},{**before,"version":2},
                     {**before,"version":True},{**before,"version":1.0},{**before,"watches":{}}):
            with self.subTest(data=data),self.assertRaises(ValueError):self.store.import_watches(data)
        bad_rows=[None,[],{}, {key:value for key,value in good.items() if key!="caption_key"}]
        bad_rows += [{**good,key:value} for key,value in (
            ("created","bad date"),("created","2026-02-30 12:00:00"),("title",None),("video_key",[]),
            ("source","other"),("duration_basis","progress"),("seconds",True),("seconds","10"),
            ("seconds",None),("seconds",[]),("seconds",0),("seconds",-1),("seconds",float("nan")),
            ("seconds",float("inf")),("seconds",10**400))]
        for row in bad_rows:
            with self.subTest(row=row),self.assertRaisesRegex(ValueError,"第 2 条"):
                self.store.import_watches({**before,"watches":[good,row]})
            self.assertEqual(self.store.export_watches(),before)
        self.assertEqual(self.store.import_watches({**before,"watches":[{**good,"seconds":10**20}]}),1)

    def test_database_failure_rolls_back_the_entire_import(self):
        self.store.save_watch(self.video,10)
        before=deepcopy(self.store.export_watches())
        row=before["watches"][0]
        self.store.db.execute("""CREATE TRIGGER reject_bad_watch BEFORE INSERT ON watches
            WHEN NEW.title='reject' BEGIN SELECT RAISE(ABORT,'test failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.import_watches({**before,"watches":[{**row,"seconds":20},{**row,"title":"reject"}]})
        self.assertEqual(self.store.export_watches(),before)

    def test_reset_clears_all_watch_records_and_preserves_other_data(self):
        self.store.save_watch(self.video,10)
        self.store.save_watch(self.video,20)
        self.store.db.execute("UPDATE watches SET duration_basis='legacy' WHERE id=2")
        self.store.save_filter("作者","","","or")
        self.store.set("threshold",8)
        self.store.log("测试","作者","保留")
        self.store.reserve_call(50)
        rules,history=self.store.rules(),self.store.history()
        self.store.reset_watches()
        self.assertEqual(self.store.export_watches()["watches"],[])
        self.assertEqual(self.store.statistics()["count"],0)
        self.assertEqual(self.store.statistics()["skipped"]["count"],0)
        self.assertIsNone(self.store.historical_watch(self.video))
        self.assertEqual(self.store.rules(),rules)
        self.assertEqual(self.store.history(),history)
        self.assertEqual(self.store.get("threshold"),8)
        self.assertEqual(self.store.calls(),1)
        self.store.save_watch(self.video,15)
        self.assertEqual(self.store.statistics()["seconds"],15)


class DesktopWatchTiming(unittest.TestCase):
    setUp=test_desktop.BoundWindow.setUp
    automatic=test_desktop.BoundWindow.automatic

    def test_metadata_cache_never_reads_progress(self):
        config={**self.automatic("@评测作者\n手机续航实测结果"),"statistics":True}
        first,_,_=self.reader.read(config)
        self.reader.fast_ocr.read_timer.side_effect=AssertionError("progress OCR is not used for statistics")
        for _ in range(5):
            snap,_,_=self.reader.read(config)
            self.assertEqual(snap.key,first.key)
            self.assertFalse(snap.timing)
        self.reader.fast_ocr.read.assert_called_once()
        self.reader.fast_ocr.read_timer.assert_not_called()

    def test_switch_event_clock_includes_ocr_delay_and_handles_same_caption(self):
        store=Store(":memory:");self.addCleanup(store.db.close)
        from autoskip.statistics import WatchTracker
        tracker=WatchTracker(store)
        config={**self.automatic("@评测作者\n手机续航实测结果"),"statistics":True}
        first,_,_=self.reader.read(config)
        tracker.observe(first,100)
        self.assertTrue(tracker.switch(first.source,first.session,105,manual=True))
        self.assertFalse(tracker.switch(first.source,first.session,105.3,manual=True))
        # Parsing finishes 3 seconds later. The start still stays at the input event.
        tracker.observe(first,108)
        self.assertEqual(tracker.elapsed(115),10)
        tracker.switch(first.source,first.session,115,manual=True)
        self.assertEqual(store.statistics()["seconds"],10)
        # Quit while the new video is still open: no extra row.
        tracker.discard()
        self.assertEqual(store.statistics()["count"],1)

    def test_automatic_events_do_not_apply_manual_wheel_debounce(self):
        store=Store(":memory:");self.addCleanup(store.db.close)
        from autoskip.statistics import WatchTracker
        tracker=WatchTracker(store)
        snap=Snapshot("desktop","window","video",author="作者",title="手机数码评测")
        tracker.observe(snap,100);tracker.switch("desktop","window",101)
        tracker.observe(snap,101.1);tracker.switch("desktop","window",101.4)
        self.assertAlmostEqual(store.statistics()["seconds"],.4)
        self.assertEqual(store.statistics()["count"],1)

    def test_switch_without_metadata_still_counts_total_duration(self):
        store=Store(":memory:");self.addCleanup(store.db.close)
        from autoskip.statistics import WatchTracker
        tracker=WatchTracker(store)
        tracker.switch("desktop","window",100)
        tracker.switch("desktop","window",110)
        self.assertEqual(store.statistics()["seconds"],10)
        self.assertEqual(store.statistics()["categories"][0]["category"],"未分类")


if __name__=="__main__":unittest.main()
