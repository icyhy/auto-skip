package com.autoskip.android;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.text.Normalizer;
import java.util.*;
import java.util.regex.*;

/** Platform-independent rules and timing; the service supplies confirmed observations. */
public final class Core {
    public static String normalize(String value) {
        return Normalizer.normalize(value == null ? "" : value, Normalizer.Form.NFKC)
            .replaceAll("[\\s\\p{Z}\\u200b-\\u200f\\u2060\\ufeff]+", "").toLowerCase(Locale.ROOT);
    }
    public static String author(String value) {
        String s = Normalizer.normalize(value == null ? "" : value, Normalizer.Form.NFKC).trim();
        s = s.replaceFirst("^[@·•.。\\s]+", "").replaceFirst("\\s*\\(\\s*主页\\s*\\)\\s*$", "");
        s = s.replaceFirst("(?:[·•.。|]\\s*|\\s+)(?:\\d+\\s*(?:秒|分钟|小时|天|周|月|年)\\s*前|刚刚|昨天|前天|\\d{1,2}月\\d{1,2}日)\\s*$", "");
        s = s.replaceAll("[\\s\\p{Z}\\u200b-\\u200f\\u2060\\ufeff]+", "");
        return Arrays.asList("", "作者", "用户", "我的", "我", "主页", "发一条友好的弹幕吧").contains(s) ? "" : s;
    }
    public static String hash(String s) {
        try {
            byte[] bytes = MessageDigest.getInstance("SHA-256").digest(s.getBytes(StandardCharsets.UTF_8));
            StringBuilder out = new StringBuilder();
            for (byte b : bytes) out.append(String.format(Locale.ROOT, "%02x", b & 255));
            return out.toString();
        } catch (Exception e) { throw new IllegalStateException(e); }
    }
    public static String linkKey(String s) {
        s = s == null ? "" : s.trim().replaceFirst("/+$", "");
        if (s.startsWith("www.")) s = "https://" + s;
        try {
            URI u = URI.create(s);
            if (("douyin.com".equals(u.getHost()) || "www.douyin.com".equals(u.getHost()))
                    && u.getPath().matches("/video/\\d+/?"))
                return "dy:video:" + u.getPath().split("/")[2];
        } catch (IllegalArgumentException ignored) { }
        return s;
    }
    public static void validateLink(String s) {
        if (s.isEmpty()) return;
        try {
            URI u = URI.create(s);
            if (!("https".equals(u.getScheme()) || "http".equals(u.getScheme())) || u.getHost() == null)
                throw new IllegalArgumentException();
        } catch (IllegalArgumentException e) { throw new IllegalArgumentException("请输入完整的 http / https 链接"); }
    }
    public static List<String> links(String s) {
        ArrayList<String> out = new ArrayList<>();
        Matcher m = Pattern.compile("(?:https?://|www\\.)[^\\s<>\"'，。；！？、（）]+").matcher(s);
        while (m.find()) out.add(m.group().replaceFirst("[.,;!?，。；！？、)]+$", ""));
        return out;
    }
    public static final class Video {
        public final String author, title, text, link, id;
        public Video(String author, String title, String text, String link) {
            this.author = Core.author(author); this.title = title.trim(); this.text = text; this.link = link;
            String k = linkKey(link); id = k.startsWith("dy:video:") ? k : "";
        }
        public String captionKey() {
            // Match the desktop identity format; keep nickname case intact.
            String a = Core.author(author);
            String t = Normalizer.normalize(title, Normalizer.Form.NFKC).replaceAll("[\\s\\p{Z}]+", "");
            return a.isEmpty() || t.length() < 5 ? "" : "dy:caption:" + hash(a + "\n" + t);
        }
        public String key() { return id.isEmpty() ? captionKey() : id; }
        public String token() { return key().isEmpty() ? author + "\n" + title : key(); }
    }
    public static final class Rule {
        public long id;
        public String kind = "filter", author = "", keyword = "", link = "", condition = "or", label = "";
        public boolean enabled = true;
        public void validate() {
            author = Core.author(author); keyword = keyword.trim(); link = link.trim();
            if (!Arrays.asList("filter", "author", "video").contains(kind)
                    || !Arrays.asList("or", "and", "video").contains(condition))
                throw new IllegalArgumentException("无效的规则类型");
            if (kind.equals("video")) {
                if (author.isEmpty() || link.isEmpty()) throw new IllegalArgumentException("视频规则需要作者和可靠视频身份");
                return;
            }
            if (condition.equals("and") && (author.isEmpty() || keyword.isEmpty() || link.isEmpty()))
                throw new IllegalArgumentException("“与”条件需要同时填写作者、关键词和链接");
            if (author.isEmpty() && keyword.isEmpty() && link.isEmpty())
                throw new IllegalArgumentException("至少填写作者、关键词或链接中的一项");
            validateLink(link);
        }
        public boolean matches(Video v) {
            if (!enabled) return false;
            if (kind.equals("video")) return !link.isEmpty() &&
                (linkKey(link).equals(v.key()) || (link.startsWith("dy:caption:") && link.equals(v.captionKey())));
            boolean a = !author.isEmpty() && Core.author(author).equals(Core.author(v.author));
            boolean k = !keyword.isEmpty() && normalize(v.title + "\n" + v.text).contains(normalize(keyword));
            boolean l = !link.isEmpty() && links(v.link + "\n" + v.text).stream().anyMatch(x -> linkKey(x).equals(linkKey(link)));
            return condition.equals("and") ? a && k && l : a || k || l;
        }
    }
    public static Rule blockRule(String kind, Video video) {
        if (!Arrays.asList("author", "video").contains(kind)) throw new IllegalArgumentException("无效的拉黑类型");
        if (video.author.isEmpty()) throw new IllegalArgumentException("未识别作者，未加入黑名单");
        Rule rule = new Rule(); rule.author = video.author; rule.label = video.author;
        if (kind.equals("author")) rule.kind = "author";
        else {
            rule.keyword = video.title;
            rule.link = video.id.isEmpty() ? "" : "https://www.douyin.com/video/" + video.id.substring(9);
            rule.label = video.title.isEmpty() ? video.author : video.title;
        }
        rule.validate(); return rule;
    }
    private static final String[][] CATEGORIES = {
        {"数码科技", "数码 科技 手机 电脑 芯片 人工智能 AI 编程 软件 机器人 摄影 相机"},
        {"美食", "美食 做饭 烹饪 菜谱 食谱 厨房 探店 小吃 火锅 烧烤"},
        {"运动健身", "运动 健身 减脂 瑜伽 跑步 篮球 足球 游泳 马拉松"},
        {"旅行风景", "旅行 旅游 风景 景点 自驾 徒步 露营 山水"},
        {"知识教育", "知识 科普 教育 学习 教程 数学 英语 历史 物理 课堂"},
        {"财经商业", "财经 股票 基金 投资 经济 商业 创业 职场 理财"},
        {"汽车", "汽车 新能源 试驾 电动车 摩托 车评"},
        {"影视娱乐", "影视 电影 电视剧 明星 综艺 搞笑 喜剧 相声 段子"},
        {"音乐舞蹈", "音乐 唱歌 歌曲 演唱 跳舞 舞蹈 吉他 钢琴"},
        {"游戏", "游戏 电竞 王者荣耀 原神 我的世界 英雄联盟"},
        {"宠物动物", "宠物 猫咪 狗狗 小猫 小狗 动物 萌宠"},
        {"生活情感", "生活 情感 家庭 婚姻 育儿 宝宝 家居 装修 穿搭 美妆"}
    };
    public static List<String> categories(String title) {
        String text = Normalizer.normalize(title, Normalizer.Form.NFKC).toLowerCase(Locale.ROOT);
        List<String> found = new ArrayList<>();
        for (String[] entry : CATEGORIES) for (String word : entry[1].split(" ")) {
            String w = word.toLowerCase(Locale.ROOT);
            boolean match = w.matches("[a-z0-9]+") ? Pattern.compile("(?<![a-z0-9])" + w + "(?![a-z0-9])").matcher(text).find() : text.contains(w);
            if (match) { found.add(entry[0]); break; }
        }
        if (found.isEmpty()) {
            Matcher tags = Pattern.compile("#([^\\s#，。！？,!?]+)").matcher(text);
            while (tags.find() && found.size() < 8) if (!found.contains(tags.group(1))) found.add(tags.group(1));
        }
        return found.isEmpty() ? Collections.singletonList("未分类") : found;
    }
    public static final class Step {
        public Video finished, learned, favorite;
        public double seconds, favoriteSeconds;
        public boolean changed;
    }
    public static final class Session {
        public Video current;
        public long started = -1, observedAt = -1, lastTick = -1;
        public double favoriteSeconds;
        public boolean favoriteSaved;
        public void reset() { current = null; started = observedAt = lastTick = -1; favoriteSeconds = 0; favoriteSaved = false; }
        public Step observe(Video v, long at, long switchAt, boolean manual, boolean listen, boolean favorites,
                boolean statistics, double threshold, double favoriteThreshold, boolean playing) {
            Step step = new Step();
            boolean changing = current != null && !current.token().equals(v.token());
            long end = changing && switchAt >= 0 && switchAt <= at ? switchAt : at;
            if (current != null && lastTick >= 0 && end >= lastTick && end - lastTick <= 1500 && playing)
                favoriteSeconds += (end - lastTick) / 1000.0;
            if (current != null && !current.token().equals(v.token())) {
                long boundary = switchAt >= 0 && switchAt <= at ? switchAt : at;
                double seconds = started >= 0 ? (boundary - started) / 1000.0 : 0;
                if (statistics && seconds > 0) { step.finished = current; step.seconds = seconds; }
                if (listen && manual && seconds > 0 && seconds < threshold
                        && !current.author.isEmpty() && !current.key().isEmpty()) step.learned = current;
                if (favorites && !favoriteSaved && favoriteSeconds > favoriteThreshold && !current.key().isEmpty()) {
                    step.favorite = current; step.favoriteSeconds = favoriteSeconds;
                }
                started = observedAt = boundary; favoriteSeconds = 0; favoriteSaved = false; step.changed = true;
            }
            if (observedAt < 0) observedAt = at;
            current = v; lastTick = at;
            if (favorites && !favoriteSaved && favoriteSeconds > favoriteThreshold && !v.key().isEmpty()) {
                step.favorite = v; step.favoriteSeconds = favoriteSeconds; favoriteSaved = true;
            }
            return step;
        }
        public double elapsed(long now) { return observedAt < 0 ? 0 : Math.max(0, (now - observedAt) / 1000.0); }
    }
}
