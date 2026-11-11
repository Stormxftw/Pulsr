// Notification mode: a notifications pulse reads as an inbox (waiting, last one, the day),
// not as a generic metric. Real engine and adapter rows -> real renderer; no network.
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
const rows=JSON.parse(execFileSync(process.env.PULSE_BUILDER_PYTHON || 'python',['scripts/qa-inbox-status.py'],{encoding:'utf8'}));
// The same reading from a backend that predates notification mode: no `inbox` field.
const older={...structuredClone(rows.find(p=>p.id==='inbox-waiting')),id:'inbox-older',title:'Older backend · notifications'};delete older.inbox;
const browser=await chromium.launch({channel:'msedge',headless:true});
const page=await browser.newPage({viewport:{width:900,height:2400},timezoneId:'UTC',locale:'en-US',reducedMotion:'reduce'});
const checks=[],errors=[],remote=[];
const check=(name,value)=>{assert.ok(value,name);checks.push(name);console.log('PASS '+name);};
page.on('pageerror',e=>errors.push(String(e)));
page.on('console',m=>{if(['error','warning'].includes(m.type())&&!m.text().includes('[vite]'))errors.push(m.text());});
await page.route('**/*',r=>{if(/^https?:/.test(r.request().url())&&!r.request().url().startsWith(origin+'/')){remote.push(r.request().url());return r.abort();}return r.continue();});
await page.route('**/ui-fixture/hero',async r=>{const response=await r.fetch();const seed=await response.json();seed.pulses=[...structuredClone(rows),structuredClone(older)];seed.drafts=[];seed.as_of=NOW;await r.fulfill({json:seed});});
// One retry: the first navigation after a cold preview-server start can exceed the timeout.
const visit=async(width,theme='dark')=>{for(let attempt=0;;attempt++){try{await page.goto(`${origin}/?mode=hero&width=${width}&theme=${theme}&case=rows`);await page.locator('.pr-row').first().waitFor();return;}catch(error){if(attempt)throw error;}}};
const row=id=>page.locator(`[data-id="${id}"]`);
// Visible text on one line; the separator dot is normalised because flex items break lines in innerText.
const words=async locator=>(await locator.innerText()).replace(/\s+/g,' ').replace(/ ?· ?/g,' · ').trim();
const open=async id=>{const trigger=row(id).locator('.pr-trigger');if(await trigger.getAttribute('aria-expanded')!=='true'){await trigger.click();await row(id).locator('.pr-details').waitFor();}};
// Text drawn wider than its box, to the fraction of a pixel (scrollWidth rounds).
const clipped=locator=>locator.evaluateAll(nodes=>nodes.filter(node=>{const range=document.createRange();range.selectNodeContents(node);const text=range.getBoundingClientRect(),box=node.getBoundingClientRect();return text.width>0&&(text.right>box.right+0.5||text.left<box.left-0.5);}).map(node=>node.className+': '+node.textContent));
const contrast=locator=>locator.evaluate(el=>{
  const rgb=value=>{const pen=document.createElement('canvas').getContext('2d',{willReadFrequently:true});pen.fillStyle='#000';pen.fillStyle=value;pen.fillRect(0,0,1,1);return [...pen.getImageData(0,0,1,1).data];};
  const lum=([r,g,b])=>{const f=v=>{v/=255;return v<=0.03928?v/12.92:((v+0.055)/1.055)**2.4;};return 0.2126*f(r)+0.7152*f(g)+0.0722*f(b);};
  const over=(top,under)=>{const a=top[3]/255;return [0,1,2].map(i=>top[i]*a+under[i]*(1-a));};
  let bg=[0,0,0,0];for(let e=el;e;e=e.parentElement){const c=rgb(getComputedStyle(e).backgroundColor);if(c[3]){bg=bg[3]?[...over(bg,c),255]:c;if(c[3]===255)break;}}
  if(!bg[3])bg=[255,255,255,255];const ink=over(rgb(getComputedStyle(el).color),bg),hi=Math.max(lum(ink),lum(bg)),lo=Math.min(lum(ink),lum(bg));return (hi+0.05)/(lo+0.05);});
try{
  await visit(320);
  // --- the collapsed row answers "do I have notifications, and when was the last one" ---
  check('waiting: the row says how many are waiting and when the latest arrived',/^2 waiting · latest 3h [67]m ago$/.test(await words(row('inbox-waiting').locator('.pr-inbox-line'))));
  check('waiting: the count is a badge on the title line',await words(row('inbox-waiting').locator('.pr-title-line .pr-inbox-count'))==='2');
  check('waiting: the badge explains itself',/2 notifications waiting in Windows/.test(await row('inbox-waiting').locator('.pr-inbox-count').getAttribute('title')));
  check('waiting: the row is marked as having notifications',await row('inbox-waiting').getAttribute('data-attention')==='notice');
  check('waiting: no "Change N/100" score on a notifications row',await row('inbox-waiting').locator('.pr-score').count()===0);
  check('waiting: the accessible name carries the same reading',/2 waiting in Windows; latest 3h [67]m ago/.test(await row('inbox-waiting').locator('.pr-trigger').getAttribute('aria-label')));
  const quietLine=await words(row('inbox-quiet').locator('.pr-inbox-line'));
  check(`quiet: the row says nothing is waiting and when the last one was (${quietLine})`,quietLine==='Nothing waiting · last 1d 3h ago');
  check('quiet: no badge and no attention',await row('inbox-quiet').locator('.pr-inbox-count').count()===0&&await row('inbox-quiet').getAttribute('data-attention')==='none');
  check('just started: waiting is known at once',await words(row('inbox-fresh').locator('.pr-inbox-line'))==='1 waiting · latest 40m ago');
  check('unreadable store: not measured, never zero',/^Not measured/.test(await words(row('inbox-missing').locator('.pr-inbox-line')))&&await row('inbox-missing').locator('.pr-inbox-count').count()===0&&await row('inbox-missing').getAttribute('data-attention')==='none');
  check('a designed pulse gets the same line and badge',/^2 waiting · latest 3h [67]m ago$/.test(await words(row('inbox-designed').locator('.pr-inbox-line')))&&await words(row('inbox-designed').locator('.pr-inbox-count'))==='2');
  check('the attention strip counts rows with notifications',/3 with notifications/.test(await words(page.locator('.pr-attention-text'))));
  await page.screenshot({path:path.join(out,'collapsed-320-dark.png'),clip:{x:0,y:0,width:340,height:520}});
  // --- an older backend (no summary) keeps the previous row exactly ---
  check('older backend: the capsule row is unchanged',(await words(row('inbox-older').locator('.pr-capsule'))).includes('2 in Action Center')&&await row('inbox-older').locator('.pr-inbox-line,.pr-inbox-count').count()===0&&await row('inbox-older').getAttribute('data-attention')==='none');
  check('older backend: the score chip is still shown',await row('inbox-older').locator('.pr-score').count()===1);
  await open('inbox-older');
  check('older backend: details have no inbox card and keep their lines',await row('inbox-older').locator('.pr-inbox').count()===0&&(await words(row('inbox-older').locator('.pr-lines'))).includes('Last one 3h'));
  // --- expanded: one card with the whole reading ---
  await open('inbox-waiting');
  const card=row('inbox-waiting').locator('.pr-inbox');
  check('card: headline is the waiting count',await words(card.locator('.pr-inbox-head'))==='2 waiting in Windows');
  check('card: the last notification has an age and a clock time',/^Last notification 3h [67]m ago · 10:53 PM$/.test(await words(card.locator('.pr-inbox-when'))));
  check('card: a fully watched day reports day and hour counts',await words(card.locator('.pr-inbox-counts'))==='4 in the last 24 hours · none in the last hour');
  const strip=card.locator('.pr-inbox-strip');
  check('card: the day strip is described for screen readers',await strip.getAttribute('role')==='img'&&/4 notifications in the last 24 hours/.test(await strip.getAttribute('aria-label')));
  const bars=await strip.locator('.pr-inbox-bar').evaluateAll(nodes=>nodes.map(node=>({count:Number(node.dataset.count),height:node.getBoundingClientRect().height,x:node.getBoundingClientRect().x})));
  const busyHeight=await strip.evaluate(node=>node.getBoundingClientRect().height);
  check('card: one slot per hour',bars.length===24);
  check('card: three hours had arrivals, in time order',bars.filter(b=>b.count>0).map(b=>b.count).join(',')==='1,1,2'&&bars.every((b,i)=>!i||b.x>bars[i-1].x));
  check('card: a busier hour draws a taller bar; an empty hour draws none',bars.find(b=>b.count===2).height>bars.find(b=>b.count===1).height&&bars.filter(b=>!b.count).every(b=>b.height===0));
  check('card: each bar names its hour and count',(await strip.locator('.pr-inbox-bar title').evaluateAll(nodes=>nodes.map(node=>node.textContent))).join(' | ')==='1 notification, 6:00 AM to 7:00 AM | 1 notification, 9:00 PM to 10:00 PM | 2 notifications, 10:00 PM to 11:00 PM');
  check('card: the strip has a time axis',await words(card.locator('.pr-inbox-axis'))==='24h ago 12h ago now');
  check('native details: no generic trend, lines or usual-sentence beside the card',await row('inbox-waiting').locator('.pr-trend,.pr-spark,.pr-normal,.pr-display').count()===0&&(await words(row('inbox-waiting').locator('.pr-lines')))==='');
  const waitingText=await words(row('inbox-waiting'));
  check('native details: the privacy statement stays',['not unread messages','never message text','No network'].every(t=>waitingText.includes(t)));
  await row('inbox-waiting').screenshot({path:path.join(out,'waiting-320-dark.png')});
  await open('inbox-quiet');
  const quiet=row('inbox-quiet').locator('.pr-inbox');
  check('quiet card: says so plainly',await words(quiet.locator('.pr-inbox-head'))==='Nothing waiting in Windows');
  check('quiet card: an old notification shows its weekday',await words(quiet.locator('.pr-inbox-when'))==='Last notification 1d 3h ago · Sat 10:55 PM');
  check('quiet card: an empty watched day is "None", not blank',await words(quiet.locator('.pr-inbox-counts'))==='None in the last 24 hours');
  check('quiet card: an empty day keeps the axis without a tall blank chart',await quiet.locator('.pr-inbox-strip').evaluate(node=>node.getBoundingClientRect().height)<=10&&busyHeight>=28);
  check('quiet card: the strip is empty but present',(await quiet.locator('.pr-inbox-bar').evaluateAll(nodes=>nodes.map(node=>Number(node.dataset.count)))).join('')==='0'.repeat(24));
  await row('inbox-quiet').screenshot({path:path.join(out,'quiet-320-dark.png')});
  await open('inbox-fresh');
  const fresh=row('inbox-fresh').locator('.pr-inbox');
  check('just started card: counts say since when, and do not claim a day',await words(fresh.locator('.pr-inbox-counts'))==='None since watching began at 2:00 AM');
  check('just started card: the unwatched part of the day is marked',await fresh.locator('.pr-inbox-unwatched').evaluate(node=>node.getBoundingClientRect().width/node.ownerSVGElement.getBoundingClientRect().width)>0.95);
  check('a fully watched day has no unwatched mark',await card.locator('.pr-inbox-unwatched').count()===0);
  await row('inbox-fresh').screenshot({path:path.join(out,'fresh-320-dark.png')});
  await open('inbox-missing');
  const missing=row('inbox-missing').locator('.pr-inbox');
  check('unreadable store card: reason, no strip, no counts',await words(missing.locator('.pr-inbox-head'))==='Not measured'&&(await words(missing)).includes('Windows notification store not found.')&&await missing.locator('.pr-inbox-strip,.pr-inbox-counts').count()===0);
  await open('inbox-designed');
  check('a designed pulse keeps its own blocks under the card',await row('inbox-designed').locator('.pr-inbox').count()===1&&await row('inbox-designed').locator('.pr-display .pr-block').count()===2);
  await row('inbox-designed').screenshot({path:path.join(out,'designed-320-dark.png')});
  check('no raw sentinels',!/(NaN|undefined|\[object Object\]|\bnull\b|minutes_since_last|new_1h)/.test(await words(page.locator('.pr-shell'))));
  // --- it is live: clearing the notifications clears the badge and the attention ---
  await page.evaluate(()=>{const p=window.__pulseStatus.pulses.find(p=>p.id==='inbox-waiting');p.inbox={...p.inbox,waiting:0};window.__emitPulse('draft.updated');});
  await page.waitForFunction(()=>document.querySelector('[data-id="inbox-waiting"]').dataset.attention==='none');
  await open('inbox-waiting');
  check('cleared: badge gone, headline updated',await row('inbox-waiting').locator('.pr-inbox-count').count()===0&&await words(row('inbox-waiting').locator('.pr-inbox-head'))==='Nothing waiting in Windows');
  check('cleared: the strip counts one fewer row',/2 with notifications/.test(await words(page.locator('.pr-attention-text'))));
  // --- Focus shows only the rows with something waiting ---
  await visit(320);
  await page.locator('.pr-attention').click();
  const visible=await page.locator('.pr-row').evaluateAll(nodes=>nodes.filter(node=>node.getBoundingClientRect().height>0).map(node=>node.dataset.id).sort());
  check('Focus keeps exactly the rows with notifications',visible.join(',')==='inbox-designed,inbox-fresh,inbox-waiting');
  // --- fit and contrast across widths and themes ---
  for(const theme of ['dark','light'])for(const width of [231,320,400]){
    const name=`${width} ${theme}`;await visit(width,theme);
    check(`${name}: collapsed lines are whole`,(await clipped(page.locator('.pr-inbox-line > span, .pr-inbox-count'))).length===0);
    // Rows open one at a time, so each card is measured while its own row is open.
    const cut=[],outside=[],ratios=[],split=[];
    for(const id of ['inbox-waiting','inbox-quiet','inbox-fresh','inbox-missing','inbox-designed']){
      await open(id);
      cut.push(...await clipped(row(id).locator('.pr-inbox p > span, .pr-inbox-head, .pr-inbox-axis span')));
      split.push(...await row(id).locator('.pr-inbox p.pr-measured-summary > span').evaluateAll(nodes=>nodes.filter(node=>getComputedStyle(node).whiteSpace!=='nowrap'||new Set([...node.getClientRects()].map(r=>Math.round(r.top))).size>1).map(node=>node.textContent)));
      if(!await row(id).locator('.pr-inbox').evaluate(node=>{const box=node.getBoundingClientRect(),host=node.closest('.pr-details').getBoundingClientRect();return box.width>0&&box.left>=host.left-0.5&&box.right<=host.right+0.5;}))outside.push(id);
      ratios.push(await contrast(row(id).locator('.pr-inbox-head strong')),await contrast(row(id).locator('.pr-inbox-when').first()));
      if(id==='inbox-waiting')await row(id).screenshot({path:path.join(out,`waiting-${width}-${theme}.png`)});
    }
    check(`${name}: card text is whole`,cut.length===0);
    check(`${name}: card phrases wrap whole, never mid-phrase`,split.length===0);
    check(`${name}: cards stay inside their rows`,outside.length===0);
    check(`${name}: no horizontal overflow`,await page.locator('.pr-shell').evaluate(e=>e.scrollWidth<=e.clientWidth+1));
    check(`${name}: badge, headline and last-notification line are readable (>=4.5:1)`,await contrast(row('inbox-waiting').locator('.pr-inbox-count'))>=4.5&&Math.min(...ratios)>=4.5);
    await page.screenshot({path:path.join(out,`all-${width}-${theme}.png`),fullPage:true});
  }
  check('no remote requests',remote.length===0);
  check('no runtime warnings',errors.length===0);
  fs.writeFileSync(path.join(out,'notification-mode-results.json'),JSON.stringify({checks,errors,remote},null,2));
  console.log(`${checks.length} notification-mode browser checks passed`);
}finally{await browser.close();}
