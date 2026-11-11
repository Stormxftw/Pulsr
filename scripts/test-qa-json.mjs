// End-to-end http_json QA: real computation + recorded public shapes; no live egress.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import {review} from './builder2-test-helpers.mjs';
const req=createRequire(path.join(process.argv[2],'package.json'));
const {chromium}=req('playwright');
const origin=process.env.PULSE_PREVIEW_ORIGIN || 'http://127.0.0.1:5531';
const out=process.argv[3];fs.mkdirSync(out,{recursive:true});
const rows=JSON.parse(execFileSync(process.env.PULSE_BUILDER_PYTHON || 'python',['scripts/qa-json-status.py'],{encoding:'utf8'}));
const browser=await chromium.launch({channel:'msedge',headless:true});
const page=await browser.newPage({viewport:{width:1200,height:1100},reducedMotion:'reduce'});
const checks=[],failures=[],errors=[],remote=[];
const check=(name,ok)=>{checks.push(name);if(!ok)failures.push(name);console.log(`${ok?'PASS':'FAIL'} ${name}`);};
page.on('pageerror',e=>errors.push(String(e)));
await page.route('**/*',r=>{if(/^https?:/.test(r.request().url())&&!r.request().url().startsWith(origin+'/')){remote.push(r.request().url());return r.abort();}return r.continue();});
await page.route('**/ui-fixture/hero',async r=>{const response=await r.fetch();const seed=await response.json();seed.pulses=rows;seed.drafts=[];seed.as_of=1794189600;await r.fulfill({json:seed});});
const visit=async(width,theme,group=false)=>{
  await page.goto(`${origin}/?mode=hero&width=${width}&theme=${theme}&case=${group?'circles':'rows'}`);
  await page.locator('.pr-row,.pr-circle').first().waitFor();
};
const shot=name=>page.screenshot({path:path.join(out,name+'.png'),fullPage:true});
try {
  for(const width of [320,480,670])for(const theme of ['dark','light']){
    await visit(width,theme);
    const weather=page.locator('[data-id=home-weather]');
    check(`${width} ${theme} weather headline`,(await weather.locator('.pr-trigger').innerText()).includes('48 °F'));
    check(`${width} ${theme} weather emoji`,(await weather.locator('.pr-avatar').innerText()).includes('🌦'));
    check(`${width} ${theme} weather accessible headline`,(await weather.locator('.pr-trigger').getAttribute('aria-label')).includes('48 °F'));
    check(`${width} ${theme} CS2 brand`,await page.locator('[data-id=live-players-cs2] .pr-brand[data-brand=counterstrike]').count()===1);
    await weather.locator('.pr-trigger').click();
    check(`${width} ${theme} all weather blocks expanded`,await weather.locator('.pr-display > .pr-block').count()===3);
    const text=await weather.locator('.pr-display').innerText();
    check(`${width} ${theme} wind rain AQI exact`,['5.7 mph','0 in','37','Air quality (US AQI)'].every(s=>text.includes(s)));
    check(`${width} ${theme} independent scales`,await weather.locator('.pr-bars').getAttribute('data-scale')==='independent');
    check(`${width} ${theme} temperature spark`,await weather.locator('.pr-spark__line').count()===1);
    check(`${width} ${theme} no overflow`,await page.locator('.pr-shell').evaluate(e=>e.scrollWidth<=e.clientWidth+1));
    await shot(`weather-${width}-${theme}`);
    const steam=page.locator('[data-id=live-players-cs2]');await steam.locator('.pr-trigger').click();
    check(`${width} ${theme} Steam grouped integer`,(await steam.locator('.pr-stat__value').last().innerText())==='459,907');
    check(`${width} ${theme} Steam usual`,(await steam.locator('.pr-display').innerText()).includes('92% of usual'));
    check(`${width} ${theme} grouped range`,(await steam.locator('.pr-range').innerText()).includes('1,000,000'));
    await shot(`steam-${width}-${theme}`);
    await page.evaluate(()=>{const p=window.__pulseStatus.pulses[0];p.title='Louisville · weather & air · very long Unicode title 🌦️ 空気';const item=p.display[1].items[2];Object.assign(item,{unknown:true,value:null,value_text:null,reason:'JSON metric missing or not a finite number.',fill:null});window.__emitPulse('draft.updated');});
    await weather.locator('.pr-trigger').click();
    check(`${width} ${theme} unknown AQI never zero`,await weather.locator('.pr-display .pr-bars > .pr-item').last().locator('.pr-bar__fill').count()===0 && (await weather.locator('.pr-display').innerText()).includes('JSON metric missing'));
    check(`${width} ${theme} long Unicode title contained`,await page.locator('.pr-shell').evaluate(e=>e.scrollWidth<=e.clientWidth+1));
    await page.evaluate(()=>{const item=window.__pulseStatus.pulses[0].display[1].items[1];item.max=0.0004;item.caption='0% of 0.0004';window.__emitPulse('draft.updated');});
    await page.waitForTimeout(80);
    check(`${width} ${theme} tiny range retains precision`,(await weather.locator('.pr-display .pr-range').nth(1).innerText()).includes('0.0004'));
    await shot(`unknown-${width}-${theme}`);
    for(const state of ['stale','degraded','backoff','error']){
      await page.evaluate(state=>{const p=window.__pulseStatus.pulses[0];p.state=state;p.error=state==='error'?'Public JSON redirect refused. Use the final HTTPS endpoint in a replacement definition. Cached values are preserved.':null;p.backoff_until=window.__pulseStatus.as_of+120;window.__emitPulse('draft.updated');},state);
      await page.waitForTimeout(80);
      const stateText=await weather.innerText();
      check(`${width} ${theme} ${state} accurate message`,stateText.includes({stale:'Stale',degraded:'Degraded',backoff:'retry',error:'redirect'}[state]));
    }
    check(`${width} ${theme} no invalid strings`,!/(NaN|undefined|\[object Object\])/.test(await page.locator('.pr-shell').innerText()));
  }
  await page.addInitScript(()=>{const layout={version:1,groups:[{id:'json-demo',title:'Weather and games',collapsed:true,children:[{pulse:'home-weather'},{pulse:'live-players-cs2'}]}],ungrouped:[]};sessionStorage.setItem('pulse-layout-fixture:hero:circles:false:preview',JSON.stringify(layout));});
  await visit(320,'dark',true);
  check('collapsed circles preserve weather emoji and CS2 glyph',await page.locator('.pr-circle .pr-avatar').count()===2&&await page.locator('.pr-circle .pr-brand').count()===1);
  const circle=page.locator('.pr-circle').first();await circle.focus();await page.waitForTimeout(700);
  check('circle accessible name uses headline',(await circle.getAttribute('aria-label')).includes('48 °F'));
  check('focus tooltip uses headline',(await page.getByRole('tooltip').last().innerText()).includes('48 °F'));
  await shot('circles-focus-dark-320');
  for(const template of ['weather','steam','json']){
    await page.goto(`${origin}/?mode=builder&width=670&theme=dark`);await page.getByRole('button',{name:'New pulse',exact:true}).click();
    const title={weather:'Weather & air',steam:'Game players (Steam)',json:'Any website JSON'}[template];
    await page.locator('.pr-b2-template').filter({has:page.getByText(title,{exact:true})}).click();
    const input=key=>page.locator(`[data-template-field="${key}"], [data-field="/template/${key}"]`).locator('input,textarea').first();
    // Template form controls are accessible by their visible labels.
    if(template==='weather'){
      await page.getByLabel('City',{exact:true}).fill('Louisville');await page.waitForTimeout(700);
      check('city typing has no lookup',await page.evaluate(()=>!window.__builderLookups));
      await page.getByLabel('Allow exactly one request',{exact:true}).check();
      await page.getByRole('button',{name:'Find',exact:true}).click();await page.getByRole('button',{name:/Louisville.*Kentucky/}).click();
      check('city explicit click sends one lookup',await page.evaluate(()=>window.__builderLookups===1));
    }else if(template==='steam'){
      await page.getByLabel('Steam store link or app ID',{exact:true}).fill('Counter-Strike 2');await page.waitForTimeout(700);
      check('Steam typing has no lookup',await page.evaluate(()=>!window.__builderLookups));
      await page.getByLabel('Allow exactly one request',{exact:true}).check();
      await page.getByRole('button',{name:'Find',exact:true}).click();await page.getByRole('button',{name:'Counter-Strike 2',exact:true}).click();
      check('Steam explicit click sends one lookup',await page.evaluate(()=>window.__builderLookups===1));
    }else{
      await page.getByLabel('Public JSON URL',{exact:true}).fill('https://example.org/counts');
      await page.getByLabel('Numbers to watch',{exact:true}).fill('{"players":"/response/player_count"}');
    }
    await page.getByRole('button',{name:'Next',exact:true}).click();await page.locator('.pr-builder-preview .pr-block').first().waitFor({state:'attached'});
    check(`${template} sample preview rendered`,await page.locator('.pr-builder-preview .pr-block').count()>0);
    if(template==='weather')check('weather preview defaults Fahrenheit', (await page.locator('.pr-builder-preview').innerText()).includes('°F'));
    await shot(`builder-${template}`);
    await review(page);
    const disclosure=await page.locator('.pr-builder-review .pr-approval').innerText();
    const hosts={weather:['api.open-meteo.com','air-quality-api.open-meteo.com'],steam:['api.steampowered.com'],json:['example.org']}[template];
    check(`${template} frozen disclosure hosts`,hosts.every(host=>disclosure.includes(host)));
    check(`${template} no arbitrary-host preapproval poll`,await page.evaluate(()=>window.__pulseStatus.drafts.at(-1).preview_calls===0));
    await shot(`review-${template}`);
  }
  check('no renderer errors',errors.length===0);check('no remote requests',remote.length===0);
  fs.writeFileSync(path.join(out,'qa-json-results.json'),JSON.stringify({checks:checks.length,failures,errors,remote},null,2));
  assert.equal(failures.length,0,failures.join('\n'));
  console.log(`${checks.length} http_json browser checks passed`);
}finally{await browser.close();}
