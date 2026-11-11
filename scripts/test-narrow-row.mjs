// Refs #92, #93: an expanded row fits narrow panes, and the usual line counts real samples.
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
const row=id=>page.locator(`[data-id="${id}"]`);
const open=async id=>{await row(id).locator('.pr-trigger').click();await row(id).locator('.pr-details').waitFor();};
// Every action button sits inside the details area, none is cut, and no two overlap.
const actionsFit=id=>row(id).locator('.pr-details').evaluate(details=>{
  const box=details.getBoundingClientRect();
  const buttons=[...details.querySelectorAll(':scope > .pr-actions .pr-action')];
  const rects=buttons.map(b=>b.getBoundingClientRect());
  const inside=rects.every(r=>r.left>=box.left-0.5&&r.right<=box.right+0.5);
  const whole=buttons.every(b=>b.scrollWidth<=b.clientWidth+1);
  const apart=rects.every((a,i)=>rects.every((b,j)=>i>=j||a.right<=b.left+0.5||b.right<=a.left+0.5||a.bottom<=b.top+0.5||b.bottom<=a.top+0.5));
  return {count:buttons.length,inside,whole,apart,scroll:details.scrollWidth<=details.clientWidth+1};
});
try {
  for (const width of [200,231,240,248,264,279,280,320]) {
    await visit('hero',width);
    for (const id of ['hugging-face','catalog-prs']) {
      await open(id);
      const fit=await actionsFit(id);
      check(`${width}px ${id}: ${fit.count} actions stay inside the row, whole and apart`,fit.count>=5&&fit.inside&&fit.whole&&fit.apart&&fit.scroll);
      check(`${width}px ${id}: every action keeps its name and a usable target`,await row(id).locator('.pr-details > .pr-actions .pr-action').evaluateAll(bs=>bs.every(b=>b.textContent.trim().length>2&&b.getBoundingClientRect().height>=14)));
      if(id==='hugging-face'&&[200,231,320].includes(width))await row(id).screenshot({path:path.join(out,`actions-${width}.png`)});
      await row(id).locator('.pr-trigger').click();
    }
    check(`${width}px: pane has no horizontal overflow with a row expanded`,await (async()=>{await open('hugging-face');return page.locator('.pr-shell').evaluate(e=>e.scrollWidth<=e.clientWidth+1);})());
  }
  // Wide panes keep the three-column arrangement with Remove at the right edge.
  await visit('hero',320);await open('hugging-face');
  check('320px: three columns, Remove right-aligned',await row('hugging-face').locator('.pr-details > .pr-actions').evaluate(e=>getComputedStyle(e).gridTemplateColumns.split(' ').length===3&&getComputedStyle(e.querySelector('.pr-danger')).textAlign==='right'));
  await visit('hero',280);await open('hugging-face');
  check('280px: still three columns',await row('hugging-face').locator('.pr-details > .pr-actions').evaluate(e=>getComputedStyle(e).gridTemplateColumns.split(' ').length===3));
  // A long link host wraps inside its column instead of widening the row.
  await visit('hero',231);
  await page.evaluate(()=>{const p=window.__pulseStatus.pulses.find(x=>x.id==='hugging-face');p.link='https://status.a-rather-long-hostname.example.org/';window.__emitPulse('draft.updated');});
  await open('hugging-face');
  {const fit=await actionsFit('hugging-face');check('231px: a 41-character host wraps and nothing leaves the row',fit.inside&&fit.whole&&fit.apart&&fit.scroll&&await row('hugging-face').locator('.pr-details > .pr-actions .pr-action').first().evaluate(b=>b.textContent.includes('status.a-rather-long-hostname.example.org')&&b.getBoundingClientRect().height>20));}
  await row('hugging-face').screenshot({path:path.join(out,'actions-231-long-host.png')});
  await visit('hero',231);await open('hugging-face');
  check('231px: two columns, Remove starts its column like the others',await row('hugging-face').locator('.pr-details > .pr-actions').evaluate(e=>getComputedStyle(e).gridTemplateColumns.split(' ').length===2&&getComputedStyle(e.querySelector('.pr-danger')).textAlign==='left'));
  // #92: the usual line reports how many samples the median used, not how many points the chart got.
  const usual=()=>row('hugging-face').locator('.pr-normal').innerText().then(t=>t.replace(/\s+/g,' ').trim());
  const fixture=await page.evaluate(()=>{const p=window.__pulseStatus.pulses.find(x=>x.id==='hugging-face');return {history:p.history.length,baseline:p.ring.baseline_samples};});
  check('fixture distinguishes chart points from baseline samples',fixture.history===12&&fixture.baseline===11);
  check('usual line counts the baseline samples',/· 11 samples over /.test(await usual()));
  await page.evaluate(()=>{const p=window.__pulseStatus.pulses.find(x=>x.id==='hugging-face');p.ring.baseline_samples=127;window.__emitPulse('draft.updated');});
  await page.waitForTimeout(250);
  check('127 baseline samples are reported although the chart has 12 points',/· 127 samples over /.test(await usual()));
  await page.evaluate(()=>{const p=window.__pulseStatus.pulses.find(x=>x.id==='hugging-face');delete p.ring.baseline_samples;window.__emitPulse('draft.updated');});
  await page.waitForTimeout(250);
  check('older backend without the count falls back to the chart points',/· 12 samples over /.test(await usual()));
  check('no remote requests',remote.length===0);
  check('no runtime warnings',errors.length===0);
  fs.writeFileSync(path.join(out,'narrow-row-results.json'),JSON.stringify({checks,errors,remote},null,2));
  console.log(`${checks.length} narrow-row browser checks passed`);
} finally {await browser.close();}
