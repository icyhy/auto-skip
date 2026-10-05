package com.autoskip.android;

import java.util.*;
import java.util.regex.*;

/** Parse visible feed nodes only. Unknown layouts leave automation idle. */
public final class FeedParser {
    public static final class Item {
        public final String text, id;
        public final int left, top, right, bottom;
        public Item(String text, String id, int left, int top, int right, int bottom) {
            this.text = text.trim(); this.id = id == null ? "" : id;
            this.left = left; this.top = top; this.right = right; this.bottom = bottom;
        }
    }
    public static Core.Video parse(List<Item> items, int width, int height) {
        if (width <= 0 || height <= 0) return null;
        String author = "", title = "";
        Item authorNode = null;
        boolean controls = false, modal = false, feedPager = false, liveCard = false;
        for (Item n : items) {
            if (n.text.isEmpty() || n.bottom <= 0 || n.top >= height || n.right <= 0 || n.left >= width) continue;
            String t = n.text;
            if (n.id.endsWith(":id/viewpager")) feedPager = true;
            if (t.startsWith("点击进入直播间") && n.right - n.left > width * .8 && n.bottom - n.top > height * .7) liveCard = true;
            if (t.matches("(?:全部评论|发送评论|回复评论|关闭评论|私信|编辑资料|退出登录|搜索历史|复制链接|分享给朋友|取消分享|__autoskip_editing__)")
                    || t.matches("\\d+条评论") || (n.left < width * .6 && t.matches("评论\\s*\\d+"))) modal = true;
            if (n.left > width * .65 && (t.contains("分享") || t.contains("评论") || t.contains("点赞"))) controls = true;
            Matcher combined = Pattern.compile("(?:作者[：:]|@)([^\n，]+?)(?:[，\n].*?(?:作品描述|视频描述|标题)[：:])(.+)", Pattern.DOTALL).matcher(t);
            if (combined.find() && n.bottom > height * .4) {
                author = combined.group(1).trim(); title = combined.group(2).replaceFirst("[，\n](?:点赞|评论|分享).*$", "");
                authorNode = n;
            }
            if (n.left < width * .65 && n.top > height * .42 && n.bottom < height * .95
                    && ((t.startsWith("@") && t.length() < 100 && !t.contains("\n"))
                        || n.id.toLowerCase(Locale.ROOT).matches(".*(?:author_name|nickname|user_name)$"))) {
                if (!t.contains("关注") && !t.contains("我的") && (authorNode == null || n.top < authorNode.top)) { author = t; authorNode = n; }
            }
        }
        if (modal || !(controls || feedPager && liveCard) || authorNode == null || Core.author(author).isEmpty()) return null;
        if (title.isEmpty()) {
            ArrayList<Item> candidates = new ArrayList<>();
            for (Item n : items) {
                if (n.left >= width * .7 || n.top < authorNode.top - 12 || n.bottom > height * .95
                        || n.text.equals(authorNode.text) || n.text.isEmpty()) continue;
                if (n.text.matches("(?:首页|推荐|关注|朋友|消息|我|展开|收起|合集.*|.*的音乐|.*原声|\\d+(?:[.,]\\d+)?(?:万|亿)?|.*小时前|.*天前|.*分钟前)")) continue;
                if (n.text.startsWith("@") || n.text.matches("(?:点赞|评论|收藏|分享|作者声明|作品含|内容由).*")) continue;
                if (n.text.endsWith("，按钮") || n.text.endsWith("的原声") || n.text.equals("拍同款") || n.text.equals("听抖音")) continue;
                if (n.text.length() >= 5) candidates.add(n);
            }
            candidates.sort(Comparator.comparingInt(n -> n.top));
            LinkedHashSet<String> unique = new LinkedHashSet<>();
            for (Item n : candidates) unique.add(n.text);
            title = String.join("\n", unique);
        }
        String text = title; // Exclude navigation, unrelated comments and engagement labels from rules.
        String link = "";
        for (String value : Core.links(text)) if (Core.linkKey(value).startsWith("dy:video:")) { link = value; break; }
        return new Core.Video(author, title, text, link);
    }
    public static boolean paused(List<Item> items) {
        for (Item n : items) if (n.text.matches("(?:播放|点击播放|继续播放|播放视频)(?:，按钮)?")) return true;
        return false;
    }
}
