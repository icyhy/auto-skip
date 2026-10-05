package com.autoskip.android;

import android.app.*;
import android.os.Bundle;
import org.json.*;

/** Run with am instrument; isolated in-memory database, no Douyin gestures or real records. */
public final class DeviceCheck extends Instrumentation {
    static void check(boolean value, String label) { if (!value) throw new AssertionError(label); }
    @Override public void onCreate(Bundle args) { super.onCreate(args); start(); }
    @Override public void onStart() {
        Bundle result = new Bundle();
        try (Store s = new Store(getTargetContext(), null)) {
            Core.Rule rule = new Core.Rule(); rule.keyword = "广告"; rule.label = "广告";
            rule.id = s.saveRule(rule); check(s.rules().size() == 1, "rule persist");
            rule.enabled = false; s.saveRule(rule); check(!s.rules().get(0).enabled, "disable persists");
            Core.Video video = new Core.Video("测试作者", "手机续航测试视频", "手机续航测试视频", "https://www.douyin.com/video/123");
            s.watch(video, 6); s.watch(video, 2);
            check(s.rows("watches").length() == 2, "watch records");
            double before = s.number("threshold", 5); s.setNumber("threshold", 5);
            try {
                Store.Stats stats = s.statistics(); check(stats.all.count == 2 && stats.valid.count == 1 && stats.skipped.count == 1, "statistics boundaries");
                check(s.budget(video) == 6, "same video budget");
                check(s.favorite(video, 301), "new favorite"); check(!s.favorite(video, 400), "favorite dedupe");
                s.editFavorite(1, "修改作者", "修改标题", "数码", "https://www.douyin.com/video/123");
                check(!s.favorite(video, 400), "edits preserve identity");
                JSONObject backup = s.exportWatches(); s.getWritableDatabase().delete("watches", null, null);
                check(s.importWatches(backup) == 2, "import restores"); check(s.importWatches(backup) == 0, "import idempotent");
                JSONObject invalid = new JSONObject(backup.toString()); invalid.getJSONArray("watches").getJSONObject(1).put("seconds", -1);
                try { s.importWatches(invalid); throw new AssertionError("invalid import accepted"); } catch (IllegalArgumentException expected) { }
                check(s.rows("watches").length() == 2, "invalid import atomic");
                result.putString("stream", "Android SQLite checks passed\n");
            } finally { s.setNumber("threshold", before); }
            finish(Activity.RESULT_OK, result);
        } catch (Throwable e) {
            result.putString("stream", "FAIL: " + e.toString() + "\n"); finish(Activity.RESULT_CANCELED, result);
        }
    }
}
