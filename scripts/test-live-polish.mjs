// Live-render regressions, using deterministic synthetic data and no source calls.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
const {chromium}=createRequire(path.join(process.argv[2],'package.json'))('playwright');
const out=process.argv[3];fs.mkdirSync(out,{recursive:true});
const origin=process.env.PULSE_PREVIEW_ORIGIN || 'http://127.0.0.1:5611';
const browser=await chromium.launch({channel:'msedge',headless:true});
const failures=[],errors=[];let checks=0;
const check=(name,ok)=>{checks++;console.log(`${ok?'PASS':'FAIL'} ${name}`);if(!ok)failures.push(name);};
try {
for(const width of [320,480])for(const theme of ['dark','light']){
 const page=await browser.newPage({viewport:{width:900,height:1400},reducedMotion:'reduce'});
 page.on('pageerror',e=>errors.push(String(e)));
 await page.route('**/*',r=>/^https?:/.test(r.request().url())&&!r.request().url().startsWith(origin+'/')?r.abort():r.continue());
 await page.goto(`${origin}/?mode=blocks&width=${width}&theme=${theme}`);await page.locator('.pr-trigger').first().waitFor();
 await page.evaluate(()=>{
  const base=structuredClone(window.__pulseStatus.pulses[0]);
  const score=(id,value,baseline,warming=false)=>({...base,id,title:id,kind:'github.repo',state:'active',error:null,lines:[],history:[],ring:{score:0,warming:false,components:[]},display:[{type:'score',label:'Change',index:0,ring:{score:68.6,unknown:false,warming,components:[{metric:'commits_week',value,baseline,delta:baseline==null?null:value-baseline,unknown:false}]}}]});
  const rows=[score('positive',108,32),score('new',108,0),score('zero',0,0),score('warming',108,0,true),score('down',2,10)];
  const search=score('search',182,53.5);search.kind='github.search';search.display[0].ring.components[0].metric='recent';search.display.push({type:'stat',index:1,label:'New PRs',ref:'main.recent',value:999,value_text:'999',unknown:false});rows.push(search);
  const componentWarming=score('component-warming',108,0);componentWarming.display[0].ring.components[0].warming=true;rows.push(componentWarming);
  const error=score('error',null,null);error.state='error';error.error='GitHub repository moved or was renamed. Update the approved repository.';error.display[0].ring.unknown=true;error.display[0].ring.components[0].unknown=true;error.display[0].ring.components[0].reason=error.error;
  error.display.push({type:'stat',index:1,label:'Last push',unknown:true,reason:error.error,caption:error.error});rows.push(error);
  const learning=score('learning',0,1);learning.display.push({type:'bar',index:1,items:[{label:'Observed',value:0,value_text:'0',learning:true,min:0,max:0,fill:null,caption:'Learning baseline',range:{samples:2}}]});rows.push(learning);
  const legacy=structuredClone(base);Object.assign(legacy,{id:'legacy',title:'Legacy',kind:'discord.invite',state:'active',display:null,error:null,history:[{value:10},{value:20}],ring:{score:68.6,warming:false,unknown:false,components:[{metric:'online',value:20,baseline:17.5,baseline_mode:'median',observed_seconds:3600}]},capsule:{label:'20 online',fill:57,caption:'114% of usual'}});rows.push(legacy);
  window.__pulseStatus.pulses=rows;window.__pulseStatus.drafts=[];window.__pulseStatus.layout={version:1,ungrouped:rows.map(p=>({pulse:p.id})),groups:[]};window.__emitPulse('draft.updated');
 });await page.waitForTimeout(400);
 const row=id=>page.locator(`[data-id="${id}"]`);const text=async id=>row(id).locator('.pr-trigger').innerText();
 check(`${width} ${theme} score measured and usual`,/108 commits.*3\.4× usual/s.test(await text('positive')));
 check('hero component is authoritative',/182 PRs.*3\.4× usual/s.test(await text('search'))&&!(await text('search')).includes('999'));
 check('component warming remains honest',/108 commits.*Learning baseline/s.test(await text('component-warming'))&&!(await text('component-warming')).includes('new'));
 check('new zero baseline',/108 commits.*new/s.test(await text('new')));
 check('zero remains measured',/0 commits.*usual is zero/s.test(await text('zero')));
 check('warming outranks zero comparison',/108 commits.*Learning baseline/s.test(await text('warming'))&&!(await text('warming')).includes('new'));
 check('direction visible',/↓.*20% of usual/s.test(await text('down'))&&/↑.*3\.4× usual/s.test(await text('positive')));
 check('integer score',/Change 69\/100/.test(await text('positive'))&&!/68\.6/.test(await text('legacy')));
 check('no idle status dot',await row('positive').locator('.pr-beat').evaluateAll(es=>es.every(e=>getComputedStyle(e).visibility==='hidden'||getComputedStyle(e).display==='none')));
 check('row heights consistent',await row('positive').locator('.pr-trigger').evaluate((e,h)=>Math.abs(e.getBoundingClientRect().height-h)<=1,await row('legacy').locator('.pr-trigger').evaluate(e=>e.getBoundingClientRect().height)));
 await row('error').locator('.pr-trigger').click();
 check('error reason once',((await row('error').innerText()).match(/GitHub repository moved/g)||[]).length===1);
 check('aria does not repeat reason',!(await row('error').locator('.pr-trigger').getAttribute('aria-label')).includes('moved'));
 check('blocks say not measured',(await row('error').locator('.pr-display').innerText()).includes('Not measured'));
 check('error fully wraps',await row('error').locator('.pr-state-line > span').evaluate(e=>getComputedStyle(e).whiteSpace!=='nowrap'&&e.scrollWidth<=e.clientWidth+1));
 check('fix hit target',await row('error').locator('.pr-fix').evaluate(e=>e.getBoundingClientRect().height>=28&&e.getBoundingClientRect().width>=44));
 await row('learning').locator('.pr-trigger').click();
 check('learning no range or rail',await row('learning').locator('.pr-display .pr-range,.pr-display .pr-bar__track').count()===0);
 check('learning explicit',(await row('learning').locator('.pr-display').innerText()).includes('Baseline not ready'));
 await row('legacy').locator('.pr-trigger').click();
 check('spark labels forward',/First 10.*Latest 20/s.test(await row('legacy').innerText()));
 check('usual count rounded and labelled',/Usual \(median\).*18/.test(await row('legacy').innerText())&&!(await row('legacy').innerText()).includes('Normal:'));
 check('duration grouped',await row('legacy').locator('.pr-normal-duration').evaluate(e=>getComputedStyle(e).whiteSpace==='nowrap'));
 check('no overflow',await page.locator('.pr-shell').evaluate(e=>e.scrollWidth<=e.clientWidth+1));
 await page.locator('.pr-shell').screenshot({path:path.join(out,`live-polish-${theme}-${width}.png`)});await page.close();
}
check('no runtime errors',errors.length===0);
} finally {fs.writeFileSync(path.join(out,'results.json'),JSON.stringify({checks,failures,errors},null,2));await browser.close();}
assert.equal(failures.length,0,failures.join('\n'));console.log(`${checks} live polish checks passed`);
