// Open the app (#109): a notifications pulse that names one app it may open opens that app
// when its row is clicked; details move to a small button. Rows without it are unchanged.
// Real engine rows from the inbox fixture -> real renderer; the open route is the preview stub.
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
const rows=JSON.parse(execFileSync(process.env.PULSE_BUILDER_PYTHON || 'python',['scripts/qa-inbox-status.py'],{encoding:'utf8'}));
// The same Discord reading from a backend that can open the app on this PC.
const opens={...structuredClone(rows.find(p=>p.id==='inbox-waiting')),id:'inbox-opens',title:'Discord pings',open_app:{name:'Discord'}};
const designed={...structuredClone(rows.find(p=>p.id==='inbox-designed')),open_app:{name:'Discord'}};
const browser=await chromium.launch({channel:'msedge',headless:true});
const page=await browser.newPage({viewport:{width:900,height:2400},timezoneId:'UTC',locale:'en-US',reducedMotion:'reduce'});
const checks=[],errors=[],remote=[];
const check=(name,value)=>{assert.ok(value,name);checks.push(name);console.log('PASS '+name);};
page.on('pageerror',e=>errors.push(String(e)));
page.on('console',m=>{if(['error','warning'].includes(m.type())&&!m.text().includes('[vite]'))errors.push(m.text());});
await page.route('**/*',r=>{if(/^https?:/.test(r.request().url())&&!r.request().url().startsWith(origin+'/')){remote.push(r.request().url());return r.abort();}return r.continue();});
await page.route('**/ui-fixture/hero',async r=>{const response=await r.fetch();const seed=await response.json();seed.pulses=[...structuredClone(rows.filter(p=>p.id!=='inbox-designed')),structuredClone(designed),structuredClone(opens)];seed.drafts=[];seed.as_of=NOW;await r.fulfill({json:seed});});
const visit=async(width,theme='dark')=>{for(let attempt=0;;attempt++){try{await page.goto(`${origin}/?mode=hero&width=${width}&theme=${theme}&case=rows`);await page.locator('.pr-row').first().waitFor();return;}catch(error){if(attempt)throw error;}}};
const row=id=>page.locator(`[data-id="${id}"]`);
const calls=()=>page.evaluate(()=>window.__pulseRestCalls.filter(c=>c.path.endsWith('/open-app')).map(c=>({path:c.path,method:c.method,body:c.body})));
const clearCalls=()=>page.evaluate(()=>{window.__pulseRestCalls.length=0;window.__pulseNotifications=[];});
const clipped=locator=>locator.evaluateAll(nodes=>nodes.filter(node=>{const range=document.createRange();range.selectNodeContents(node);const text=range.getBoundingClientRect(),box=node.getBoundingClientRect();return text.width>0&&(text.right>box.right+0.5||text.left<box.left-0.5);}).map(node=>node.className+': '+node.textContent));
const overlaps=(a,b)=>!(a.right<=b.left+0.5||b.right<=a.left+0.5||a.bottom<=b.top+0.5||b.bottom<=a.top+0.5);
const box=locator=>locator.evaluate(n=>{const r=n.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width};});
// Where the text itself is drawn, not its (possibly wider) box.
const textBox=locator=>locator.evaluate(n=>{const range=document.createRange();range.selectNodeContents(n);const r=range.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width};});
try{
  await visit(320);
  const trigger=row('inbox-opens').locator('.pr-trigger'),toggle=row('inbox-opens').locator('.pr-details-toggle');
  // --- the row says what a click does ---
  check('opens: the row is marked as opening its app',await row('inbox-opens').getAttribute('data-opens')==='true');
  check('opens: the accessible name says the click opens Discord',/; opens Discord$/.test(await trigger.getAttribute('aria-label')));
  check('opens: the row is not a disclosure button any more',await trigger.getAttribute('aria-expanded')===null);
  check('opens: hovering says so',await trigger.getAttribute('title')==='Open Discord');
  check('opens: the inbox reading is unchanged',/^2 waiting · latest 3h [67]m ago$/.test((await row('inbox-opens').locator('.pr-inbox-line').innerText()).replace(/\s+/g,' ').replace(/ ?· ?/g,' · ').trim()));
  // --- a click opens the app, through the confirmed route, and nothing else ---
  await clearCalls();
  await trigger.click();
  await page.waitForFunction(()=>window.__pulseRestCalls.some(c=>c.path.endsWith('/open-app')));
  const sent=await calls();
  check('click: one confirmed POST to this pulse, no target in the body',sent.length===1&&sent[0].path==='/pulses/inbox-opens/open-app'&&sent[0].method==='POST'&&JSON.stringify(sent[0].body)==='{"confirm":true}');
  check('click: details stay closed',await row('inbox-opens').locator('.pr-details').count()===0);
  check('click: no warning on success',(await page.evaluate(()=>window.__pulseNotifications||[])).length===0);
  // --- keyboard: Enter on the row opens; the details button is the next stop ---
  await clearCalls();
  await trigger.focus();await page.keyboard.press('Enter');
  await page.waitForFunction(()=>window.__pulseRestCalls.some(c=>c.path.endsWith('/open-app')));
  check('keyboard: Enter on the row opens the app',(await calls()).length===1);
  // --- details live on the small button ---
  check('details button: present, named and collapsed',await toggle.count()===1&&await toggle.getAttribute('aria-label')==='Discord pings details'&&await toggle.getAttribute('aria-expanded')==='false');
  await clearCalls();
  await toggle.click();
  await row('inbox-opens').locator('.pr-details').waitFor();
  check('details button: opens the inbox card without opening the app',await row('inbox-opens').locator('.pr-inbox').count()===1&&(await calls()).length===0);
  check('details button: says it is expanded and what it controls',await toggle.getAttribute('aria-expanded')==='true'&&await toggle.getAttribute('aria-controls')==='pr-details-inbox-opens'&&await page.locator('#pr-details-inbox-opens').count()===1);
  check('details button: title flips to Hide details',await toggle.getAttribute('title')==='Hide details');
  await row('inbox-opens').screenshot({path:path.join(out,'opens-expanded-320-dark.png')});
  await toggle.click();
  await row('inbox-opens').locator('.pr-details').waitFor({state:'detached'});
  check('details button: closes again',await toggle.getAttribute('aria-expanded')==='false');
  // --- a refusal is a plain warning and the row recovers ---
  await clearCalls();
  await page.evaluate(()=>{window.__openAppError='Windows could not open this app.';});
  await trigger.click();
  await page.waitForFunction(()=>(window.__pulseNotifications||[]).length>0);
  const warned=await page.evaluate(()=>window.__pulseNotifications);
  check('refusal: one warning naming the app and the reason',warned.length===1&&warned[0].kind==='warning'&&/^Could not open Discord\. /.test(warned[0].message)&&warned[0].message.includes('Windows could not open this app.'));
  check('refusal: the row is not left busy',await trigger.getAttribute('aria-busy')===null);
  await page.evaluate(()=>{delete window.__openAppError;});
  await clearCalls();
  await trigger.click();
  await page.waitForFunction(()=>window.__pulseRestCalls.some(c=>c.path.endsWith('/open-app')));
  check('refusal: the next click tries again',(await calls()).length===1);
  // --- a designed pulse gets the same click and button ---
  check('designed: opens too, and keeps a details button',await row('inbox-designed').getAttribute('data-opens')==='true'&&await row('inbox-designed').locator('.pr-details-toggle').count()===1);
  await row('inbox-designed').locator('.pr-details-toggle').click();
  await row('inbox-designed').locator('.pr-details').waitFor();
  check('designed: details keep the card and its blocks',await row('inbox-designed').locator('.pr-inbox').count()===1&&await row('inbox-designed').locator('.pr-display .pr-block').count()===2);
  // --- rows without open_app are exactly as before ---
  for(const id of ['inbox-waiting','inbox-quiet','inbox-missing']){
    const plain=row(id).locator('.pr-trigger');
    check(`${id}: no details button, no opens mark`,await row(id).locator('.pr-details-toggle').count()===0&&await row(id).getAttribute('data-opens')===null);
    check(`${id}: the row is still the disclosure`,await plain.getAttribute('aria-expanded')==='false'&&!/opens /.test(await plain.getAttribute('aria-label')));
  }
  await clearCalls();
  await row('inbox-waiting').locator('.pr-trigger').click();
  await row('inbox-waiting').locator('.pr-details').waitFor();
  check('inbox-waiting: a click still expands and never opens an app',(await calls()).length===0&&await row('inbox-waiting').locator('.pr-trigger').getAttribute('aria-expanded')==='true');
  // --- fit: the button never covers the title, the count pill or the line ---
  for(const theme of ['dark','light'])for(const width of [231,320,400]){
    const name=`${width} ${theme}`;await visit(width,theme);
    for(const id of ['inbox-opens','inbox-designed']){
      const button=await box(row(id).locator('.pr-details-toggle'));
      const covered=[];
      for(const sel of ['.pr-title-line','.pr-inbox-count','.pr-inbox-line > span']){
        for(const target of await row(id).locator(sel).all()){const ink=await textBox(target);if(ink.width>0&&overlaps(button,ink))covered.push(sel);}
      }
      check(`${name} ${id}: the details button covers no text`,covered.length===0);
      const rowBox=await box(row(id));
      check(`${name} ${id}: the details button sits inside the row`,button.left>=rowBox.left-0.5&&button.right<=rowBox.right+0.5&&button.top>=rowBox.top-0.5&&button.bottom<=rowBox.bottom+0.5);
    }
    check(`${name}: collapsed lines are whole`,(await clipped(page.locator('.pr-inbox-line > span, .pr-inbox-count'))).length===0);
    check(`${name}: no horizontal overflow`,await page.locator('.pr-shell').evaluate(e=>e.scrollWidth<=e.clientWidth+1));
    await row('inbox-opens').screenshot({path:path.join(out,`opens-${width}-${theme}.png`)});
  }
  // --- rings-only rail: no room for a button, the ring opens the app, the tip says so ---
  await visit(160);
  check('rail: compact mode',await page.locator('.pr-shell').getAttribute('data-compact')==='true');
  check('rail: no details button',await row('inbox-opens').locator('.pr-details-toggle').count()===0);
  await clearCalls();
  await row('inbox-opens').locator('.pr-trigger').click();
  await page.waitForFunction(()=>window.__pulseRestCalls.some(c=>c.path.endsWith('/open-app')));
  check('rail: the ring opens the app',(await calls()).length===1);
  await page.mouse.move(0,0);
  await row('inbox-opens').locator('.pr-trigger').hover();await page.waitForTimeout(350);
  const tip=await page.getByRole('tooltip').allInnerTexts();
  check(`rail: the tooltip says a click opens Discord (${tip.join(' | ')})`,tip.some(t=>/Click to open Discord$/.test(t)&&t.includes('Discord pings')&&!/\[object|undefined/.test(t)));
  check('no remote requests',remote.length===0);
  check('no runtime warnings',errors.length===0);
  fs.writeFileSync(path.join(out,'open-app-results.json'),JSON.stringify({checks,errors,remote},null,2));
  console.log(`${checks.length} open-app browser checks passed`);
}finally{await browser.close();}
