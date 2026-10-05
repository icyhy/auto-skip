package com.autoskip.android;

import java.util.*;

public final class CoreCheck {
    static int checks;
    static void check(boolean value, String message) { checks++; if (!value) throw new AssertionError(message); }
    static Core.Video video(String author, String title) { return new Core.Video(author, title, title, ""); }
    static FeedParser.Item node(String t, int l, int y, int r, int b) { return new FeedParser.Item(t, "", l, y, r, b); }
    public static void main(String[] args) {
        Core.Video a = video("@张 三 · 3小时前", "手机续航实测 #数码");
        check(a.author.equals("张三"), "author cleanup");
        check(Core.author("@主页").isEmpty(), "navigation is not author");
        check(a.key().startsWith("dy:caption:"), "video identity");
        check(Core.linkKey("https://www.douyin.com/video/123?x=1").equals("dy:video:123"), "canonical video link");
        Core.Rule r = new Core.Rule(); r.author = "张三"; r.keyword = "广告"; r.link = "https://www.douyin.com/video/123";
        check(r.matches(a), "OR author");
        check(!r.matches(video("张三丰", "普通视频标题")), "exact author");
        check(!r.matches(video("李四", "正文提到张三")), "mention is not author");
        Core.Rule generated = Core.blockRule("video", a);
        check(generated.kind.equals("filter") && generated.condition.equals("or"), "new video blocks default to OR");
        check(generated.keyword.equals(a.title) && generated.link.isEmpty(), "save caption as keyword without inventing a URL");
        check(generated.matches(video(a.author, "另一条视频的标题")), "generated OR matches author independently");
        check(generated.matches(video("另一作者", a.title)), "generated OR matches caption independently");
        check(!generated.matches(video("另一作者", "完全无关的内容")), "generated OR rejects unrelated video");
        Core.Rule linked = Core.blockRule("video", new Core.Video("链接作者", "链接视频标题", "", "https://www.douyin.com/video/123?share=1"));
        check(linked.matches(new Core.Video("无关作者", "无关视频标题", "", "https://www.douyin.com/video/123?other=2")), "generated OR matches canonical URL independently");
        check(Core.blockRule("author", a).keyword.isEmpty(), "author block does not add caption keyword");
        try { Core.blockRule("video", video("", "无作者的视频标题")); throw new AssertionError("missing author accepted"); }
        catch (IllegalArgumentException expected) { checks++; }
        r.condition = "and";
        check(!r.matches(a), "AND requires all");
        Core.Video full = new Core.Video("张三", "这是广告 ＡＩ", "这是广告", "https://www.douyin.com/video/123?share=1");
        check(r.matches(full), "AND all three");
        r.author = ""; try { r.validate(); throw new AssertionError("invalid AND accepted"); } catch (IllegalArgumentException expected) { checks++; }
        r.condition = "or"; r.keyword = "AI"; r.link = "";
        check(r.matches(full), "NFKC keyword"); r.enabled = false; check(!r.matches(full), "disabled rule");
        Core.Rule v = new Core.Rule(); v.kind = "video"; v.condition = "video"; v.author = a.author; v.keyword = a.title; v.link = a.key();
        check(v.matches(a), "learned video"); check(!v.matches(video(a.author, "另一条手机视频")), "video rule does not block author");
        check(v.matches(new Core.Video(a.author, a.title, a.text, "https://www.douyin.com/video/123")), "caption rule can gain a real link");
        v.link = "dy:video:123"; check(!v.matches(new Core.Video("张三", full.title, full.text, "https://www.douyin.com/video/456")), "distinct video IDs");
        check(Core.categories("手机AI摄影").contains("数码科技"), "category");
        check(Core.categories("#冷门话题").equals(Collections.singletonList("冷门话题")), "unknown topic");
        Core.Session s = new Core.Session(); Core.Video b = video("李四", "旅行风景实拍");
        s.observe(a, 1000, -1, false, true, true, true, 5, 300, true);
        check(s.elapsed(7000) == 6, "first video historical timer without completed statistic");
        Core.Step first = s.observe(b, 11000, 10000, true, true, true, true, 5, 300, true);
        check(first.finished == null && first.learned == null, "first switch only establishes baseline");
        Core.Step quick = s.observe(a, 14000, 13000, true, true, true, true, 5, 300, true);
        check(quick.finished == b && quick.seconds == 3 && quick.learned == b, "manual fast switch");
        Core.Step exact = s.observe(b, 18500, 18000, true, true, true, true, 5, 300, true);
        check(exact.seconds == 5 && exact.learned == null, "strict threshold");
        Core.Step auto = s.observe(a, 20500, 20000, false, true, true, true, 5, 300, true);
        check(auto.learned == null, "automatic skip never learns");
        s.reset(); check(s.current == null && s.started < 0, "pause resets incomplete visit");
        s.observe(a, 0, -1, false, false, true, false, 5, 6, true);
        for (int i = 1; i <= 6; i++) check(s.observe(a, i * 1000, -1, false, false, true, false, 5, 6, true).favorite == null, "strict favorite boundary");
        check(s.observe(a, 6100, -1, false, false, true, false, 5, 6, true).favorite == a, "immediate favorite");
        check(s.observe(a, 7100, -1, false, false, true, false, 5, 6, true).favorite == null, "once per visit");
        s.reset(); s.observe(a, 0, -1, false, false, true, false, 5, 6, true);
        s.observe(a, 10000, -1, false, false, true, false, 5, 6, true);
        check(s.favoriteSeconds == 0, "observation gaps excluded");
        s.observe(a, 11000, -1, false, false, true, false, 5, 6, false);
        check(s.favoriteSeconds == 0, "known playback pause excluded");
        List<FeedParser.Item> nodes = new ArrayList<>(Arrays.asList(node("@张三", 20, 1500, 500, 1570), node("手机续航实测 #数码", 20, 1580, 800, 1650),
            node("评论 128", 950, 1400, 1080, 1460), node("分享", 950, 1700, 1080, 1760)));
        Core.Video parsed = FeedParser.parse(nodes, 1080, 2400);
        check(parsed != null && parsed.author.equals("张三") && parsed.title.equals("手机续航实测 #数码"), "visible feed parsing");
        nodes.add(node("@李四 这是正文中的提及", 20, 1650, 800, 1700));
        check(FeedParser.parse(nodes, 1080, 2400).author.equals("张三"), "caption mention does not replace author");
        nodes.add(node("全部评论", 20, 1100, 600, 1180)); check(FeedParser.parse(nodes, 1080, 2400) == null, "comments excluded");
        check(FeedParser.parse(Arrays.asList(node("@张三", 20, 1500, 500, 1570)), 1080, 2400) == null, "unknown page idle");
        List<FeedParser.Item> mate40 = Arrays.asList(
            new FeedParser.Item("@实机样例", "com.ss.android.ugc.aweme:id/title", 36, 1979, 252, 2054),
            new FeedParser.Item("#实机话题 #标题测试", "com.ss.android.ugc.aweme:id/desc", 36, 2054, 843, 2190),
            node("评论141，按钮", 972, 1454, 1152, 1655), node("分享1333，按钮", 972, 1851, 1152, 2052));
        check(FeedParser.parse(mate40, 1152, 2376).title.equals("#实机话题 #标题测试"), "Mate40 full display coordinates retain bottom caption");
        List<FeedParser.Item> disclosures = new ArrayList<>(mate40);
        disclosures.add(node("作者声明：个人观点，仅供参考", 36, 2190, 873, 2240));
        disclosures.add(node("图片1，按钮", 36, 2160, 480, 2220));
        check(FeedParser.parse(disclosures, 1152, 2376).title.equals("#实机话题 #标题测试"), "disclosures and picture controls excluded");
        check(FeedParser.paused(Collections.singletonList(node("播放视频，按钮", 0, 0, 1152, 2229))), "real Douyin paused state");
        check(!FeedParser.paused(Collections.singletonList(node("暂停视频，按钮", 0, 0, 1152, 2229))), "pause action means video is playing");
        List<FeedParser.Item> live = Arrays.asList(
            new FeedParser.Item("视频", "com.ss.android.ugc.aweme:id/viewpager", 0, 0, 1152, 2229),
            node("点击进入直播间按钮", 0, 0, 1152, 2229), node("@直播样例", 36, 2041, 480, 2109),
            node("这个月最后一场直播", 36, 2132, 873, 2193));
        check(FeedParser.parse(live, 1152, 2376).title.equals("这个月最后一场直播"), "live recommendation card preserves feed continuity");
        check(FeedParser.parse(live.subList(1, live.size()), 1152, 2376) == null, "actual live room without feed pager stays idle");
        System.out.println("Android core checks passed: " + checks);
    }
}
