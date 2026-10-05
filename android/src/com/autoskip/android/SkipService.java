package com.autoskip.android;

import android.accessibilityservice.*;
import android.app.KeyguardManager;
import android.content.*;
import android.graphics.*;
import android.graphics.drawable.GradientDrawable;
import android.os.*;
import android.view.*;
import android.view.accessibility.*;
import android.widget.*;
import java.util.*;
import java.io.FileDescriptor;
import java.io.PrintWriter;

public final class SkipService extends AccessibilityService {
    static final String DOUYIN = "com.ss.android.ugc.aweme";
    static SkipService live;
    final Handler handler = new Handler(Looper.getMainLooper());
    final Core.Session session = new Core.Session();
    Store store;
    boolean running, expanded, visibleFeed, pausedVideo, gestureInFlight, closed;
    String status = "已暂停", candidateToken = "", pendingToken = "", suppressedToken = "";
    long candidateAt, userScrollAt = -1, pendingAt, noticeUntil, unreadableAt = -1;
    double budget;
    final Deque<Core.Rule> undo = new ArrayDeque<>();
    final Deque<Long> undoIds = new ArrayDeque<>();
    WindowManager windows;
    WindowManager.LayoutParams overlayParams;
    LinearLayout overlay;
    TextView handle, info;
    Button toggle;
    int bubbleX, bubbleY, compactDiameter;
    Core.Video candidate;
    int scrollEvents, acceptedScrolls, confirmedChanges, learnedVideos;
    long lastScrollEventAt = -1;

    @Override protected void onServiceConnected() {
        live = this; store = new Store(this); windows = (WindowManager) getSystemService(WINDOW_SERVICE);
        running = false; expanded = false; closed = store.flag("app_closed", false);
        if (closed) status = "已退出";
        else { createOverlay(); handler.post(tick); }
    }
    @Override public void onAccessibilityEvent(AccessibilityEvent e) {
        if (!running || e.getPackageName() == null || !DOUYIN.contentEquals(e.getPackageName())) return;
        if (e.getEventType() == AccessibilityEvent.TYPE_VIEW_SCROLLED && pendingToken.isEmpty() && !gestureInFlight) {
            scrollEvents++; lastScrollEventAt = e.getEventTime();
            AccessibilityNodeInfo node = e.getSource();
            if (node != null) {
                Rect b = new Rect(); node.getBoundsInScreen(b); String cls = String.valueOf(node.getClassName()); node.recycle();
                int h = screenSize().y;
                if (b.height() > h * .75 && (cls.contains("Pager") || cls.contains("Recycler") || cls.contains("List"))
                        && SystemClock.uptimeMillis() - userScrollAt > 700) {
                    userScrollAt = e.getEventTime(); acceptedScrolls++;
                }
            }
        }
    }
    private final Runnable tick = new Runnable() {
        @Override public void run() {
            try { poll(); }
            catch (Exception e) { setRunning(false); notice("读取失败，已暂停：" + e.getClass().getSimpleName()); }
            handler.postDelayed(this, running ? 350 : 800);
        }
    };
    private void poll() throws Exception {
        PowerManager power = (PowerManager) getSystemService(POWER_SERVICE);
        KeyguardManager lock = (KeyguardManager) getSystemService(KEYGUARD_SERVICE);
        if (!power.isInteractive() || lock.isKeyguardLocked()) {
            visibleFeed = false; session.reset(); clearTransition(); budget = 0;
            if (overlay != null) overlay.setVisibility(View.GONE); return;
        }
        AccessibilityNodeInfo root = getRootInActiveWindow();
        boolean target = root != null && DOUYIN.contentEquals(root.getPackageName());
        if (root != null && !target) root.recycle();
        if (!target) {
            visibleFeed = false; if (overlay != null) overlay.setVisibility(View.GONE);
            session.reset(); clearTransition(); budget = 0; return;
        }
        if (overlay != null) overlay.setVisibility(View.VISIBLE);
        if (!running) { root.recycle(); refreshOverlay(); return; }
        if (!store.flag("listen", true) && !store.flag("auto", false) && !store.flag("favorites", true)) {
            root.recycle(); session.reset(); visibleFeed = false; status = "功能均已关闭"; refreshOverlay(); return;
        }
        ArrayList<FeedParser.Item> items = new ArrayList<>();
        try { collect(root, items, 0, new int[]{0}); } finally { root.recycle(); }
        // Node bounds use full display coordinates, including system bars.
        Point size = screenSize();
        Core.Video video = FeedParser.parse(items, size.x, size.y);
        pausedVideo = FeedParser.paused(items);
        if (video == null) {
            long now = SystemClock.uptimeMillis(); visibleFeed = false;
            if (unreadableAt < 0) unreadableAt = now;
            session.lastTick = -1; candidateToken = "";
            if (!pendingToken.isEmpty() && now - pendingAt > 3000) { setRunning(false); notice("切换未确认，已暂停"); }
            else if (pendingToken.isEmpty() && now - unreadableAt > 1800) { session.reset(); clearTransition(); budget = 0; }
            if (now > noticeUntil) status = "等待可识别的视频页";
            refreshOverlay(); return;
        }
        visibleFeed = true; unreadableAt = -1;
        long now = SystemClock.uptimeMillis(); String token = video.token();
        if (!token.equals(candidateToken)) { candidateToken = token; candidate = video; candidateAt = now; }
        else candidate = video;
        if (now - candidateAt < 450) { refreshOverlay(); return; }
        if (!pendingToken.isEmpty() && pendingToken.equals(token)) {
            if (now - pendingAt > 3000) { setRunning(false); notice("切换未确认，已暂停"); }
            refreshOverlay(); return;
        }
        boolean changed = session.current != null && !session.current.token().equals(token);
        boolean automatic = !pendingToken.isEmpty();
        boolean manual = !automatic && changed && userScrollAt >= 0 && now - userScrollAt < 3000;
        long boundary = automatic ? pendingAt : manual ? userScrollAt : now;
        // Determine the budget before saving the departing visit; current visits never predict themselves.
        if (session.current == null || changed) budget = store.budget(video);
        Core.Step step = session.observe(candidate, now, boundary, manual, store.flag("listen", true),
            store.flag("favorites", true), store.flag("listen", true) || store.flag("auto", false),
            store.number("threshold", 5), store.number("favorite_threshold", 300), !pausedVideo);
        if (step.finished != null) store.watch(step.finished, step.seconds);
        if (step.learned != null) { learnedVideos++; remember("video", step.learned); notice("已记住快速划走的视频"); }
        if (step.favorite != null && store.favorite(step.favorite, step.favoriteSeconds)) notice("已加入本机收藏");
        if (changed) { confirmedChanges++; pendingToken = ""; userScrollAt = -1; suppressedToken = ""; }
        if (store.flag("auto", false) && !token.equals(suppressedToken)) {
            for (Core.Rule rule : store.rules()) if (rule.matches(candidate)) { next("命中黑名单"); return; }
            if (store.flag("history", false) && budget > 0 && session.elapsed(now) >= budget) { next("达到历史观看时长"); return; }
        }
        if (now > noticeUntil) status = "运行中 · " + (pausedVideo ? "视频已暂停" : "继续观看") + (session.favoriteSaved ? " · 已收藏" : "");
        refreshOverlay();
    }
    private void collect(AccessibilityNodeInfo n, List<FeedParser.Item> out, int depth, int[] count) {
        if (depth > 45 || ++count[0] > 2500 || !n.isVisibleToUser()) return;
        Rect b = new Rect(); n.getBoundsInScreen(b);
        if (n.isEditable() && n.isFocused()) out.add(new FeedParser.Item("__autoskip_editing__", "", b.left, b.top, b.right, b.bottom));
        CharSequence text = n.getText(), desc = n.getContentDescription();
        if (text != null && text.length() > 0) out.add(new FeedParser.Item(text.toString(), n.getViewIdResourceName(), b.left, b.top, b.right, b.bottom));
        if (desc != null && desc.length() > 0 && !desc.equals(text)) out.add(new FeedParser.Item(desc.toString(), n.getViewIdResourceName(), b.left, b.top, b.right, b.bottom));
        for (int i = 0; i < n.getChildCount(); i++) {
            AccessibilityNodeInfo child = n.getChild(i); if (child == null) continue;
            try { collect(child, out, depth + 1, count); } finally { child.recycle(); }
        }
    }
    void setRunning(boolean value) {
        running = value; session.reset(); clearTransition(); budget = 0;
        status = value ? "等待视频画面" : "已暂停"; noticeUntil = 0; refreshOverlay();
    }
    void settingsChanged() { session.reset(); clearTransition(); budget = 0; refreshOverlay(); }
    void close() {
        setRunning(false); closed = true; status = "已退出"; store.setFlag("app_closed", true);
        handler.removeCallbacksAndMessages(null);
        if (overlay != null) windows.removeView(overlay);
        overlay = null; handle = info = null; toggle = null;
    }
    void wake() {
        if (!closed) return;
        closed = false; expanded = false; status = "已暂停"; store.setFlag("app_closed", false);
        createOverlay(); handler.post(tick);
    }
    private void clearTransition() {
        candidateToken = pendingToken = suppressedToken = ""; candidate = null; userScrollAt = -1;
        unreadableAt = -1; gestureInFlight = false;
    }
    private boolean ready() {
        if (!running || !visibleFeed || session.current == null || SystemClock.uptimeMillis() - session.lastTick > 1500) {
            notice("请开始后返回可识别的抖音视频页"); return false;
        }
        return true;
    }
    private void remember(String kind, Core.Video video) {
        Core.Rule r = Core.blockRule(kind, video);
        Core.Rule previous = store.duplicate(r);
        if (previous != null) { r.id = previous.id; r.enabled = true; }
        long id = store.saveRule(r); undoIds.push(id); undo.push(previous == null ? new Core.Rule() : previous);
        while (undo.size() > 30) { undo.removeLast(); undoIds.removeLast(); }
    }
    void block(String kind) {
        if (!ready()) return;
        try { remember(kind, session.current); next("已拉黑" + (kind.equals("author") ? "作者" : "视频")); }
        catch (IllegalArgumentException e) { notice(e.getMessage()); }
    }
    void undoBlock() {
        if (undo.isEmpty()) { notice("没有可撤销的拉黑记录"); return; }
        Core.Rule previous = undo.pop(); long id = undoIds.pop();
        if (previous.id == 0) store.delete("rules", id); else store.saveRule(previous);
        suppressedToken = session.current == null ? "" : session.current.token(); notice("已撤销最近一次拉黑");
    }
    void reparse() { candidateToken = ""; notice("正在重新读取当前视频"); }
    private void next(String reason) {
        if (!ready() || !pendingToken.isEmpty() || gestureInFlight) return;
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) { setRunning(false); notice("视频页已离开，已暂停"); return; }
        boolean target = DOUYIN.contentEquals(root.getPackageName()); root.recycle();
        if (!target) return;
        Point size = screenSize(); float w = size.x, h = size.y;
        Path path = new Path(); path.moveTo(w * .45f, h * .72f); path.lineTo(w * .45f, h * .28f);
        GestureDescription gesture = new GestureDescription.Builder().addStroke(new GestureDescription.StrokeDescription(path, 0, 280)).build();
        gestureInFlight = true; pendingToken = session.current.token(); pendingAt = SystemClock.uptimeMillis();
        boolean accepted = dispatchGesture(gesture, new GestureResultCallback() {
            @Override public void onCompleted(GestureDescription g) { gestureInFlight = false; }
            @Override public void onCancelled(GestureDescription g) { setRunning(false); notice("上滑被中断，已暂停"); }
        }, handler);
        if (!accepted) { setRunning(false); notice("无法执行上滑，已暂停"); }
        else notice(reason + " · 上滑下一条");
    }
    void notice(String text) { status = text; noticeUntil = SystemClock.uptimeMillis() + 3500; refreshOverlay(); }
    private int dp(float n) { return Math.round(n * getResources().getDisplayMetrics().density); }
    private float bubbleScale() { return (float) Math.max(.75, Math.min(2, store.number("bubble_scale", 1))); }
    private int panelOffset() { return (dp(172) - compactDiameter) / 2; }
    void resizeOverlay() {
        if (overlay == null) return;
        bubbleX += (compactDiameter - dp(24 * bubbleScale())) / 2;
        rebuildOverlay();
        store.settings.edit().putInt("bubble_x", bubbleX).putInt("bubble_y", bubbleY).apply();
    }
    private Point screenSize() {
        Point size = new Point(); windows.getDefaultDisplay().getRealSize(size); return size;
    }
    private Button button(String text, Runnable action) {
        Button b = new Button(this); b.setText(text); b.setTextSize(12); b.setMinHeight(dp(44));
        b.setPadding(dp(6), 0, dp(6), 0); b.setOnClickListener(v -> action.run()); return b;
    }
    private void createOverlay() {
        compactDiameter = dp(24 * bubbleScale());
        overlay = new LinearLayout(this); overlay.setOrientation(LinearLayout.VERTICAL);
        overlay.setGravity(Gravity.CENTER_HORIZONTAL); overlay.setClipChildren(false);
        overlayParams = new WindowManager.LayoutParams(compactDiameter, WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE | WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL, PixelFormat.TRANSLUCENT);
        overlayParams.gravity = Gravity.TOP | Gravity.LEFT;
        // Preserve the old panel's horizontal center when migrating to the small button.
        bubbleX = store.settings.getInt("bubble_x", store.settings.getInt("overlay_x", dp(12)) + panelOffset());
        bubbleY = store.settings.getInt("bubble_y", store.settings.getInt("overlay_y", dp(160)));
        rebuildOverlay(); windows.addView(overlay, overlayParams);
    }
    private void draggable(View view, Runnable tap) {
        view.setOnClickListener(v -> tap.run());
        view.setOnTouchListener(new View.OnTouchListener() {
            float x, y; int startX, startY; boolean moved;
            public boolean onTouch(View view, MotionEvent e) {
                if (e.getActionMasked() == MotionEvent.ACTION_DOWN) { x = e.getRawX(); y = e.getRawY(); startX = overlayParams.x; startY = overlayParams.y; moved = false; }
                if (e.getActionMasked() == MotionEvent.ACTION_MOVE) {
                    float dx = e.getRawX() - x, dy = e.getRawY() - y;
                    if (Math.abs(dx) + Math.abs(dy) > dp(8)) moved = true;
                    if (moved) {
                        bubbleX = startX + (int) dx + (expanded ? panelOffset() : 0); bubbleY = startY + (int) dy;
                        positionOverlay();
                        bubbleX = overlayParams.x + (expanded ? panelOffset() : 0); bubbleY = overlayParams.y;
                        windows.updateViewLayout(overlay, overlayParams);
                    }
                }
                if (e.getActionMasked() == MotionEvent.ACTION_UP) {
                    if (!moved) view.performClick();
                    store.settings.edit().putInt("bubble_x", bubbleX).putInt("bubble_y", bubbleY).apply();
                }
                return true;
            }
        });
    }
    private void positionOverlay() {
        overlayParams.width = expanded ? dp(172) : compactDiameter;
        Point size = screenSize();
        overlayParams.x = Math.max(0, Math.min(size.x - overlayParams.width, bubbleX - (expanded ? panelOffset() : 0)));
        int bar = getResources().getIdentifier("status_bar_height", "dimen", "android");
        int top = bar == 0 ? dp(24) : getResources().getDimensionPixelSize(bar);
        int available = getResources().getDisplayMetrics().heightPixels - top;
        float scale = bubbleScale();
        int height = expanded ? dp(344) : compactDiameter + dp(12 * scale) - dp(3 * scale);
        overlayParams.y = Math.max(0, Math.min(available - height, bubbleY));
    }
    private GradientDrawable circle(int color) {
        GradientDrawable bg = new GradientDrawable(); bg.setShape(GradientDrawable.OVAL); bg.setColor(color); return bg;
    }
    private void rebuildOverlay() {
        float scale = bubbleScale(); compactDiameter = dp(24 * scale);
        overlay.removeAllViews(); handle = info = null;
        if (expanded) {
            overlay.setPadding(dp(8), dp(3), dp(8), dp(5));
            GradientDrawable bg = new GradientDrawable(); bg.setColor(Color.rgb(244, 250, 251)); bg.setCornerRadius(dp(16));
            bg.setStroke(dp(1), Color.rgb(8, 127, 140)); overlay.setBackground(bg); overlay.setElevation(dp(8));
            handle = new TextView(this); handle.setTextSize(12); handle.setTextColor(Color.rgb(8, 127, 140));
            handle.setGravity(Gravity.CENTER); handle.setMinHeight(dp(44)); handle.setContentDescription("拖动面板；点按收起");
            draggable(handle, () -> { expanded = false; rebuildOverlay(); }); overlay.addView(handle, new LinearLayout.LayoutParams(-1, -2));
            toggle = button("", () -> setRunning(!running)); overlay.addView(toggle, new LinearLayout.LayoutParams(-1, -2));
            info = new TextView(this); info.setTextSize(11); info.setTextColor(Color.DKGRAY); info.setMaxLines(5);
            overlay.addView(info, new LinearLayout.LayoutParams(-1, dp(100)));
            LinearLayout row = new LinearLayout(this);
            row.addView(button("拉黑作者", () -> block("author")), new LinearLayout.LayoutParams(0, dp(48), 1));
            row.addView(button("拉黑视频", () -> block("video")), new LinearLayout.LayoutParams(0, dp(48), 1)); overlay.addView(row);
            LinearLayout second = new LinearLayout(this);
            second.addView(button("重读", this::reparse), new LinearLayout.LayoutParams(0, dp(48), 1));
            second.addView(button("撤销", this::undoBlock), new LinearLayout.LayoutParams(0, dp(48), 1)); overlay.addView(second);
            overlay.addView(button("规则 / 收藏 / 设置", () -> startActivity(new Intent(this, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))), new LinearLayout.LayoutParams(-1, -2));
        } else {
            overlay.setPadding(0, 0, 0, 0); overlay.setBackground(null); overlay.setElevation(0);
            toggle = button("", () -> setRunning(!running));
            toggle.setPadding(0, 0, 0, 0); toggle.setMinWidth(0); toggle.setMinimumWidth(0); toggle.setMinHeight(0); toggle.setMinimumHeight(0);
            toggle.setIncludeFontPadding(false); toggle.setTextSize(12 * scale);
            GradientDrawable bg = circle(Color.WHITE); bg.setStroke(dp(1), Color.rgb(8, 127, 140)); toggle.setBackground(bg);
            draggable(toggle, () -> setRunning(!running)); overlay.addView(toggle, new LinearLayout.LayoutParams(compactDiameter, compactDiameter));
            Button expand = button("▾", () -> { expanded = true; rebuildOverlay(); });
            expand.setPadding(0, 0, 0, 0); expand.setMinWidth(0); expand.setMinimumWidth(0); expand.setMinHeight(0); expand.setMinimumHeight(0);
            expand.setIncludeFontPadding(false); expand.setTextSize(10 * scale); expand.setTextColor(Color.WHITE); expand.setBackground(circle(Color.rgb(8, 127, 140)));
            expand.setContentDescription("展开 Auto Skip 控制面板");
            LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(dp(14 * scale), dp(12 * scale)); p.topMargin = -dp(3 * scale); overlay.addView(expand, p);
        }
        positionOverlay();
        if (overlay.isAttachedToWindow()) windows.updateViewLayout(overlay, overlayParams);
        refreshOverlay();
    }
    private void refreshOverlay() {
        if (overlay == null || toggle == null) return;
        String action = expanded ? (running ? "暂停" : "开始") : (running ? "Ⅱ" : "▶");
        if (!action.contentEquals(toggle.getText())) {
            toggle.setText(action);
            if (!expanded) {
                ((GradientDrawable) toggle.getBackground()).setColor(running ? Color.rgb(8, 127, 140) : Color.WHITE);
                toggle.setTextColor(running ? Color.WHITE : Color.rgb(8, 127, 140));
            }
        }
        String description = (running ? "暂停" : "开始") + " Auto Skip · " + status;
        if (!description.equals(String.valueOf(toggle.getContentDescription()))) toggle.setContentDescription(description);
        if (expanded) {
            if (!"Auto Skip  ·  收起 ▴".contentEquals(handle.getText())) handle.setText("Auto Skip  ·  收起 ▴");
            String meta = session.current == null ? "" : "\n@" + session.current.author + "\n" + session.current.title;
            if (!(status + meta).contentEquals(info.getText())) {
                info.setText(status + meta); info.setContentDescription(status + meta);
            }
        }
        overlay.setAlpha((float) store.number("opacity", .88));
    }
    @Override public void onInterrupt() { setRunning(false); }
    @Override protected void dump(FileDescriptor fd, PrintWriter writer, String[] args) {
        long now = SystemClock.uptimeMillis();
        writer.println("running=" + running + " closed=" + closed + " overlay=" + (overlay != null)
            + " scale=" + bubbleScale() + " listen=" + store.flag("listen", true) + " current=" + (session.current != null)
            + " started=" + session.started + " now=" + now + " scrollAt=" + userScrollAt + " lastScrollEvent=" + lastScrollEventAt);
        writer.println("scrollEvents=" + scrollEvents + " acceptedScrolls=" + acceptedScrolls
            + " confirmedChanges=" + confirmedChanges + " learnedVideos=" + learnedVideos);
    }
    @Override public void onDestroy() {
        handler.removeCallbacksAndMessages(null); live = null;
        if (overlay != null) windows.removeView(overlay);
        if (store != null) store.close(); super.onDestroy();
    }
}
