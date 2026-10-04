import json
import unittest
from unittest.mock import Mock,patch
from dataclasses import replace
from PIL import Image
from autoskip import jev
from autoskip.core import Snapshot
from autoskip.fast_ocr import FastOCR


class JevChecks(unittest.TestCase):
    def setUp(self):
        self.snapshot=Snapshot("desktop","window","video",author="@作者",title="手机实测",text="手机实测\n点击链接购买\n00:01 / 00:30")
        self.rules=[{"kind":"category","target":"purchase","label":"购买引导","reason":"购买链接或优惠口令","enabled":1},
                    {"kind":"author","target":"private-author","label":"作者","reason":"手动","enabled":1}]
        self.categories=[self.rules[0]]
        self.answer={"answers":{"category_0":{"type":"choice","choice":"block","confidence":.98,
                     "probabilities":{"block":.98,"allow":.01,"unknown":.01}}}}

    def test_typed_questions_only_include_enabled_categories(self):
        body,categories=jev.request_body("jev-latest",self.snapshot,self.rules)
        self.assertEqual(body["model"],"jev-latest")
        self.assertEqual(len(categories),1)
        self.assertEqual(body["questions"]["category_0"]["type"],"choice")
        self.assertNotIn("private-author",json.dumps(body))
        self.assertNotIn("messages",body)
        self.assertNotIn("00:01",body["state"]["window_text"])

    def test_strong_block_maps_to_existing_engine_result(self):
        result=jev.parse_decision(self.answer,self.categories,.9)
        self.assertTrue(result["match"]);self.assertEqual(result["category"],"purchase")

    def test_low_confidence_or_unknown_never_skips(self):
        answer=self.answer["answers"]["category_0"]
        answer["confidence"]=.7
        self.assertFalse(jev.parse_decision(self.answer,self.categories,.9)["match"])
        answer.update(choice="unknown",confidence=.99,probabilities={"block":.005,"allow":.005,"unknown":.99})
        self.assertFalse(jev.parse_decision(self.answer,self.categories,.9)["match"])

    def test_invalid_distribution_is_rejected(self):
        for values in [{"block":float('nan'),"allow":0,"unknown":0},{"block":1,"allow":1,"unknown":1},
                       {"block":True,"allow":0,"unknown":0},{"block":.9}]:
            self.answer["answers"]["category_0"]["probabilities"]=values
            with self.assertRaises(ValueError):jev.parse_decision(self.answer,self.categories,.9)

    def test_typesafe_endpoint_auth_and_bounded_timeout(self):
        response=Mock();response.read.return_value=json.dumps(self.answer).encode()
        context=Mock();context.__enter__=Mock(return_value=response);context.__exit__=Mock(return_value=False)
        opener=Mock();opener.open.return_value=context
        with patch("autoskip.jev.build_opener",return_value=opener):
            result=jev.classify({"jev_model":"jev-latest","jev_confidence":.9},"synthetic-key",self.snapshot,self.rules)
        self.assertTrue(result["match"])
        request=opener.open.call_args.args[0]
        self.assertEqual(request.full_url,"https://api.typesafe.ai/v1/systemone")
        self.assertEqual(request.get_header("Authorization"),"Bearer synthetic-key")
        self.assertEqual(opener.open.call_args.kwargs["timeout"],4)
        self.assertNotIn("synthetic-key",request.data.decode())

    def test_no_key_sends_nothing(self):
        with patch("autoskip.jev.build_opener") as network:
            with self.assertRaises(ValueError):jev.classify({"jev_model":"jev-latest"},"",self.snapshot,self.rules)
            network.assert_not_called()

    def test_timer_changes_do_not_change_semantic_cache_input(self):
        next_frame=replace(self.snapshot,text="手机实测\n点击链接购买\n00:02 / 00:30")
        self.assertEqual(jev.state(self.snapshot),jev.state(next_frame))

    def test_identical_window_reuses_ocr_and_preserves_chinese_lines(self):
        reader=FastOCR();reader.initialized=True;reader.engine=object()
        image=Image.new("RGB",(100,100),"white")
        async def native(_):return "@ 作 者\n真 实 测 试\n购 买 链 接"
        with patch.object(reader,"_native",side_effect=native) as recognize:
            first=reader.read(image);second=reader.read(image)
        self.assertEqual(first,"@ 作者\n真实测试\n购买链接")
        self.assertEqual(first,second);recognize.assert_called_once()

    def test_ocr_typo_only_corrects_after_independent_exact_reading(self):
        reader=FastOCR()
        reader.author_regions=[("@红衣大叔周 鸿 帏 。 3 小 时 前",(0,0,200,30))]
        image=Image.new("RGB",(300,100),"black")
        reader.fallback=Mock(return_value=([["@红衣大叔周鸿祎 · 3小时前",.97]],None))
        value=reader.verify_author(image,"@红衣大叔周鸿帏",["@红衣大叔周鸿祎"])
        self.assertEqual(value,"@红衣大叔周鸿祎")
        reader.fallback.assert_called_once()
        reader.author_cache.clear()
        reader.fallback.return_value=([["@红衣大叔周鸿帏 · 3小时前",.99]],None)
        self.assertEqual(reader.verify_author(image,"@红衣大叔周鸿帏",["@红衣大叔周鸿祎"]),"@红衣大叔周鸿帏")


if __name__=="__main__":unittest.main()
