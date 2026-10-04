import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image
from autoskip.desktop import DesktopReader, caption_fields, parse_times
from autoskip.windows import WindowBinding, next_video


class BoundWindow(unittest.TestCase):
    def setUp(self):
        self.target=(123,456,789)
        self.input=SimpleNamespace(hwnd=0,region=None,last_next=0.0)
        self.reader=DesktopReader(self.input)
        self.reader.capture=Mock()
        self.image=Image.new("RGB",(900,600),"blue")
        self.reader.capture.snapshot.side_effect=lambda hwnd:(self.image.copy(),time.monotonic())
        self.reader.ocr=lambda image:([[[],line,0.99] for line in ["首页","搜索","@评测作者 · 9月22日","手机续航实测结果","00:08 / 02:10"]],None)
        self.config={"desktop_target":self.target}
        self.patches=[]
        for target,kwargs in [
            ("autoskip.windows.valid_target",{"side_effect":lambda t:t==self.target}),
            ("autoskip.windows.foreground",{"return_value":999}),
            ("autoskip.windows.user32.IsIconic",{"return_value":False}),
            ("autoskip.windows.user32.IsWindowVisible",{"return_value":True}),
            ("autoskip.windows.client_rect",{"return_value":(0,30,900,630)}),
            ("autoskip.desktop.read_controls",{"return_value":[]}),
        ]:
            patcher=patch(target,**kwargs);self.patches.append(patcher.start());self.addCleanup(patcher.stop)
        self.valid,self.foreground,self.minimized,self.visible,self.client,self.controls=self.patches

    def test_background_whole_window_without_player_controls(self):
        snap,image,note=self.reader.read(self.config)
        self.assertTrue(self.reader.capture.snapshot.called)
        self.assertTrue(all(call.args==(123,) for call in self.reader.capture.snapshot.call_args_list))
        self.assertTrue(snap.active)
        self.assertEqual(snap.session,"123:456:789")
        self.assertEqual(snap.author,"@评测作者")
        self.assertEqual(snap.title,"手机续航实测结果")
        self.assertTrue(snap.timing)
        self.assertTrue(image.startswith(b"\xff\xd8"))
        self.assertIn("整窗识别",note)
        self.assertIn("首页",snap.text)

    def test_listen_mode_keeps_frames_without_running_uia_or_ocr(self):
        self.reader.ocr=Mock(side_effect=AssertionError('OCR must be gated by short input intervals'))
        for _ in range(3):
            snap,image,note=self.reader.read({**self.config,"mode":"listen","threshold":4})
            self.assertIsNone(snap);self.assertIsNone(image);self.assertIn('小于 4 秒',note)
        self.reader.ocr.assert_not_called();self.controls.assert_not_called()
        self.reader.capture.snapshot.assert_called_with(123)

    def test_auto_mode_uses_fast_whole_window_ocr_without_uia(self):
        self.reader.fast_ocr=Mock(backend="Windows OCR",last_ms=100)
        self.reader.fast_ocr.read.return_value="@评测作者\n手机续航实测结果\n00:08 / 02:10"
        self.reader.fast_ocr.verify_author.side_effect=lambda image,author,names:author
        self.reader.ocr=Mock(side_effect=AssertionError("slow OCR is not the automatic path"))
        snap,_,_=self.reader.read({**self.config,"mode":"auto"})
        self.assertEqual(snap.author,"@评测作者")
        self.reader.fast_ocr.read.assert_called_once()
        self.reader.ocr.assert_not_called();self.controls.assert_not_called()

    def test_automatic_ocr_extracts_links_and_video_identity(self):
        config=self.automatic("@评测作者\n手机续航实测结果\nhttps://www.douyin.com/video/123456\nhttps://example.com/item/42")
        snap,_,_=self.reader.read(config)
        self.assertEqual(snap.video_id,"dy:video:123456")
        self.assertIn("https://example.com/item/42",snap.links)

    def exclusions(self,span=100):
        return {"player_type":"抖音桌面版 Windows","player_profiles":[
            {"name":"抖音桌面版 Windows","regions":[{"direction":"bottom","span":span}]}]}

    def test_excluded_toolbar_never_reaches_auto_ocr_author_verification_or_jpeg(self):
        self.image.paste("red",(0,500,900,600))
        config={**self.automatic(),**self.exclusions()}
        def recognize(image):
            self.assertEqual(image.size,(900,500))
            self.assertEqual(image.getpixel((450,499)),(0,0,255))
            return "@评测作者\n手机续航实测结果"
        self.reader.fast_ocr.read.side_effect=recognize
        snap,jpeg,_=self.reader.read(config)
        self.assertNotIn("下一章",snap.text)
        self.assertEqual(self.reader.fast_ocr.verify_author.call_args.args[0].size,(900,500))
        import io
        self.assertEqual(Image.open(io.BytesIO(jpeg)).size,(900,500))
        # Saving a changed margin must not keep an earlier video's cached OCR.
        self.reader.fast_ocr.read.side_effect=None
        self.reader.read({**config,**self.exclusions(80)})
        self.assertEqual(self.reader.fast_ocr.read.call_count,2)
        self.assertEqual(self.reader.fast_ocr.read.call_args.args[0].size,(900,520))

    def test_manual_ocr_and_uia_cannot_reintroduce_excluded_toolbar(self):
        self.reader.ocr=Mock(return_value=([[[],"@作者",.99],[[],"测试视频标题",.99]],None))
        self.controls.return_value=[{"name":"下一章","link":"","editing":False,"kind":"Text","rect":(0,500,900,600)},
            {"name":"视频正文","link":"","editing":False,"kind":"Text","rect":(0,100,900,150)}]
        with patch("autoskip.windows.rect",return_value=(0,0,900,600)):
            snap,_,_=self.reader.read({**self.config,**self.exclusions()})
        self.assertEqual(self.reader.ocr.call_args.args[0].shape,(500,900,3))
        self.assertNotIn("下一章",snap.text)
        self.assertIn("视频正文",snap.text)

    def test_overlarge_exclusions_stop_before_ocr(self):
        self.reader.ocr=Mock()
        with self.assertRaisesRegex(ValueError,"覆盖"):
            self.reader.read({**self.config,**self.exclusions(600)})
        self.reader.ocr.assert_not_called()

    def automatic(self,text="@评测作者\n手机续航实测结果\n00:08 / 02:10"):
        self.reader.fast_ocr=Mock(backend="Windows OCR",last_ms=100)
        self.reader.fast_ocr.read.return_value=text
        self.reader.fast_ocr.verify_author.side_effect=lambda image,author,names:author
        return {**self.config,"mode":"auto"}

    def test_playing_frames_reuse_author_without_ocr_or_playback_predictions(self):
        config=self.automatic()
        first,jpeg,_=self.reader.read(config)
        for color in ["red","green","white","black"]*10:
            self.image=Image.new("RGB",(900,600),color)
            snap,other,note=self.reader.read(config)
            self.assertEqual(snap.key,first.key)
            self.assertEqual(other,jpeg)
            self.assertFalse(snap.playing or snap.timing or snap.ended)
            self.assertIn("等待视频切换",note)
        self.reader.fast_ocr.read.assert_called_once()
        self.reader.fast_ocr.verify_author.assert_called_once()
        self.controls.assert_not_called()
        self.assertEqual(self.reader.capture.snapshot.call_count,41)

    def test_no_author_retries_then_stops_even_without_title(self):
        config=self.automatic("画面暂时没有作者")
        self.assertFalse(self.reader.read(config)[0].author)
        self.reader.fast_ocr.read.return_value="@新作者"
        self.assertEqual(self.reader.read(config)[0].author,"@新作者")
        self.reader.read(config)
        self.assertEqual(self.reader.fast_ocr.read.call_count,2)

    def test_reparse_replaces_cached_author_once_using_manual_ocr(self):
        config={**self.automatic("@错误作者\n手机续航实测结果"),**self.exclusions()}
        first,_,_=self.reader.read(config)
        self.reader.ocr=Mock(return_value=([[[],"@正确作者",.99],[[],"手机续航实测结果",.99]],None))
        corrected,_,_=self.reader.read({**config,"mode":"reparse"})
        self.assertEqual(corrected.author,"@正确作者")
        self.assertNotEqual(corrected.token,first.token)
        self.assertFalse(corrected.user_from or corrected.timing or corrected.ended)
        self.assertEqual(self.reader.ocr.call_args.args[0].shape,(500,900,3))
        for _ in range(3):
            self.assertEqual(self.reader.read(config)[0].author,"@正确作者")
        self.reader.ocr.assert_called_once()
        self.reader.fast_ocr.read.assert_called_once()
        self.controls.assert_not_called()

    def test_failed_reparse_keeps_previous_author_cache_and_allows_retry(self):
        config=self.automatic()
        first,_,_=self.reader.read(config)
        self.reader.ocr=Mock(return_value=([],None))
        self.assertFalse(self.reader.read({**config,"mode":"reparse"})[0].author)
        self.assertEqual(self.reader.read(config)[0].key,first.key)
        self.reader.ocr.return_value=([[[],"@修正作者",.99]],None)
        self.assertEqual(self.reader.read({**config,"mode":"reparse"})[0].author,"@修正作者")
        self.assertEqual(self.reader.read(config)[0].author,"@修正作者")
        self.assertEqual(self.reader.ocr.call_count,2)

    def test_manual_switch_discards_old_frame_and_recognizes_same_author_new_video(self):
        config=self.automatic()
        first,_,_=self.reader.read(config)
        self.input.last_next=time.monotonic()
        # Navigation can precede the actual frame transition. Do not latch it.
        snap,_,_=self.reader.read(config)
        self.assertIsNone(snap)
        self.reader.fast_ocr.read.return_value="@评测作者\n同作者的另一个视频"
        second,_,_=self.reader.read(config)
        self.assertNotEqual(second.token,first.token)
        self.reader.read(config)
        self.assertEqual(self.reader.fast_ocr.read.call_count,3)

    def test_automatic_switch_waits_for_new_video_without_locking_departing_author(self):
        config=self.automatic()
        first,_,_=self.reader.read(config)
        config.update(video_switch_at=time.monotonic()-2,pending_token=first.token)
        for _ in range(2):
            self.assertEqual(self.reader.read(config)[0].key,first.key)
            self.assertIsNone(self.reader.cached)
        self.reader.fast_ocr.read.return_value="@下一位作者\n下一条视频的标题"
        following,_,_=self.reader.read(config)
        self.assertEqual(following.author,"@下一位作者")
        config["pending_token"]=""
        self.reader.read(config)
        self.assertEqual(self.reader.fast_ocr.read.call_count,4)

    def test_lost_window_frames_clear_cached_author_before_recovery(self):
        config=self.automatic()
        self.reader.read(config)
        self.reader.capture.snapshot.side_effect=ValueError("No new frame")
        with self.assertRaises(ValueError):self.reader.read(config)
        self.reader.capture.snapshot.side_effect=lambda hwnd:(self.image.copy(),time.monotonic())
        self.reader.fast_ocr.read.return_value="@恢复后的作者\n恢复后的新视频"
        self.assertEqual(self.reader.read(config)[0].author,"@恢复后的作者")
        self.reader.fast_ocr.read.assert_called()
        self.assertEqual(self.reader.fast_ocr.read.call_count,2)
        self.minimized.return_value=True
        self.input.last_next=time.monotonic()
        last_input=self.input.last_next
        self.assertIsNone(self.reader.read(config)[0])
        self.assertIsNone(self.reader.cached)
        self.assertEqual(self.input.last_next,last_input)
        self.minimized.return_value=False
        self.reader.read(config)
        self.assertEqual(self.reader.fast_ocr.read.call_count,3)

    def test_focus_changes_keep_bound_target_and_continuity(self):
        first,_,_=self.reader.read(self.config)
        self.foreground.return_value=888
        second,_,_=self.reader.read(self.config)
        self.assertEqual(first.key,second.key)
        self.assertEqual(self.input.hwnd,123)
        self.assertEqual(self.reader.capture.close.call_count,1)

    def test_minimize_keeps_binding_but_stops_capture(self):
        self.minimized.return_value=True
        snap,image,note=self.reader.read(self.config)
        self.assertIsNone(snap);self.assertIsNone(image)
        self.reader.capture.snapshot.assert_not_called()
        self.assertIn("最小化",note)

    def test_reused_handle_discards_result(self):
        self.valid.side_effect=[True,False]
        snap,image,note=self.reader.read(self.config)
        self.assertIsNone(snap);self.assertIsNone(image)
        self.assertIn("关闭",note)

    def test_typing_in_other_app_does_not_pause_reader(self):
        self.controls.return_value=[{"name":"输入框","editing":True,"link":"","kind":"Edit"}]
        self.assertIsNotNone(self.reader.read(self.config)[0])
        self.foreground.return_value=123
        self.assertIsNone(self.reader.read(self.config)[0])

    def test_blank_metadata_does_not_gate_whole_window_analysis(self):
        self.reader.ocr=lambda image:([],None)
        snap,image,_=self.reader.read(self.config)
        self.assertTrue(snap.active)
        self.assertTrue(image)
        self.assertFalse(snap.author_id)

    def test_navigation_text_does_not_enter_caption_identity(self):
        self.assertEqual(caption_fields("首页\n搜索\n@作者\n客观数码评测标题\n合集 · 数码\n发送"),("@作者","客观数码评测标题"))

    def test_self_and_unrelated_profile_links_never_become_author_id(self):
        self.controls.return_value=[{"kind":"Hyperlink","name":"我的","link":"https://www.douyin.com/user/self","editing":False},
            {"kind":"Hyperlink","name":"@其他作者","link":"https://www.douyin.com/user/MS4_other","editing":False}]
        snap,_,_=self.reader.read(self.config)
        self.assertEqual(snap.author_id,"")
        self.controls.return_value.append({"kind":"Hyperlink","name":"@评测作者","link":"https://www.douyin.com/user/MS4_actual","editing":False})
        snap,_,_=self.reader.read(self.config)
        self.assertEqual(snap.author_id,"dy:author:MS4_actual")

    def test_windows_ocr_spaced_timer_is_not_part_of_video_identity(self):
        self.assertEqual(parse_times("00 ： 08 / 02 ： 10"),(8,130))
        self.assertEqual(caption_fields("·@作者\n客观数码评测标题\n00 ： 08 / 02 ： 10"),("@作者","客观数码评测标题"))


class WindowBindingChecks(unittest.TestCase):
    def test_discovery_reuses_binding_and_rebinds_closed_window(self):
        binding=WindowBinding()
        def bind(hwnd):binding.target=(hwnd,10,20);binding.title="抖音"
        with patch("autoskip.windows.windows",return_value=[(123,"抖音")]) as discover,patch.object(binding,"bind",side_effect=bind),patch("autoskip.windows.valid_target",side_effect=lambda t:t is not None):
            self.assertEqual(binding.discover(),(123,10,20))
            binding.discover();discover.assert_called_once()
        with patch("autoskip.windows.valid_target",return_value=False),patch("autoskip.windows.windows",return_value=[]):
            self.assertIsNone(binding.discover())

    def test_multiple_windows_wait_for_user_click(self):
        with patch("autoskip.windows.windows",return_value=[(123,"抖音"),(456,"抖音")]):
            self.assertIsNone(WindowBinding().discover())

    def test_background_next_uses_targeted_messages_only(self):
        target=(123,456,789)
        with patch("autoskip.windows.valid_target",return_value=True),patch("autoskip.windows.user32.IsIconic",return_value=False),patch("autoskip.windows.message_target",return_value=124),patch("autoskip.windows.client_rect",return_value=(-1920,0,-920,800)),patch("autoskip.windows.user32.PostMessageW",return_value=1) as post,patch("autoskip.windows.foreground",side_effect=AssertionError("must not require foreground")):
            self.assertTrue(next_video(target))
            post.assert_called_once_with(124,0x20A,(-120&0xffff)<<16,(-1420&0xffff)|(400<<16))

    def test_invalid_handle_never_receives_messages(self):
        with patch("autoskip.windows.valid_target",return_value=False),patch("autoskip.windows.user32.PostMessageW") as post:
            self.assertFalse(next_video((123,456,789)));post.assert_not_called()


if __name__=="__main__":unittest.main()
