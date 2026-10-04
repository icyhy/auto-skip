import unittest
from unittest.mock import Mock, patch

import numpy as np
from autoskip.capture import WindowCapture
from autoskip.core import caption_key
from autoskip.learning import QuickSkip, ScreenshotAnalyzer, SkipEvent, qualifies
from autoskip.windows import UserInput, input_time


class FastLearning(unittest.TestCase):
    def setUp(self):
        self.capture=WindowCapture();self.capture.hwnd=123
        self.output=[]
        self.gate=QuickSkip(self.capture.freeze,lambda event,text:self.output.append((event,text)))
        self.gate.configure((123,456,789),True,5)
        self.input=UserInput();self.input.hwnd=123
        self.input.on_navigation=self.gate.navigation;self.input.on_drag_start=self.gate.drag_frame
        self.frame(99.9,10)

    def frame(self,at,value):
        image=np.full((20,20,3),value,dtype=np.uint8);image.flags.writeable=False
        self.capture.frame=(image,at)

    def wheel(self,at):self.input.mouse_event("wheel",123,10,10,at,delta=-120)

    def test_freezes_previous_video_before_slow_ocr_then_matches_again(self):
        self.wheel(100);self.assertEqual(self.output,[])
        self.frame(102.9,20);self.wheel(103)
        event,_=self.output[-1]
        self.assertEqual(event.elapsed,3)
        self.frame(103.1,30)  # The user has already moved to the next video.
        analyzer=ScreenshotAnalyzer()
        analyzer.ocr=lambda image:([[[],s,0.99] for s in ["@旧作者" if image[0,0,0]==20 else "@新作者","划走前的视频标题","合集"]],None)
        result=analyzer.analyze(event)
        self.assertEqual(result["author"],"@旧作者")
        self.assertEqual(result["target"],caption_key("@旧作者","划走前的视频标题"))
        self.assertNotEqual(result["target"],caption_key("@新作者","划走前的视频标题"))

    def test_threshold_uses_event_interval_and_is_strict(self):
        self.wheel(100);self.frame(104.9,20);self.wheel(105)
        self.assertEqual(self.output,[])
        self.frame(108.9,30);self.wheel(109)
        self.assertEqual(self.output[-1][0].elapsed,4)

    def test_frozen_learning_frame_excludes_toolbar_without_mutating_capture(self):
        pixels=np.zeros((200,300,3),dtype=np.uint8);pixels[100:]=255;pixels.flags.writeable=False
        event=SkipEvent((123,456,789),100,3,"wheel",(pixels,99.9))
        analyzer=ScreenshotAnalyzer()
        def recognize(image):
            self.assertEqual(image.shape,(100,300,3))
            self.assertFalse(image.any())
            return ([[[],"@旧作者",.99],[[],"真实的视频标题",.99]],None)
        analyzer.ocr=Mock(side_effect=recognize)
        config={"player_type":"抖音","player_profiles":[{"name":"抖音","regions":[{"direction":"bottom","span":100}]}]}
        result=analyzer.analyze(event,config)
        self.assertEqual(result["title"],"真实的视频标题")
        self.assertTrue((pixels[100:]==255).all())
        self.assertFalse(pixels.flags.writeable)

    def test_long_view_never_freezes_or_enqueues_including_trailing_wheel(self):
        self.wheel(100)
        self.gate.freeze=Mock()
        self.wheel(110)
        self.wheel(110.3)  # Reproduces the old 250 ms debounce allowing a false short view.
        self.wheel(110.65)
        self.assertEqual(self.output,[])
        self.gate.freeze.assert_not_called()
        self.assertEqual(self.gate.previous,110)

    def test_four_second_setting_blocks_equal_and_longer_durations_before_capture(self):
        self.gate.configure((123,456,789),True,4)
        self.wheel(100)
        self.gate.freeze=Mock()
        self.wheel(104);self.wheel(110);self.wheel(114.1)
        self.gate.freeze.assert_not_called()
        self.assertEqual(self.output,[])

    def test_cross_device_duplicate_does_not_restart_clock(self):
        self.wheel(100);self.wheel(110)
        self.input.key_event(True,123,110.4)
        self.assertEqual(self.gate.previous,110)
        self.assertEqual(self.output,[])

    def test_parser_refuses_ineligible_event_without_constructing_ocr(self):
        analyzer=ScreenshotAnalyzer()
        for elapsed in [4,5,30,float('nan'),float('inf')]:
            event=SkipEvent((123,456,789),100,elapsed,"key",self.capture.frame,4)
            with self.assertRaises(ValueError):analyzer.analyze(event)
        self.assertIsNone(analyzer.ocr)

    def test_lowered_threshold_cancels_queued_event_but_increase_cannot_requalify(self):
        event=SkipEvent((123,456,789),100,4.5,"key",self.capture.frame,5)
        self.assertTrue(qualifies(event))
        self.gate.configure((123,456,789),True,4)
        self.assertFalse(self.gate.qualifies(event))
        event=SkipEvent((123,456,789),100,4.5,"key",self.capture.frame,4)
        self.assertFalse(qualifies(event,5))

    def test_delayed_callbacks_use_original_windows_input_times(self):
        with patch('autoskip.windows._input_clock_offset',None),patch('autoskip.windows.kernel32.GetTickCount64',return_value=20000),patch('autoskip.windows.time.monotonic',return_value=120):
            first=input_time(10000);second=input_time(16000)
        self.assertEqual(second-first,6)
        self.gate.freeze=Mock()
        self.gate.navigation("key",first);self.gate.navigation("key",second)
        self.gate.freeze.assert_not_called()
        with patch('autoskip.windows._input_clock_offset',None),patch('autoskip.windows.kernel32.GetTickCount64',return_value=2**32+250),patch('autoskip.windows.time.monotonic',return_value=120):
            self.assertAlmostEqual(input_time(2**32-750),119)

    def test_exact_threshold_is_not_rounded_down_by_float_subtraction(self):
        self.gate.configure((123,456,789),True,4)
        self.wheel(100.1);self.gate.freeze=Mock()
        self.wheel(104.1)
        self.gate.freeze.assert_not_called();self.assertEqual(self.output,[])

    def test_long_view_does_not_retain_drag_frame(self):
        self.wheel(100);self.gate.freeze=Mock()
        self.input.mouse_event("down",123,100,300,110)
        self.input.mouse_event("move",123,100,200,110.3)
        self.gate.freeze.assert_not_called();self.assertEqual(self.output,[])

    def test_wheel_burst_is_one_action(self):
        self.wheel(100);self.wheel(100.05);self.wheel(100.1)
        self.assertEqual(self.output,[])
        self.frame(101.9,20);self.wheel(102);self.wheel(102.05)
        self.assertEqual(len(self.output),1)
        self.assertEqual(self.output[0][0].elapsed,2)

    def test_key_hold_and_injected_keys_never_duplicate(self):
        self.input.key_event(True,123,100)
        self.input.key_event(True,123,101)
        self.assertEqual(self.output,[])
        self.input.key_event(False,123,101.1)
        self.frame(102.9,20)
        self.input.key_event(True,123,103,injected=True)
        self.assertEqual(self.output,[])
        self.input.key_event(True,123,103)
        self.assertEqual(self.output[-1][0].kind,"key")

    def test_drag_uses_mouse_down_frame_and_ignores_clicks_and_horizontal_seek(self):
        self.wheel(100)
        self.frame(101.9,20);self.input.mouse_event("down",123,100,300,102)
        self.input.mouse_event("move",123,130,303,102.1)
        self.assertEqual(self.output,[])
        self.frame(102.2,30)
        self.input.mouse_event("move",123,105,220,102.3)
        self.input.mouse_event("move",123,105,100,102.4)
        event,_=self.output[-1]
        self.assertEqual(event.kind,"drag")
        self.assertEqual(event.frame[0][0,0,0],20)
        self.assertEqual(len(self.output),1)

    def test_other_windows_and_disabled_mode_do_not_learn(self):
        self.input.mouse_event("wheel",999,0,0,100,delta=-120)
        self.input.key_event(True,999,101)
        self.assertIsNone(self.gate.previous)
        self.gate.configure((123,456,789),False,5)
        self.wheel(102);self.wheel(103)
        self.assertEqual(self.output,[])

    def test_pause_or_rebind_resets_baseline(self):
        self.wheel(100)
        self.gate.configure(None,False,5)
        self.gate.configure((123,456,789),True,5)
        self.frame(101.9,20);self.wheel(102)
        self.assertEqual(self.output,[])

    def test_automatic_switch_only_starts_a_new_clock_without_learning(self):
        self.wheel(100)
        self.gate.automatic_transition(110)
        self.assertEqual(self.output,[])
        self.frame(112.9,20);self.wheel(113)
        self.assertEqual(self.output[-1][0].elapsed,3)

    def test_missing_stale_or_future_frame_is_never_replaced_with_next_frame(self):
        self.wheel(100);self.wheel(103)
        self.assertIsNone(self.output[-1][0])
        self.frame(106.1,20);self.wheel(106)
        self.assertIsNone(self.output[-1][0])

    def test_queue_limit_reports_overload(self):
        self.wheel(100)
        for i in range(1,10):
            self.frame(100+i-0.1,i);self.wheel(100+i)
        self.assertEqual(sum(event is not None for event,_ in self.output),8)
        self.assertIn("队列已满",self.output[-1][1])

    def test_unreadable_frame_does_not_invent_blacklist_identity(self):
        self.wheel(100);self.frame(102.9,20);self.wheel(103)
        analyzer=ScreenshotAnalyzer();analyzer.ocr=Mock(return_value=([],None))
        with self.assertRaises(ValueError):analyzer.analyze(self.output[-1][0])


if __name__=="__main__":unittest.main()
