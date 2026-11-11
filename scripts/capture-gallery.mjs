// Rebuild the README gallery (docs/screens/*.png) from the current renderer in the preview
// harness. Sample data only: recorded public Discord counts and GitHub search from the test
// fixtures, and real-engine rows from the scripted QA sources. No network beyond the harness.
//   node scripts/preview-server.mjs <hermes-agent checkout> 5571   # keep running
//   PULSE_PREVIEW_ORIGIN=http://127.0.0.1:5571 node scripts/capture-gallery.mjs <dir with playwright> [out-dir]
import {createRequire} from 'node:module';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
const req=createRequire(path.join(process.argv[2],'package.json'));
const {chromium}=req('playwright');
const origin=process.env.PULSE_PREVIEW_ORIGIN || 'http://127.0.0.1:5571';
const out=process.argv[3] || 'docs/screens';fs.mkdirSync(out,{recursive:true});
const python=process.env.PULSE_BUILDER_PYTHON || 'python';
const rowsFrom=script=>JSON.parse(execFileSync(python,[script],{encoding:'utf8'}));
const inbox=rowsFrom('scripts/qa-inbox-status.py');
const servers=rowsFrom('scripts/qa-server-status.py');
const browser=await chromium.launch({channel:'msedge',headless:true});
const page=await browser.newPage({viewport:{width:900,height:2400},deviceScaleFactor:2,timezoneId:'UTC',locale:'en-US',reducedMotion:'reduce'});
const remote=[],errors=[];
page.on('pageerror',e=>errors.push(String(e)));
await page.route('**/*',r=>{if(/^https?:/.test(r.request().url())&&!r.request().url().startsWith(origin+'/')){remote.push(r.request().url());return r.abort();}return r.continue();});
let seedPulses=null,seedAsOf=null;
await page.route('**/ui-fixture/hero',async r=>{const response=await r.fetch();const seed=await response.json();if(seedPulses){seed.pulses=structuredClone(seedPulses);seed.drafts=[];if(seedAsOf)seed.as_of=seedAsOf;}await r.fulfill({json:seed});});
const visit=async(mode='hero',width=320,extra='')=>{await page.goto(`${origin}/?mode=${mode}&width=${width}&theme=dark${extra}`);await page.locator('.pr-shell,.pr-approval').first().waitFor();await page.mouse.move(0,0);await page.waitForTimeout(400);};
// The harness frame follows the viewport; shrink it to the pane's content so the image has no empty tail.
const fit=()=>page.evaluate(()=>{const shell=document.querySelector('.pr-shell'),list=shell?.querySelector('.pr-list'),foot=shell?.querySelector('.pr-foot'),frame=shell?.closest('.preview-frame');if(!shell||!list||!frame)return;
  const cs=getComputedStyle(shell),gap=parseFloat(cs.rowGap)||0,pad=parseFloat(cs.paddingBottom)||0;
  const needed=list.getBoundingClientRect().bottom-shell.getBoundingClientRect().top+(foot?gap+foot.getBoundingClientRect().height:0)+pad;
  frame.style.height=Math.ceil(needed)+'px';});
const shoot=async(name,locator)=>{if(name!=='approval-dark.png'&&name!=='builder-design-dark.png'){await fit();await page.waitForTimeout(150);}await locator.screenshot({path:path.join(out,name),animations:'disabled'});console.log('wrote',path.join(out,name));};
const open=async id=>{const row=page.locator(`[data-id="${id}"]`);const toggle=row.locator('.pr-details-toggle');if(await toggle.count())await toggle.click();else await row.locator('.pr-trigger').click();await row.locator('.pr-details').waitFor();await page.waitForTimeout(300);};
try{
  // The pane: the recorded hero fixture as shipped.
  seedPulses=null;await visit();
  await shoot('pane-dark.png',page.locator('.pr-shell'));
  // Focus: the attention strip's lens.
  await page.locator('.pr-attention').click();await page.waitForTimeout(300);
  await shoot('focus-dark.png',page.locator('.pr-shell'));
  // A Discord server expanded: figures, today against yesterday, member growth, people in voice.
  seedPulses=servers.filter(p=>['server-lantern','server-harbor','server-quietco'].includes(p.id));seedAsOf=1794189600;
  if(seedPulses.length<2)seedPulses=servers.slice(0,3);
  await visit();
  // These servers are invented: show the generic Discord mark, never a real server's icon.
  await page.evaluate(()=>{for(const p of window.__pulseStatus.pulses){p.icon_data=null;p.icon_url=null;}window.__emitPulse('draft.updated');});await page.waitForTimeout(300);
  await open(seedPulses[0].id);
  await shoot('trend-dark.png',page.locator('.pr-shell'));
  // Notification mode: a Windows-notifications pulse expanded.
  seedPulses=inbox.filter(p=>['inbox-waiting','inbox-quiet','inbox-designed'].includes(p.id));seedAsOf=1794189600;
  await visit();await open('inbox-waiting');
  await shoot('notifications-dark.png',page.locator('.pr-shell'));
  // The approval card: hosts, requests per hour, parameters.
  seedPulses=null;seedAsOf=null;await visit('approval');
  await shoot('approval-dark.png',page.locator('.pr-shell,.pr-approval').first());
  // The builder's Design step for a Discord server.
  await page.goto(`${origin}/?mode=builder&width=900&theme=dark`);await page.getByRole('button',{name:'New pulse',exact:true}).click();await page.waitForTimeout(650);
  await page.locator('.pr-b2-template').filter({has:page.getByText('Discord server',{exact:true})}).click();await page.waitForTimeout(650);
  const invite=page.locator('[data-field="/template/invite"], [data-template-field="invite"]').locator('input').first();
  if(await invite.count()&&!(await invite.inputValue()))await invite.fill('https://discord.gg/nousresearch');
  await page.waitForTimeout(650);await page.getByRole('button',{name:'Next',exact:true}).click();await page.waitForTimeout(1200);await page.mouse.move(0,0);
  await shoot('builder-design-dark.png',page.locator('.pr-builder').first());
  if(remote.length||errors.length)throw new Error(`remote=${JSON.stringify(remote)} errors=${JSON.stringify(errors)}`);
}finally{await browser.close();}
