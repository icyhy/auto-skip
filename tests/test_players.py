import unittest
from unittest.mock import Mock, patch
from PIL import Image

from autoskip.players import analysis_bounds, validate_profiles
from autoskip.capture import capture_region
from autoskip.windows import find_player_window


class PlayerRegions(unittest.TestCase):
    def config(self, regions):
        return {"player_type":"测试播放器","player_profiles":[{"name":"测试播放器","regions":regions}]}

    def test_all_edges_and_overlapping_regions_use_original_pixels(self):
        config=self.config([{"direction":d,"span":s} for d,s in
            [("top",20),("bottom",100),("left",30),("right",40),("bottom",50)]])
        self.assertEqual(analysis_bounds((900,600),config),(30,20,860,500))
        config["player_profiles"].append({"name":"其他播放器","regions":[]})
        config["player_type"]="其他播放器"
        self.assertEqual(analysis_bounds((900,600),config),(0,0,900,600))

    def test_invalid_settings_and_fully_excluded_window_are_rejected(self):
        for region in [{"direction":"diagonal","span":100},{"direction":"bottom","span":0},
                       {"direction":"bottom","span":-1},{"direction":"bottom","span":1.5},
                       {"direction":"bottom","span":True}]:
            with self.assertRaises(ValueError):validate_profiles(self.config([region])["player_profiles"],"测试播放器")
        config=self.config([{"direction":"top","span":300},{"direction":"bottom","span":300}])
        with self.assertRaisesRegex(ValueError,"覆盖"):analysis_bounds((900,600),config)
        for names,selected in [(["同名","同名"],"同名"),([""],""),(["播放器"],"不存在")]:
            with self.assertRaises(ValueError):
                validate_profiles([{"name":name,"regions":[]} for name in names],selected)

    def test_preview_finds_configured_process_and_prefers_valid_binding(self):
        target=(123,456,789)
        with patch("autoskip.windows.valid_target",return_value=True) as valid,patch("autoskip.windows.windows") as discover,\
             patch("autoskip.windows.user32.IsIconic",return_value=False),patch("autoskip.windows.user32.IsWindowVisible",return_value=True):
            self.assertEqual(find_player_window("player.exe",target),target)
            valid.assert_called_once_with(target,"player.exe");discover.assert_not_called()
        with patch("autoskip.windows.valid_target",return_value=False),patch("autoskip.windows.windows",return_value=[(123,"播放器")]) as discover,\
             patch("autoskip.windows.window_identity",return_value=target) as identity,\
             patch("autoskip.windows.user32.IsIconic",return_value=False),patch("autoskip.windows.user32.IsWindowVisible",return_value=True):
            self.assertEqual(find_player_window("player.exe"),target)
            discover.assert_called_once_with("player.exe");identity.assert_called_once_with(123,"player.exe")
            discover.return_value=[]
            with self.assertRaisesRegex(ValueError,"未找到"):find_player_window("player.exe")
            discover.return_value=[(123,"播放器"),(124,"播放器")]
            with self.assertRaisesRegex(ValueError,"多个"):find_player_window("player.exe")

    def test_preview_crops_original_pixels_maps_screen_coordinates_and_closes_capture(self):
        config=self.config([{"direction":d,"span":s} for d,s in [("top",20),("bottom",100),("left",30),("right",40)]])
        target=(123,456,789);image=Image.new("RGB",(900,600),"blue")
        image.paste("red",(0,500,900,600));capture=Mock();capture.snapshot.return_value=(image,1.0)
        with patch("autoskip.capture.WindowCapture",return_value=capture),patch("autoskip.windows.valid_target",return_value=True),\
             patch("autoskip.windows.rect",return_value=(-1800,50,-450,950)) as rect,\
             patch("autoskip.windows.user32.IsIconic",return_value=False),patch("autoskip.windows.user32.IsWindowVisible",return_value=True):
            crop,area=capture_region(target,config)
            self.assertEqual(crop.size,(830,480));self.assertEqual(area,(-1755,80,-510,800))
            self.assertEqual(crop.getpixel((0,479)),(0,0,255));self.assertEqual(image.size,(900,600))
            capture.close.assert_called_once()
            rect.side_effect=[(0,0,900,600),(100,0,1000,600)]
            with self.assertRaisesRegex(ValueError,"变化"):capture_region(target,config)
            self.assertEqual(capture.close.call_count,2)
        profile=config["player_profiles"][0]
        for process in ["", "C:/player.exe", "../player.exe", "player", "player.exe\n"]:
            profile["process"]=process
            with self.assertRaises(ValueError):validate_profiles([profile],profile["name"])


if __name__=="__main__":unittest.main()
