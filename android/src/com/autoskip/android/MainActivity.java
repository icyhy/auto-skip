package com.autoskip.android;

import android.app.*;
import android.content.*;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.os.*;
import android.provider.Settings;
import android.text.*;
import android.text.InputType;
import android.view.*;
import android.widget.*;
import org.json.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;

public final class MainActivity extends Activity {
    static final int INK = Color.rgb(23, 37, 53), TEAL = Color.rgb(8, 127, 140), MUTED = Color.rgb(96, 112, 128);
    Store store;
    LinearLayout shell, content;
    String page = "首页";
    TextView state;
    Button start;
    Button serviceSetup;
    final Handler handler = new Handler(Looper.getMainLooper());
    final ExecutorService files = Executors.newSingleThreadExecutor();
    final Set<Long> selected = new HashSet<>();
    private final Runnable update = new Runnable() {
        public void run() {
            if (state != null && page.equals("首页")) {
                SkipService s = SkipService.live;
                String message = s == null ? "无障碍服务未开启" : s.status;
                String action = s != null && s.running ? "暂停" : "开始";
                if (!message.contentEquals(state.getText())) state.setText(message);
                if (!action.contentEquals(start.getText())) start.setText(action);
                if (serviceSetup != null) serviceSetup.setVisibility(s == null ? View.VISIBLE : View.GONE);
            }
            handler.postDelayed(this, 1000);
        }
    };
    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved); store = new Store(this); store.setFlag("app_closed", false);
        if (saved != null) page = saved.getString("page", "首页");
        show(page);
    }
    @Override protected void onResume() { super.onResume(); if (SkipService.live != null) SkipService.live.wake(); handler.post(update); }
    @Override protected void onPause() { handler.removeCallbacks(update); super.onPause(); }
    @Override protected void onSaveInstanceState(Bundle out) { out.putString("page", page); super.onSaveInstanceState(out); }
    @Override protected void onDestroy() {
        handler.removeCallbacksAndMessages(null);
        // Close after any pending import/export has released the connection.
        files.execute(store::close); files.shutdown();
        super.onDestroy();
    }
    int dp(float n) { return Math.round(n * getResources().getDisplayMetrics().density); }
    TextView text(String value, int size, int color) {
        TextView t = new TextView(this); t.setText(value); t.setTextSize(size); t.setTextColor(color); t.setPadding(0, dp(4), 0, dp(4)); return t;
    }
    Button button(String label, Runnable action) {
        Button b = new Button(this); b.setText(label); b.setTextSize(14); b.setMinHeight(dp(48)); b.setAllCaps(false);
        b.setOnClickListener(v -> action.run()); return b;
    }
    LinearLayout column() { LinearLayout v = new LinearLayout(this); v.setOrientation(LinearLayout.VERTICAL); return v; }
    LinearLayout card(LinearLayout parent) {
        LinearLayout v = column(); v.setPadding(dp(16), dp(12), dp(16), dp(12));
        GradientDrawable bg = new GradientDrawable(); bg.setColor(Color.WHITE); bg.setCornerRadius(dp(18)); v.setBackground(bg);
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(-1, -2); p.bottomMargin = dp(14); parent.addView(v, p); return v;
    }
    void row(LinearLayout parent, Button... buttons) {
        LinearLayout r = new LinearLayout(this);
        for (Button b : buttons) r.addView(b, new LinearLayout.LayoutParams(0, -2, 1)); parent.addView(r);
    }
    void show(String next) {
        page = next; state = null; serviceSetup = null;
        shell = column(); shell.setBackgroundColor(Color.rgb(245, 247, 250)); shell.setFitsSystemWindows(true);
        shell.setPadding(dp(16), dp(12), dp(16), 0);
        TextView heading = text(page.equals("首页") ? "Auto Skip" : page, 28, INK); heading.setTypeface(null, 1);
        if (page.equals("首页")) {
            LinearLayout title = new LinearLayout(this); title.setGravity(Gravity.CENTER_VERTICAL);
            title.addView(heading, new LinearLayout.LayoutParams(0, -2, 1));
            ImageButton exit = new ImageButton(this); exit.setImageResource(R.drawable.exit); exit.setBackgroundColor(Color.TRANSPARENT);
            exit.setPadding(dp(12), dp(12), dp(12), dp(12)); exit.setContentDescription("退出 Auto Skip"); exit.setTooltipText("退出 Auto Skip");
            exit.setOnClickListener(v -> exitApp()); title.addView(exit, new LinearLayout.LayoutParams(dp(48), dp(48))); shell.addView(title);
        } else shell.addView(heading);
        if (page.equals("首页")) shell.addView(text("让每一次上滑，更合心意", 14, MUTED));
        ScrollView scroll = new ScrollView(this); scroll.setFillViewport(true); content = column(); content.setPadding(0, dp(14), 0, dp(8));
        scroll.addView(content); shell.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        LinearLayout nav = new LinearLayout(this); nav.setPadding(0, dp(4), 0, dp(4));
        for (String label : new String[]{"首页", "黑名单", "收藏", "统计", "设置"}) {
            Button b = button(label, () -> show(label)); b.setTextSize(12); b.setPadding(0, 0, 0, 0); b.setMinWidth(0);
            b.setTextColor(page.equals(label) ? TEAL : MUTED); nav.addView(b, new LinearLayout.LayoutParams(0, dp(52), 1));
        }
        shell.addView(nav); setContentView(shell);
        try {
            switch (page) {
                case "首页": home(); break;
                case "黑名单": rules(); break;
                case "收藏": favorites(); break;
                case "统计": statistics(); break;
                default: settings();
            }
        } catch (Exception e) { content.addView(text("无法读取：" + e.getMessage(), 14, MUTED)); }
    }
    void home() {
        LinearLayout c = card(content);
        c.addView(text("运行状态", 14, MUTED)); state = text("已暂停", 21, INK); c.addView(state);
        start = button("开始", () -> {
            if (SkipService.live == null) { explainAccessibility(); return; }
            SkipService.live.setRunning(!SkipService.live.running); handler.removeCallbacks(update); handler.post(update);
        });
        row(c, start, button("打开抖音", this::openDouyin));
        serviceSetup = button("开启无障碍服务", this::explainAccessibility);
        serviceSetup.setVisibility(SkipService.live == null ? View.VISIBLE : View.GONE); c.addView(serviceSetup);
        c.addView(text("圆形浮窗点按开始 / 暂停，拖动圆钮调整位置；点下沿小箭头展开，点面板顶部收起。", 13, MUTED));
        LinearLayout features = card(content); features.addView(text("选择功能", 18, INK));
        feature(features, "listen", "监听快速划走", "在阈值内手动上滑，学习上一条视频", true);
        feature(features, "auto", "自动过滤", "命中启用的黑名单时上滑下一条", false);
        feature(features, "favorites", "自动收藏", "观看超过阈值后保存到本机收藏", true);
        feature(features, "history", "按历史时长跳过", "需同时开启自动过滤；无有效历史则继续观看", false);
        LinearLayout actions = card(content); actions.addView(text("管理", 18, INK));
        row(actions, button("黑名单", () -> show("黑名单")), button("收藏列表", () -> show("收藏")));
        row(actions, button("观看统计", () -> show("统计")), button("撤销拉黑", () -> {
            if (SkipService.live != null) { SkipService.live.undoBlock(); toast(SkipService.live.status); }
            else toast("服务未开启");
        }));
        actions.addView(text("黑名单和收藏属于本工具，均不修改抖音账号。", 13, MUTED));
    }
    void feature(LinearLayout parent, String key, String label, String note, boolean fallback) {
        Switch s = new Switch(this); s.setText(label); s.setTextSize(16); s.setTextColor(INK); s.setMinHeight(dp(48));
        s.setChecked(store.flag(key, fallback)); s.setOnCheckedChangeListener((b, on) -> {
            store.setFlag(key, on); if (SkipService.live != null) SkipService.live.settingsChanged();
        }); parent.addView(s); parent.addView(text(note, 12, MUTED));
    }
    void explainAccessibility() {
        new AlertDialog.Builder(this).setTitle("启用抖音辅助控制")
            .setMessage("Auto Skip 会读取抖音视频页的作者和标题，并按你保存的规则执行上滑。观看记录、黑名单和收藏只保存在手机。\n\n你可以随时从浮窗暂停，或在系统设置中关闭服务。\n\n下一步在“已安装的服务 / 已下载的服务”中找到“Auto Skip 视频过滤”并开启。")
            .setNegativeButton("取消", null).setPositiveButton("前往设置", (d, w) -> startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))).show();
    }
    void openDouyin() {
        Intent i = getPackageManager().getLaunchIntentForPackage(SkipService.DOUYIN);
        if (i == null) toast("未找到抖音，请先安装抖音安卓版本"); else startActivity(i);
    }
    void exitApp() {
        store.setFlag("app_closed", true);
        if (SkipService.live != null) SkipService.live.close();
        for (ActivityManager.AppTask task : ((ActivityManager) getSystemService(ACTIVITY_SERVICE)).getAppTasks()) task.finishAndRemoveTask();
    }
    EditText input(LinearLayout parent, String hint, String value) {
        EditText e = new EditText(this); e.setHint(hint); e.setText(value); e.setTextSize(15); e.setMinHeight(dp(48));
        e.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE); parent.addView(e); return e;
    }
    void search(EditText e, Runnable refresh) {
        e.addTextChangedListener(new TextWatcher() {
            public void beforeTextChanged(CharSequence s, int st, int count, int after) { }
            public void onTextChanged(CharSequence s, int st, int before, int count) { refresh.run(); }
            public void afterTextChanged(Editable e) { }
        });
    }
    void rules() {
        row(content, button("添加规则", () -> editRule(null)), button("撤销拉黑", () -> {
            if (SkipService.live != null) { SkipService.live.undoBlock(); show(page); } else toast("服务未开启");
        }));
        EditText query = input(content, "搜索作者、关键词或链接", ""); LinearLayout list = column(); content.addView(list);
        final int[] limit = {50}; Runnable refresh = new Runnable() {
            public void run() {
                list.removeAllViews(); int matching = 0;
                for (Core.Rule rule : store.rules()) {
                    if (!Core.normalize(rule.author + rule.keyword + rule.link).contains(Core.normalize(query.getText().toString()))) continue;
                    if (++matching > limit[0]) continue;
                    LinearLayout c = card(list);
                    Switch enabled = new Switch(MainActivity.this); enabled.setMinHeight(dp(48));
                    enabled.setText(rule.kind.equals("video") ? "仅视频" : rule.condition.equals("and") ? "全部符合（与）" : "任一符合（或）");
                    enabled.setChecked(rule.enabled); enabled.setOnCheckedChangeListener((v, value) -> {
                        rule.enabled = value; store.saveRule(rule);
                    }); c.addView(enabled);
                    c.addView(text("作者：" + (rule.author.isEmpty() ? "—" : rule.author), 16, INK));
                    c.addView(text("关键词：" + (rule.keyword.isEmpty() ? "—" : rule.keyword), 14, MUTED));
                    c.addView(text("链接：" + (rule.link.startsWith("dy:caption:") ? "已学习视频（作者 + 完整标题）" : rule.link.startsWith("dy:video:") ? "https://www.douyin.com/video/" + rule.link.substring(9) : rule.link.isEmpty() ? "—" : rule.link), 12, MUTED));
                    row(c, button("编辑", () -> editRule(rule)), button("删除", () -> confirm("删除这条规则？", () -> {
                        store.delete("rules", rule.id); run();
                    })));
                }
                if (matching == 0) list.addView(text("暂无匹配规则。添加关键词，或在抖音浮窗拉黑当前作者 / 视频。", 14, MUTED));
                if (matching > limit[0]) list.addView(button("显示更多（共 " + matching + " 条）", () -> { limit[0] += 50; run(); }));
            }
        }; search(query, refresh); refresh.run();
    }
    void editRule(Core.Rule original) {
        LinearLayout form = column(); form.setPadding(dp(20), dp(8), dp(20), dp(8));
        EditText author = input(form, "作者完整名称", original == null ? "" : original.author);
        EditText keyword = input(form, "关键词 / 视频标题", original == null ? "" : original.keyword);
        EditText link = input(form, "完整链接", original == null || original.link.startsWith("dy:caption:") ? "" : original.link.startsWith("dy:video:") ? "https://www.douyin.com/video/" + original.link.substring(9) : original.link);
        Spinner condition = new Spinner(this); boolean video = original != null && original.kind.equals("video");
        condition.setAdapter(new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item,
            video ? new String[]{"仅当前视频", "任一符合（或）", "全部符合（与）"} : new String[]{"任一符合（或）", "全部符合（与）"}));
        condition.setMinimumHeight(dp(48)); form.addView(condition);
        if (original != null && !video) condition.setSelection(original.condition.equals("and") ? 1 : 0);
        if (video) form.addView(text("“仅当前视频”按原视频身份匹配。改为“或 / 与”后，可编辑组合条件。", 12, MUTED));
        ScrollView scroller = new ScrollView(this); scroller.addView(form);
        AlertDialog dialog = new AlertDialog.Builder(this).setTitle(original == null ? "添加规则" : "编辑规则")
            .setView(scroller).setNegativeButton("取消", null).setPositiveButton("保存", null).create(); dialog.show();
        dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
            try {
                Core.Rule r = new Core.Rule(); if (original != null) { r.id = original.id; r.enabled = original.enabled; }
                r.author = author.getText().toString(); r.keyword = keyword.getText().toString(); r.link = link.getText().toString();
                int selected = condition.getSelectedItemPosition();
                if (video && selected == 0) { r.kind = "video"; r.condition = "video"; r.link = original.link; }
                else { r.kind = "filter"; r.condition = selected == (video ? 2 : 1) ? "and" : "or"; }
                r.label = r.author.isEmpty() ? r.keyword.isEmpty() ? r.link : r.keyword : r.author;
                r.validate(); Core.Rule existing = store.duplicate(r);
                if (r.id == 0 && existing != null) { toast("已有相同规则，可编辑或启用它"); return; }
                store.saveRule(r); dialog.dismiss(); show("黑名单");
            } catch (IllegalArgumentException e) { toast(e.getMessage()); }
        });
    }
    void favorites() throws JSONException {
        EditText query = input(content, "搜索作者、标题、类型或链接", "");
        row(content, button("复制所选链接", () -> copyFavorites()), button("删除所选", () -> {
            if (selected.isEmpty()) { toast("请先勾选收藏"); return; }
            confirm("删除选中的 " + selected.size() + " 条收藏？", () -> {
                for (long id : selected) store.delete("favorites", id); selected.clear(); show("收藏");
            });
        }));
        content.addView(button("清空收藏", () -> confirm("清空全部本机收藏？", () -> {
            store.getWritableDatabase().delete("favorites", null, null); selected.clear(); show("收藏");
        })));
        LinearLayout list = column(); content.addView(list); final int[] limit = {50};
        Runnable refresh = new Runnable() {
            public void run() {
                try {
                    list.removeAllViews(); JSONArray rows = store.rows("favorites"); int matching = 0;
                    Set<Long> existing = new HashSet<>();
                    for (int i = 0; i < rows.length(); i++) {
                        JSONObject item = rows.getJSONObject(i); long id = item.getLong("id"); existing.add(id);
                        String searchable = item.getString("author") + item.getString("title") + item.getString("category") + item.getString("link");
                        if (!Core.normalize(searchable).contains(Core.normalize(query.getText().toString()))) continue;
                        if (++matching > limit[0]) continue;
                        LinearLayout c = card(list); CheckBox box = new CheckBox(MainActivity.this);
                        box.setText("@" + item.getString("author")); box.setTextSize(16); box.setMinHeight(dp(48)); box.setChecked(selected.contains(id));
                        box.setOnCheckedChangeListener((b, value) -> { if (value) selected.add(id); else selected.remove(id); }); c.addView(box);
                        TextView title = text(item.getString("title"), 15, INK); title.setTextIsSelectable(true); c.addView(title);
                        c.addView(text(item.getString("category") + " · " + item.getString("created"), 12, MUTED));
                        String url = item.getString("link"); c.addView(text(url.isEmpty() ? "未取得链接，可编辑补填" : url, 12, MUTED));
                        Button copy = button("复制链接", () -> copy(url)); copy.setEnabled(!url.isEmpty());
                        row(c, copy, button("编辑", () -> editFavorite(item)));
                    }
                    selected.retainAll(existing);
                    if (matching == 0) list.addView(text("暂无收藏。观看超过设置中的阈值后，自动保存在这里。", 14, MUTED));
                    if (matching > limit[0]) list.addView(button("显示更多（共 " + matching + " 条）", () -> { limit[0] += 50; run(); }));
                } catch (JSONException e) { toast("收藏读取失败"); }
            }
        }; search(query, refresh); refresh.run();
    }
    void copyFavorites() {
        try {
            Set<String> links = new LinkedHashSet<>(); JSONArray rows = store.rows("favorites");
            for (int i = 0; i < rows.length(); i++) {
                JSONObject row = rows.getJSONObject(i);
                if (selected.contains(row.getLong("id")) && !row.getString("link").isEmpty()) links.add(row.getString("link"));
            }
            if (links.isEmpty()) toast("所选收藏没有可复制的链接"); else copy(String.join("\n", links));
        } catch (JSONException e) { toast("收藏读取失败"); }
    }
    void editFavorite(JSONObject item) {
        LinearLayout form = column(); form.setPadding(dp(20), dp(8), dp(20), dp(8));
        EditText author = input(form, "作者", item.optString("author"));
        EditText title = input(form, "标题", item.optString("title"));
        EditText category = input(form, "类型", item.optString("category"));
        EditText link = input(form, "真实视频链接", item.optString("link"));
        ScrollView scroller = new ScrollView(this); scroller.addView(form);
        AlertDialog d = new AlertDialog.Builder(this).setTitle("编辑收藏").setView(scroller)
            .setNegativeButton("取消", null).setPositiveButton("保存", null).create(); d.show();
        d.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
            try {
                store.editFavorite(item.optLong("id"), author.getText().toString(), title.getText().toString(), category.getText().toString(), link.getText().toString());
                d.dismiss(); show("收藏");
            } catch (IllegalArgumentException e) { toast(e.getMessage()); }
        });
    }
    String summary(Store.Group g) { return g.count + " 次 · 总计 " + String.format(Locale.ROOT, "%.1f", g.seconds) + " 秒\n平均 " + String.format(Locale.ROOT, "%.1f", g.average()) + " 秒"; }
    void statistics() throws JSONException {
        Store.Stats s = store.statistics();
        LinearLayout all = card(content); all.addView(text("全部观看", 18, INK)); all.addView(text(summary(s.all), 16, MUTED));
        LinearLayout valid = card(content); valid.addView(text("有效观看（严格超过 " + store.number("threshold", 5) + " 秒）", 18, TEAL)); valid.addView(text(summary(s.valid), 16, MUTED));
        LinearLayout skipped = card(content); skipped.addView(text("跳过（严格低于阈值）", 18, INK)); skipped.addView(text(summary(s.skipped), 16, MUTED));
        for (Map.Entry<String, Store.Group> group : s.categories.entrySet()) {
            LinearLayout c = card(content); c.addView(text(group.getKey(), 16, INK)); c.addView(text(summary(group.getValue()), 14, MUTED));
        }
        content.addView(text("只记录两次确认切换之间的完整观看。启动时第一条、退出前最后一条不计入统计。离开视频页会放弃未完成区间。", 13, MUTED));
        row(content, button("导出记录", this::exportWatches), button("导入记录", () -> {
            Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("*/*").addCategory(Intent.CATEGORY_OPENABLE); startActivityForResult(i, 101);
        }));
        content.addView(button("重置统计", () -> confirm("清空观看记录和历史预测？黑名单及收藏保留。", () -> {
            store.getWritableDatabase().delete("watches", null, null);
            if (SkipService.live != null) SkipService.live.settingsChanged(); show("统计");
        })));
    }
    void exportWatches() {
        try {
            File temp = new File(getCacheDir(), "watch-export.json");
            try (OutputStream output = new FileOutputStream(temp)) { output.write(store.exportWatches().toString(2).getBytes(StandardCharsets.UTF_8)); }
            Intent i = new Intent(Intent.ACTION_CREATE_DOCUMENT).setType("application/json").addCategory(Intent.CATEGORY_OPENABLE)
                .putExtra(Intent.EXTRA_TITLE, "autoskip-watches-" + Store.now().substring(0, 10) + ".json"); startActivityForResult(i, 100);
        } catch (Exception e) { toast("导出失败：" + e.getMessage()); }
    }
    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (result != RESULT_OK || data == null || data.getData() == null) return;
        if (request != 100 && request != 101) return;
        files.execute(() -> {
            String message;
            try {
                if (request == 100) {
                    try (InputStream in = new FileInputStream(new File(getCacheDir(), "watch-export.json")); OutputStream out = getContentResolver().openOutputStream(data.getData(), "wt")) {
                        if (out == null) throw new IOException("无法打开文件"); byte[] bytes = new byte[8192]; int n;
                        while ((n = in.read(bytes)) != -1) out.write(bytes, 0, n);
                    } message = "观看记录已导出";
                } else {
                    ByteArrayOutputStream buffer = new ByteArrayOutputStream();
                    try (InputStream in = getContentResolver().openInputStream(data.getData())) {
                        if (in == null) throw new IOException("无法打开文件"); byte[] bytes = new byte[8192]; int n;
                        while ((n = in.read(bytes)) != -1) {
                            if (buffer.size() + n > 16 * 1024 * 1024) throw new IOException("文件超过 16 MB"); buffer.write(bytes, 0, n);
                        }
                    }
                    int count = store.importWatches(new JSONObject(new String(buffer.toByteArray(), StandardCharsets.UTF_8)));
                    message = "已导入 " + count + " 条新记录";
                }
            } catch (Exception e) { message = "操作失败：" + e.getMessage(); }
            String finalMessage = message; runOnUiThread(() -> { if (!isDestroyed()) { toast(finalMessage); show("统计"); } });
        });
    }
    void settings() {
        LinearLayout c = card(content); c.addView(text("观看阈值", 18, INK));
        c.addView(text("快速划走阈值 · 秒", 13, MUTED));
        EditText quick = input(c, "快速划走阈值（秒）", "" + store.number("threshold", 5)); quick.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL);
        c.addView(text("自动收藏阈值 · 分钟", 13, MUTED));
        EditText favorite = input(c, "自动收藏阈值（分钟）", "" + store.number("favorite_threshold", 300) / 60); favorite.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL);
        c.addView(button("保存阈值", () -> {
            try {
                double q = Double.parseDouble(quick.getText().toString()), f = Double.parseDouble(favorite.getText().toString());
                if (!Double.isFinite(q) || q < .1 || q > 60 || !Double.isFinite(f) || f < .1 || f > 1440) throw new IllegalArgumentException();
                store.setNumber("threshold", q); store.setNumber("favorite_threshold", f * 60);
                if (SkipService.live != null) SkipService.live.settingsChanged(); toast("已保存");
            } catch (IllegalArgumentException e) { toast("快速阈值为 0.1–60 秒；收藏阈值为 0.1–1440 分钟"); }
        }));
        c.addView(text("快速划走严格低于阈值才学习；自动收藏严格超过阈值才保存。", 12, MUTED));
        LinearLayout overlay = card(content); overlay.addView(text("浮窗透明度", 18, INK));
        SeekBar opacity = new SeekBar(this); opacity.setMax(60); opacity.setProgress((int) (store.number("opacity", .88) * 100) - 40);
        opacity.setMinimumHeight(dp(48)); overlay.addView(opacity);
        opacity.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            public void onProgressChanged(SeekBar s, int p, boolean user) { if (user) { store.setNumber("opacity", (p + 40) / 100.0); if (SkipService.live != null) SkipService.live.settingsChanged(); } }
            public void onStartTrackingTouch(SeekBar s) { }
            public void onStopTrackingTouch(SeekBar s) { }
        });
        int percent = Math.max(75, Math.min(200, (int) Math.round(store.number("bubble_scale", 1) * 100)));
        TextView sizeLabel = text("折叠浮窗大小 · " + percent + "%", 18, INK); overlay.addView(sizeLabel);
        SeekBar size = new SeekBar(this); size.setMax(125); size.setProgress(percent - 75); size.setContentDescription("折叠浮窗大小");
        size.setMinimumHeight(dp(48)); overlay.addView(size);
        size.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            public void onProgressChanged(SeekBar s, int p, boolean user) {
                if (user) {
                    store.setNumber("bubble_scale", (p + 75) / 100.0); sizeLabel.setText("折叠浮窗大小 · " + (p + 75) + "%");
                    if (SkipService.live != null) SkipService.live.resizeOverlay();
                }
            }
            public void onStartTrackingTouch(SeekBar s) { }
            public void onStopTrackingTouch(SeekBar s) { }
        });
        LinearLayout help = card(content); help.addView(text("服务与手机设置", 18, INK));
        help.addView(button("无障碍服务设置", this::explainAccessibility));
        help.addView(text("华为手机：若服务被后台关闭，请在“设置 → 应用 → 应用启动管理”中找到 Auto Skip，改为手动管理并允许后台运行。\n\n抖音评论、搜索、分享或作者主页不执行自动上滑。界面无法读取时会等待，不猜测作者。\n\n没有真实视频链接时，收藏显示“未取得链接”，可编辑补填。标题相同的同名作者可能无法区分。", 13, MUTED));
        LinearLayout about = card(content); about.addView(text("关于", 18, INK));
        TextView version = text("Android 0.1.2 开发预览版\n更新：2026-10-05\nhuangyangh2004@gmail.com\n数据仅保存在本机；无需 API Key。", 14, MUTED);
        version.setTextIsSelectable(true); about.addView(version);
    }
    void confirm(String message, Runnable action) {
        new AlertDialog.Builder(this).setTitle(message).setNegativeButton("取消", null).setPositiveButton("确认", (d, w) -> action.run()).show();
    }
    void copy(String value) {
        ((android.content.ClipboardManager) getSystemService(CLIPBOARD_SERVICE)).setPrimaryClip(ClipData.newPlainText("Auto Skip 视频链接", value)); toast("已复制链接");
    }
    void toast(String message) { Toast.makeText(this, message, Toast.LENGTH_LONG).show(); }
}
