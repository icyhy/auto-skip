(() => {
  "use strict";
  const session = crypto.randomUUID();
  let previous = null, navigation = null, sent = "", endedToken = "";
  let previousTime = 0, previousDuration = 0, sequence = 0, lastDecision = -1;
  const stamps = new WeakMap();
  function visible(el) {
    if (!el) return false;
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 1 && r.height > 1 && r.bottom > 0 && r.top < innerHeight &&
      r.right > 0 && r.left < innerWidth && s.display !== "none" && s.visibility !== "hidden" && s.opacity !== "0";
  }
  function video() {
    return [...document.querySelectorAll("video")].filter(visible).sort((a,b) => {
      const area = v => { const r=v.getBoundingClientRect(); return Math.max(0,Math.min(r.bottom,innerHeight)-Math.max(r.top,0))*Math.max(0,Math.min(r.right,innerWidth)-Math.max(r.left,0)); };
      return area(b)-area(a);
    })[0];
  }
  function root(v) {
    const known = v.closest('[data-e2e="feed-active-video"], [data-e2e="feed-video"], [data-e2e="recommend-list-item-container"], [data-e2e="video-detail"], [data-e2e="feed-item"]');
    if (known && known !== document.body) return known;
    let p = v.parentElement;
    // Bounded to the single player: never collect the entire feed/sidebar.
    for (let i=0; p && i<5; i++,p=p.parentElement) {
      if (p === document.body || p.querySelectorAll("video").length > 1) break;
      if (p.querySelector('a[href*="/user/"]')) return p;
    }
    return v.parentElement;
  }
  function idFromLink(container, kind) {
    const links = [...container.querySelectorAll(`a[href*="/${kind}/"]`)].filter(visible);
    const values = new Set(links.map(a => {
      try { const u = new URL(a.href); return u.hostname === "www.douyin.com" ? u.pathname.match(new RegExp(`^/${kind}/([A-Za-z0-9_-]+)`))?.[1] : null; } catch (_) { return null; }
    }).filter(value => value && !(kind === "user" && ["self","me"].includes(value))));
    return values.size === 1 ? [...values][0] : "";
  }
  function observe() {
    const v=video();
    if (!v) return null;
    const scope=root(v);
    if (!scope) return null;
    let videoId=idFromLink(scope,"video");
    if (!videoId) {
      const explicit=scope.getAttribute("data-aweme-id") || scope.getAttribute("data-video-id");
      if (/^\d{10,30}$/.test(explicit || "")) videoId=explicit;
    }
    if (!videoId) videoId=[...scope.classList].map(c=>c.match(/^video_(\d{10,30})$/)?.[1]).find(Boolean) || "";
    if (!videoId) {
      const path=location.pathname.match(/^\/video\/(\d+)/);
      if (path && document.querySelectorAll("video").length === 1) videoId=path[1];
    }
    const authorId=idFromLink(scope,"user");
    const authorNode=[...scope.querySelectorAll('a[href*="/user/"]')].find(a=>visible(a) && !/\/user\/(self|me)(?:[/?#]|$)/.test(a.href));
    const titleNode=scope.querySelector('[data-e2e="video-desc"], [data-e2e="video-title"], [data-e2e="feed-desc"]');
    const author=(scope.querySelector('[data-e2e="feed-video-nickname"]')?.innerText || authorNode?.innerText || "").trim();
    const title=(titleNode?.innerText || "").trim().slice(0,1000);
    if (!stamps.has(v)) stamps.set(v,crypto.randomUUID());
    // A session token can identify the current player without claiming a persistent ID.
    const token=videoId || `${stamps.get(v)}:${v.currentSrc || v.src}:${authorId}:${title}`;
    const purchaseNodes=[...scope.querySelectorAll('a,button,[role="button"],[data-e2e*="product"],[data-e2e*="shopping"]')].filter(visible);
    const purchase=purchaseNodes.map(n=>(n.innerText || n.getAttribute("aria-label") || "").trim())
      .find(t => /^(?:立即购买|立即下单|去购买|购买同款|查看商品|商品橱窗|小黄车|领券购买)(?:\s|$)/.test(t) && t.length < 100) || "";
    const active=document.visibilityState === "visible" &&
      !document.querySelector('input:focus,textarea:focus,[contenteditable="true"]:focus') &&
      ![...document.querySelectorAll('[role="dialog"]')].some(visible);
    return {v, scope, source:"chrome",session,token,video_id:videoId ? `dy:video:${videoId}` : "",
      author_id:authorId ? `dy:author:${authorId}` : "",author,title,
      links:[...new Set([...scope.querySelectorAll('a[href]')].filter(visible).map(a=>a.href)
        .filter(url=>/^https?:\/\//i.test(url)))].join("\n").slice(0,8000),
      text:scope.innerText?.slice(0,8000) || "", purchase, active,
      playing:!v.paused && !v.ended && !v.seeking && v.readyState>=3,
      timing:Number.isFinite(v.duration) && v.duration>0, ended:v.ended};
  }
  function report() {
    if (navigation && performance.now()-navigation.at>1500) navigation=null;
    const item=observe();
    if (!item) {
      if (previous) chrome.runtime.sendMessage({...previous,type:"snapshot",active:false,sequence:++sequence}).catch(()=>{});
      previous=null; return;
    }
    if (previous?.token !== item.token) {
      item.user_from=navigation && navigation.token===previous?.token && performance.now()-navigation.at<1500 ? navigation.token : "";
      sent="";endedToken="";previousTime=0;previousDuration=0;navigation=null;
    } else {
      item.user_from="";
      // Looping media does not fire ended. Require a known end->start wrap with no seek.
      if (item.active && item.v.loop && !item.v.paused && !item.v.seeking && previousDuration>0 && previousTime>=previousDuration-0.7 &&
          item.v.currentTime<0.7 && previousTime-item.v.currentTime>1 && !navigation) endedToken=item.token;
    }
    previousTime=item.v.currentTime;previousDuration=item.v.duration;
    if (endedToken===item.token) item.ended=true;
    const {v,scope,...data}=item;
    data.sequence=++sequence;
    previous=data;
    chrome.runtime.sendMessage({...data,type:"snapshot"}).catch(()=>{});
  }
  function intent(event) {
    if (!event.isTrusted || !previous?.active) return;
    if (event.target.closest?.('input,textarea,[contenteditable="true"],[data-e2e*="comment"]')) return;
    const item=observe();
    if (!item) return;
    if (event.type==="wheel") {
      const r=item.v.getBoundingClientRect();
      if (event.deltaY<=0 || event.clientX<r.left || event.clientX>r.right || event.clientY<r.top || event.clientY>r.bottom) return;
    } else if (event.key!=="ArrowDown" || event.ctrlKey || event.altKey || event.metaKey) return;
    navigation={token:item.token,at:performance.now()};
  }
  addEventListener("wheel",intent,{capture:true,passive:true});
  addEventListener("keydown",intent,true);
  document.addEventListener("visibilitychange",report);
  addEventListener("blur",report);addEventListener("focus",report);
  document.addEventListener("pause",report,true);
  document.addEventListener("ended",report,true);
  document.addEventListener("seeking",()=>{navigation={token:"seek",at:performance.now()};endedToken="";},true);
  chrome.runtime.onMessage.addListener(message => {
    if (message.type==="crop") {
      const item=observe();
      if (!item?.active || item.token!==message.token) return;
      const bounds=item.scope.getBoundingClientRect();
      const img=new Image();img.onload=()=>{
        const live=observe();if (!live?.active || live.token!==message.token) return;
        const scale=img.width/innerWidth;
        const x=Math.max(0,bounds.left),y=Math.max(0,bounds.top),w=Math.min(innerWidth,bounds.right)-x,h=Math.min(innerHeight,bounds.bottom)-y;
        if (w<2||h<2)return;
        const out=document.createElement("canvas"),factor=Math.min(1,960/w,960/h);
        out.width=w*factor;out.height=h*factor;
        out.getContext("2d").drawImage(img,x*scale,y*scale,w*scale,h*scale,0,0,out.width,out.height);
        chrome.runtime.sendMessage({type:"image",session,token:live.token,active:true,image:out.toDataURL("image/jpeg",0.75)}).catch(()=>{});
      };img.src=message.image;return;
    }
    if (message.type!=="decision" || message.action!=="next") return;
    const item=observe();
    if (!item?.active || item.token!==message.token || sent===item.token || message.sequence<lastDecision) return;
    if (!message.session?.endsWith(`:${session}`)) return;
    lastDecision=message.sequence;
    sent=item.token;
    navigation=null;
    const next=[...document.querySelectorAll('[data-e2e="video-switch-next-arrow"],[aria-label="下一个视频"],[aria-label="下一条"],[title="下一条"]')].find(visible);
    if (next) next.click();
    else document.dispatchEvent(new KeyboardEvent("keydown",{key:"ArrowDown",code:"ArrowDown",keyCode:40,which:40,bubbles:true}));
    report();
  });
  setInterval(report,400);
  report();
})();
