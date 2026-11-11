// Message preview (opt-in): a notifications pulse approved with `preview: true` shows who each
// waiting notification is from and its text, one at a time on the row and all of them in the card.
// Real engine rows from the preview fixture -> real renderer. Rows without items are unchanged,
// and the agent's compact status carries no preview text.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
const req=createRequire(path.join(process.argv[2],'package.json'));
const {chromium}=req('playwright');
const origin=process.env.PULSE_PREVIEW_ORIGIN || 'http://127.0.0.1:5571';
const out=process.argv[3];fs.mkdirSync(out,{recursive:true});
const NOW=1794189600;
const fixture=JSON.parse(execFileSync(process.env.PULSE_BUILDER_PYTHON || 'python',['scripts/qa-preview-status.py'],{encoding:'utf8'}));
const rows=fixture.pane;
const checks=[],errors=[],remote=[];
const check=(name,value)=>{assert.ok(value,name);checks.push(name);console.log('PASS '+name);};
// --- backend shape, before any rendering ---
const on=rows.find(p=>p.id==='preview-on'),off=rows.find(p=>p.id==='preview-off');
check('backend: preview pulse carries items',Array.isArray(on.inbox.items)&&on.inbox.items.length===3);
check('backend: items are bounded to 120 characters',on.inbox.items.every(it=>(it.text||'').length<=120&&(it.from||'').length<=120));
check('backend: counts-only pulse carries no items',off.inbox&&!('items' in off.inbox));
check('backend: preview disclosure is marked',on.notifications.preview===true&&!('preview' in off.notifications));
check('backend: the agent status carries no preview text',!JSON.stringify(fixture.agent).includes('Ada')&&!JSON.stringify(fixture.agent).includes('demo at four')&&fixture.agent.every(p=>!p.inbox||!('items' in p.inbox)));
const run=async(reducedMotion)=>{
  const browser=await chromium.launch({channel:'msedge',headless:true});
  const page=await browser.newPage({viewport:{width:900,height:2000},timezoneId:'UTC',locale:'en-US',reducedMotion});
  page.on('pageerror',e=>errors.push(String(e)));
  page.on('console',m=>{if(['error','warning'].includes(m.type())&&!m.text().includes('[vite]'))errors.push(m.text());});
  await page.route('**/*',r=>{if(/^https?:/.test(r.request().url())&&!r.request().url().startsWith(origin+'/')){remote.push(r.request().url());return r.abort();}return r.continue();});
  await page.route('**/ui-fixture/hero',async r=>{const response=await r.fetch();const seed=await response.json();seed.pulses=structuredClone(rows);seed.drafts=[];seed.as_of=NOW;await r.fulfill({json:seed});});
  return {browser,page};
};
const visit=async(page,width,theme='dark')=>{for(let attempt=0;;attempt++){try{await page.goto(`${origin}/?mode=hero&width=${width}&theme=${theme}&case=rows`);await page.locator('.pr-row').first().waitFor();return;}catch(error){if(attempt)throw error;}}};
let {browser,page}=await run('no-preference');
const row=id=>page.locator(`[data-id="${id}"]`);
const line=id=>row(id).locator('.pr-preview-line');
try{
  await page.clock.install({time:NOW*1000});
  await visit(page,320);
  // --- collapsed: the counts stay, one notification under them ---
  check('row: the counts line is unchanged',/^3 waiting · latest/.test((await row('preview-on').locator('.pr-inbox-line').innerText()).replace(/\s+/g,' ').replace(/ ?· ?/g,' · ').trim()));
  check('row: one preview line',await line('preview-on').count()===1);
  check('row: newest first, sender then text',(await line('preview-on').innerText()).startsWith('Ada (#general, Test Server): Are we still on for the demo at four?'));
  check('row: position shown',(await line('preview-on').locator('.pr-preview-pos').innerText()).includes('1/3'));
  check('row: never announced',await line('preview-on').getAttribute('aria-live')==='off');
  check('row: the accessible name stays counts only',!(await row('preview-on').locator('.pr-trigger').getAttribute('aria-label')).includes('Ada'));
  check('row: a long text is cut with an ellipsis, not wrapped',await line('preview-on').evaluate(n=>getComputedStyle(n).whiteSpace==='nowrap'&&getComputedStyle(n).textOverflow==='ellipsis'));
  // --- rotation every four seconds ---
  await page.clock.runFor(4100);
  check('rotate: the second after four seconds',(await line('preview-on').getAttribute('data-index'))==='1'&&(await line('preview-on').innerText()).startsWith('Grace: This message'));
  await page.clock.runFor(4000);
  check('rotate: a one-line toast shows its text alone',(await line('preview-on').getAttribute('data-index'))==='2'&&(await line('preview-on').innerText()).startsWith('A toast with only one line'));
  await page.clock.runFor(4000);
  check('rotate: wraps back to the newest',(await line('preview-on').getAttribute('data-index'))==='0');
  // --- hover holds it ---
  await row('preview-on').locator('.pr-trigger').hover();
  check('hover: held',await line('preview-on').getAttribute('data-held')==='true');
  await page.clock.runFor(9000);
  check('hover: does not turn while held',(await line('preview-on').getAttribute('data-index'))==='0');
  await page.mouse.move(0,1990);
  await page.clock.runFor(4100);
  check('hover: turns again after leaving',(await line('preview-on').getAttribute('data-index'))==='1');
  // --- keyboard focus holds it too ---
  await row('preview-on').locator('.pr-trigger').focus();
  const held=await line('preview-on').getAttribute('data-index');
  await page.clock.runFor(9000);
  check('focus: does not turn while focused',(await line('preview-on').getAttribute('data-index'))===held);
  await page.locator('body').evaluate(()=>document.activeElement?.blur());
  // --- expanded: the card lists them all ---
  await row('preview-on').locator('.pr-trigger').click();
  await row('preview-on').locator('.pr-details').waitFor();
  const list=row('preview-on').locator('.pr-preview-list li');
  check('card: lists every waiting preview',await list.count()===3);
  check('card: named list',await row('preview-on').locator('.pr-preview-list').getAttribute('aria-label')==='Waiting notifications');
  check('card: sender, text and age',/^Ada \(#general, Test Server\): Are we still on for the demo at four\? · 1m ago$/.test((await list.first().innerText()).replace(/\s+/g,' ').trim()));
  check('card: the disclosure says previews are on',(await row('preview-on').locator('.pr-details').innerText()).includes('Shows who waiting notifications are from and their text, here only. Never sent to Hermes. Local only. Never saved · No network.'));
  await row('preview-on').screenshot({path:path.join(out,'preview-expanded-320-dark.png')});
  // --- designed pulse: the same line, blocks kept ---
  check('designed: preview line too',await line('preview-designed').count()===1);
  // --- counts-only pulse: exactly as before ---
  check('counts only: no preview line',await line('preview-off').count()===0);
  await row('preview-off').locator('.pr-trigger').click();
  await row('preview-off').locator('.pr-details').waitFor();
  check('counts only: no list, counts-only disclosure',await row('preview-off').locator('.pr-preview-list').count()===0&&(await row('preview-off').locator('.pr-details').innerText()).includes('Counts and times only, never message text'));
  // --- fit across widths and themes ---
  for(const theme of ['dark','light'])for(const width of [231,320,400]){
    await visit(page,width,theme);
    const name=`${width} ${theme}`;
    check(`${name}: preview line stays one line inside the row`,await line('preview-on').evaluate(n=>{const r=n.getBoundingClientRect(),row=n.closest('.pr-trigger').getBoundingClientRect();return r.height<=20&&r.right<=row.right+0.5;}));
    check(`${name}: no horizontal overflow`,await page.locator('.pr-shell').evaluate(e=>e.scrollWidth<=e.clientWidth+1));
    await row('preview-on').screenshot({path:path.join(out,`preview-${width}-${theme}.png`)});
  }
  // --- rings-only rail: no line ---
  await visit(page,160);
  check('rail: no preview line in the rings-only rail',await line('preview-on').count()===0);
  await browser.close();
  // --- reduced motion: the newest, never turning ---
  ({browser,page}=await run('reduce'));
  await page.clock.install({time:NOW*1000});
  await visit(page,320);
  await page.clock.runFor(13000);
  check('reduced motion: stays on the newest',(await page.locator('[data-id="preview-on"] .pr-preview-line').getAttribute('data-index'))==='0');
  check('no remote requests',remote.length===0);
  check('no runtime warnings',errors.length===0);
  fs.writeFileSync(path.join(out,'notification-preview-results.json'),JSON.stringify({checks,errors,remote},null,2));
  console.log(`${checks.length} notification-preview browser checks passed`);
}finally{await browser.close();}
