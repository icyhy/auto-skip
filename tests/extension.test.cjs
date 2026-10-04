/* Integration check in an isolated headless browser, using a synthetic feed. */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');

test('content script: real DOM identity, safe switching, loops and user learning',async()=>{
  const browser=await chromium.launch({executablePath:process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
  try{
    const page=await browser.newPage({viewport:{width:1000,height:800}});
    await page.route('https://www.douyin.com/**',route=>route.fulfill({contentType:'text/html; charset=utf-8',body:`<!doctype html><html><meta charset="utf-8"><body>
      <div data-e2e="feed-active-video" class="video_1234567890123456789" style="width:700px;height:600px">
        <video style="width:600px;height:430px"></video>
        <a data-e2e="video-avatar" href="https://www.douyin.com/user/MS4_author" style="display:block;width:30px;height:30px">头像</a>
        <a href="https://www.douyin.com/user/self">我的主页</a>
        <div data-e2e="feed-video-nickname">@评测作者</div><div data-e2e="video-desc">客观评测</div>
        <button id="purchase">立即购买</button>
        <a href="https://example.com/item/123">商品链接</a>
        <a href="https://example.com/hidden" style="display:none">隐藏链接</a>
      </div><button data-e2e="video-switch-next-arrow">下一条</button><textarea></textarea>
      <script>
      window.messages=[];window.callbacks=[];window.clicks=0;
      window.chrome={runtime:{sendMessage:m=>{messages.push(m);return Promise.resolve()},onMessage:{addListener:f=>callbacks.push(f)}}};
      const v=document.querySelector('video');window.playTime=3;
      Object.defineProperties(v,{duration:{get:()=>10},currentTime:{get:()=>window.playTime},readyState:{get:()=>4},paused:{get:()=>false},ended:{get:()=>false}});
      document.querySelector('[data-e2e="video-switch-next-arrow"]').onclick=()=>{clicks++};
      </script></body></html>`}));
    await page.goto('https://www.douyin.com/');
    await page.addScriptTag({path:path.join(__dirname,'../extension/content.js')});
    let message=await page.evaluate(()=>messages.at(-1));
    assert.equal(message.video_id,'dy:video:1234567890123456789');
    assert.equal(message.author_id,'dy:author:MS4_author');
    assert.equal(message.author,'@评测作者');
    assert.equal(message.purchase,'立即购买');
    assert.equal(message.playing,true);
    assert.ok(message.links.includes('https://example.com/item/123'));
    assert.ok(!message.links.includes('https://example.com/hidden'));
    const decision={type:'decision',action:'next',token:message.token,session:`1:${message.session}`,sequence:message.sequence};
    await page.evaluate(d=>callbacks[0](d),{...decision,token:'stale'});
    assert.equal(await page.evaluate(()=>clicks),0,'stale results must not act');
    await page.evaluate(d=>{callbacks[0](d);callbacks[0](d)},decision);
    assert.equal(await page.evaluate(()=>clicks),1,'duplicate decisions must not click twice');
    await page.locator('textarea').focus();
    await page.waitForTimeout(450);
    assert.equal(await page.evaluate(()=>messages.at(-1).active),false,'editing blocks auto switching');
    await page.locator('video').click();
    await page.waitForTimeout(450);
    await page.keyboard.press('ArrowDown');
    await page.evaluate(()=>{document.querySelector('[data-e2e="feed-active-video"]').className='video_2234567890123456789';});
    await page.waitForTimeout(450);
    message=await page.evaluate(()=>messages.find(m=>m.token==='2234567890123456789'));
    assert.equal(message.user_from,'1234567890123456789','trusted keyboard navigation associates the departed video');
    await page.evaluate(()=>{document.querySelector('video').loop=true;playTime=9.8});
    await page.waitForTimeout(450);
    await page.evaluate(()=>{playTime=0.1});
    await page.waitForTimeout(450);
    assert.equal(await page.evaluate(()=>messages.at(-1).ended),true,'loop wrap counts as playback end');
  }finally{await browser.close()}
});
