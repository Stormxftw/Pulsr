// WP12 presentation regressions. All data is synthetic; no source is polled.
import assert from 'node:assert/strict';
import {authoring, compatibleField, previewTools, applyDefinition, review} from './builder2-test-helpers.mjs';
import {createRequire} from 'node:module';
import path from 'node:path';
import fs from 'node:fs';
const req = createRequire(path.join(process.argv[2], 'package.json'));
const {chromium} = req('playwright');
const out = process.argv[3];
fs.mkdirSync(out, {recursive:true});
const origin = process.env.PULSE_PREVIEW_ORIGIN || 'http://127.0.0.1:5331';
const section = process.env.PULSE_NITS_SECTION || 'all';
const browser = await chromium.launch({channel:'msedge',headless:true});
const page = await browser.newPage({viewport:{width:1400,height:1200},reducedMotion:'reduce'});
const checks=[],failures=[],errors=[],remote=[],scans=[];
page.on('pageerror',e=>errors.push(String(e)));
page.on('console',m=>{if(['error','warning'].includes(m.type()))errors.push(m.text());});
await page.route('**/*',r=>{if(/^https?:/.test(r.request().url())&&!r.request().url().startsWith(origin+'/')){remote.push(r.request().url());return r.abort();}return r.continue();});
const check=(name,ok)=>{checks.push(name);if(!ok)failures.push(name);console.log(`${ok?'PASS':'FAIL'} ${name}`);};
const wait=()=>page.waitForTimeout(650);
const visit=async(mode,width,theme,extra='')=>{await page.goto(`${origin}/?mode=${mode}&width=${width}&theme=${theme}${extra}`);if(mode==='migration')await page.getByRole('button',{name:'Review import…',exact:true}).waitFor();else await page.locator('.pr-trigger,.pr-approval').first().waitFor();};
const tab=async name=>{const t=page.getByRole('tab',{name,exact:true});if(await t.isVisible())await t.click();};
const shot=async(name,locator)=>{await locator.scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,name+'.png'),fullPage:true});};
const scan=async(name,locator)=>{
  const text=await locator.innerText();
  // JSON/definitions are intentionally exact data, not display-number formatting.
  const bad=text.match(/\b(?:NaN|undefined|null|Infinity)\b|\b\d+\.\d{4,}\b/g)||[];
  scans.push({name,bad});check(name+' no raw/invalid display numbers',bad.length===0);
};
const rate=4.166666666666667;
const feed={kind:'github.search',every:'15m',params:{repo:'NousResearch/hermes-agent',type:'pr'}};
const draft={definition:{pulse:1,id:'fractional-review',title:'Search review',icon:'hermes',feeds:{main:feed},display:[{type:'bar',value:'main.recent'}]},preview:null,preview_state:'after_approval',preview_calls:0,budget:{hosts:['api.github.com'],req_per_hour:rate},remaining_req_per_hour:4.16,disclosure:{feeds:[{name:'main',...feed,req_per_hour:rate,hosts:['api.github.com'],target:feed.params.repo}],icon_hosts:[]}};
const install=async value=>{await page.evaluate(value=>{Object.assign(window.__pulseStatus.drafts[0],value);window.__emitPulse('draft.updated');},value);await wait();};
const approval=async name=>{
  const card=page.locator('.pr-approval').first(),text=await card.innerText();
  check(name+' feed ceil estimate',await card.locator('.pr-feed-disclosure').innerText().then(t=>t.includes('≈5 req/h')));
  check(name+' total ceil estimate',text.includes('total ≈5 req/h'));
  await scan(name,card);
};
try {
  if(section !== 'edges') {
    for(const theme of ['dark','light'])for(const width of [248,320,900,1280]){
      const id=`${width}-${theme}`;
      await visit('blocks',width,theme);
      for(const trigger of await page.locator('.pr-trigger').all())await trigger.click();
      await scan(id+' display pulse cards',page.locator('.pr-shell').first());
      await shot('cards-'+id,page.locator('.pr-shell').first());
      await visit('pending',width,theme);await install(draft);
      await approval(id+' pending');
      check(id+' exact fractional headroom still blocks approval',await page.locator('.pr-approval').first().getByRole('button',{name:'Approve',exact:true}).isDisabled());
      await install({...draft,remaining_req_per_hour:rate});
      check(id+' exact equal fractional headroom permits approval',!await page.locator('.pr-approval').first().getByRole('button',{name:'Approve',exact:true}).isDisabled());
      check(id+' footer uses estimate convention',/≈\d[\d,]* req\/h/.test(await page.locator('.pr-foot').getAttribute('title') || await page.locator('.pr-foot [title]').getAttribute('title')));
      await shot('pending-'+id,page.locator('.pr-approval').first());
      await page.locator('.pr-pending .pr-trigger').first().click();await approval(id+' expanded');
      await scan(id+' expanded pulse cards',page.locator('.pr-shell').first());
      await visit('pending',width,theme,'&card');await install(draft);await approval(id+' transcript');
      await shot('transcript-'+id,page.locator('.pr-approval').first());
      await visit('builder',width,theme);await authoring(page);
      const field=p=>compatibleField(page,p);
      await previewTools(page,async()=>{
        await field('/appearance').selectOption(theme);
        check(id+' data source labelled',await page.getByRole('group',{name:'Preview data',exact:true}).count()===1);
        check(id+' simulate state labelled',await page.getByRole('combobox',{name:'Simulate condition',exact:true}).count()===1);
        check(id+' normal simulated by default',await field('/sample-state').textContent()==='Simulate: normal');
        await field('/sample-state').click();
        check(id+' all state options explicitly simulated',await page.getByRole('option').evaluateAll(es=>es.length===7&&es.every(e=>e.textContent.startsWith('Simulate: '))));
        await page.keyboard.press('Escape');
      });
      check(id+' persistent sample watermark',await page.locator('.pr-builder-watermark').isVisible());
      await scan(id+' builder preview',page.locator('.pr-b2-preview'));
      check(id+' no overflow',await page.locator('.pr-shell').evaluate(e=>e.scrollWidth<=e.clientWidth+1));
      await shot('builder-'+id,page.locator('.pr-builder-preview'));
      await scan(id+' builder compose',page.locator('.pr-b2-controls'));
      await previewTools(page,()=>field('/sample-state').selectOption('Simulate: stale'));
      check(id+' stale explicitly simulated',await page.locator('.pr-builder-preview').innerText().then(t=>t.includes('Simulated stale')&&!t.includes('cached measurements')));
      await applyDefinition(page,draft.definition);
      check(id+' definition budget ceil estimate',await page.locator('.pr-b2-controls').innerText().then(t=>t.includes('≈5 req/h')));
      await review(page);
      await approval(id+' builder review');
      await shot('builder-review-'+id,page.locator('.pr-builder-review .pr-approval'));
      check(id+' builder exact rate retained',await page.evaluate(rate=>Math.abs(window.__pulseStatus.drafts.at(-1).budget.req_per_hour-rate)<1e-12,rate));
      check(id+' no implicit approval',await page.evaluate(()=>!window.__pulseRestCalls.some(c=>c.path.endsWith('/approve'))));
    }
    await visit('builder',900,'dark');await page.locator('[data-id="builder-live"] .pr-trigger').click();
    await page.getByRole('button',{name:'Edit pulse',exact:true}).click();await wait();
    for(const mode of ['Cached','Measured']){
      await previewTools(page,()=>page.getByRole('button',{name:mode,exact:true}).click());
      check(mode+' hides simulated state control',await page.locator('[data-field="/sample-state"]').count()===0);
      await previewTools(page,async()=>check(mode+' explains actual state',await page.locator('.pr-b2-tools').innerText().then(t=>t.includes('State comes from the approved pulse; simulation is Sample-only.'))));
      check(mode+' no sample watermark',await page.locator('.pr-builder-watermark').count()===0);
      await shot('builder-'+mode.toLowerCase(),page.locator('.pr-builder-preview'));
    }
    await previewTools(page,()=>page.getByRole('button',{name:'Sample',exact:true}).click());
    check('return to sample restores simulated normal and watermark',await page.locator('.pr-builder-watermark').isVisible());
  }
  if(section !== 'matrix') {
    // Unknown/nonfinite disclosure never leaks a JS sentinel or enables consent.
    for(const value of [null,'NaN','undefined',-1]){
      await visit('pending',320,'dark');const d=structuredClone(draft);d.disclosure.feeds[0].req_per_hour=value;await install(d);
      await scan('invalid rate '+String(value),page.locator('.pr-approval').first());
      check('invalid rate '+String(value)+' displays unknown',await page.locator('.pr-feed-disclosure').innerText().then(t=>t.includes('unknown req/h')));
      check('invalid rate '+String(value)+' cannot approve',await page.locator('.pr-approval').first().getByRole('button',{name:'Approve',exact:true}).isDisabled());
    }
    for(const value of [0,4,1234.1]){
      await visit('pending',320,'dark');const d=structuredClone(draft);d.budget.req_per_hour=value;d.disclosure.feeds[0].req_per_hour=value;await install(d);
      const expected=`≈${new Intl.NumberFormat().format(Math.ceil(value))} req/h`;
      check('rate '+value+' ceiling/grouping',await page.locator('.pr-feed-disclosure').innerText().then(t=>t.includes(expected)));
      check('rate '+value+' total convention',await page.locator('.pr-approval').first().innerText().then(t=>t.includes('total '+expected)));
    }
    await visit('pending',320,'dark');
    const mixed=structuredClone(draft);mixed.definition.feeds.second=feed;mixed.disclosure.feeds.push({...mixed.disclosure.feeds[0],name:'second'});mixed.budget.req_per_hour=rate*2;await install(mixed);
    check('multi-feed rates each round up',await page.locator('.pr-feed-disclosure').evaluateAll(es=>es.length===2&&es.every(e=>e.textContent.includes('≈5 req/h'))));
    check('total rounds exact sum not displayed feeds',await page.locator('.pr-approval').first().innerText().then(t=>t.includes('total ≈9 req/h')));
    for(const value of ['NaN','Infinity','missing']){
      await visit('pending',320,'dark');
      await page.evaluate(value=>{for(const p of window.__pulseStatus.pulses){if(value==='missing')delete p.budget;else p.budget.req_per_hour=Number(value);}window.__emitPulse('draft.updated');},value);await wait();
      await page.locator('.pr-row:not(.pr-pending) .pr-trigger').first().click();
      check('active '+value+' budget unknown not zero',await page.locator('.pr-details').first().innerText().then(t=>t.includes('unknown req/h')));
      check('footer '+value+' budget unknown',await page.locator('.pr-foot [title]').getAttribute('title').then(t=>t.includes('unknown req/h')));
      await scan('active '+value,page.locator('.pr-shell').first());
    }
    for(const value of [rate,null]){
      await visit('migration',320,'dark');
      await page.evaluate(value=>{window.__pulseStatus.import_plan.budget={hosts:['discord.com'],req_per_hour:value};},value);
      await page.getByRole('button',{name:'Review import…',exact:true}).click();await page.getByRole('button',{name:'Confirm import',exact:true}).waitFor();await wait();
      const card=page.getByRole('region',{name:'Import from Discord Pulse',exact:true});
      check('import '+value+' honest estimate and collection wording',await card.innerText().then(t=>t.includes(value===null?'unknown req/h':'≈5 req/h')&&t.includes('After import:')&&!t.includes('while viewed')));
      await scan('import '+value,card);
    }
  }
  check('no runtime errors',errors.length===0);check('no remote requests',remote.length===0);
} finally {
  fs.writeFileSync(path.join(out,`ui-nits-${section}-results.json`),JSON.stringify({checks:checks.length,failures,errors,remote,scans},null,2));
  await browser.close();
}
assert.equal(failures.length,0,failures.join('\n'));
console.log(`${checks.length} UI nits browser checks passed`);
