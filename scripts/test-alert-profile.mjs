// Refs #70: alert state stays scoped per profile and pulse; actual renderer, fixture data only.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
const {chromium}=createRequire(path.join(process.argv[2],'package.json'))('playwright');
const out=process.argv[3];fs.mkdirSync(out,{recursive:true});
const origin=process.env.PULSE_PREVIEW_ORIGIN || 'http://127.0.0.1:5611';
const browser=await chromium.launch({channel:'msedge',headless:true});
const checks=[],errors=[];
const check=(name,ok)=>{checks.push({name,ok});console.log(`${ok?'PASS':'FAIL'} ${name}`);assert.ok(ok,name);};
try {
 const page=await browser.newPage({viewport:{width:800,height:1000},reducedMotion:'reduce'});
 page.on('pageerror',e=>errors.push(String(e)));
 await page.route('**/*',r=>/^https?:/.test(r.request().url())&&!r.request().url().startsWith(origin+'/')?r.abort():r.continue());
 await page.goto(origin+'/?mode=hero&width=320');await page.locator('.pr-row').first().waitFor();
 const emit=async(fn,arg)=>{await page.evaluate(fn,arg);await page.waitForTimeout(350);};
 const profile=async name=>{await page.evaluate(value=>window.__setPulseProfile(value),name);await page.waitForTimeout(950);await page.locator('.pr-row').first().waitFor();};
 // Count alert toasts only; a profile switch may legitimately raise unrelated info notices.
 const count=()=>page.evaluate(()=>(window.__pulseNotifications||[]).filter(n=>n.kind==='warning'&&String(n.message).includes('waiting_on_you')).length);
 await emit(()=>{for(const p of window.__pulseStatus.pulses)p.alert={...p.alert,active:false};window.__emitPulse('hermes.waiting');});
 const baseline=await count();
 await emit(()=>{const p=window.__pulseStatus.pulses.find(p=>p.id==='hermes-self');p.alert={active:true,reason:'waiting_on_you: 1',notify:'toast'};window.__emitPulse('hermes.waiting');});
 check('first profile notifies on its rising edge',await count()===baseline+1);
 await profile('other-profile');
 check('another profile keeps its own alert state',await count()===baseline+2);
 await emit(()=>{window.__pulseStatus.pulses.find(p=>p.id==='hermes-self').alert.reason='waiting_on_you: 2';window.__emitPulse('hermes.waiting');});
 check('changing value stays silent in the second profile',await count()===baseline+2);
 await profile('preview');
 check('returning to the first profile does not repeat its active alert',await count()===baseline+2);
 await profile('other-profile');
 check('returning to the second profile does not repeat its active alert',await count()===baseline+2);
 check('no renderer runtime errors',errors.length===0);
 await page.screenshot({path:path.join(out,'alert-profile.png'),fullPage:true});
} finally {fs.writeFileSync(path.join(out,'results.json'),JSON.stringify({checks,errors},null,2));await browser.close();}
console.log(`${checks.length} alert profile checks passed`);
