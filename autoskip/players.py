"""Player-specific edge exclusions, measured before any OCR resizing."""

DIRECTIONS = {"top": "上方", "bottom": "下方", "left": "左侧", "right": "右侧"}
DEFAULT_PLAYER = "抖音桌面版 Windows"


def validate_profiles(profiles, selected):
    if not isinstance(profiles, list) or not profiles:
        raise ValueError("请至少定义一个播放器类型")
    names = set()
    for profile in profiles:
        if not isinstance(profile, dict):raise ValueError("播放器配置格式不正确")
        name = profile.get("name")
        if not isinstance(name, str) or not name.strip() or name != name.strip():
            raise ValueError("播放器类型名称不能为空，首尾不能包含空白")
        if name in names:raise ValueError("播放器类型名称不能重复")
        names.add(name)
        process = profile.get("process", "douyin.exe")
        if not isinstance(process, str) or process != process.strip() or not process.lower().endswith(".exe") or any(
                c in process for c in '\\/:*?"<>|\r\n'):
            raise ValueError("窗口进程请填写可执行文件名，例如 douyin.exe")
        regions = profile.get("regions")
        if not isinstance(regions, list):raise ValueError("排除区域格式不正确")
        for region in regions:
            if not isinstance(region, dict) or region.get("direction") not in DIRECTIONS:
                raise ValueError("排除方向必须是上、下、左或右")
            span = region.get("span")
            if type(span) is not int or not 1 <= span <= 2147483647:
                raise ValueError("排除跨度必须是正整数像素")
    if selected not in names:raise ValueError("请选择已定义的播放器类型")


def analysis_bounds(size, config):
    width, height = size
    edges = dict.fromkeys(DIRECTIONS, 0)
    profiles = config.get("player_profiles", [])
    if profiles:
        selected = config.get("player_type", DEFAULT_PLAYER)
        validate_profiles(profiles, selected)
        profile = next(p for p in profiles if p["name"] == selected)
        for region in profile["regions"]:
            direction = region["direction"]
            # Regions on the same edge overlap; their spans do not accumulate.
            edges[direction] = max(edges[direction], region["span"])
    bounds = edges["left"], edges["top"], width-edges["right"], height-edges["bottom"]
    if bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
        raise ValueError("排除区域覆盖了整个播放窗口，请减小跨度")
    return bounds
