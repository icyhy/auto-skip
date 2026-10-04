/* Extension replacement must leave old page scripts inert and error-free. */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');

async function feed(browser) {
  const page=await browser.newPage({viewport:{width:1000,height:800}});
  const errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('https://www.douyin.com/**',route=>route.fulfill({contentType:'text/html; charset=utf-8',body:`
    <!doctype html><html><body>
    <div data-e2e="feed-active-video" data-video-id="1234567890123456789" style="width:700px;height:600px">
      <video style="width:600px;height:430px"></video>
      <a href="https://www.douyin.com/user/MS4_author">测试作者</a>
      <div data-e2e="video-desc">测试视频标题</div>
    </div><button data-e2e="video-switch-next-arrow">下一条</button>
    <script>
    window.messages=[];window.attempts=[];window.callbacks=[];window.clicks=0;window.failure='';
    window.intervals=new Set();
    const originalInterval=window.setInterval.bind(window),originalClear=window.clearInterval.bind(window);
    window.setInterval=(...args)=>{const id=originalInterval(...args);intervals.add(id);return id};
    window.clearInterval=id=>{intervals.delete(id);originalClear(id)};
    window.chrome={runtime:{id:'test-extension',sendMessage:message=>{
      attempts.push(message.type);
      if(failure==='sync' || failure==='sync-'+message.type)throw new Error('Extension context invalidated.');
      if(failure==='async')return Promise.reject(new Error('Extension context invalidated.'));
      if(failure==='transient')return Promise.reject(new Error('Could not establish connection. Receiving end does not exist.'));
      messages.push(message);return Promise.resolve();
    },onMessage:{addListener:fn=>callbacks.push(fn),removeListener:fn=>{callbacks=callbacks.filter(item=>item!==fn)}}}};
    const v=document.querySelector('video');
    Object.defineProperties(v,{duration:{get:()=>10},currentTime:{get:()=>3},readyState:{get:()=>4},paused:{get:()=>false},ended:{get:()=>false}});
    document.querySelector('button').onclick=()=>{clicks++};
    </script></body></html>`}));
  await page.goto('https://www.douyin.com/');
  await page.addScriptTag({path:path.join(__dirname,'../extension/content.js')});
  return {page,errors};
}

test('content script stops safely when its extension context is replaced',async t=>{
  const browser=await chromium.launch({executablePath:process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
  try {
    for(const mode of ['sync','async','missing-id','inactive-snapshot','image']) {
      await t.test(mode,async()=>{
        const {page,errors}=await feed(browser);
        try {
          await page.evaluate(mode=>{
            window.staleCallback=callbacks[0];window.lastSnapshot=messages.at(-1);
            if(mode==='missing-id')chrome.runtime.id=undefined;
            else if(mode==='inactive-snapshot'){failure='sync';document.querySelector('video').remove()}
            else failure=mode==='image'?'sync-image':mode;
            if(mode==='image'){
              const canvas=document.createElement('canvas');canvas.width=1000;canvas.height=800;
              callbacks[0]({type:'crop',image:canvas.toDataURL(),token:lastSnapshot.token});
            }else document.dispatchEvent(new Event('pause'));
          },mode);
          await page.waitForFunction(()=>intervals.size===0,{},{timeout:2000});
          const stoppedAttempts=await page.evaluate(()=>attempts.length);
          await page.evaluate(()=>{
            failure='';chrome.runtime.id='replacement-extension';
            staleCallback({type:'decision',action:'next',token:lastSnapshot.token,session:'1:'+lastSnapshot.session,sequence:lastSnapshot.sequence});
            document.dispatchEvent(new Event('visibilitychange'));
            document.dispatchEvent(new Event('seeking'));
            window.dispatchEvent(new Event('focus'));
          });
          await page.waitForTimeout(450);
          assert.equal(await page.evaluate(()=>attempts.length),stoppedAttempts,'old script must not resume sending');
          assert.equal(await page.evaluate(()=>clicks),0,'old decisions must not switch videos');
          assert.equal(await page.evaluate(()=>callbacks.length),0,'runtime listener should be removed');
          assert.deepEqual(errors,[],'no uncaught exception or rejected promise');
        }finally{await page.close()}
      });
    }
    await t.test('temporary connection errors recover without stopping',async()=>{
      const {page,errors}=await feed(browser);
      try {
        await page.evaluate(()=>{failure='transient';document.dispatchEvent(new Event('pause'))});
        await page.waitForTimeout(450);
        assert.equal(await page.evaluate(()=>intervals.size),1);
        const before=await page.evaluate(()=>messages.length);
        await page.evaluate(()=>{failure=''});
        await page.waitForFunction(before=>messages.length>before,before);
        assert.deepEqual(errors,[]);
      }finally{await page.close()}
    });
  }finally{await browser.close()}
});
