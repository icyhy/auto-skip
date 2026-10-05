package com.autoskip.android;

import android.app.*;
import android.accessibilityservice.AccessibilityServiceInfo;
import android.graphics.Rect;
import android.os.Bundle;
import android.os.ParcelFileDescriptor;
import android.view.accessibility.*;
import org.json.*;

/** Inspect task-related windows without suppressing the running accessibility service. */
public final class UiRead extends Instrumentation {
    String requested;
    boolean probeSwipe;
    @Override public void onCreate(Bundle args) {
        super.onCreate(args); requested = args == null ? "" : args.getString("package", "");
        probeSwipe = args != null && "true".equals(args.getString("swipe")); start();
    }
    @Override public void onStart() {
        Bundle result = new Bundle();
        try {
            UiAutomation ui = getUiAutomation(UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES);
            AccessibilityServiceInfo info = ui.getServiceInfo();
            info.flags |= AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS | AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS;
            ui.setServiceInfo(info);
            if (probeSwipe) {
                JSONArray events = new JSONArray();
                ui.setOnAccessibilityEventListener(e -> {
                    if (e.getEventType() != AccessibilityEvent.TYPE_VIEW_SCROLLED) return;
                    AccessibilityNodeInfo node = e.getSource(); Rect b = new Rect();
                    if (node != null) node.getBoundsInScreen(b);
                    try {
                        synchronized (events) {
                            events.put(new JSONObject().put("package", String.valueOf(e.getPackageName()))
                                .put("eventClass", String.valueOf(e.getClassName())).put("sourceClass", node == null ? "null" : String.valueOf(node.getClassName()))
                                .put("bounds", b.flattenToString()).put("time", e.getEventTime()));
                        }
                    } catch (JSONException ignored) { } finally { if (node != null) node.recycle(); }
                });
                try (ParcelFileDescriptor.AutoCloseInputStream output = new ParcelFileDescriptor.AutoCloseInputStream(ui.executeShellCommand("input swipe 500 1740 500 700 250"))) {
                    while (output.read() != -1) { }
                }
                Thread.sleep(1700);
                synchronized (events) { result.putString("events", events.toString()); }
            }
            JSONArray items = new JSONArray();
            for (AccessibilityWindowInfo window : ui.getWindows()) {
                AccessibilityNodeInfo root = window.getRoot();
                if (root != null) {
                    try {
                        String pkg = String.valueOf(root.getPackageName());
                        if (pkg.equals("com.autoskip.android") || pkg.equals("com.ss.android.ugc.aweme")) {
                            if (requested.isEmpty() || requested.equals(pkg)) collect(root, items, 0);
                        }
                    } finally { root.recycle(); }
                }
                window.recycle();
            }
            result.putString("ui", items.toString()); finish(Activity.RESULT_OK, result);
        } catch (Throwable e) { result.putString("stream", "FAIL: " + e.toString()); finish(Activity.RESULT_CANCELED, result); }
    }
    void collect(AccessibilityNodeInfo n, JSONArray items, int depth) throws JSONException {
        if (depth > 45 || items.length() > 1500 || !n.isVisibleToUser()) return;
        String text = n.getText() == null ? "" : n.getText().toString();
        String desc = n.getContentDescription() == null ? "" : n.getContentDescription().toString();
        if (!text.isEmpty() || !desc.isEmpty()) {
            Rect bounds = new Rect(); n.getBoundsInScreen(bounds);
            items.put(new JSONObject().put("text", text).put("desc", desc).put("id", n.getViewIdResourceName())
                .put("bounds", bounds.flattenToString()).put("clickable", n.isClickable()).put("checked", n.isChecked()));
        }
        for (int i = 0; i < n.getChildCount(); i++) {
            AccessibilityNodeInfo child = n.getChild(i); if (child == null) continue;
            try { collect(child, items, depth + 1); } finally { child.recycle(); }
        }
    }
}
