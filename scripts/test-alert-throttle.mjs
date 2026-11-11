// Refs #70: actual renderer regression; no network, OS delivery or live source calls.
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
 const count=()=>page.evaluate(()=>window.__pulseNotifications?.length||0);
 await emit(()=>{for(const p of window.__pulseStatus.pulses)p.alert={...p.alert,active:false};window.__emitPulse('hermes.waiting');});
 const baseline=await count();
 await emit(()=>{const p=window.__pulseStatus.pulses.find(p=>p.id==='hermes-self');p.alert={active:true,reason:'waiting_on_you: 1',notify:'toast'};window.__emitPulse('hermes.waiting');});
 check('first rising edge notifies',await count()===baseline+1);
 await emit(()=>{window.__pulseStatus.pulses.find(p=>p.id==='hermes-self').alert.reason='waiting_on_you: 2';window.__emitPulse('hermes.waiting');});
 check('changing value while active never creates a new rising edge',await count()===baseline+1);
 await emit(()=>window.__emitPulse('hermes.waiting'));
 check('repeated status is silent',await count()===baseline+1);
 await emit(()=>{window.__pulseStatus.pulses.find(p=>p.id==='hermes-self').alert.active=false;window.__emitPulse('hermes.waiting');});
 await emit(()=>{const p=window.__pulseStatus.pulses.find(p=>p.id==='hermes-self');p.alert={active:true,reason:'waiting_on_you: 3',notify:'toast'};window.__emitPulse('hermes.waiting');});
 check('different value rising again inside thirty minutes is throttled',await count()===baseline+1);
 await emit(()=>{const p=window.__pulseStatus.pulses.find(p=>p.id==='nous-discord');p.alert={active:true,reason:'online: 17000',notify:'toast'};window.__emitPulse('hermes.waiting');});
 check('different pulse is independently eligible',await count()===baseline+2);
 await emit(()=>{window.__pulseStatus.pulses.find(p=>p.id==='hermes-self').alert.active=false;window.__pulseStatus.as_of+=1801;window.__emitPulse('hermes.waiting');});
 await emit(()=>{const p=window.__pulseStatus.pulses.find(p=>p.id==='hermes-self');p.alert={active:true,reason:'waiting_on_you: 4',notify:'toast'};window.__emitPulse('hermes.waiting');});
 check('new rising edge after thirty minutes may notify',await count()===baseline+3);
 check('no renderer runtime errors',errors.length===0);
 await page.screenshot({path:path.join(out,'alert-throttle.png'),fullPage:true});
} finally {fs.writeFileSync(path.join(out,'results.json'),JSON.stringify({checks,errors},null,2));await browser.close();}
console.log(`${checks.length} alert throttle checks passed`);
