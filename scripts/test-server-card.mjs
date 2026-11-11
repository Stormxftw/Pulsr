// Server card: a Discord server pulse shows who is online, who is in voice and how membership
// moved over the day, as three figures and three small day charts across the cell.
// Real engine and Discord source rows (qa-server-status.py) -> real renderer; no network.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
const req=createRequire(path.join(process.argv[2],'package.json'));
const {chromium}=req('playwright');
const origin=process.env.PULSE_PREVIEW_ORIGIN || 'http://127.0.0.1:5571';
const out=process.argv[3];fs.mkdirSync(out,{recursive:true});
const NOW=1794189600; // 2026-11-09 02:00 UTC
const rows=JSON.parse(execFileSync(process.env.PULSE_BUILDER_PYTHON || 'python',['scripts/qa-server-status.py'],{encoding:'utf8',maxBuffer:64*1024*1024}));
const lantern=rows.find(p=>p.id==='server-lantern'),harbor=rows.find(p=>p.id==='server-harbor'),quiet=rows.find(p=>p.id==='server-quietco'),big=rows.find(p=>p.id==='server-bigquiet');
// The same reading from a backend that predates the server card: no `server` field.
const older={...structuredClone(lantern),id:'server-older',title:'Older backend'};delete older.server;
// A server watched for one check: figures, but no day to draw yet.
const fresh=structuredClone(lantern);fresh.id='server-fresh';fresh.title='Just added';
fresh.server.members={value:lantern.server.members.value,delta:null,span_seconds:0,points:[]};
fresh.server.voice={...fresh.server.voice,points:fresh.server.voice.points.slice(-1),peak:fresh.server.voice.points.at(-1)};delete fresh.trend;
const designed=rows.find(p=>p.id==='server-designed'); // the owner's own display blocks, from the real engine
// A backend is never trusted: wrong types must not break the row.
const hostile=structuredClone(lantern);hostile.id='server-hostile';hostile.title='Hostile';
hostile.server.voice={state:'available',users:'<b>9</b>',channels:{},capped:'yes',floor:1,points:[{ts:'x',value:5},null,{ts:NOW-60,value:'<img src=x onerror="window.__pwned=1">'}],peak:{ts:'bad',value:'<i>'}};
hostile.server.members={value:'lots',delta:'<script>window.__pwned=2</script>',span_seconds:'x',points:'nope'};
const browser=await chromium.launch({channel:'msedge',headless:true});
const page=await browser.newPage({viewport:{width:900,height:2600},timezoneId:'UTC',locale:'en-US',reducedMotion:'reduce'});
const checks=[],errors=[],remote=[];
const check=(name,value)=>{assert.ok(value,name);checks.push(name);console.log('PASS '+name);};
page.on('pageerror',e=>errors.push(String(e)));
page.on('console',m=>{if(['error','warning'].includes(m.type())&&!m.text().includes('[vite]'))errors.push(m.text());});
await page.route('**/*',r=>{if(/^https?:/.test(r.request().url())&&!r.request().url().startsWith(origin+'/')){remote.push(r.request().url());return r.abort();}return r.continue();});
await page.route('**/ui-fixture/hero',async r=>{const response=await r.fetch();const seed=await response.json();seed.pulses=[lantern,harbor,big,quiet,older,fresh,designed,hostile].map(p=>structuredClone(p));seed.drafts=[];seed.as_of=NOW;await r.fulfill({json:seed});});
// One retry: the first navigation after a cold preview-server start can exceed the timeout.
const visit=async(width,theme='dark')=>{for(let attempt=0;;attempt++){try{await page.goto(`${origin}/?mode=hero&width=${width}&theme=${theme}&case=rows`);await page.locator('.pr-row').first().waitFor();return;}catch(error){if(attempt)throw error;}}};
const row=id=>page.locator(`[data-id="${id}"]`);
const words=async locator=>(await locator.innerText()).replace(/\s+/g,' ').replace(/ ?· ?/g,' · ').trim();
// Rows are opened one at a time: the pane keeps a single row expanded.
const open=async id=>{const trigger=row(id).locator('.pr-trigger');if(await trigger.getAttribute('aria-expanded')!=='true'){await trigger.click();await row(id).locator('.pr-details').waitFor();}await page.mouse.move(880,2500);await page.waitForTimeout(200);};
const box=locator=>locator.evaluate(node=>{const r=node.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height};});
// Text drawn wider than its box, to the fraction of a pixel (scrollWidth rounds).
const clipped=locator=>locator.evaluateAll(nodes=>nodes.filter(node=>{const range=document.createRange();range.selectNodeContents(node);const text=range.getBoundingClientRect(),b=node.getBoundingClientRect();return text.width>0&&(text.right>b.right+0.5||text.left<b.left-0.5);}).map(node=>node.textContent));
const contrast=locator=>locator.evaluate(el=>{
  const rgb=value=>{const pen=document.createElement('canvas').getContext('2d',{willReadFrequently:true});pen.fillStyle='#000';pen.fillStyle=value;pen.fillRect(0,0,1,1);return [...pen.getImageData(0,0,1,1).data];};
  const lum=([r,g,b])=>{const f=v=>{v/=255;return v<=0.03928?v/12.92:((v+0.055)/1.055)**2.4;};return 0.2126*f(r)+0.7152*f(g)+0.0722*f(b);};
  const over=(top,under)=>{const a=top[3]/255;return [0,1,2].map(i=>top[i]*a+under[i]*(1-a));};
  let bg=[0,0,0,0];for(let e=el;e;e=e.parentElement){const c=rgb(getComputedStyle(e).backgroundColor);if(c[3]){bg=bg[3]?[...over(bg,c),255]:c;if(c[3]===255)break;}}
  if(!bg[3])bg=[255,255,255,255];const ink=over(rgb(getComputedStyle(el).color),bg),hi=Math.max(lum(ink),lum(bg)),lo=Math.min(lum(ink),lum(bg));return (hi+0.05)/(lo+0.05);});
const n=value=>value.toLocaleString('en-US');
const L={online:lantern.ring.components.find(c=>c.metric==='online').value,voice:lantern.server.voice,members:lantern.server.members};
try{
  check('fixture: the engine produced a day of voice checks and member readings',L.voice.points.length>60&&L.members.points.length>40&&L.voice.users>0&&L.members.delta===164);
  await visit(320);
  // --- the collapsed row answers the three questions in one line ---
  const line=row('server-lantern').locator('.pr-trigger .pr-server-line');
  check('row: online, people in voice and the day\'s member change, in that order',await words(line)===`${n(L.online)} online · ${L.voice.users} in voice · +164 in 24h`);
  check('row: one line, nothing cut mid-word',(await box(line)).height<=20&&(await clipped(line.locator('.pr-hero-more > span'))).length===0);
  check('row: no change score on a server row beyond the existing chip',await row('server-lantern').locator('.pr-server-line').count()===1);
  check('row: the accessible name carries the same reading in spoken units',(await row('server-lantern').locator('.pr-trigger').getAttribute('aria-label')).includes(`${n(L.online)} online; ${L.voice.users} in voice; +164 members in 1 day`));
  check('row: a full public list reads as a minimum',(await words(row('server-harbor').locator('.pr-trigger .pr-server-line'))).includes(`At least ${harbor.server.voice.users} in voice`));
  check('row: a server with its widget off shows no voice figure, and a loss reads with a minus',await words(row('server-quietco').locator('.pr-trigger .pr-server-line'))===`${n(quiet.ring.components[0].value)} online · −37 in 24h`);
  check('row: a full list with nobody in voice makes no voice claim',await words(row('server-bigquiet').locator('.pr-trigger .pr-server-line'))===`${n(big.ring.components[0].value)} online · +209 in 24h`&&!/voice/.test(await row('server-bigquiet').locator('.pr-trigger').getAttribute('aria-label')));
  await page.screenshot({path:path.join(out,'collapsed-320.png'),clip:{x:0,y:0,width:900,height:520}});
  // --- the card: three figures across the cell ---
  await open('server-lantern');
  const card=row('server-lantern').locator('.pr-details .pr-server');
  const tiles=card.locator('.pr-server-tile');
  check('card: three figures: Online, In voice, Members',JSON.stringify(await card.locator('.pr-server-label').allInnerTexts())===JSON.stringify(['ONLINE','IN VOICE','MEMBERS'])||JSON.stringify((await card.locator('.pr-server-label').allInnerTexts()).map(t=>t.toLowerCase()))===JSON.stringify(['online','in voice','members']));
  check('card: the figures are the measured values',JSON.stringify(await card.locator('.pr-server-value').allInnerTexts())===JSON.stringify([n(L.online),String(L.voice.users),n(L.members.value)]));
  check('card: each figure has its context underneath',JSON.stringify((await card.locator('.pr-server-sub').allInnerTexts()).map(t=>t.trim()))===JSON.stringify([`${Math.round(L.online/L.members.value*100)}% of members`,`${L.voice.channels} channels`,'+164 in 24h']));
  const tileBoxes=await tiles.evaluateAll(nodes=>nodes.map(e=>{const r=e.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,width:r.width};}));
  const cardBox=await box(card);
  check('card: the figures sit side by side and span the cell',tileBoxes.every(t=>Math.abs(t.top-tileBoxes[0].top)<1)&&Math.abs(tileBoxes[0].left-cardBox.left)<1&&Math.abs(tileBoxes[2].right-cardBox.right)<1&&tileBoxes.every(t=>Math.abs(t.width-tileBoxes[0].width)<1));
  check('card: no figure or caption is cut',(await clipped(card.locator('.pr-server-value, .pr-server-label, .pr-server-sub'))).length===0);
  check('card: growth is tinted, and a tint is never the only signal',await card.locator('.pr-server-sub[data-trend="up"]').count()===1&&(await card.locator('.pr-server-sub[data-trend="up"]').innerText()).startsWith('+'));
  // --- the day as three charts ---
  check('card: the online chart keeps today against yesterday',await card.locator('[data-part="online"] .pr-trend svg').count()===1);
  check('card: the online chart has the same heading as the other two, with the reading against this time yesterday',/^online [+−]\d+% vs this time yesterday \([\d,]+\)$/i.test(await words(card.locator('[data-part="online"] .pr-server-head')))&&await card.locator('[data-part="online"] .pr-trend-head').count()===0);
  check('card: yesterday is drawn as its own line',await card.locator('[data-part="online"] .pr-trend-prev').count()>=1);
  const growth=card.locator('[data-part="growth"]'),voice=card.locator('[data-part="voice"]');
  check('card: the net change is said once, on the Members tile, not again on the growth chart',(await words(growth.locator('.pr-server-head'))).toLowerCase()==='member growth'&&await words(card.locator('[data-tile="members"] .pr-server-sub'))==='+164 in 24h'&&(await words(card)).split('+164 in 24h').length===2);
  check('card: member growth is drawn from zero with a baseline',await growth.locator('svg.pr-server-chart polyline').count()===1&&await growth.locator('.pr-server-zero').count()===1&&/Net change in members over the last 24h: \+164\./.test(await growth.locator('svg').getAttribute('aria-label')));
  const peak=L.voice.peak,peakClock=new Date(peak.ts*1000).toLocaleTimeString('en-US',{hour:'numeric',minute:'2-digit',timeZone:'UTC'});
  check('card: people in voice has a heading with the day\'s peak and when',(await words(voice.locator('.pr-server-head'))).toLowerCase()===`in voice peak ${peak.value} at ${peakClock}`.toLowerCase());
  const voicePoints=(await voice.locator('svg.pr-server-chart polyline').getAttribute('points')).split(' ').map(pair=>pair.split(',').map(Number));
  check('card: the voice line is stepped: a count holds until the next check',voicePoints.length===L.voice.points.length*2-1&&voicePoints.every(([x,y])=>Number.isFinite(x)&&Number.isFinite(y)&&x>=0&&x<=300&&y>=0&&y<=40));
  check('card: the voice line ends at the current count',Math.abs(voicePoints.at(-1)[1]-(36-(L.voice.users/Math.max(1,peak.value))*31))<0.01);
  const ring=voice.locator('svg .pr-server-peak');
  check('card: a ring marks the peak of the day on the voice line',await ring.count()===1&&Math.abs(Number(await ring.getAttribute('cy'))-5)<0.01&&Number(await ring.getAttribute('cx'))<voicePoints.at(-1)[0]);
  check('card: the growth line takes the tint of its direction, the voice line the accent',await growth.locator('svg.pr-server-chart').getAttribute('data-trend')==='up'&&await voice.locator('svg.pr-server-chart').getAttribute('data-trend')===null);
  check('card: the two day charts share one 24h ago to now axis, under the last chart',await growth.locator('.pr-trend-axis').count()===0&&await voice.locator('.pr-trend-axis').count()===1&&/24h ago\s*12h ago\s*now/.test(await voice.locator('.pr-trend-axis').innerText()));
  const charts=await card.locator('svg.pr-server-chart').evaluateAll(nodes=>nodes.map(e=>{const r=e.getBoundingClientRect();return {width:r.width,height:r.height};}));
  check('card: the day charts span the cell at 40px',charts.length===2&&charts.every(c=>Math.abs(c.width-cardBox.width)<1&&Math.abs(c.height-40)<1));
  check('card: the old text lines and usual-range sentence are replaced, not repeated',await row('server-lantern').locator('.pr-details .pr-lines > div').count()===0&&await row('server-lantern').locator('.pr-details .pr-normal').count()===0);
  check('card: what is watched and the actions are still there',/Watching: .*discord\.com/.test(await words(row('server-lantern').locator('.pr-details')))&&await row('server-lantern').locator('.pr-details button').count()>=3);
  for(const [name,locator] of [['label',card.locator('.pr-server-label').first()],['value',card.locator('.pr-server-value').first()],['context',card.locator('.pr-server-sub').first()],['growth tint',card.locator('.pr-server-sub[data-trend="up"]')],['heading',voice.locator('.pr-server-head > span').first()]])
    check(`card: ${name} text contrast is at least 4.5:1 (dark)`,await contrast(locator)>=4.5);
  check('card: nothing overflows the row at 320px',await row('server-lantern').evaluate(e=>e.scrollWidth<=e.clientWidth+1));
  await row('server-lantern').screenshot({path:path.join(out,'open-320.png')});
  // --- a full public list is a minimum, said once ---
  await open('server-harbor');
  const capped=row('server-harbor').locator('.pr-details .pr-server');
  check('minimum: the figure carries a ≥ and explains itself',await capped.locator('[data-tile="in-voice"] .pr-server-value').innerText()===`≥${harbor.server.voice.users}`&&/at most 100 members publicly/.test(await capped.locator('[data-tile="in-voice"] .pr-server-value').getAttribute('title')));
  check('minimum: the peak is a minimum too and the chart says why',(await words(capped.locator('[data-part="voice"] .pr-server-head'))).includes(`Peak ≥${harbor.server.voice.peak.value} at`)&&/at most 100 members publicly, so this is a minimum/.test(await capped.locator('.pr-server-note').innerText()));
  await row('server-harbor').screenshot({path:path.join(out,'minimum-320.png')});
  // --- a full list with nobody in voice is unknown, never zero ---
  await open('server-bigquiet');
  const unseen=row('server-bigquiet').locator('.pr-details .pr-server');
  check('none seen: the figure is a dash with "None seen", and says why',await unseen.locator('[data-tile="in-voice"] .pr-server-value').innerText()==='—'&&(await unseen.locator('[data-tile="in-voice"] .pr-server-sub').innerText()).trim()==='None seen'&&/at most 100 of this server's members publicly/.test(await unseen.locator('[data-tile="in-voice"] .pr-server-value').getAttribute('title')));
  check('none seen: no flat zero line is drawn; one sentence explains the limit',await unseen.locator('[data-part="voice"] svg').count()===0&&(await words(unseen.locator('[data-part="voice"] .pr-server-head'))).toLowerCase()==='in voice only 100 members are listed publicly'&&/How many of the rest are is not public\./.test(await unseen.locator('[data-part="voice"] .pr-server-note').innerText()));
  await row('server-bigquiet').screenshot({path:path.join(out,'none-seen-320.png')});
  // --- widget off: no voice figures, said plainly, never zero ---
  await open('server-quietco');
  const off=row('server-quietco').locator('.pr-details .pr-server');
  check('widget off: the figure is a dash with "Not public", not a zero',await off.locator('[data-tile="in-voice"] .pr-server-value').innerText()==='—'&&(await off.locator('[data-tile="in-voice"] .pr-server-sub').innerText()).trim()==='Not public');
  check('widget off: no voice chart, one plain sentence',await off.locator('[data-part="voice"] svg').count()===0&&(await words(off.locator('[data-part="voice"] .pr-server-head'))).toLowerCase()==='in voice not public for this server');
  check('widget off: a loss of members is drawn below the baseline and tinted down',await off.locator('[data-tile="members"] .pr-server-sub[data-trend="down"]').innerText()==='−37 in 24h'&&await off.locator('[data-part="growth"] svg polyline').count()===1);
  const lossLine=(await off.locator('[data-part="growth"] svg polyline').getAttribute('points')).split(' ').map(pair=>Number(pair.split(',')[1]));
  const zeroY=Number(await off.locator('[data-part="growth"] .pr-server-zero').getAttribute('y1'));
  check('widget off: the loss line ends under its baseline and is tinted down',lossLine.at(-1)>zeroY&&lossLine.every(y=>y>=0&&y<=40)&&await off.locator('[data-part="growth"] svg').getAttribute('data-trend')==='down');
  await row('server-quietco').screenshot({path:path.join(out,'widget-off-320.png')});
  // --- just added: figures without invented charts ---
  await open('server-fresh');
  const young=row('server-fresh').locator('.pr-details .pr-server');
  check('just added: figures show, the member change is blank rather than zero',await young.locator('[data-tile="members"] .pr-server-value').innerText()===n(L.members.value)&&(await young.locator('[data-tile="members"] .pr-server-sub').innerText()).trim()==='');
  check('just added: no growth chart and no voice chart are invented',await young.locator('svg.pr-server-chart').count()===0&&await young.locator('[data-part="growth"]').count()===0);
  check('just added: the voice part says when a trend will exist',/Trend after two checks, 15 minutes apart/.test(await words(young.locator('[data-part="voice"]'))));
  check('just added: the row leaves out the member change',await words(row('server-fresh').locator('.pr-trigger .pr-server-line'))===`${n(L.online)} online · ${L.voice.users} in voice`);
  // --- compatibility ---
  check('older backend: the row and details render as before',await row('server-older').locator('.pr-server-line').count()===0);
  await open('server-older');
  check('older backend: trend chart, text lines and the usual sentence remain',await row('server-older').locator('.pr-details .pr-server').count()===0&&await row('server-older').locator('.pr-details .pr-trend').count()===1&&await row('server-older').locator('.pr-details .pr-lines > div').count()>=2&&await row('server-older').locator('.pr-details .pr-normal').count()===1);
  await open('server-designed');
  check('designed: the owner\'s display blocks are shown instead of the server card',await row('server-designed').locator('.pr-details .pr-server').count()===0&&await row('server-designed').locator('.pr-details .pr-block').count()===1&&await row('server-designed').locator('.pr-server-line').count()===0);
  await open('server-hostile');
  const bad=row('server-hostile').locator('.pr-details .pr-server');
  check('untrusted: wrong types show as not measured, not as markup',await bad.locator('[data-tile="in-voice"] .pr-server-value').innerText()==='—'&&await bad.locator('[data-tile="members"] .pr-server-value').innerText()==='—'&&await bad.locator('img, script, b').count()===0&&!(await bad.innerText()).includes('<'));
  check('untrusted: no chart is drawn from malformed points and nothing ran',await bad.locator('svg.pr-server-chart').count()===0&&await page.evaluate(()=>window.__pwned===undefined));
  // --- widths and themes ---
  for(const [width,theme] of [[231,'dark'],[400,'dark'],[320,'light']]){
    await visit(width,theme);await open('server-lantern');
    const c=row('server-lantern').locator('.pr-details .pr-server');
    check(`${width}px ${theme}: nothing overflows the row`,await row('server-lantern').evaluate(e=>e.scrollWidth<=e.clientWidth+1)&&await page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth));
    check(`${width}px ${theme}: no figure, label or heading is cut`,(await clipped(c.locator('.pr-server-value, .pr-server-label, .pr-server-sub, .pr-server-head > span'))).length===0);
    const tops=await c.locator('.pr-server-tile').evaluateAll(nodes=>nodes.map(e=>Math.round(e.getBoundingClientRect().top)));
    check(`${width}px ${theme}: ${width<250?'online leads on its own line above the other two figures':'three figures on one line'}`,width<250?tops[0]<tops[1]&&tops[1]===tops[2]:tops[0]===tops[1]&&tops[1]===tops[2]);
    if(width<250)check('231px: the online heading drops the bracketed figure rather than wrapping it alone',await c.locator('.pr-server-detail').evaluate(e=>getComputedStyle(e).display==='none'));
    check(`${width}px ${theme}: the collapsed row is one line`,(await box(row('server-lantern').locator('.pr-trigger .pr-server-line'))).height<=20);
    if(theme==='light')for(const [name,locator] of [['label',c.locator('.pr-server-label').first()],['context',c.locator('.pr-server-sub').first()],['growth tint',c.locator('.pr-server-sub[data-trend="up"]')]])
      check(`light: ${name} text contrast is at least 4.5:1`,await contrast(locator)>=4.5);
    await row('server-lantern').screenshot({path:path.join(out,`open-${width}-${theme}.png`)});
  }
  check('no page errors or warnings',errors.length===0);
  check('no remote requests',remote.length===0);
  console.log(JSON.stringify({checks:checks.length,errors,remote}));
}catch(error){console.error(error);console.error(JSON.stringify({errors,remote}));process.exitCode=1;}finally{await browser.close();}
