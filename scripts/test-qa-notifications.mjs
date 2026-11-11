// Counts-only synthetic engine -> real renderer; all source/network I/O blocked.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import {review} from './builder2-test-helpers.mjs';
const req=createRequire(path.join(process.argv[2],'package.json'));
const {chromium}=req('playwright');
const origin=process.env.PULSE_PREVIEW_ORIGIN || 'http://127.0.0.1:5571';
const out=process.argv[3];fs.mkdirSync(out,{recursive:true});
const rows=JSON.parse(execFileSync(process.env.PULSE_BUILDER_PYTHON || 'python',['scripts/qa-notifications-status.py'],{encoding:'utf8'}));
const browser=await chromium.launch({channel:'msedge',headless:true});
const page=await browser.newPage({viewport:{width:1250,height:1100},reducedMotion:'reduce'});
const checks=[],failures=[],errors=[],remote=[];
const check=(name,ok)=>{checks.push(name);if(!ok)failures.push(name);console.log(`${ok?'PASS':'FAIL'} ${name}`);};
page.on('pageerror',e=>errors.push(String(e)));
await page.route('**/*',r=>{if(/^https?:/.test(r.request().url())&&!r.request().url().startsWith(origin+'/')){remote.push(r.request().url());return r.abort();}return r.continue();});
await page.route('**/ui-fixture/hero',async r=>{const response=await r.fetch();const seed=await response.json();seed.pulses=rows;seed.drafts=[];seed.as_of=1794189600;await r.fulfill({json:seed});});
const visit=async(width,theme,circles=false)=>{
  await page.goto(`${origin}/?mode=hero&width=${width}&theme=${theme}&case=${circles?'circles':'rows'}`);
  await page.locator('.pr-row,.pr-circle').first().waitFor();
};
const shot=name=>page.screenshot({path:path.join(out,name+'.png'),fullPage:true});
const expand=async id=>{const trigger=page.locator(`[data-id=${id}] .pr-trigger`);if(await trigger.getAttribute('aria-expanded')==='false')await trigger.click();};
try{
  for(const width of [320,480,670])for(const theme of ['dark','light']){
    const name=`${width}-${theme}`;await visit(width,theme);
    for(const kind of ['stat','rings','bar','bars','score','spark']){
      await expand('notify-'+kind);
      check(name+' '+kind+' block renders',await page.locator(`[data-id=notify-${kind}] .pr-display .pr-block`).count()>0);
    }
    await expand('notify-stat');
    check(name+' age is a readable duration',(await page.locator('[data-id=notify-stat]').innerText()).includes('3h 7m ago'));
    await shot('duration-'+name);
    // Notification mode: the collapsed row is the inbox line, not the hero block's bare number.
    check(name+' zero is measured',(await page.locator('[data-id=notify-zero] .pr-trigger .pr-inbox-line').innerText()).startsWith('Nothing waiting'));
    check(name+' large count grouping',(await page.locator('[data-id=notify-large] .pr-trigger .pr-inbox-line').innerText()).startsWith('12,345 waiting')&&(await page.locator('[data-id=notify-large] .pr-inbox-count').innerText())==='99+');
    await expand('notify-partial');
    check(name+' partial coverage is unknown',(await page.locator('[data-id=notify-partial]').innerText()).includes('Only 1 of 2 selected apps available'));
    await shot('unknown-'+name);
    await expand('notify-missing');
    check(name+' missing store reason',(await page.locator('[data-id=notify-missing]').innerText()).includes('Windows notification store not found'));
    await expand('notify-unsupported');
    check(name+' unsupported reason',(await page.locator('[data-id=notify-unsupported]').innerText()).includes('only available on Windows'));
    await expand('notify-bars');
    check(name+' hour warming is explicit',(await page.locator('[data-id=notify-bars]').innerText()).includes('first complete observation window'));
    await expand('notify-bar');
    check(name+' learning range not absurd percent',(await page.locator('[data-id=notify-bar]').innerText()).includes('Baseline not ready'));
    await expand('notify-legacy');
    const legacy=await page.locator('[data-id=notify-legacy]').innerText();
    // Notification mode: a pulse without its own display shows the inbox card in place of capsule and lines.
    check(name+' legacy Action Center semantics',['2 waiting','in Windows','not unread messages','No network','never message text','3h 7m ago'].every(t=>legacy.includes(t)));
    check(name+' no overflow',await page.locator('.pr-shell').evaluate(e=>e.scrollWidth<=e.clientWidth+1));
    check(name+' no raw sentinels',!/(NaN|undefined|\[object Object\]|\bnull\b|minutes_since_last)/.test(await page.locator('.pr-shell').innerText()));
    await shot('notifications-'+name);
    await expand('notify-stat');
    for(const state of ['stale','error','degraded']){
      await page.evaluate(state=>{const p=window.__pulseStatus.pulses.find(p=>p.id==='notify-stat');p.state=state;p.error=state==='error'?'Desktop notification counts are temporarily unavailable.':null;window.__emitPulse('draft.updated');},state);
      await page.waitForTimeout(100);
      check(name+' '+state+' message',(await page.locator('[data-id=notify-stat]').innerText()).includes({stale:'Stale',error:'temporarily unavailable',degraded:'Degraded'}[state]));
    }
    await page.evaluate(()=>{window.__pulseStatus.pulses[0].title='Notifications · long Unicode name 通知 🔔 '.repeat(8);window.__emitPulse('draft.updated');});
    check(name+' long title contained',await page.locator('.pr-shell').evaluate(e=>e.scrollWidth<=e.clientWidth+1));
  }
  await page.addInitScript(()=>{const layout={version:1,groups:[{id:'notifications',title:'Local notifications',collapsed:true,children:[{pulse:'notify-stat'},{pulse:'notify-legacy'}]}],ungrouped:[]};sessionStorage.setItem('pulse-layout-fixture:hero:circles:false:preview',JSON.stringify(layout));});
  for(const theme of ['dark','light']){
    await visit(320,theme,true);const circle=page.locator('.pr-circle').first();
    // Notification mode: names and tooltips say where the notifications are waiting.
    check(theme+' circle headline honest',(await circle.getAttribute('aria-label')).includes('2 waiting in Windows'));
    await circle.hover();await page.waitForTimeout(700);
    check(theme+' hover tip honest',(await page.getByRole('tooltip').last().innerText()).includes('2 waiting in Windows'));
    await page.mouse.move(1200,1000);await circle.focus();await page.waitForTimeout(700);
    check(theme+' focus tip honest',(await page.getByRole('tooltip').last().innerText()).includes('2 waiting in Windows'));
    await shot('circles-focus-'+theme);
  }
  await page.goto(`${origin}/?mode=builder&width=320&theme=dark`);
  await page.getByRole('button',{name:'New pulse',exact:true}).click();
  await page.locator('.pr-b2-template').filter({has:page.getByText('Desktop notifications',{exact:true})}).click();
  check('template explains local source',(await page.locator('.pr-b2-controls').innerText()).includes('local Windows notification store'));
  await page.getByRole('button',{name:'Next',exact:true}).click();
  await page.locator('.pr-builder-preview .pr-block').first().waitFor({state:'attached'});
  check('template sample preview labelled',await page.locator('.pr-builder-watermark').isVisible());
  check('template preview honest label',(await page.locator('.pr-builder-preview').innerText()).includes('In Action Center'));
  await shot('builder-notifications');
  await review(page);
  const approval=await page.locator('.pr-builder-review .pr-approval').innerText();
  check('draft local disclosure complete',['local Windows notification store','read-only','never message text','No network','not unread messages','0 req/h','none direct'].every(t=>approval.includes(t)));
  check('draft preview has no local reads',await page.evaluate(()=>window.__pulseStatus.drafts.at(-1).preview_calls===0));
  check('no implicit approval',await page.evaluate(()=>!window.__pulseRestCalls.some(c=>c.path.endsWith('/approve'))));
  await shot('review-notifications');
  check('no renderer errors',errors.length===0);check('no remote requests',remote.length===0);
}finally{
  fs.writeFileSync(path.join(out,'qa-notifications-results.json'),JSON.stringify({checks:checks.length,failures,errors,remote},null,2));
  await browser.close();
}
assert.equal(failures.length,0,failures.join('\n'));
console.log(`${checks.length} notifications browser checks passed`);
