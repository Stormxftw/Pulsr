// Read-only snapshot renderer. Uses copied cached icons, never live sources or DB writes.
import {createRequire} from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
const {chromium}=createRequire(path.join(process.argv[2],'package.json'))('playwright');
const statusPath=process.env.STATUS;
if(!statusPath)throw new Error('Set STATUS to a snapshot live-status.json');
const out=process.argv[3];fs.mkdirSync(out,{recursive:true});
const origin=process.env.PULSE_PREVIEW_ORIGIN || 'http://127.0.0.1:5611';
const live=JSON.parse(fs.readFileSync(statusPath,'utf8'));
const iconDir=path.join(path.dirname(statusPath),'snapshot-data','icons');
const icons=[];
for(const p of live.pulses){
 const url=p.icon_url || p.icon_resolved?.url;
 if(!p.icon_data && /^\/icons\/(?:[0-9]{15,22}-(?:a_)?[a-f0-9]{32}|sha256-[a-f0-9]{64})$/.test(url || '')){
  const file=path.join(iconDir,path.basename(url)+'.image');
  if(fs.existsSync(file)){
   const bytes=fs.readFileSync(file);
   const type=bytes.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10]))?'image/png':bytes[0]===255&&bytes[1]===216?'image/jpeg':bytes.subarray(0,4).toString()==='RIFF'?'image/webp':null;
   if(type)p.icon_data=`data:${type};base64,${bytes.toString('base64')}`;
  }
 }
 icons.push({id:p.id,url,cachedRaster:!!p.icon_data});
}
const browser=await chromium.launch({channel:'msedge',headless:true});
const errors=[],report=[];
try{
for(const theme of ['dark','light'])for(const width of [320,480]){
 const page=await browser.newPage({viewport:{width:900,height:1400},reducedMotion:'reduce'});
 page.on('pageerror',e=>errors.push(String(e)));
 await page.route('**/*',r=>/^https?:/.test(r.request().url())&&!r.request().url().startsWith(origin+'/')?r.abort():r.continue());
 await page.goto(`${origin}/?mode=blocks&width=${width}&theme=${theme}&case=live-${theme}-${width}`);
 await page.locator('.pr-arrangement[aria-busy="false"]').waitFor();
 await page.evaluate(s=>{s.as_of=Date.now()/1000;window.__pulseStatus=s;window.__emitPulse('draft.updated');},live);await page.waitForTimeout(600);
 await page.locator('.pr-shell').screenshot({path:path.join(out,`pane-${theme}-${width}.png`)});
 if(theme==='dark'&&width===320)for(const p of live.pulses){
  const row=page.locator(`[data-id="${p.id}"]`);if(!await row.count()){report.push({id:p.id,missing:true});continue;}
  const collapsed=(await row.locator('.pr-trigger').innerText()).replace(/\s+/g,' ');
  const aria=await row.locator('.pr-trigger').getAttribute('aria-label');
  const icon=await row.locator('.pr-avatar').evaluateAll(es=>es.map(e=>({image:!!e.querySelector('img'),loaded:!!e.querySelector('img')?.naturalWidth,text:e.textContent})));
  await row.locator('.pr-trigger').click();await page.waitForTimeout(300);
  const expanded=(await row.innerText()).replace(/\s+/g,' ');await row.screenshot({path:path.join(out,`row-${p.id}.png`)});
  report.push({id:p.id,collapsed,aria,icon,expanded:expanded.slice(0,900)});await row.locator('.pr-trigger').click();
 }
 await page.close();
}
}finally{await browser.close();}
fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({errors,icons,report},null,2));
console.log(JSON.stringify({errors,icons,report},null,2));
if(errors.length)process.exitCode=1;
