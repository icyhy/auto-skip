package com.autoskip.android;

import android.content.*;
import android.database.Cursor;
import android.database.sqlite.*;
import org.json.*;
import java.text.*;
import java.util.*;

final class Store extends SQLiteOpenHelper {
    final SharedPreferences settings;
    Store(Context context) { this(context, "autoskip.db"); }
    Store(Context context, String name) {
        super(context, name, null, 1);
        settings = context.getSharedPreferences("settings", Context.MODE_PRIVATE);
    }
    @Override public void onCreate(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE rules(id INTEGER PRIMARY KEY,kind TEXT,author TEXT,keyword TEXT,link TEXT,condition TEXT,enabled INTEGER,label TEXT,created TEXT)");
        db.execSQL("CREATE TABLE watches(id INTEGER PRIMARY KEY,video_key TEXT,caption_key TEXT,author TEXT,title TEXT,source TEXT,seconds REAL,duration_basis TEXT,created TEXT)");
        db.execSQL("CREATE INDEX watch_identity ON watches(video_key)");
        db.execSQL("CREATE TABLE favorites(id INTEGER PRIMARY KEY,video_key TEXT,caption_key TEXT,author TEXT,title TEXT,category TEXT,link TEXT,seconds REAL,created TEXT)");
    }
    @Override public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) { }
    boolean flag(String key, boolean fallback) { return settings.getBoolean(key, fallback); }
    double number(String key, double fallback) { return settings.getFloat(key, (float) fallback); }
    void setFlag(String key, boolean value) { settings.edit().putBoolean(key, value).apply(); }
    void setNumber(String key, double value) { settings.edit().putFloat(key, (float) value).apply(); }
    static String now() { return new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.ROOT).format(new Date()); }
    List<Core.Rule> rules() {
        List<Core.Rule> out = new ArrayList<>();
        try (Cursor c = getReadableDatabase().rawQuery("SELECT * FROM rules ORDER BY id DESC", null)) {
            while (c.moveToNext()) {
                Core.Rule r = new Core.Rule(); r.id = c.getLong(0); r.kind = c.getString(1); r.author = c.getString(2);
                r.keyword = c.getString(3); r.link = c.getString(4); r.condition = c.getString(5);
                r.enabled = c.getInt(6) != 0; r.label = c.getString(7); out.add(r);
            }
        }
        return out;
    }
    long saveRule(Core.Rule r) {
        r.validate();
        ContentValues v = new ContentValues(); v.put("kind", r.kind); v.put("author", r.author);
        v.put("keyword", r.keyword); v.put("link", r.link); v.put("condition", r.condition);
        v.put("enabled", r.enabled ? 1 : 0); v.put("label", r.label);
        if (r.id > 0) { getWritableDatabase().update("rules", v, "id=?", new String[]{"" + r.id}); return r.id; }
        v.put("created", now()); return getWritableDatabase().insertOrThrow("rules", null, v);
    }
    Core.Rule duplicate(Core.Rule candidate) {
        for (Core.Rule r : rules()) if (r.kind.equals(candidate.kind) && r.author.equals(candidate.author)
                && r.keyword.equals(candidate.keyword) && r.link.equals(candidate.link) && r.condition.equals(candidate.condition)) return r;
        return null;
    }
    void delete(String table, long id) { getWritableDatabase().delete(table, "id=?", new String[]{"" + id}); }
    JSONArray rows(String table) throws JSONException {
        JSONArray rows = new JSONArray();
        try (Cursor c = getReadableDatabase().rawQuery("SELECT * FROM " + table + " ORDER BY id DESC", null)) {
            while (c.moveToNext()) {
                JSONObject row = new JSONObject();
                for (int i = 0; i < c.getColumnCount(); i++) {
                    String key = c.getColumnName(i);
                    row.put(key, c.getType(i) == Cursor.FIELD_TYPE_INTEGER ? c.getLong(i)
                        : c.getType(i) == Cursor.FIELD_TYPE_FLOAT ? c.getDouble(i) : c.getString(i));
                }
                rows.put(row);
            }
        }
        return rows;
    }
    ContentValues videoValues(Core.Video video) {
        ContentValues v = new ContentValues(); v.put("video_key", video.key()); v.put("caption_key", video.captionKey());
        v.put("author", video.author); v.put("title", video.title); v.put("created", now()); return v;
    }
    void watch(Core.Video video, double seconds) {
        if (!Double.isFinite(seconds) || seconds <= 0) return;
        ContentValues v = videoValues(video); v.put("source", "android"); v.put("duration_basis", "switch"); v.put("seconds", seconds);
        getWritableDatabase().insertOrThrow("watches", null, v);
    }
    boolean favorite(Core.Video video, double seconds) throws JSONException {
        if (video.key().isEmpty()) return false;
        JSONArray all = rows("favorites");
        for (int i = 0; i < all.length(); i++) {
            JSONObject row = all.getJSONObject(i);
            if (sameVideo(row, video)) return false;
        }
        ContentValues v = videoValues(video); v.put("seconds", seconds);
        v.put("category", String.join("、", Core.categories(video.title)));
        v.put("link", video.id.isEmpty() ? "" : "https://www.douyin.com/video/" + video.id.substring(9));
        getWritableDatabase().insertOrThrow("favorites", null, v); return true;
    }
    static boolean sameVideo(JSONObject row, Core.Video v) {
        String key = row.optString("video_key");
        if (!v.key().isEmpty() && key.equals(v.key())) return true;
        return !v.captionKey().isEmpty() && v.captionKey().equals(row.optString("caption_key"))
            && !(key.startsWith("dy:video:") && !v.id.isEmpty());
    }
    void editFavorite(long id, String author, String title, String category, String link) {
        Core.validateLink(link); ContentValues v = new ContentValues();
        v.put("author", author.trim()); v.put("title", title.trim()); v.put("category", category.trim()); v.put("link", link.trim());
        // Identity remains attached to the collected video even when display fields are edited.
        getWritableDatabase().update("favorites", v, "id=?", new String[]{"" + id});
    }
    static final class Group {
        int count; double seconds;
        void add(double value) { count++; seconds += value; }
        double average() { return count == 0 ? 0 : seconds / count; }
    }
    static final class Stats {
        final Group all = new Group(), valid = new Group(), skipped = new Group();
        final Map<String, Group> categories = new LinkedHashMap<>();
    }
    Stats statistics() throws JSONException {
        Stats stats = new Stats(); double threshold = number("threshold", 5);
        JSONArray all = rows("watches");
        for (int i = 0; i < all.length(); i++) {
            JSONObject row = all.getJSONObject(i); if (!row.optString("duration_basis").equals("switch")) continue;
            double seconds = row.getDouble("seconds"); stats.all.add(seconds);
            if (seconds < threshold) stats.skipped.add(seconds);
            if (seconds > threshold) {
                stats.valid.add(seconds);
                for (String category : Core.categories(row.getString("title")))
                    stats.categories.computeIfAbsent(category, k -> new Group()).add(seconds);
            }
        }
        return stats;
    }
    double budget(Core.Video video) throws JSONException {
        if (video.key().isEmpty()) return 0;
        Group same = new Group(); double threshold = number("threshold", 5);
        JSONArray all = rows("watches");
        for (int i = 0; i < all.length(); i++) {
            JSONObject row = all.getJSONObject(i); double seconds = row.getDouble("seconds");
            if (row.optString("duration_basis").equals("switch") && seconds > threshold && sameVideo(row, video)) same.add(seconds);
        }
        if (same.count > 0) return same.average();
        Stats stats = statistics(); Group best = null;
        for (String category : Core.categories(video.title)) {
            Group g = stats.categories.get(category);
            if (!category.equals("未分类") && g != null && (best == null || g.count > best.count)) best = g;
        }
        return best == null ? 0 : best.average();
    }
    private static final String[] WATCH_FIELDS = {"video_key", "caption_key", "author", "title", "source", "seconds", "duration_basis", "created"};
    JSONObject exportWatches() throws JSONException {
        JSONArray clean = new JSONArray(), all = rows("watches");
        for (int i = 0; i < all.length(); i++) {
            JSONObject row = all.getJSONObject(i), v = new JSONObject();
            for (String field : WATCH_FIELDS) v.put(field, row.get(field)); clean.put(v);
        }
        return new JSONObject().put("format", "autoskip-watches").put("version", 1).put("watches", clean);
    }
    static List<ContentValues> validateWatches(JSONObject data) throws Exception {
        if (!"autoskip-watches".equals(data.optString("format")) || !(data.opt("version") instanceof Integer)
                || data.getInt("version") != 1) throw new IllegalArgumentException("请选择 Auto Skip 观看记录 JSON（版本 1）");
        JSONArray rows = data.getJSONArray("watches"); List<ContentValues> checked = new ArrayList<>();
        SimpleDateFormat date = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.ROOT); date.setLenient(false);
        for (int i = 0; i < rows.length(); i++) {
            JSONObject row = rows.getJSONObject(i); ContentValues v = new ContentValues();
            for (String field : WATCH_FIELDS) {
                Object value = row.get(field);
                if (field.equals("seconds")) {
                    if (!(value instanceof Number)) throw new IllegalArgumentException("观看时长必须为数字");
                    double seconds = ((Number) value).doubleValue();
                    if (!Double.isFinite(seconds) || seconds <= 0) throw new IllegalArgumentException("观看时长必须大于 0");
                    v.put(field, seconds);
                } else {
                    if (!(value instanceof String) || ((String) value).length() > 8000) throw new IllegalArgumentException("观看记录字段无效");
                    v.put(field, (String) value);
                }
            }
            if (!Arrays.asList("android", "desktop", "chrome").contains(v.getAsString("source"))
                || !Arrays.asList("switch", "legacy").contains(v.getAsString("duration_basis")))
                throw new IllegalArgumentException("观看记录来源无效");
            ParsePosition position = new ParsePosition(0); String created = v.getAsString("created");
            if (!created.matches("\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}")
                    || date.parse(created, position) == null || position.getIndex() != created.length()) throw new IllegalArgumentException("观看时间无效");
            checked.add(v);
        }
        return checked;
    }
    private static String watchSignature(ContentValues v) {
        StringBuilder key = new StringBuilder();
        for (String f : WATCH_FIELDS) {
            String value = f.equals("seconds") ? "" + v.getAsDouble(f) : v.getAsString(f);
            key.append(value.length()).append(':').append(value);
        }
        return key.toString();
    }
    int importWatches(JSONObject data) throws Exception {
        List<ContentValues> checked = validateWatches(data);
        Map<String, Integer> counts = new HashMap<>();
        for (ContentValues v : validateWatches(exportWatches())) counts.merge(watchSignature(v), 1, Integer::sum);
        SQLiteDatabase db = getWritableDatabase(); int added = 0; db.beginTransaction();
        try {
            for (ContentValues v : checked) {
                String key = watchSignature(v); int count = counts.getOrDefault(key, 0);
                if (count > 0) { counts.put(key, count - 1); continue; }
                db.insertOrThrow("watches", null, v); added++;
            }
            db.setTransactionSuccessful(); return added;
        } finally { db.endTransaction(); }
    }
}
