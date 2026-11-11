// Refs #89: an unmeasured stat reads as a quiet placeholder, not as a headline number.
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
const page = await browser.newPage({viewport:{width:900,height:3000}});
const checks=[], errors=[], remote=[];
page.on('pageerror', e=>errors.push(String(e)));
page.on('console',m=>{if(['error','warning'].includes(m.type())&&!m.text().includes('[vite]'))errors.push(m.text());});
page.on('request',r=>{if(/^https?:/.test(r.url())&&!r.url().startsWith(origin+'/'))remote.push(r.url());});
await page.route('**/*',route=>/^https?:/.test(route.request().url())&&!route.request().url().startsWith(origin+'/')?route.abort():route.continue());
const check=(name,value)=>{assert.ok(value,name);checks.push(name);console.log('PASS '+name);};
// One retry: the first navigation after a cold preview-server start can exceed the timeout.
const visit=async(mode,theme)=>{for(let attempt=0;;attempt++){try{await page.goto(`${origin}/?mode=${mode}&width=320&theme=${theme}`);await page.locator('.pr-row').first().waitFor();break;}catch(error){if(attempt)throw error;}}
  await page.waitForTimeout(300);};
// Rows open one at a time, so open each in turn and read the stats in its details.
const collect=async()=>{const all=[];for(const id of await page.locator('.pr-row').evaluateAll(rows=>rows.map(row=>row.dataset.id))){const trigger=page.locator(`[data-id="${id}"] .pr-trigger`).first();
  if(await trigger.getAttribute('aria-expanded')!=='true'){await trigger.click();await page.waitForTimeout(150);}all.push(...(await stats()).map(s=>({...s,id})));}return all;};
// Expanded stat values with the state of their block, their size, weight, and contrast against the pane.
const stats=()=>page.evaluate(()=>{
  const rgb=value=>{const pen=document.createElement('canvas').getContext('2d',{willReadFrequently:true});pen.fillStyle='#000';pen.fillStyle=value;pen.fillRect(0,0,1,1);return [...pen.getImageData(0,0,1,1).data];};
  const lum=([r,g,b])=>{const f=v=>{v/=255;return v<=0.03928?v/12.92:((v+0.055)/1.055)**2.4;};return 0.2126*f(r)+0.7152*f(g)+0.0722*f(b);};
  const over=(top,under)=>{const a=top[3]/255;return [0,1,2].map(i=>top[i]*a+under[i]*(1-a));};
  const background=el=>{let color=[0,0,0,0];for(let e=el;e;e=e.parentElement){const c=rgb(getComputedStyle(e).backgroundColor);if(c[3]){color=color[3]?[...over(color,c),255]:c;if(c[3]===255)break;}}return color[3]?color:[255,255,255,255];};
  return [...document.querySelectorAll('.pr-details .pr-item')].flatMap(item=>{const value=item.querySelector('.pr-stat__value');if(!value)return [];
    const style=getComputedStyle(value),bg=background(value),ink=over(rgb(style.color),bg),hi=Math.max(lum(ink),lum(bg)),lo=Math.min(lum(ink),lum(bg));
    return [{state:item.dataset.state||'',text:value.textContent.trim(),size:parseFloat(style.fontSize),weight:Number(style.fontWeight),contrast:(hi+0.05)/(lo+0.05),color:style.color}];});});
try {
  for (const theme of ['dark','light']) {
    await visit('block-states',theme);
    const all=await collect(),unknown=all.filter(s=>s.state==='unknown'),measured=all.filter(s=>s.state==='measured');
    check(`${theme}: the fixture has an unmeasured and a measured expanded stat`,unknown.length>=1&&measured.length>=1);
    check(`${theme}: a measured stat keeps its headline size`,measured.every(s=>s.size>=24&&s.weight>=600));
    check(`${theme}: an unmeasured stat is body-sized, not a headline (${unknown.map(s=>s.size).join(', ')}px)`,unknown.every(s=>s.size<=14&&s.weight<=500));
    check(`${theme}: an unmeasured stat still says why, in words`,unknown.every(s=>/[A-Za-z]{3}/.test(s.text)));
    check(`${theme}: it is quieter than a measured value but still readable (>=4.5:1)`,unknown.every(s=>s.contrast>=4.5&&s.color!==measured[0].color));
    await page.locator(`[data-id="${unknown[0].id}"] .pr-trigger`).first().click();await page.waitForTimeout(200);
    if(!(await page.locator(`[data-id="${unknown[0].id}"] .pr-details`).count())){await page.locator(`[data-id="${unknown[0].id}"] .pr-trigger`).first().click();await page.waitForTimeout(200);}
    await page.locator(`[data-id="${unknown[0].id}"]`).first().screenshot({path:path.join(out,`stat-unknown-${theme}.png`)});
  }
  check('no remote requests',remote.length===0);
  check('no runtime warnings',errors.length===0);
  fs.writeFileSync(path.join(out,'stat-placeholder-results.json'),JSON.stringify({checks,errors,remote},null,2));
  console.log(`${checks.length} stat-placeholder browser checks passed`);
} finally {await browser.close();}
