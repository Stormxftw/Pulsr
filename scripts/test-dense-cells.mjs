// Refs #77: expanded display blocks use the width of the cell. Paired stats sit side by side,
// a stat's change sits beside its value, and a bar's range and caption share a line.
// Rows come from the real engine (qa-json-status.py, qa-repo-ui-fixtures.py); no network.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
const req=createRequire(path.join(process.argv[2],'package.json'));
const {chromium}=req('playwright');
const origin=process.env.PULSE_PREVIEW_ORIGIN || 'http://127.0.0.1:5571';
const out=process.argv[3];fs.mkdirSync(out,{recursive:true});
const python=process.env.PULSE_BUILDER_PYTHON || 'python';
const json=JSON.parse(execFileSync(python,['scripts/qa-json-status.py'],{encoding:'utf8'}));
const repos=JSON.parse(execFileSync(python,['scripts/qa-repo-ui-fixtures.py'],{encoding:'utf8'}));
const types=p=>(p.display||[]).map(b=>b.type).join(',');
const weather={...json.find(p=>types(p)==='stat,bars,spark'),id:'dense-weather'};
const repo={...repos.activity,id:'dense-repo'}; // score, then two stats: last push and CI
assert.equal(types(repo),'score,stat,stat');
const counts={...repos.counts,id:'dense-counts'}; // stat, bars, then a spark that moves
const spark=counts.display.find(b=>b.type==='spark');assert.ok(spark.hi>spark.lo,'the counts fixture has a moving trend');
assert.ok(weather.display&&repo.display,'fixtures found');
const browser=await chromium.launch({channel:'msedge',headless:true});
const page=await browser.newPage({viewport:{width:900,height:2000},reducedMotion:'reduce'});
const checks=[],errors=[],remote=[];
const check=(name,value)=>{assert.ok(value,name);checks.push(name);console.log('PASS '+name);};
page.on('pageerror',e=>errors.push(String(e)));
page.on('console',m=>{if(['error','warning'].includes(m.type())&&!m.text().includes('[vite]'))errors.push(m.text());});
await page.route('**/*',r=>{if(/^https?:/.test(r.request().url())&&!r.request().url().startsWith(origin+'/')){remote.push(r.request().url());return r.abort();}return r.continue();});
await page.route('**/ui-fixture/hero',async r=>{const response=await r.fetch();const seed=await response.json();seed.pulses=[structuredClone(weather),structuredClone(repo),structuredClone(counts)];seed.drafts=[];await r.fulfill({json:seed});});
// One retry: the first navigation after a cold preview-server start can exceed the timeout.
const visit=async(width,theme='dark')=>{for(let attempt=0;;attempt++){try{await page.goto(`${origin}/?mode=hero&width=${width}&theme=${theme}&case=rows`);await page.locator('.pr-row').first().waitFor();return;}catch(error){if(attempt)throw error;}}};
const row=id=>page.locator(`[data-id="${id}"]`);
const open=async id=>{const trigger=row(id).locator('.pr-trigger');if(await trigger.getAttribute('aria-expanded')!=='true'){await trigger.click();await row(id).locator('.pr-details').waitFor();}await page.waitForTimeout(250);};
const box=locator=>locator.evaluate(node=>{const r=node.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height};});
// Text drawn wider than its box, to the fraction of a pixel (scrollWidth rounds).
const clipped=locator=>locator.evaluateAll(nodes=>nodes.filter(node=>{const range=document.createRange();range.selectNodeContents(node);const text=range.getBoundingClientRect(),b=node.getBoundingClientRect();return text.width>0&&(text.right>b.right+0.5||text.left<b.left-0.5);}).map(node=>node.className+': '+node.textContent));
const measure={};
try{
  // Facts on the collapsed line: {text, state} where state is shown, hidden (wrapped below and clipped) or cut.
  const facts=id=>row(id).locator('.pr-hero-more > span').evaluateAll(nodes=>nodes.map(node=>{const line=node.parentElement.getBoundingClientRect(),r=node.getBoundingClientRect();
    return {text:node.textContent,state:r.top>=line.bottom-1?'hidden':r.right<=line.right+0.5&&r.bottom<=line.bottom+1?'shown':'cut'};}));
  for(const width of [400,320]){
    await visit(width);
    const line=await facts('dense-weather');
    check(`${width}: the collapsed weather row adds facts beside its number (${line.filter(f=>f.state==='shown').map(f=>f.text).join(' ')})`,(await row('dense-weather').locator('.pr-trigger .pr-stat__value').innerText()).trim().length>0&&line.length>=2&&line[0].state==='shown'&&/^· Wind /.test(line[0].text));
    check(`${width}: a fact that does not fit is hidden whole, never cut`,line.every(f=>f.state!=='cut'));
    const gap=await row('dense-weather').locator('.pr-hero-line').evaluate(node=>node.querySelector('.pr-hero-more > span').getBoundingClientRect().left-node.querySelector('.pr-stat__value').getBoundingClientRect().right);
    check(`${width}: the first fact follows the number closely (${Math.round(gap)}px)`,gap>=0&&gap<=6);
    check(`${width}: a score row keeps its own summary and gets no extra line`,await row('dense-repo').locator('.pr-hero-line').count()===0);
    await open('dense-repo');
    const stats=row('dense-repo').locator('.pr-details .pr-block[data-type="stat"]');
    const [a,b]=[await box(stats.nth(0)),await box(stats.nth(1))];
    check(`${width}: two stats in a row sit side by side`,Math.abs(a.top-b.top)<=1&&b.left>=a.right-0.5);
    check(`${width}: paired stats share the width`,Math.abs(a.width-b.width)<=2&&a.width+b.width>=(await box(row('dense-repo').locator('.pr-details .pr-display'))).width*0.8);
    check(`${width}: paired stat values are whole`,(await clipped(stats.locator('.pr-stat__value'))).length===0);
    const score=await box(row('dense-repo').locator('.pr-details .pr-block[data-type="score"]'));
    check(`${width}: other blocks keep the full width`,score.width>=a.width+b.width);
    measure[`repo-${width}`]=Math.round((await box(row('dense-repo').locator('.pr-details .pr-display'))).height);
    await row('dense-repo').screenshot({path:path.join(out,`repo-${width}.png`)});
    await open('dense-weather');
    const stat=row('dense-weather').locator('.pr-details .pr-block[data-type="stat"]').first();
    const value=await box(stat.locator('.pr-stat__value')),delta=await box(stat.locator('.pr-stat__delta'));
    check(`${width}: a stat's change sits beside its value, not under it`,delta.left>=value.right-0.5&&delta.top<value.bottom&&delta.bottom>value.top);
    // Measured on the drawn text, not the boxes: a reserved-width box would hide a gap.
    const ink=await stat.evaluate(node=>{const rect=el=>{const range=document.createRange();range.selectNodeContents(el);return range.getBoundingClientRect();};return {value:rect(node.querySelector('.pr-stat__value')).right,delta:rect(node.querySelector('.pr-stat__delta')).left};});
    check(`${width}: the change follows the value closely (${Math.round(ink.delta-ink.value)}px)`,ink.delta-ink.value>=2&&ink.delta-ink.value<=14);
    const item=row('dense-weather').locator('.pr-details .pr-bars > .pr-item').filter({has:page.locator('.pr-range')}).filter({has:page.locator('.pr-caption')}).first();
    const range=await box(item.locator('.pr-range')),caption=await box(item.locator('.pr-caption'));
    check(`${width}: a bar's range and caption share one line`,Math.abs(range.top-caption.top)<=3&&caption.left>=range.right-0.5);
    check(`${width}: the bar track still spans the block`,(await box(item.locator('.pr-bar__track'))).width>=(await box(item)).width-1);
    check(`${width}: block text is whole`,(await clipped(row('dense-weather').locator('.pr-details .pr-display .pr-item-label, .pr-details .pr-display .pr-range, .pr-details .pr-display .pr-caption, .pr-details .pr-display .pr-stat__value'))).length===0);
    measure[`weather-${width}`]=Math.round((await box(row('dense-weather').locator('.pr-details .pr-display'))).height);
    check(`${width}: no horizontal overflow`,await page.locator('.pr-shell').evaluate(e=>e.scrollWidth<=e.clientWidth+1));
    await row('dense-weather').screenshot({path:path.join(out,`weather-${width}.png`)});
    check(`${width}: a flat trend shows no low/high line`,await row('dense-weather').locator('.pr-details .pr-spark-range').count()===0);
    await open('dense-counts');
    const scale=(await row('dense-counts').locator('.pr-details .pr-spark-range').innerText()).replace(/\s+/g,' ').trim();
    check(`${width}: a moving trend names its low and high (${scale})`,/^Low [\d,.]+ High [\d,.]+$/.test(scale));
    check(`${width}: the low/high line stays out of the collapsed row`,await row('dense-counts').locator('.pr-trigger .pr-spark-range').evaluateAll(nodes=>nodes.every(node=>node.getClientRects().length===0)));
    await row('dense-counts').screenshot({path:path.join(out,`counts-${width}.png`)});
  }
  // Measured before this change at 320px: weather blocks 456px tall, repository blocks 220px.
  check(`320: the weather blocks are at least 60px shorter than before (${measure['weather-320']}px, was 456px)`,measure['weather-320']<=396);
  check(`320: the repository blocks are at least 40px shorter than before (${measure['repo-320']}px, was 220px)`,measure['repo-320']<=180);
  // A narrow pane has no room for two 100px tiles: stats stack again and nothing is cut.
  await visit(231);
  const tight=await facts('dense-weather');
  check('231: collapsed facts are whole or hidden, never cut',tight.every(f=>f.state!=='cut'));
  await page.screenshot({path:path.join(out,'collapsed-231.png'),clip:{x:0,y:0,width:900,height:420}});
  await open('dense-repo');
  const narrow=row('dense-repo').locator('.pr-details .pr-block[data-type="stat"]');
  const [n1,n2]=[await box(narrow.nth(0)),await box(narrow.nth(1))];
  check('231: stats stack in a narrow pane',n2.top>=n1.bottom-0.5);
  check('231: stat values are whole',(await clipped(narrow.locator('.pr-stat__value'))).length===0);
  await open('dense-weather');
  check('231: block text is whole',(await clipped(row('dense-weather').locator('.pr-details .pr-display .pr-item-label, .pr-details .pr-display .pr-range, .pr-details .pr-display .pr-caption, .pr-details .pr-display .pr-stat__value'))).length===0);
  check('231: no horizontal overflow',await page.locator('.pr-shell').evaluate(e=>e.scrollWidth<=e.clientWidth+1));
  await row('dense-weather').screenshot({path:path.join(out,'weather-231.png')});
  await visit(320,'light');await open('dense-weather');await row('dense-weather').screenshot({path:path.join(out,'weather-320-light.png')});
  check('no remote requests',remote.length===0);
  check('no runtime warnings',errors.length===0);
  console.log('MEASURE '+JSON.stringify(measure));
  fs.writeFileSync(path.join(out,'dense-cells-results.json'),JSON.stringify({checks,measure,errors,remote},null,2));
  console.log(`${checks.length} dense-cells browser checks passed`);
}finally{console.log('MEASURE-PARTIAL '+JSON.stringify(measure));await browser.close();}
