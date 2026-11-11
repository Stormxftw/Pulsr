// Synthetic local preview capture; never contacts a live Hermes session.
// CDP captures actual frames; the existing ffmpeg encodes measured timing.
import {spawnSync} from 'node:child_process';
import {createRequire} from 'node:module';
import path from 'node:path';
import fs from 'node:fs';
const req = createRequire(path.join(process.argv[2], 'package.json'));
const {chromium} = req('playwright');
const out = process.argv[3];
const origin = process.env.PULSE_PREVIEW_ORIGIN || 'http://127.0.0.1:5442';
fs.mkdirSync(out,{recursive:true});
const browser = await chromium.launch({channel:'msedge',headless:true});
let context;
try {
  context = await browser.newContext({viewport:{width:760,height:640}});
  const page = await context.newPage();
  const remote=[];
  await page.route('**/*', route => {
    const url=route.request().url();
    if(/^https?:/.test(url)&&!url.startsWith(origin+'/')){remote.push(url);return route.abort();}
    return route.continue();
  });
  await page.goto(`${origin}/?mode=sessions&width=320&case=motion-capture`);
  await page.locator('.pr-session[data-state="Working"]').waitFor();
  await page.mouse.move(0,0);
  const frameDir=path.join(out,'frames');fs.mkdirSync(frameDir,{recursive:true});
  const cdp=await context.newCDPSession(page), frames=[], phases=[];
  cdp.on('Page.screencastFrame',event=>{
    const filename=`frame-${String(frames.length).padStart(5,'0')}.jpg`;
    fs.writeFileSync(path.join(frameDir,filename),Buffer.from(event.data,'base64'));
    frames.push({filename,timestamp:event.metadata.timestamp});
    void cdp.send('Page.screencastFrameAck',{sessionId:event.sessionId});
  });
  await cdp.send('Page.startScreencast',{format:'jpeg',quality:90,maxWidth:760,maxHeight:640,everyNthFrame:1});
  const phase=async name=>phases.push({name,browserTimestamp:await page.evaluate(()=>performance.timeOrigin/1000+performance.now()/1000)});
  await phase('Working');
  await page.waitForTimeout(2800);
  await phase('Tool ripple');await page.evaluate(()=>window.__sessionTool());
  await page.waitForTimeout(2800);
  await page.evaluate(()=>{
    const target=document.querySelector('.pr-session[data-state="Working"]');
    const observer=new MutationObserver(()=>{
      if(target.dataset.state==='Done'){
        window.__doneRenderedAt=performance.timeOrigin/1000+performance.now()/1000;observer.disconnect();
      }
    });
    observer.observe(target,{attributes:true,attributeFilter:['data-state']});
  });
  await phase('Done tick');await page.evaluate(()=>window.__sessionDone());
  await page.waitForTimeout(2200);
  const doneRenderedAt=await page.evaluate(()=>window.__doneRenderedAt);
  if(!doneRenderedAt)throw Error('Completion DOM transition was not observed');
  await phase('Collapsed group');await page.locator('#hermes-sessions .pr-group-toggle').click();
  await page.mouse.move(0,0);
  await page.waitForTimeout(1400);
  const captureEnd=await page.evaluate(()=>performance.timeOrigin/1000+performance.now()/1000);
  await cdp.send('Page.stopScreencast');
  // CDP can deliver frames out of presentation order. Encode by the browser's
  // timestamps, not arrival order; retain the final still through captureEnd.
  frames.sort((a,b)=>a.timestamp-b.timestamp);
  for(let i=frames.length-1;i>0;i--)if(frames[i].timestamp===frames[i-1].timestamp)frames.splice(i,1);
  if(frames.length<12)throw Error(`Only ${frames.length} actual frames captured`);
  // Reopen after the real-time recording and sample the actual CSS animation
  // at controlled offsets. PNG row captures expose the first check without
  // CDP's occasional stale compositor frame or JPEG softness.
  await page.locator('#hermes-sessions .pr-group-toggle').click();
  const doneRow=page.locator('.pr-session[data-id="session:'+ 'a'.repeat(64) +'"]');
  await doneRow.locator('.pr-session-tick').waitFor();
  const tickFrames=[];
  for(const ms of [0,40,80,140,220,350,500,650]){
    await doneRow.locator('.pr-session-tick').evaluate((e,ms)=>{
      const animation=e.getAnimations()[0];
      if(!animation)throw Error('Done tick animation is missing');
      animation.pause();animation.currentTime=ms;
    },ms);
    const filename=`done-${ms}.png`;
    await doneRow.screenshot({path:path.join(out,filename)});
    tickFrames.push({filename,ms});
  }
  const strip=await context.newPage();
  await strip.setViewportSize({width:720,height:520});
  await strip.setContent('<body style="margin:0;background:#16201c;color:#dae9df;font:12px system-ui"><p style="margin:12px">Done tick · actual renderer PNGs · controlled CSS timeline offsets · synthetic local feed · native scale</p><main style="display:grid;grid-template-columns:repeat(2,1fr);gap:12px;padding:12px"></main></body>');
  await strip.evaluate(async frames=>{
    for(const frame of frames){
      const card=document.createElement('div'),label=document.createElement('div');label.textContent=frame.ms+'ms';card.append(label);
      const img=new Image();img.src=frame.src;await img.decode();img.style.display='block';card.append(img);document.querySelector('main').append(card);
    }
  },tickFrames.map(f=>({...f,src:'data:image/png;base64,'+fs.readFileSync(path.join(out,f.filename)).toString('base64')})));
  await strip.screenshot({path:path.join(out,'done-frame-strip.png'),fullPage:true});
  await strip.close();
  const concat=[];
  for(let i=0;i<frames.length;i++){
    concat.push(`file '${frames[i].filename}'`);
    concat.push(`duration ${Math.max(.001,(frames[i+1]?.timestamp??captureEnd)-frames[i].timestamp)}`);
  }
  concat.push(`file '${frames.at(-1).filename}'`);
  const timeline=path.join(frameDir,'timeline.txt');fs.writeFileSync(timeline,concat.join('\n')+'\n');
  const destination=path.join(out,'session-motion.webm');
  const encoded=spawnSync(process.env.PULSE_FFMPEG||'ffmpeg',['-y','-f','concat','-safe','0','-i',timeline,'-vf','fps=30,format=yuv420p','-c:v','libvpx-vp9','-crf','36','-b:v','0','-an',destination],{encoding:'utf8'});
  fs.writeFileSync(path.join(out,'ffmpeg.txt'),(encoded.stdout||'')+(encoded.stderr||''));
  if(encoded.status!==0)throw Error(`ffmpeg failed: ${encoded.error||encoded.stderr}`);
  fs.writeFileSync(path.join(out,'motion-capture.json'),JSON.stringify({video:destination,provenance:'Synthetic local session fixtures; actual plugin and real SDK UI components; not live Hermes',capture:'CDP actual JPEG frames sorted by measured presentation timestamps; existing ffmpeg; output 30fps',captureEnd,doneRenderedAt,tickFrames,phases,frames,remote},null,2));
  console.log(JSON.stringify({video:destination,frames:frames.length,remote}));
} finally {if(context)await context.close();await browser.close();}
