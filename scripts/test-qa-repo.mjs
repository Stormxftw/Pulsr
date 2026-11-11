import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {compatibleField, pause} from './builder2-test-helpers.mjs';
const {chromium} = createRequire(path.join(process.argv[2], 'package.json'))('playwright');
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const out = process.argv[3]; fs.mkdirSync(out, {recursive:true});
const origin = process.env.PULSE_PREVIEW_ORIGIN || 'http://127.0.0.1:5521';
const rows = JSON.parse(execFileSync(process.env.PULSE_BUILDER_PYTHON || 'python', [path.join(root,'scripts/qa-repo-ui-fixtures.py')], {encoding:'utf8'}));
const browser = await chromium.launch({channel:'msedge',headless:true});
const page = await browser.newPage({viewport:{width:1100,height:1250},reducedMotion:'reduce'});
page.setDefaultTimeout(30000);
const checks=[], failures=[], errors=[], remote=[];
page.on('pageerror', e=>errors.push(String(e)));
await page.route('**/*', r=>{
  if (/^https?:/.test(r.request().url()) && !r.request().url().startsWith(origin+'/')) {remote.push(r.request().url());return r.abort();}
  return r.continue();
});
const check=(name,ok)=>{checks.push(name);if(!ok)failures.push(name);console.log(`${ok?'PASS':'FAIL'} ${name}`);};
const visit=async(mode,width,theme)=>{
  await page.goto(`${origin}/?mode=${mode}&width=${width}&theme=${theme}&case=qa-repo`,{waitUntil:'domcontentloaded',timeout:90000});
  await page.locator('.pr-row').first().waitFor({timeout:90000});
};
const set=async(name)=>{
  await page.evaluate(row=>{window.__pulseStatus.pulses=[row];window.__pulseStatus.drafts=[];window.__pulseStatus.as_of=1794189600;window.__emitPulse('draft.updated');},rows[name]);
  await page.waitForTimeout(180);
  const trigger=page.locator('[data-id=synthetic-ebay] .pr-trigger');
  await trigger.waitFor();if(await trigger.getAttribute('aria-expanded')!=='true')await trigger.click();
};
const shot=async(name)=>{await page.mouse.move(0,0);await page.screenshot({path:path.join(out,name+'.png'),fullPage:true});};
const contained=()=>page.locator('.pr-display').evaluate(root=>{
  const bounds=root.getBoundingClientRect();
  return root.scrollWidth<=root.clientWidth+1 && [...root.querySelectorAll('.pr-block,.pr-stat__value,.pr-item-label,.pr-range')].every(el=>{
    const b=el.getBoundingClientRect();return el.scrollWidth<=el.clientWidth+1 && b.left>=bounds.left-1 && b.right<=bounds.right+1;
  });
});
try {
  if(process.argv[4] !== 'circles') {
  for(const width of [320,480,670])for(const theme of ['dark','light']){
    await visit('blocks',width,theme);
    for(const name of ['counts','rings','activity','first','computing','queued','failing','no-access','large']){
      await set(name);
      check(`${name} ${theme} ${width}: display contained`,await contained());
      const text=await page.locator('.pr-display').innerText();
      check(`${name} ${theme} ${width}: no raw or invalid values`,!/(NaN|undefined|\[object Object\]|commits_week|ci_passing|hours_since_push)/.test(text));
      if(name==='counts')check(`${theme} ${width}: captured stars have separators`,text.includes('261,781'));
      if(name==='computing')check(`${theme} ${width}: unknown commits and no CI never zero/failing`,text.includes('GitHub is still computing commit stats')&&text.includes('No CI runs')&&!text.includes('Failing'));
      if(name==='queued')check(`${theme} ${width}: pending CI not failing`,text.includes('CI run is still running')&&!text.includes('Failing'));
      if(name==='failing')check(`${theme} ${width}: failed CI critical`,await page.locator('.pr-display [data-tone=crit]').count()===1);
      if(name==='activity') {check(`${theme} ${width}: duration is hours not count`,text.includes('3h 12m ago'));await shot(`activity-${theme}-${width}`);}
      if(name==='computing'&&width===320)await shot(`computing-${theme}-${width}`);
      if(name==='large'&&width===320)await shot(`large-${theme}-${width}`);
    }
  }
  for(const mode of ['value','delta']){
    await set(mode);
    check(`stat show=${mode} honors visibility`,await page.locator('.pr-display .pr-stat__value').count()===(mode==='value'?1:0)&&await page.locator('.pr-display .pr-stat__delta').count()===(mode==='delta'?1:0));
  }
  await set('large');
  check('large range has thousands separators',await page.locator('.pr-display .pr-range').innerText()==='0–1,000,000,000,000');
  for(const state of ['stale','degraded','error','backoff']){
    await set(state);
    check(`${state} state visible`,await page.locator(`[data-id=synthetic-ebay][data-state=${state}]`).count()===1);
    if(['stale','degraded'].includes(state))check(`${state} feed banner clear`,await page.locator('.pr-feed-status').innerText().then(t=>t.toLowerCase().includes(state)));
    if(state==='error')check('renamed error actionable in UI',(await page.locator('.pr-state-line').innerText()).includes('moved or was renamed'));
  }
  }
  await visit('groups',320,'dark');
  await page.evaluate(row=>{const p=window.__pulseStatus.pulses[0];const id=p.id;Object.assign(p,row,{id});window.__emitPulse('draft.updated');},rows.computing);
  await page.waitForTimeout(200);
  await page.locator('[data-group-id=communities] > .pr-group-head .pr-group-toggle').click();
  const circle=page.locator('[data-arr-pulse=pulse-1] .pr-circle');
  await circle.hover();await page.waitForTimeout(500);
  const tooltip=await page.getByRole('tooltip').innerText();
  check('collapsed tooltip describes displayed commit score, not hidden stars',tooltip.includes('GitHub is still computing commit stats')&&!tooltip.includes('stars'));
  check('unknown commit tooltip never appends a measured legacy intensity',!tooltip.includes('change intensity'));
  check('collapsed circle uses display hero unknown state',await circle.locator('[data-type=score] [data-state=unknown]').count()===1);
  await page.screenshot({path:path.join(out,'collapsed-computing-dark-320.png'),fullPage:true});
  await page.mouse.move(0,0);
  await page.getByRole('button',{name:'Manage Communities',exact:true}).focus();await page.keyboard.press('Tab');await page.waitForTimeout(500);
  check('keyboard focus has same semantic tooltip',await page.getByRole('tooltip').innerText().then(t=>t.includes('GitHub is still computing commit stats')));
  for(const activity of process.argv[4] === 'circles' ? [] : [false,true]) {
    await visit('builder',900,'dark');
    const button=name=>page.getByRole('button',{name,exact:true});
    await button('New pulse').click();await pause(page);
    await page.locator('.pr-b2-template').filter({has:page.getByText('GitHub repo',{exact:true})}).click();await pause(page);
    await compatibleField(page,'/template/repo').fill('NousResearch/hermes-agent');
    if(activity)for(const key of ['commits','last_push','ci'])await compatibleField(page,'/template/'+key).check();
    await pause(page);await button('Next').click();await pause(page);
    if(activity)check('builder activity preset matches live score/duration/states',await page.locator('.pr-builder-preview .pr-block[data-type=score]').count()===1&&await page.locator('.pr-builder-preview').innerText().then(t=>t.includes('3h 12m ago')&&t.includes('Passing')));
    await button('Next').click();await pause(page);
    const summary=await page.locator('.pr-b2-review-summary').innerText();
    check(`builder ${activity?'activity':'default'} discloses correct hosts and rate`,summary.includes('api.github.com')&&summary.includes(activity?'13':'8'));
    await button('Review permissions').click();await page.locator('.pr-builder-review .pr-approval').waitFor();
    const approval=await page.locator('.pr-builder-review .pr-approval').innerText();
    check(`builder ${activity?'activity':'default'} draft preserves options`,activity?approval.includes('participation')&&approval.includes('actions/runs'):!approval.includes('participation')&&!approval.includes('actions/runs'));
    await shot(`builder-${activity?'activity':'default'}-review`);
  }
  check('never activates a draft automatically',await page.evaluate(()=>!window.__pulseRestCalls.some(c=>c.path.endsWith('/approve'))));
  check('no page errors or remote requests',errors.length===0&&remote.length===0);
  fs.writeFileSync(path.join(out,'qa-repo-results.json'),JSON.stringify({checks:checks.length,failures,errors,remote},null,2));
  assert.deepEqual(failures,[]);
  console.log(`${checks.length} repo QA browser checks passed`);
} finally {await browser.close();}
