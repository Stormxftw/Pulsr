import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import path from 'node:path';
import fs from 'node:fs';
const req = createRequire(path.join(process.argv[2], 'package.json'));
const {chromium} = req('playwright');
const out = process.argv[3];
fs.mkdirSync(out, {recursive:true});
const origin = process.env.PULSE_PREVIEW_ORIGIN || 'http://127.0.0.1:5261';
const browser = await chromium.launch({channel:'msedge',headless:true});
const page = await browser.newPage({viewport:{width:640,height:1400},timezoneId:'UTC',locale:'en-US'});
const checks=[], errors=[], remote=[];
page.on('pageerror', e=>errors.push(String(e)));
page.on('console',m=>{if(['error','warning'].includes(m.type())&&!m.text().includes('[vite]'))errors.push(m.text());});
page.on('request',r=>{if(/^https?:/.test(r.url())&&!r.url().startsWith(origin+'/'))remote.push(r.url());});
await page.route('**/*',route=>/^https?:/.test(route.request().url())&&!route.request().url().startsWith(origin+'/')?route.abort():route.continue());
const check=(name,value)=>{assert.ok(value,name);checks.push(name);console.log('PASS '+name);};
// One retry: the first navigation after a cold preview-server start can exceed the timeout.
const visit=async(mode,width=320)=>{for(let attempt=0;;attempt++){try{await page.goto(`${origin}/?mode=${mode}&width=${width}`);await page.locator('.pr-row').first().waitFor();return;}catch(error){if(attempt)throw error;}}};
const ID='hugging-face';
const row=()=>page.locator(`[data-id="${ID}"]`);
const DAY=86400, END=1794009600; // 2026-11-07 00:00 UTC
// A plain daily wave, sampled every half hour: low 13,300 at 03:00, peak 17,300 at 15:00 UTC.
const wave=ts=>Math.round(15300-2000*Math.cos(((ts-3*3600)%DAY)/DAY*2*Math.PI));
const points=(from,to,shift=0)=>{const list=[];for(let ts=from;ts<=to;ts+=1800)list.push({ts,value:wave(ts)+shift});return list;};
const trendOf=changes=>{const today=points(END-DAY,END,changes.shift||0);const latest=today.at(-1);const then=wave(END-DAY);
  return {metric:'online',window_seconds:DAY,bucket_seconds:1800,points:today,previous:points(END-2*DAY,END-DAY-1800),
    low:today.reduce((a,b)=>b.value<a.value?b:a),high:today.reduce((a,b)=>b.value>a.value?b:a),latest,
    yesterday:{value:then,delta:latest.value-then,ratio:latest.value/then},...changes.override};};
const apply=async changes=>{await page.evaluate(({id,changes})=>{const p=window.__pulseStatus.pulses.find(x=>x.id===id);for(const [k,v] of Object.entries(changes)){if(v===undefined)delete p[k];else p[k]=v;}window.__emitPulse('draft.updated');},{id:ID,changes});await page.waitForTimeout(250);};
const text=sel=>row().locator(sel).innerText().then(t=>t.replace(/\s+/g,' ').trim());
const voice=()=>row().locator('.pr-lines > div').nth(1); // the fixture's second line is voice_channels
try {
  await visit('hero');
  await row().locator('.pr-trigger').click();
  check('without trend data the row keeps the existing sparkline',await row().locator('.pr-chart').count()===1&&await row().locator('.pr-trend').count()===0);
  const oldVoice=await voice().innerText();

  await apply({trend:trendOf({shift:0})});
  check('trend replaces the first/latest sparkline',await row().locator('.pr-trend').count()===1&&await row().locator('.pr-chart').count()===0&&!(await row().innerText()).includes('First '));
  check('a normal daily rhythm reads as no change',await text('.pr-trend-head')===`About the same as this time yesterday (${wave(END-DAY).toLocaleString('en-US')})`);
  check('low and peak are named with their times',await text('.pr-trend-range')==='Low 13,300 at 3:00 AM Peak 17,300 at 3:00 PM');
  check('time axis runs from a day ago to now',await text('.pr-trend-axis')==='24h ago 12h ago now');
  check('today and yesterday are both drawn and labelled',await row().locator('.pr-trend-today').count()===1&&await row().locator('.pr-trend-prev').count()===1&&await text('.pr-trend-legend')==='today yesterday');
  const geometry=await row().locator('.pr-trend-chart').evaluate(svg=>{const xs=sel=>svg.querySelector(sel).getAttribute('points').split(' ').map(p=>Number(p.split(',')[0]));const t=xs('.pr-trend-today'),p=xs('.pr-trend-prev');const dot=svg.querySelector('circle:last-of-type');return {tFirst:t[0],tLast:t.at(-1),pFirst:p[0],pLast:p.at(-1),rising:t.every((x,i)=>!i||x>t[i-1]),dot:Number(dot.getAttribute('cx'))};});
  check('both days share one time scale ending at now',Math.abs(geometry.tFirst-3)<0.5&&Math.abs(geometry.tLast-297)<0.5&&Math.abs(geometry.pFirst-3)<0.5&&geometry.pLast<297&&geometry.rising&&Math.abs(geometry.dot-297)<0.5);
  check('chart has a spoken summary',await row().locator('.pr-trend-chart').getAttribute('aria-label').then(t=>t.replace(/\s+/g,' '))===`Online over the last 24 hours: now ${wave(END).toLocaleString('en-US')}. About the same as this time yesterday (${wave(END-DAY).toLocaleString('en-US')}). Low 13,300 at 3:00 AM, Peak 17,300 at 3:00 PM.`);
  await row().screenshot({path:path.join(out,'trend-same-320.png')});

  await apply({trend:trendOf({shift:1543})});
  check('a real rise is stated against yesterday',/^\+11% vs this time yesterday \(13,886\)$/.test(await text('.pr-trend-head')));
  await apply({trend:trendOf({shift:-2000})});
  check('a real drop is stated against yesterday',/^−14% vs this time yesterday \(13,886\)$/.test(await text('.pr-trend-head')));
  await apply({trend:trendOf({override:{yesterday:{value:0,delta:14000,ratio:null}}})});
  check('a zero yesterday is a difference, never a percentage',await text('.pr-trend-head')==='+14,000 vs this time yesterday (0)');
  await apply({trend:trendOf({override:{yesterday:null,previous:[]}})});
  check('no yesterday yet is said plainly, with no ghost line or legend',await text('.pr-trend-head')==='No sample from this time yesterday yet'&&await row().locator('.pr-trend-prev').count()===0&&await row().locator('.pr-trend-legend').count()===0);

  const gappy=trendOf({});gappy.points=gappy.points.filter(p=>p.ts<END-20*3600||p.ts>END-8*3600);
  await apply({trend:gappy});
  const parts=await row().locator('.pr-trend-today').evaluateAll(ls=>ls.map(l=>l.getAttribute('points').split(' ').map(p=>Number(p.split(',')[0]))));
  check('a gap in collection breaks the line instead of bridging it',parts.length===2&&parts[1][0]-parts[0].at(-1)>140);
  await row().screenshot({path:path.join(out,'trend-gap-320.png')});

  await apply({trend:{metric:'online',window_seconds:DAY,points:[{ts:END,value:5}],previous:[],latest:{ts:END,value:5},yesterday:null}});
  check('one point is not a chart',await row().locator('.pr-trend').count()===0&&(await row().innerText()).includes('First sample recorded'));
  await apply({trend:{metric:'online',points:'<img src=x>',previous:null,latest:{ts:'x'},yesterday:{value:'9'}}});
  check('malformed trend data cannot break the row',await row().locator('.pr-details').count()===1&&await row().locator('img[src="x"]').count()===0);

  await apply({trend:trendOf({shift:0}),voice:{state:'available',users:7,channels:2,capped:false}});
  check('people in voice are counted with their channels',await voice().innerText()==='7 in voice · 2 channels'&&await voice().getAttribute('title')===null);
  await apply({voice:{state:'available',users:1,channels:1,capped:false}});
  check('one channel is singular',await voice().innerText()==='1 in voice · 1 channel');
  await apply({voice:{state:'available',users:12,channels:3,capped:true}});
  check('a full member list makes the count a floor and says why',await voice().innerText()==='At least 12 in voice · 3 channels'&&(await voice().getAttribute('title')).includes('at most 100 members'));
  await apply({voice:{state:'available',users:0,channels:0,capped:false}});
  check('an empty voice list is a measured zero',await voice().innerText()==='No one in voice right now');
  await apply({voice:{state:'available',users:0,channels:0,capped:true}});
  check('zero on a full list is not claimed as nobody',await voice().innerText()==='No one seen in voice');
  await apply({voice:{state:'unavailable',users:null,channels:null,capped:false}});
  check('a server without a public widget says so',await voice().innerText()==='Voice not public for this server'&&(await voice().getAttribute('title')).includes('public widget is off'));
  await apply({voice:{state:'pending',users:null,channels:null,capped:false}});
  check('voice not yet checked is not shown as zero',await voice().innerText()==='Voice not checked yet');
  await apply({voice:{state:'available',users:null,channels:2,capped:false}});
  check('state saved before people were counted keeps the old line',await voice().innerText()===oldVoice);
  await apply({voice:undefined});
  check('an older backend keeps the old voice line',await voice().innerText()===oldVoice);

  await apply({trend:trendOf({shift:0}),voice:{state:'available',users:7,channels:2,capped:false}});
  for(const width of [231,248,320,480]){
    await visit('hero',width);await row().locator('.pr-trigger').click();
    await apply({trend:trendOf({shift:612}),voice:{state:'available',users:7,channels:2,capped:false}});
    // Scoped to the trend: the row's action buttons have their own narrow-pane overflow (#93).
    check(`${width}px: trend stays inside the details and no text is cut`,await row().locator('.pr-details').evaluate(d=>{const box=d.getBoundingClientRect();return [...d.querySelectorAll('.pr-trend,.pr-trend *,.pr-lines div')].every(e=>e.getBoundingClientRect().right<=box.right+0.5&&e.getBoundingClientRect().left>=box.left-0.5);})&&await row().locator('.pr-trend-head,.pr-trend-range span,.pr-trend-axis span').evaluateAll(es=>es.every(e=>e.scrollWidth<=e.clientWidth+1)));
    await row().screenshot({path:path.join(out,`trend-${width}.png`)});
  }
  await page.emulateMedia({colorScheme:'light'});
  await page.goto(`${origin}/?mode=hero&width=320&theme=light`);await row().locator('.pr-trigger').click();
  await apply({trend:trendOf({shift:612}),voice:{state:'available',users:7,channels:2,capped:false}});
  check('light theme: yesterday is drawn distinct from today',await row().locator('.pr-trend-chart').evaluate(svg=>getComputedStyle(svg.querySelector('.pr-trend-today')).stroke!==getComputedStyle(svg.querySelector('.pr-trend-prev')).stroke&&getComputedStyle(svg.querySelector('.pr-trend-prev')).strokeDasharray!=='none'));
  await row().screenshot({path:path.join(out,'trend-light-320.png')});
  check('no remote requests',remote.length===0);
  check('no runtime warnings',errors.length===0);
  fs.writeFileSync(path.join(out,'trend-results.json'),JSON.stringify({checks,errors,remote},null,2));
  console.log(`${checks.length} trend browser checks passed`);
} finally {await browser.close();}
