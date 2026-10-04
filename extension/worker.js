/* The page cannot send native messages directly. Only our content script can. */
let port = null;
let reconnectAfter = 0;
let current = null;
let state = {connected: false, status: "请先打开 Auto Skip 桌面程序"};
const routes = new Map();

function connect() {
  if (port || Date.now() < reconnectAfter) return;
  port = chrome.runtime.connectNative("com.autoskip.bridge");
  port.onDisconnect.addListener(() => {
    const error = chrome.runtime.lastError;
    state = {connected: false, status: error ? "桌面连接未就绪，请检查扩展 ID 注册及桌面程序" : "桌面连接已断开"};
    port = null;
    reconnectAfter = Date.now() + 5000;
  });
  port.onMessage.addListener(async message => {
    state = {connected: true, status: message.status || "已连接"};
    const route = routes.get(message.request);
    if (!route) return;
    try {
      const target = await chrome.tabs.get(route.tabId);
      const window = await chrome.windows.get(target.windowId);
      if (message.action === "next" && (!target.active || !window.focused)) return;
      if (message.capture && target.active && window.focused) {
        // activeTab is granted by an explicit extension-button click, never silently.
        try {
          const image = await chrome.tabs.captureVisibleTab(target.windowId, {format: "jpeg", quality: 75});
          await chrome.tabs.sendMessage(route.tabId, {type: "crop", image, token: route.token});
        } catch (_) { /* Text analysis remains available without capture permission. */ }
      }
      await chrome.tabs.sendMessage(route.tabId, {...message, type: "decision"});
    } catch (_) { /* Tab closed or navigated away. */ }
  });
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "status" && !sender.tab) {
    sendResponse({...state, extensionId: chrome.runtime.id});
    return;
  }
  if (!sender.tab || sender.frameId !== 0 || !/^https:\/\/www\.douyin\.com\//.test(sender.url || "")) return;
  if (message.type !== "snapshot" && message.type !== "image") return;
  (async () => {
    const window = await chrome.windows.get(sender.tab.windowId);
    const tab = await chrome.tabs.get(sender.tab.id);
    const active = tab.active && window.focused;
    if (message.type === "image" && (!active || typeof message.image !== "string" || message.image.length > 700000)) return;
    if (message.type === "snapshot" && !active && current !== sender.tab.id) return;
    if (active) current = sender.tab.id;
    connect();
    if (!port) return;
    const request = crypto.randomUUID();
    for (const [key,value] of routes) if (Date.now() - value.at > 20000) routes.delete(key);
    routes.set(request, {tabId: sender.tab.id, token: message.token, at: Date.now()});
    port.postMessage({...message, source: "chrome", session: `${sender.tab.id}:${message.session}`,
      active: active && message.active === true, request});
  })().catch(() => {});
});
