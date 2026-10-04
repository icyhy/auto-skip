import io
import json
import struct
import shutil
import uuid
import unittest
import sqlite3
from itertools import product
from dataclasses import replace
from pathlib import Path

from autoskip.store import Store
from autoskip.core import Engine, Snapshot, purchase_evidence, author_name_key, author_name
from autoskip.bridge import read_frame
from autoskip.cloud import validate_url
from autoskip.desktop import parse_times


class Scenarios(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).resolve().parents[1]/".local"/"tests"
        root.mkdir(parents=True,exist_ok=True)
        self.test_dir=root/uuid.uuid4().hex
        self.test_dir.mkdir()
        self.store=Store(self.test_dir/"data.db")
        self.now=100.0
        self.engine=Engine(self.store,lambda:self.now)
        self.engine.pause(False)
        self.first=Snapshot("chrome","tab1","v1","dy:video:1","dy:author:a","评测","作者",active=True,playing=True,timing=True)

    def tearDown(self):
        self.store.db.close()
        root=Path(__file__).resolve().parents[1]/".local"/"tests"
        assert self.test_dir.resolve().is_relative_to(root.resolve())
        shutil.rmtree(self.test_dir)

    def tick(self,snap,seconds=1):
        self.now+=seconds
        return self.engine.update(snap)

    def video_rules(self):
        return [r for r in self.store.rules(enabled=True) if r["kind"]=="video"]

    def test_three_seconds_learns_previous_video_only(self):
        self.engine.update(self.first)
        self.tick(self.first);self.tick(self.first)
        self.tick(replace(self.first,token="v2",video_id="dy:video:2",user_from="v1"))
        rules=self.video_rules()
        self.assertEqual([r["target"] for r in rules],["dy:video:1"])
        self.assertFalse(any(r["kind"]=="author" for r in self.store.rules()))

    def test_learning_requires_departing_author_even_with_video_and_account_ids(self):
        for author in ("", " \t\u200b", "＠ ·"):
            with self.subTest(author=author):
                self.engine.reset()
                snap=replace(self.first,author=author)
                self.engine.update(snap);self.tick(snap)
                self.tick(replace(self.first,token="v2",video_id="dy:video:2",user_from="v1"))
                self.assertEqual(self.video_rules(),[])
                self.assertEqual(self.engine.undo_stack,[])
                self.assertFalse(any(r["action"]=="拉黑" for r in self.store.history()))
        self.engine.reset()
        self.engine.update(self.first);self.tick(self.first)
        self.tick(replace(self.first,token="v2",video_id="dy:video:2",author="",user_from="v1"))
        self.assertEqual([r["target"] for r in self.video_rules()],[self.first.video_id])

    def test_threshold_is_strict_and_configurable(self):
        self.engine.update(self.first)
        for _ in range(4):self.tick(self.first)
        self.tick(replace(self.first,token="v2",user_from="v1"))
        self.assertEqual(self.video_rules(),[])
        self.store.set("threshold",7)
        self.tick(replace(self.first,token="v3",user_from="v2"))
        self.assertEqual(len(self.video_rules()),1)

    def test_background_breaks_learning_continuity(self):
        self.engine.update(self.first)
        self.tick(replace(self.first,active=False))
        self.tick(replace(self.first,token="v2",user_from="v1"))
        self.assertEqual(self.video_rules(),[])

    def test_pause_time_does_not_count(self):
        self.engine.update(self.first)
        self.tick(replace(self.first,playing=False))
        for _ in range(10):self.tick(replace(self.first,playing=False))
        self.assertEqual(self.engine.watched,1)

    def test_comment_scroll_and_platform_switch_do_not_learn(self):
        self.engine.update(self.first);self.tick(self.first)
        self.tick(replace(self.first,token="v2"))
        self.assertEqual(self.video_rules(),[])

    def test_auto_mode_never_learns_user_skip(self):
        self.engine.set_features(listen=False,auto=True);self.engine.update(self.first)
        self.tick(replace(self.first,token="v2",user_from="v1"))
        self.assertEqual(self.video_rules(),[])

    def test_listening_and_auto_can_learn_then_skip_together(self):
        self.engine.set_features(listen=True,auto=True)
        self.engine.update(self.first);self.tick(self.first);self.tick(self.first)
        self.tick(replace(self.first,token="v2",video_id="dy:video:2",user_from="v1"))
        self.assertEqual([r["target"] for r in self.video_rules()],["dy:video:1"])
        action=self.tick(self.first)
        self.assertEqual(action["action"],"next")
        before=len([r for r in self.store.history() if r["action"]=="拉黑"])
        self.tick(replace(self.first,token="v3",video_id="dy:video:3",user_from="v1"))
        self.assertEqual(len([r for r in self.store.history() if r["action"]=="拉黑"]),before)

    def test_listen_toggle_does_not_cancel_automatic_skip(self):
        self.engine.set_features(listen=True,auto=True)
        self.store.add_rule("video",self.first.video_id,"视频","手动")
        self.assertIsNotNone(self.engine.update(self.first))
        pending,epoch=self.engine.pending,self.engine.epoch
        self.engine.set_features(listen=False)
        self.assertTrue(self.engine.auto_enabled)
        self.assertEqual(self.engine.pending,pending)
        self.assertEqual(self.engine.epoch,epoch)
        self.engine.set_features(listen=True)
        self.engine.set_features(auto=False)
        self.assertTrue(self.engine.listen_enabled)
        self.assertIsNone(self.engine.update(self.first))

    def test_both_switches_off_disables_learning_and_automatic_actions(self):
        self.engine.set_features(listen=False,auto=False)
        self.engine.update(self.first);self.tick(self.first)
        self.assertIsNone(self.tick(replace(self.first,token="v2",video_id="dy:video:2",user_from="v1")))
        self.assertEqual(self.video_rules(),[])
        self.store.add_rule("video",self.first.video_id,"视频","手动")
        self.assertIsNone(self.tick(self.first))
        self.assertIsNone(self.engine.cloud_result(self.first.key,{"match":True,"category":"purchase","confidence":.99,"evidence":"购买"}))

    def test_feature_flags_and_old_hotkey_migrate_without_overriding_new_values(self):
        self.store.db.execute("DELETE FROM settings WHERE key IN ('listen_enabled','auto_enabled')")
        self.store.db.commit();self.store.set("mode","auto")
        self.store.set("hotkeys",{"mode":"Ctrl+Shift+F8","pause":"Ctrl+Alt+P"})
        self.store.db.close();self.store=Store(self.test_dir/"data.db")
        self.assertFalse(self.store.get("listen_enabled"));self.assertTrue(self.store.get("auto_enabled"))
        self.assertIsNone(self.store.get("mode"))
        self.assertEqual(self.store.get("hotkeys")["auto"],"Ctrl+Shift+F8")
        self.assertEqual(self.store.get("hotkeys")["listen"],"Ctrl+Alt+L")
        self.assertNotIn("mode",self.store.get("hotkeys"))
        engine=Engine(self.store);engine.set_features(listen=True,auto=True)
        self.store.db.close();self.store=Store(self.test_dir/"data.db")
        restored=Engine(self.store)
        self.assertTrue(restored.listen_enabled and restored.auto_enabled)

    def test_author_rule_and_undo(self):
        self.engine.update(self.first);self.engine.manual_block("author")
        self.assertEqual(self.tick(self.first)["action"],"next")
        self.engine.set_features(listen=False,auto=True)
        self.assertEqual(self.tick(replace(self.first,token="v2",video_id="dy:video:2"))["action"],"next")
        self.engine.undo();self.engine.reset()
        self.assertIsNone(self.tick(replace(self.first,token="v3",video_id="dy:video:3")))

    def test_duplicate_manual_rule_undo_preserves_existing(self):
        self.engine.update(self.first);self.engine.manual_block("author");self.engine.manual_block("author")
        self.engine.undo()
        self.assertTrue(self.engine.match(self.first))

    def test_ambiguous_author_cannot_be_blacklisted(self):
        self.engine.update(replace(self.first,author_id=""))
        with self.assertRaises(ValueError):self.engine.manual_block("author")

    def test_manual_block_requires_author_even_with_reliable_ids(self):
        for source,kind,author in product(("chrome","desktop"),("author","video"),(""," \t\u200b","＠ ·")):
            with self.subTest(source=source,kind=kind,author=author):
                snap=replace(self.first,source=source,author=author)
                self.engine.update(snap)
                with self.assertRaisesRegex(ValueError,"未能识别作者"):
                    self.engine.manual_block(kind)
                self.assertEqual(self.store.rules(),[])
                self.assertEqual(self.engine.undo_stack,[])
                self.assertIsNone(self.engine.manual)
                self.assertIsNone(self.tick(snap))
                self.assertFalse(any(r["action"]=="拉黑" for r in self.store.history()))

    def test_remember_without_author_does_not_reenable_disabled_rule(self):
        rule=self.store.add_rule("video",self.first.video_id,self.first.title,"手动")
        self.store.enable(rule["id"],False)
        with self.assertRaisesRegex(ValueError,"未能识别作者"):
            self.engine.remember("video",self.first.video_id,self.first.title,"手动",author="")
        self.assertFalse(self.store.rules(enabled=True))
        self.assertEqual(self.engine.undo_stack,[])
        self.assertFalse(any(r["action"]=="拉黑" for r in self.store.history()))

    def test_named_author_matches_desktop_ocr_without_account_id(self):
        self.engine.remember("author","dy:author:self","@红衣大叔周鸿祎","手动拉黑",author="@红衣大叔周鸿祎")
        snap=replace(self.first,source="desktop",author_id="",author="＠红衣大叔周 鸿 祎 。 3 小 时 前",title="另一个视频")
        self.engine.set_features(listen=False,auto=True)
        action=self.tick(snap)
        self.assertIsNotNone(action)
        self.assertIn("作者黑名单",action["reason"])
        self.assertIsNone(self.tick(snap))

    def test_author_name_does_not_match_typo_prefix_or_unrelated_mention(self):
        self.engine.remember("author","dy:author:self","@红衣大叔周鸿祎","手动拉黑",author="@红衣大叔周鸿祎")
        for name in ["@红衣大叔周鸿帏","@红衣大叔周鸿祎讲解","@其他作者",""]:
            self.assertFalse(self.engine.match(replace(self.first,author_id="",author=name,text="提到@红衣大叔周鸿祎")))

    def test_valid_account_ids_take_priority_over_same_nickname(self):
        self.engine.remember("author","dy:author:MS4_one","@同名作者","手动",author="@同名作者")
        self.assertFalse(self.engine.match(replace(self.first,author="@同名作者",author_id="dy:author:MS4_two")))
        self.assertTrue(self.engine.match(replace(self.first,author="@同名作者",author_id="")))

    def test_manual_author_without_id_creates_name_rule(self):
        self.engine.update(replace(self.first,author="@红衣大叔周鸿祎",author_id=""))
        self.engine.manual_block("author")
        self.assertTrue(any(r["target"]==author_name_key("红衣大叔周鸿祎") for r in self.store.rules()))

    def test_author_normalization_preserves_real_name_punctuation(self):
        self.assertEqual(author_name("＠红衣大叔周 鸿 祎 。 3 小 时 前"),"红衣大叔周鸿祎")
        self.assertEqual(author_name("@红衣·大叔（主页）"),"红衣·大叔")

    def test_existing_self_rule_is_repaired_on_upgrade(self):
        self.store.db.execute("INSERT INTO rules(kind,target,label,reason,enabled) VALUES (?,?,?,?,?)",
                              ("author","dy:author:self","@红衣大叔周鸿祎","手动拉黑",1))
        self.store.db.commit();self.store.db.close();self.store=Store(self.test_dir/"data.db")
        rule=next(r for r in self.store.rules() if r["kind"]=="author")
        self.assertEqual(rule["target"],author_name_key("红衣大叔周鸿祎"))
        self.assertEqual(rule["enabled"],1)
        self.store.repair_author_rules()
        self.assertEqual(len([r for r in self.store.rules() if r["kind"]=="author"]),1)

    def test_repair_does_not_reenable_explicitly_disabled_duplicate(self):
        self.store.add_rule("author",author_name_key("@红衣大叔周鸿祎"),"@红衣大叔周鸿祎","手动")
        row=next(r for r in self.store.rules() if r["kind"]=="author")
        self.store.enable(row["id"],False)
        self.store.db.execute("INSERT INTO rules(kind,target,label,reason) VALUES (?,?,?,?)",
            ("author","dy:author:self","@红衣大叔周鸿祎","旧记录"))
        self.store.db.commit();self.store.repair_author_rules()
        self.assertFalse(any(r["kind"]=="author" for r in self.store.rules(enabled=True)))

    def test_only_one_end_action_and_stop_on_failure(self):
        self.engine.set_features(listen=False,auto=True)
        snap=replace(self.first,ended=True,playing=False)
        self.assertIsNotNone(self.tick(snap))
        for _ in range(4):self.assertIsNone(self.tick(snap))
        self.assertTrue(self.engine.paused)

    def test_unknown_timing_never_triggers_end(self):
        self.engine.set_features(listen=False,auto=True)
        self.assertIsNone(self.tick(replace(self.first,ended=True,timing=False)))

    def test_late_cloud_response_cannot_skip_next_or_resumed_session(self):
        self.engine.set_features(listen=False,auto=True);self.engine.update(self.first);epoch=self.engine.epoch
        result={"match":True,"category":"purchase","confidence":0.98,"evidence":"点击链接购买"}
        self.tick(replace(self.first,token="v2"))
        self.assertIsNone(self.engine.cloud_result(self.first.key,result,epoch))
        self.engine.pause(True);self.engine.pause(False);self.engine.update(self.first)
        self.assertIsNone(self.engine.cloud_result(self.first.key,result,epoch))
        self.assertIsNone(self.engine.cloud_result(self.first.key,result,self.engine.epoch))

    def test_filter_or_and_truth_table(self):
        for condition in ("or","and"):
            change=self.store.save_filter("@评测作者","手机","https://www.douyin.com/video/123",condition)
            for author_hit,keyword_hit,link_hit in product((False,True),repeat=3):
                snap=replace(self.first,author="评测作者" if author_hit else "另一个作者",
                    title="这款手机实测" if keyword_hit else "风景记录",video_id="dy:video:123" if link_hit else "dy:video:456")
                expected=all((author_hit,keyword_hit,link_hit)) if condition=="and" else any((author_hit,keyword_hit,link_hit))
                with self.subTest(condition=condition,hits=(author_hit,keyword_hit,link_hit)):
                    self.assertEqual(bool(self.engine.match(snap)),expected)
            self.store.undo(change)

    def test_optional_fields_and_missing_observations_do_not_match(self):
        for values,snap in [
            (("评测作者","",""),replace(self.first,author="@评测作者")),
            (("","手机",""),replace(self.first,text="字幕：手 机评测")),
            (("","","https://example.com/item/123"),replace(self.first,links="https://example.com/item/123"))]:
            change=self.store.save_filter(*values,"or")
            self.assertTrue(self.engine.match(snap))
            self.assertFalse(self.engine.match(replace(snap,author="",author_id="",title="",text="",links="",video_id="")))
            self.store.undo(change)
        self.store.save_filter("评测作者","手机","https://example.com/item/123","and")
        self.assertFalse(self.engine.match(replace(self.first,author="评测作者",title="手机",video_id="",links="")))

    def test_filter_validation(self):
        invalid=[("","","","or"),("@","","","or"),("作者","关键词","","and"),
                 ("作者","","https://example.com","and"),("","关键词","https://example.com","and"),
                 ("作者","","","bad"),("","","javascript:alert(1)","or"),
                 ("","","https://[bad","or"),("x"*2001,"","","or")]
        for args in invalid:
            with self.subTest(args=args),self.assertRaises(ValueError):self.store.save_filter(*args)
        self.assertEqual(self.store.rules(),[])

    def test_filter_complete_author_keyword_text_and_exact_link(self):
        self.store.save_filter("＠红衣大叔周鸿祎","ＩＰＨＯＮＥ 实测","https://example.com/item/123","and")
        snap=replace(self.first,author="@红衣大叔周 鸿 祎 · 3小时前",text="iPhone实测\n链接 https://example.com/item/123。")
        self.assertTrue(self.engine.match(snap))
        self.assertFalse(self.engine.match(replace(snap,author="红衣大叔周鸿祎讲解")))
        self.assertFalse(self.engine.match(replace(snap,text=snap.text.replace("/123","/1234"))))
        self.assertFalse(self.engine.match(replace(snap,text="iPhone实测\nhttps://[invalid")))

    def test_filter_edit_disable_restart_and_duplicate_undo(self):
        change=self.store.save_filter("","广告","","or")
        duplicate=self.store.save_filter("","广告","","or")
        self.store.undo(duplicate)
        self.assertEqual(len(self.store.rules()),1)
        self.store.enable(change["id"],False)
        self.store.save_filter("作者","评测","https://www.douyin.com/video/1?from=share","and",change["id"])
        self.assertFalse(self.engine.match(self.first))
        self.store.db.close();self.store=Store(self.test_dir/"data.db");self.engine=Engine(self.store)
        rule=self.store.rules()[0]
        self.assertEqual((rule["condition"],rule["enabled"]),("and",0))
        self.store.enable(rule["id"],True)
        self.assertTrue(self.engine.match(self.first))
        self.store.delete(rule["id"]);self.assertFalse(self.engine.match(self.first))

    def test_old_database_migrates_without_categories_or_losing_exact_identities(self):
        old_path=self.test_dir/"old.db"
        with sqlite3.connect(old_path) as db:
            db.executescript("""CREATE TABLE rules (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, target TEXT NOT NULL,
                label TEXT NOT NULL, reason TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
                created TEXT NOT NULL DEFAULT (datetime('now')), UNIQUE(kind,target));
                INSERT INTO rules(kind,target,label,reason) VALUES ('category','purchase','购买引导','旧类别');
                INSERT INTO rules(kind,target,label,reason) VALUES ('author','dy:author:a','作者','旧作者');
                INSERT INTO rules(kind,target,label,reason,enabled) VALUES ('video','dy:video:1','评测','旧视频',0);
            """)
        db.close()
        for _ in range(2):
            store=Store(old_path)
            try:
                rules=store.rules();self.assertEqual(len(rules),2)
                self.assertEqual(rules[0]["link"],"https://www.douyin.com/video/1")
                self.assertEqual(rules[0]["enabled"],0)
                engine=Engine(store);self.assertTrue(engine.match(self.first))
                self.assertFalse(engine.match(replace(self.first,author_id="dy:author:other")))
                self.assertFalse(engine.match(replace(self.first,author_id="",author="其他作者",purchase="立即购买")))
                with self.assertRaises(ValueError):store.add_rule("category","new","新类别","测试")
            finally:store.db.close()

    def test_cloud_cannot_create_categories_or_use_nan(self):
        self.engine.set_features(listen=False,auto=True);self.engine.update(self.first)
        for result in [
            {"match":True,"category":"new","confidence":1,"evidence":"anything"},
            {"match":True,"category":"purchase","confidence":float("nan"),"evidence":"anything"},
            {"match":True,"category":"purchase","confidence":0.89,"evidence":"anything"},
            {"match":True,"category":"purchase","confidence":0.99,"evidence":""}]:
            self.assertIsNone(self.engine.cloud_result(self.first.key,result))

    def test_daily_limit_and_data_survive_restart(self):
        self.assertTrue(self.store.reserve_call(1));self.assertFalse(self.store.reserve_call(1))
        self.engine.remember("video","dy:video:1","title","manual",author=self.first.author)
        self.store.db.close();self.store=Store(self.test_dir/"data.db")
        self.assertEqual(self.store.calls(),1)
        self.assertTrue(any(r["target"]=="dy:video:1" for r in self.store.rules()))

    def test_marketing_counterexamples(self):
        self.assertTrue(purchase_evidence("点击小黄车立即下单"))
        for text in ["售价 5999 元，续航测试", "不要点击链接购买", "警惕小黄车骗局", "商城", "这款手机值得购买吗？"]:
            self.assertEqual(purchase_evidence(text),"")

    def test_native_message_bounds_and_partial_reads(self):
        raw=json.dumps({"type":"snapshot"}).encode()
        class Partial(io.BytesIO):
            def read(self,n):return super().read(min(n,2))
        self.assertEqual(read_frame(Partial(struct.pack("<I",len(raw))+raw)),raw)
        with self.assertRaises(ValueError):read_frame(io.BytesIO(struct.pack("<I",1000001)))
        with self.assertRaises(EOFError):read_frame(io.BytesIO(b"\x04\x00"))

    def test_endpoint_validation(self):
        self.assertEqual(validate_url("https://api.deepseek.com/"),"https://api.deepseek.com")
        for url in ["http://host", "https://user:secret@host", "https://host/?key=secret"]:
            with self.assertRaises(ValueError):validate_url(url)

    def test_native_progress_parser(self):
        self.assertEqual(parse_times("00:08 / 02:10"),(8,130))
        self.assertIsNone(parse_times("00:80 / 01:00"))
        self.assertIsNone(parse_times("视频播放中"))

    def test_old_calibration_migrates_once_preserving_rules(self):
        self.store.add_rule("author","dy:author:test","作者","手动")
        self.store.set("source","desktop")
        self.store.set("desktop_roi",[0.1,0.1,0.9,0.9])
        self.store.set("automatic_window_v1",False)
        self.store.db.close();self.store=Store(self.test_dir/"data.db")
        self.assertEqual(self.store.get("source"),"auto")
        self.assertIsNone(self.store.get("desktop_roi"))
        self.assertTrue(any(r["target"]=="dy:author:test" for r in self.store.rules()))
        self.store.set("source","chrome")
        self.store.db.close();self.store=Store(self.test_dir/"data.db")
        self.assertEqual(self.store.get("source"),"chrome")


if __name__ == "__main__":unittest.main()
