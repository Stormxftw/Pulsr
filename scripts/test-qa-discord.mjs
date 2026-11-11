// Discord QA: real renderer + pure engine preview; no live network or activation.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
const {chromium}=createRequire(path.join(process.argv[2],'package.json'))('playwright');
const origin=process.env.PULSE_PREVIEW_ORIGIN || 'http://127.0.0.1:5511';
const out=process.argv[3];fs.mkdirSync(out,{recursive:true});
const browser=await chromium.launch({channel:'msedge',headless:true});
const page=await browser.newPage({viewport:{width:1100,height:1200},reducedMotion:'reduce'});
const checks=[],errors=[],remote=[];
page.on('pageerror',e=>errors.push(String(e)));
await page.route('**/*',r=>{if(/^https?:/.test(r.request().url())&&!r.request().url().startsWith(origin+'/')){remote.push(r.request().url());return r.abort();}return r.continue();});
const check=(name,ok)=>{assert.ok(ok,name);checks.push(name);console.log('PASS '+name);};
const visit=async(width,theme,mode='hero')=>{await page.goto(`${origin}/?mode=${mode}&width=${width}&theme=${theme}`);await page.locator('.pr-trigger').first().waitFor();};
const shot=name=>page.screenshot({path:path.join(out,name+'.png'),fullPage:true});
const pure=(route,body)=>page.evaluate(async({route,body})=>{const r=await fetch('/builder-mock',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:route,body})});const x=await r.json();if(!r.ok)throw Error(JSON.stringify(x));return x;},{route,body});
const inject=async pulses=>{await page.evaluate(pulses=>{window.__pulseStatus.pulses=pulses;window.__pulseStatus.drafts=[];window.__emitPulse('draft.updated');},pulses);await page.waitForTimeout(250);};
try{
  // Regression: these are engine captions; the renderer must not erase their meaning.
  await visit(320,'dark');
  const legacy=await page.evaluate(()=>structuredClone(window.__pulseStatus.pulses.find(p=>p.kind==='discord.invite')));
  legacy.id='qa-discord';legacy.title='Nous Research';legacy.state='active';legacy.ring.warming=false;legacy.ring.unknown=false;legacy.ring.score=4.1;legacy.capsule={label:'16,082 online',fill:50,caption:'100% of usual'};
  await inject([legacy]);
  check('legacy baseline ratio labelled in row',(await page.locator('.pr-ratio').innerText()).includes('usual'));
  check('a Discord row shows no Change N/100 and no score arc',await page.locator('.pr-score').count()===0&&await page.locator('[data-id="qa-discord"] .pr-orbit .pr-arc').evaluate(e=>getComputedStyle(e).opacity==='0'));
  await inject([{...structuredClone(legacy),alert:{...(legacy.alert||{}),active:true}}]);
  check('an alerting Discord row fills its ring in the warning colour',await page.locator('[data-id="qa-discord"] .pr-orbit').getAttribute('data-hot')==='hot'&&await page.locator('[data-id="qa-discord"] .pr-orbit .pr-arc').evaluate(e=>getComputedStyle(e).opacity==='1'&&e.getAttribute('stroke-dasharray').startsWith('100 '))&&await page.locator('.pr-score').count()===0);
  await inject([legacy]);
  for(const width of [320,480,670])for(const theme of ['dark','light']){
    await visit(width,theme);await inject([legacy]);
    check(`${width} ${theme} count formatted`,(await page.locator('.pr-capsule').innerText()).includes('16,082 online'));
    check(`${width} ${theme} no pane overflow`,await page.locator('.pr-shell').evaluate(e=>e.scrollWidth<=e.clientWidth+1));
    await shot(`legacy-${width}-${theme}`);
    for(const state of ['warming','stale','backoff','error','paused','degraded']){
      const p=structuredClone(legacy);p.state=state;p.error=state==='error'?'Invite expired or invalid. Replace it to resume polling.':state==='backoff'?'Rate limited; retry later.':null;p.backoff_until=Date.now()/1000+600;
      if(state==='warming'){p.last_ok_ts=null;p.ring.warming=true;p.capsule={label:'Online unknown',fill:null,caption:'Learning baseline'};}
      await inject([p]);
      check(`${width} ${theme} ${state} clean text`,!/NaN|undefined|\[object Object\]/.test(await page.locator('.pr-row').innerText()));
    }
    await inject([legacy]);
    const defs=[
      [{type:'score',label:'Online change',components:[{metric:'online',type:'delta',weight:100,baseline:'median'}]}, {type:'rings',rings:[{value:'online',label:'Online',max:'members'},{value:'voice_channels',label:'Public voice channels',max:5}]}],
      [{type:'bar',value:'online',label:'Online',max:'members'},{type:'bars',scale:'independent',bars:[{value:'online',label:'Online',max:'members'},{value:'members',label:'Members',max:'usual'}]}],
      [{type:'stat',value:'online',label:'Online'},{type:'spark',value:'online',label:'Online trend'}]
    ];
    for(let i=0;i<defs.length;i++){
      const definition={pulse:1,title:'Discord 声 🎙 long community with a verbose server title',icon:{brand:'discord'},source:{kind:'discord.invite',params:{invite:'nousresearch',voice:true}},display:defs[i]};
      const row=await pure('/builder/preview',{definition,state:'measured',seed:1});
      assert.equal(row.ok,true,JSON.stringify(row.errors));
      const p={...legacy,...row,id:'qa-discord',kind:'discord.invite',state:'active',lines:[],history:[]};
      await inject([p]);await page.locator('[data-id="qa-discord"] .pr-trigger').click();
      await page.locator('[data-id="qa-discord"] .pr-display').waitFor();
      const blockCount=await page.locator('[data-id="qa-discord"] .pr-display .pr-block').count();
      check(`${width} ${theme} blocks ${i} visible (${blockCount})`,blockCount===2);
      if(i===0){
        check(`${width} ${theme} score block labelled`,/Change\s+[\d.]+\/100/.test(await page.locator('.pr-display [data-type="score"]').innerText()));
        check(`${width} ${theme} score hero shows measured online and comparison`,/\d[\d,]* online/.test(await page.locator('.pr-hero-values').innerText())&&/usual|Learning baseline|new/.test(await page.locator('.pr-hero-values').innerText()));
      }
      if(i===1){
        const format=new Intl.NumberFormat('en-US',{maximumFractionDigits:3});
        const expected=row.display.flatMap(b=>(b.items || []).map(item=>`${format.format(item.min)}–${format.format(item.max)}${item.unit?' '+item.unit:''}`));
        check(`${width} ${theme} bar ranges use formatted numbers`,JSON.stringify(await page.locator('.pr-display .pr-range').allTextContents())===JSON.stringify(expected));
      }
      check(`${width} ${theme} blocks ${i} no pane overflow`,await page.locator('.pr-shell').evaluate(e=>e.scrollWidth<=e.clientWidth+1));
      check(`${width} ${theme} blocks ${i} no invalid values`,!/NaN|undefined|\[object Object\]/.test(await page.locator('.pr-row').innerText()));
      await shot(`blocks-${i}-${width}-${theme}`);
      await page.locator('[data-id="qa-discord"] .pr-trigger').click();
    }
  }
  await visit(320,'dark','groups');
  await page.waitForTimeout(300);
  await page.evaluate(legacy=>{const p=window.__pulseStatus.pulses[0];Object.assign(p,legacy,{id:p.id});window.__emitPulse('draft.updated');},legacy);
  const group=page.locator('[data-group-id="communities"]');
  await group.locator(':scope > .pr-group-head .pr-group-toggle').click();
  const circle=group.locator('.pr-circle').first();await circle.hover();await page.waitForTimeout(450);
  check('collapsed tooltip retains usual baseline',(await page.getByRole('tooltip').innerText()).includes('100% of usual'));
  check('collapsed tooltip explains score',(await page.getByRole('tooltip').innerText()).includes('change intensity 4 of 100'));
  await shot('collapsed-tooltip');
  await page.mouse.move(5,5);await group.getByRole('button',{name:'Manage Communities',exact:true}).focus();await page.keyboard.press('Tab');await page.waitForTimeout(400);
  check('collapsed keyboard tooltip',await page.getByRole('tooltip').count()===1);
  // Template form -> real source/metrics -> layouts -> draft review/disclosure.
  await visit(670,'light','builder');
  await page.getByRole('button',{name:'New pulse',exact:true}).click();
  await page.locator('.pr-b2-template').filter({has:page.getByText('Discord server',{exact:true})}).click();
  await page.getByLabel('Discord invite link',{exact:true}).fill('https://discord.gg/nousresearch');
  await page.waitForTimeout(800);await page.getByRole('button',{name:'Next',exact:true}).click();await page.waitForTimeout(700);
  check('Discord template preview marked sample',(await page.locator('.pr-builder').innerText()).includes('Sample'));
  await page.getByRole('button',{name:'Next',exact:true}).click();await page.waitForTimeout(700);
  await page.getByRole('button',{name:'Review permissions',exact:true}).click();await page.locator('.pr-builder-review .pr-approval').waitFor();
  const disclosure=await page.locator('.pr-builder-review').innerText();
  check('draft discloses public Discord hosts',disclosure.includes('discord.com')&&disclosure.includes('cdn.discordapp.com'));
  check('draft discloses 10 req/hour',/10\s*req\/h/.test(disclosure));
  check('review never activates',await page.evaluate(()=>!window.__pulseRestCalls.some(c=>c.path.endsWith('/approve'))));
  await shot('builder-disclosure');
  await page.getByRole('button',{name:'Jump to Approve',exact:true}).click();
  const approve=page.locator('.pr-builder-review').getByRole('button',{name:'Approve',exact:true});
  await approve.waitFor();
  check('scrolling review reaches unobscured approval without deciding',await approve.evaluate(e=>{const r=e.getBoundingClientRect();return document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)?.closest('button')===e;}));
  check('jump to approval is not approval',await page.evaluate(()=>!window.__pulseRestCalls.some(c=>c.path.endsWith('/approve'))));
  await shot('builder-approval-reachable');
  check('zero renderer errors',errors.length===0);check('zero remote requests',remote.length===0);
  fs.writeFileSync(path.join(out,'discord-results.json'),JSON.stringify({checks:checks.length,errors,remote},null,2));
  console.log(`${checks.length} Discord browser checks passed`);
}finally{await browser.close();}
