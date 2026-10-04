document.querySelector("#id").textContent=chrome.runtime.id;
chrome.runtime.sendMessage({type:"status"}, state=>{
  document.querySelector("#status").textContent=state?.status || "请先打开 Auto Skip 桌面程序";
});
