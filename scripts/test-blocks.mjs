import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import path from 'node:path';
import fs from 'node:fs';
const req=createRequire(path.join(process.argv[2],'package.json'));
const {chromium}=req('playwright');
const out=process.argv[3] || 'artifacts/wp8-render';
fs.mkdirSync(out,{recursive:true});
const origin=process.env.PULSE_PREVIEW_ORIGIN || 'http://127.0.0.1:5198';
const browser=await chromium.launch({channel:'msedge',headless:true});
const page=await browser.newPage({viewport:{width:640,height:1200},deviceScaleFactor:2});
const errors=[],remote=[],checks=[];
page.on('pageerror',e=>errors.push(String(e)));
page.on('console',m=>{if(['error','warning'].includes(m.type())&&!m.text().includes('[vite]'))errors.push(m.text());});
page.on('request',r=>{if(/^https?:/.test(r.url())&&!r.url().startsWith(origin+'/'))remote.push(r.url());});
await page.route('**/*',route=>/^https?:/.test(route.request().url())&&!route.request().url().startsWith(origin+'/')?route.abort():route.continue());
const check=(name,value)=>{assert.ok(value,name);checks.push(name);console.log('PASS '+name);};
const visit=async(mode='blocks',width=248,extra='')=>{await page.goto(`${origin}/?mode=${mode}&width=${width}${extra}`);await page.locator('.pr-row').first().waitFor();await page.waitForTimeout(180);};
const open=async id=>{const trigger=page.locator(`[data-id="${id}"] .pr-trigger`);if(await trigger.getAttribute('aria-expanded')!=='true')await trigger.click();};
const shot=async name=>page.screenshot({path:path.join(out,name+'.png'),fullPage:true});
const types=['score','rings','bar','bars','stat','spark'];
const states=['measured','learning','unknown','unavailable','over','under','degraded','stale'];
try {
  await visit();
  check('synthetic caption is explicit',await page.locator('footer').textContent().then(s=>s.includes('HAND-AUTHORED SYNTHETIC')));
  check('multi-feed example plus GPU, score and legacy',await page.locator('.pr-row').count()===4);
  await open('synthetic-ebay');
  check('expanded renders every eBay block',await page.locator('[data-id=synthetic-ebay] .pr-display > .pr-block').count()===3);
  check('shared bars have shared divider semantics',await page.locator('[data-id=synthetic-ebay] .pr-display .pr-bars').getAttribute('data-scale')==='shared');
  check('rings own two concentric arcs',await page.locator('[data-id=synthetic-ebay] .pr-display .pr-ring__arc').count()===2);
  check('ranges and engine caption shown',await page.locator('.pr-display .pr-range').count()===2 && await page.locator('.pr-display').textContent().then(t=>t.includes('Auto range · 7d') && !t.includes('auto 0–25')));
  await shot('blocks-ebay-dark-248');
  const ringHandle=await page.locator('.pr-display .pr-ring__arc').first().elementHandle();
  const statHandle=await page.locator('.pr-display .pr-stat__value').elementHandle();
  await page.evaluate(()=>{const p=window.__pulseStatus.pulses.find(p=>p.id==='synthetic-ebay');p.display[0].items[0].fill=83;p.display[0].items[0].value_text='415';p.display[0].items[0].caption='83% of limit';p.display[2].value_text='4';window.__emitPulse('draft.updated');});
  await page.waitForTimeout(100);
  check('rings update their original arc in place',await ringHandle.evaluate(e=>e.isConnected && e.getAttribute('stroke-dasharray')==='83 100'));
  await page.waitForTimeout(750);
  check('stat updates its original value in place',await statHandle.evaluate(e=>e.isConnected && e.textContent==='4'));
  await open('synthetic-gpu');
  check('GPU uses one independent bars path',await page.locator('.pr-display .pr-bars').getAttribute('data-scale')==='independent' && await page.locator('.pr-display .pr-bar__track').count()===3);
  check('spark nulls split into two polylines and areas',await page.locator('.pr-display .pr-spark__line').count()===2 && await page.locator('.pr-display .pr-spark__area').count()===2 && await page.locator('.pr-display .pr-spark__dot').count()===1);
  check('zone ticks are engine-provided',await page.locator('.pr-display .pr-bar__tick').count()===5);
  await shot('blocks-gpu-dark-248');
  for(const width of [176,248,320])for(const theme of ['dark','light']){
    await visit('blocks',width,`&theme=${theme}`);await open('synthetic-gpu');
    check(`${theme} ${width}px no overflow`,await page.locator('.pr-shell').evaluate(root=>{const r=root.getBoundingClientRect();return root.scrollWidth<=root.clientWidth+1 && [...root.querySelectorAll('.pr-trigger,.pr-display,.pr-block,.pr-details')].every(el=>{const b=el.getBoundingClientRect();return b.left>=r.left-1&&b.right<=r.right+1;});}));
    check(`${theme} ${width}px readable block text`,await page.locator('.pr-display').evaluate(root=>{
      const canvas=document.createElement('canvas'),c=canvas.getContext('2d',{willReadFrequently:true});canvas.width=canvas.height=1;
      const rgb=color=>{c.clearRect(0,0,1,1);c.fillStyle=color;c.fillRect(0,0,1,1);return [...c.getImageData(0,0,1,1).data];};
      const luminance=rgb=>rgb.slice(0,3).map(v=>{const c=v/255;return c<=.04045?c/12.92:((c+.055)/1.055)**2.4;}).reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
      const bg=rgb(getComputedStyle(document.documentElement).getPropertyValue('--ui-bg-editor'));
      return [...root.querySelectorAll('.pr-item-label,.pr-caption,.pr-range')].every(el=>{const text=rgb(getComputedStyle(el).color);const a=luminance(text),b=luminance(bg);return (Math.max(a,b)+.05)/(Math.min(a,b)+.05)>=4.5;});
    }));
    await shot(`blocks-gpu-${theme}-${width}`);
  }
  await visit('block-states');
  check('complete 6 × 8 state scenario gallery',await page.locator('.pr-row').count()===48);
  for(const type of types)for(const state of states){
    await open(`${type}-${state}`);
    const block=page.locator('.pr-display .pr-block');
    check(`${type} × ${state}: accessible stable hooks`,await block.getAttribute('data-type')===type && await block.getAttribute('data-index')==='0' && Boolean(await block.getAttribute('aria-label')));
    if(['rings','bar','bars'].includes(type)){
      const expected=state==='degraded'?'unknown':['measured','learning','unknown','unavailable'].includes(state)?state:'measured';
      check(`${type} × ${state}: engine state`,await block.locator('.pr-item').first().getAttribute('data-state')===expected);
      if(['unknown','degraded','learning','unavailable'].includes(state))check(`${type} × ${state}: never a fabricated zero`,await block.locator('.pr-bar__fill,.pr-ring__arc').count()===0);
      if(state==='unknown'||state==='degraded')check(`${type} × ${state}: reason`,await block.textContent().then(t=>t.includes('Synthetic feed unavailable')));
      if(state==='learning')check(`${type} learning caption`,await block.textContent().then(t=>t.includes(type==='rings'?'Learning range · 2 samples':'Baseline not ready · 2 samples')));
      if(state==='unavailable')check(`${type} unavailable caption`,await block.textContent().then(t=>t.includes('Range unavailable')));
      if(state==='over'||state==='under')check(`${type} ${state} marker`,await block.locator(`[aria-label="${state==='over'?'Above max':'Below min'}"]`).count()>0);
    }
    if(type==='score'){
      if(state==='unknown'||state==='degraded')check(`score ${state} preserves reason`,await block.textContent().then(t=>t.includes('Synthetic feed unavailable')));
      if(state==='learning')check('score learning track and caption',await block.locator('.pr-ring__track').evaluate(e=>getComputedStyle(e).strokeDasharray==='3px, 3px') && await block.textContent().then(t=>t.includes('Learning baseline')));
    }
    if(type==='stat'){
      check(`stat ${state} value/reason`,await block.locator('.pr-stat__value').textContent().then(t=>t===(state==='unknown'||state==='degraded'?'Synthetic feed unavailable':state==='over'?'120 %':state==='under'?'−10 %':'62 %')));
      check(`stat ${state} delta availability`,await block.locator('.pr-stat__delta').count()===(['unknown','degraded','learning'].includes(state)?0:1));
      if(state==='learning')check('stat learning baseline caption',await block.textContent().then(t=>t.includes('Learning baseline')));
    }
    if(type==='spark')check(`spark ${state} measured gaps or unknown`,await block.locator('.pr-spark__line').count()===(state==='unknown'||state==='degraded'?0:2));
    if(state==='stale'||state==='degraded')check(`${type} ${state} feed banner`,await page.locator(`[data-id="${type}-${state}"] .pr-feed-status`).textContent().then(t=>t.includes(state==='stale'?'Stale':'Degraded')));
    check(`${type} × ${state}: no NaN/undefined`,!/(?:NaN|undefined)/.test(await page.locator('.pr-shell').innerText()));
  }
  await shot('block-states-spark-stale');
  await visit('styles');await open('synthetic-ebay');
  check('style parameters become clamped CSS variables',await page.locator('.pr-display .pr-block').first().evaluate(el=>el.style.getPropertyValue('--pr-b-thickness')==='8px' && el.style.getPropertyValue('--pr-b-gap')==='2px' && el.style.getPropertyValue('--pr-b-direction')==='ccw'));
  check('theme is isolated to one pulse',await page.locator('[data-id=synthetic-ebay] .pr-display').evaluate(el=>el.style.getPropertyValue('--pr-t-accent')==='#7c5cff') && await page.locator('[data-id=nous-discord] .pr-trigger').getAttribute('style')===null);
  check('malicious colors and wrong types dropped; integer bounds clamped',await page.evaluate(()=>{
    const s=window.__displayPulseStyle({color:'red;background:url(x)',color2:'expression(1)',track:'rgb(1,2,3)',thickness:99,radius:-1,glow:17,gap:99},false,'rings');
    return !s['--pr-b-color']&&!s['--pr-b-color2']&&!s['--pr-b-track']&&s['--pr-b-thickness']==='24px'&&s['--pr-b-radius']==='0px'&&s['--pr-b-glow']==='16px'&&s['--pr-b-gap']==='6px';
  }));
  check('prototype names are not color tokens',await page.evaluate(()=>['__proto__','constructor','toString','expression(1)'].every(color=>!window.__displayPulseStyle({color},false,'bar')['--pr-b-color'])));
  check('presence/data selectors are scoped and custom lengths bounded',await page.evaluate(()=>{const s=window.__sanitizePulseCss('.pr-pulse[data-id] .pr-block[data-type="bar"][data-index] .pr-item[data-tone][data-state] {--pr-b-thickness:999px;stroke-width:999}');return s.startsWith('.pr-shell .pr-pulse:not(.pr-pending)[data-id]') && s.includes('--pr-b-thickness:24px') && s.includes('stroke-width:24');}));
  await open('synthetic-gpu');
  check('show_range false suppresses range',await page.locator('.pr-display .pr-range').count()===0);
  check('theme motion none disables transitions',await page.locator('.pr-display .pr-bar__fill').first().evaluate(e=>getComputedStyle(e).transitionDuration==='0s'));
  await shot('blocks-styles');
  await visit('blocks');await open('synthetic-gpu');
  check('700ms transition',await page.locator('.pr-display .pr-bar__fill').first().evaluate(e=>getComputedStyle(e).transitionDuration.split(',')[0]==='0.7s'));
  await page.emulateMedia({reducedMotion:'reduce'});
  check('reduced motion disables transitions',await page.locator('.pr-display .pr-bar__fill').first().evaluate(e=>getComputedStyle(e).transitionDuration==='0s'));
  await page.emulateMedia({reducedMotion:'no-preference'});
  const handle=await page.locator('.pr-display .pr-bar__fill').first().elementHandle();
  await page.evaluate(()=>window.__pulseTick());await page.waitForTimeout(100);
  check('live update keeps exact DOM element',await handle.evaluate(e=>e.isConnected&&e===document.querySelector('.pr-display .pr-bar__fill')&&e.style.width==='71%'));
  check('feed timestamp beat marker',await page.locator('[data-id=synthetic-gpu] .pr-beat').getAttribute('data-beat')==='true');
  await visit('blocks',248,'&css');
  check('one owned custom style loads via SDK',await page.locator('style[data-pulse-rings-custom]').count()===1 && await page.evaluate(()=>window.__pulseRestCalls.some(c=>c.path==='/custom.css?format=json')));
  check('custom CSS is scoped',await page.locator('style[data-pulse-rings-custom]').textContent().then(s=>s.startsWith('.pr-shell .pr-pulse:not(.pr-pending) .pr-block')));
  check('CSS sanitizer drops imports/fonts/resources/escape/host/approval rules',await page.evaluate(()=>{
    const css='@IMPORT "https://evil.invalid/a"; @font-face {font-family:x;src:URL(https://evil.invalid/x)} body{color:red}.pr-approval{color:red}.pr-block .pr-approval{color:red}.pr-block{background-image:uRl(x);color:rebeccapurple;behavior:url(x);-moz-binding:url(x);width:expression(1);position:fixed} .pr-caption{font-weight:700}';
    const s=window.__sanitizePulseCss(css);
    return s.includes('color:rebeccapurple')&&s.includes('font-weight:700')&&!/url\(|expression\(|@import|@font-face|behavior:|-moz-binding|position:|body/i.test(s)&&window.__sanitizePulseCss('.pr-bl\\6f ck{color:red}')==='';
  }));
  // Pending rows cannot inherit customization; approved disclosure controls are outside themed scopes.
  await visit('pending',248,'&css');
  await page.locator('.pr-trigger').first().click();
  const approvalBefore=await page.locator('.pr-approval').first().evaluate(e=>({color:getComputedStyle(e).color,html:e.innerHTML}));
  await page.evaluate(()=>{document.querySelector('style[data-pulse-rings-custom]').textContent=window.__sanitizePulseCss('.pr-pulse{color:red}.pr-approval{display:none}.pr-block .pr-btn{color:red}.pr-caption{color:red}.pr-block{color:red}');window.__pulseStatus.drafts[0].preview.theme={text:'#f00',surface:'#f00'};window.__emitPulse('draft.updated');});
  await page.waitForTimeout(150);
  check('approval ignores CSS/theme',await page.locator('.pr-approval').first().evaluate((e,before)=>getComputedStyle(e).color===before.color && e.innerHTML===before.html,approvalBefore));
  // Cleanup uses a real React root unmount, not a manual style deletion.
  await page.evaluate(()=>window.__unmountPulse());
  check('owned style removed on final unmount',await page.locator('style[data-pulse-rings-custom]').count()===0);
  await page.emulateMedia({reducedMotion:'reduce'});
  for(const theme of ['dark','light'])for(const expanded of [false,true]){
    // Expanded rows compare at 288px: below a 280px pane the action buttons are
    // intentionally laid out in two columns (#93), which the frozen renderer is not.
    await visit('blocks',expanded?288:248,`&theme=${theme}&baseline`);
    if(expanded)await open('nous-discord');
    const baselineRow=page.locator('[data-id=nous-discord]');
    await page.mouse.move(0,0);
    // Align pixel grids: neighboring NEW block rows intentionally have new heights.
    await baselineRow.evaluate(e=>{e.style.position='fixed';e.style.top='300px';e.style.left='100px';e.style.width='226px';e.style.zIndex='999';e.style.backgroundColor=getComputedStyle(document.documentElement).getPropertyValue('--ui-bg-editor');});
    // Intentional live-polish changes: integer scores, comparison in the accessible
    // name, forward trend labels, grouped usual-baseline duration and its sample
    // count (#92). All other
    // legacy DOM and pixels still compare against the frozen renderer.
    await baselineRow.evaluate(root=>{
      // Discord rows no longer show the change score: no `Change N/100`, no score arc.
      root.querySelector('.pr-score')?.remove();
      const orbit=root.querySelector('.pr-orbit');
      if(orbit&&orbit.dataset.alert!=='true'){orbit.dataset.hot='none';const arc=orbit.querySelector('.pr-arc');arc?.setAttribute('stroke-dasharray','0 100');arc?.setAttribute('opacity','0');}
      const score=root.querySelector('.pr-score');
      if(score)score.textContent=`Change ${Math.round(Number(score.textContent))}/100`;
      const ratio=root.querySelector('.pr-ratio');
      if(ratio)ratio.textContent+=ratio.textContent.includes('×')?' usual':' of usual';
      const trigger=root.querySelector('.pr-trigger');
      trigger.setAttribute('aria-label',trigger.getAttribute('aria-label').replace('; change intensity',`; ${ratio?.textContent || ''}; change intensity`).replace(/change intensity ([\d.]+)/,(_,n)=>`change intensity ${Math.round(Number(n))}`));
      for(const el of root.querySelectorAll('.pr-chart-labels span'))el.textContent=el.textContent.replace(/^(.+) · first$/,'First $1').replace(/^(.+) · latest$/,'Latest $1');
      const normal=[...root.querySelectorAll('.pr-details p')].find(e=>e.textContent.startsWith('Normal: Median · '));
      if(normal){const m=normal.textContent.match(/^Normal: Median · (.+) · (\d+) recorded samples over (.+)$/);normal.className='pr-normal';normal.style.textWrap='pretty';normal.replaceChildren(document.createTextNode(`Usual (median) ${m[1]} · `));const samples=document.createElement('span');/* #92: the frozen renderer counted chart points; the count is now the median's own samples. */const used=window.__pulseStatus.pulses.find(p=>p.id==='nous-discord').ring.baseline_samples;samples.textContent=`${Number.isFinite(used)?used:m[2]} samples `;const span=document.createElement('span');span.className='pr-normal-duration';span.style.whiteSpace='nowrap';span.textContent=`over ${m[3]}`;normal.append(samples,span);}

    });
    const html=await baselineRow.innerHTML();
    const pixels=await baselineRow.screenshot({animations:'disabled',path:path.join(out,`baseline-${theme}-${expanded?'expanded':'compact'}.png`)});
    await visit('blocks',expanded?288:248,`&theme=${theme}`);
    if(expanded)await open('nous-discord');
    const row=page.locator('[data-id=nous-discord]');
    await page.mouse.move(0,0);
    await row.evaluate(e=>{e.style.position='fixed';e.style.top='300px';e.style.left='100px';e.style.width='226px';e.style.zIndex='999';e.style.backgroundColor=getComputedStyle(document.documentElement).getPropertyValue('--ui-bg-editor');});
    // The new Edit authoring action is intentionally additive; characterize the
    // exact legacy measurement/display and original management actions without it.
    await row.locator('.pr-builder-edit').evaluateAll(es=>es.forEach(e=>e.remove()));
    await row.evaluate(root=>{root.querySelectorAll('.pr-normal-duration').forEach(e=>e.style.whiteSpace='nowrap');root.querySelectorAll('.pr-normal').forEach(e=>e.style.textWrap='pretty');});
    check(`${theme} legacy ${expanded?'expanded':'compact'} DOM matches main 3b04572 plus semantic labels (excluding new Edit action)`,await row.innerHTML()===html);
    const current=await row.screenshot({animations:'disabled',path:path.join(out,`legacy-${theme}-${expanded?'expanded':'compact'}.png`)});
    check(`${theme} legacy ${expanded?'expanded':'compact'} pixels match baseline plus semantic labels`,current.equals(pixels));
  }
  await page.emulateMedia({reducedMotion:'no-preference'});
  await visit('live-blocks');await open('synthetic-gpu');
  const live=await page.locator('.pr-display .pr-bar__fill').first().elementHandle();
  const old=await live.evaluate(e=>e.style.width);
  await page.waitForFunction(old=>document.querySelector('.pr-display .pr-bar__fill')?.style.width!==old,old);
  check('automatic live tick updates without remount',await live.evaluate(e=>e.isConnected && e===document.querySelector('.pr-display .pr-bar__fill')));
  check('no remote requests',remote.length===0);
  check(`no renderer errors: ${JSON.stringify(errors)}`,errors.length===0);
  fs.writeFileSync(path.join(out,'blocks-results.json'),JSON.stringify({checks:checks.length,errors,remote},null,2));
  console.log(`${checks.length} block browser checks passed`);
} finally { await browser.close(); }
