// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

/* Exercise the packaged observer in an isolated Chromium profile using CDP. */
const fs=require('node:fs');
const path=require('node:path');
const {spawn}=require('node:child_process');
const assert=require('node:assert/strict');
const {setTimeout:delay}=require('node:timers/promises');
const report=path.resolve(process.argv[2]);
const folder=path.dirname(report);
const profile=path.join(folder,'browser-profile');
const url=fs.readFileSync(0,'utf8').trim();
const candidates=[path.join(process.env.ProgramFiles,'Google/Chrome/Application/chrome.exe'),
  path.join(process.env['ProgramFiles(x86)'],'Microsoft/Edge/Application/msedge.exe')];
const binary=candidates.find(fs.existsSync);
assert.ok(binary,'Local Chromium browser required');

async function until(fn,message){
  const stop=Date.now()+20000;
  while(Date.now()<stop){const v=await fn();if(v)return v;await delay(100);}
  throw Error(message);
}
(async()=>{
  const browser=spawn(binary,['--headless=new','--no-first-run','--disable-background-networking','--disable-component-update',
    '--enable-unsafe-swiftshader','--use-angle=swiftshader','--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'],
    {stdio:'ignore',windowsHide:true});
  let socket;
  const errors=[],httpErrors=[];
  try{
    const portFile=path.join(profile,'DevToolsActivePort');
    const port=await until(()=>fs.existsSync(portFile)&&fs.readFileSync(portFile,'utf8').split('\n')[0],'Browser startup timed out');
    const targets=await(await fetch('http://127.0.0.1:'+port+'/json/list')).json();
    socket=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);
    await new Promise((ok,no)=>{socket.onopen=ok;socket.onerror=no;});
    let seq=0;const waiting=new Map();
    socket.onmessage=({data})=>{
      const m=JSON.parse(data);
      if(m.id){const [ok,no]=waiting.get(m.id)||[];waiting.delete(m.id);if(m.error)no?.(Error(m.error.message));else ok?.(m.result);}
      if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.exception?.description||m.params.exceptionDetails.text);
      if(m.method==='Network.responseReceived'&&m.params.response.status>=400&&m.params.response.url.includes('/observe/api/'))httpErrors.push(m.params.response.status);
    };
    function send(method,params={}){
      const id=++seq;
      return new Promise((ok,no)=>{waiting.set(id,[ok,no]);socket.send(JSON.stringify({id,method,params}));});
    }
    async function run(expression){
      const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
      if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);
      return r.result.value;
    }
    await send('Runtime.enable');await send('Network.enable');await send('Page.enable');
    await send('Emulation.setDeviceMetricsOverride',{width:1500,height:900,deviceScaleFactor:1,mobile:false});
    await send('Page.navigate',{url});
    const licenses=await require('./check_legal_ui.cjs')(run,send,until,async()=>{
      const image=await send('Page.captureScreenshot',{format:'png'});
      fs.writeFileSync(path.join(folder,'licenses.png'),Buffer.from(image.data,'base64'));
    });
    assert.ok(await run("Array.from(document.images).some(img => img.getAttribute('src') === '/favicon.svg' && img.complete && img.naturalWidth > 0)"));
    assert.ok(await run("document.querySelector('link[rel=icon][type=\"image/svg+xml\"]').href.endsWith('/favicon.svg')"));
    if(process.argv[3]==='--licenses'){
      assert.deepEqual(errors,[]);
      fs.writeFileSync(report,JSON.stringify({ok:true,version:require('../frontend/package.json').version,pageErrors:errors,httpErrors,licenses}));
      await send('Browser.close');
      return;
    }
    await until(()=>run("document.querySelectorAll('.study-run').length === 4"),'Observer did not display four real runs');
    await run("[...document.querySelectorAll('.study-run')].find(b=>b.textContent.includes('reference')).click()");
    await until(()=>run("!!document.querySelector('.study-geometry canvas') && !!document.querySelector('.study-chart svg')"),'Missing detector geometry or measured spectrum');
    const shot=await send('Page.captureScreenshot',{format:'png'});
    fs.writeFileSync(path.join(folder,'observer.png'),Buffer.from(shot.data,'base64'));
    await run("[...document.querySelectorAll('button')].find(b=>b.textContent==='Run settings').click()");
    await until(()=>run("!!document.querySelector('.study-settings details')"),'Settings inspection failed');
    assert.equal(await run("document.querySelectorAll('.study-settings input,.study-settings select,.study-settings textarea').length"),0);
    await run("[...document.querySelectorAll('.study-run')].find(b=>b.textContent.includes('lifetime')).click()");
    await run("[...document.querySelectorAll('button')].find(b=>b.textContent==='Measurement').click()");
    await until(()=>run("!!document.querySelector('.study-chart') && document.querySelector('article').textContent.includes('Pairs analyzed')"),'M3 measurement missing');
    await send('Emulation.setDeviceMetricsOverride',{width:390,height:820,deviceScaleFactor:1,mobile:true});
    assert.ok(await run("document.documentElement.scrollWidth <= innerWidth+2"),'Horizontal overflow on narrow screen');
    assert.equal(await run("location.hash"),'');
    assert.deepEqual(errors,[]);assert.deepEqual(httpErrors,[]);
    fs.writeFileSync(report,JSON.stringify({ok:true,version:require('../frontend/package.json').version,pageErrors:errors,httpErrors,licenses,
      checks:['Four runs','Pinned run','Real detector geometry and measured spectrum','Read-only settings','M3 detail','390 px layout']})); 
    await send('Browser.close');
  }finally{
    socket?.close();
    if(browser.exitCode===null){await Promise.race([new Promise(ok=>browser.once('exit',ok)),delay(2500)]);}
    if(browser.exitCode===null)browser.kill();
  }
})().catch(e=>{console.error(e);process.exitCode=1;});

