import assert from 'node:assert/strict';
import {authoring, compatibleField, previewTools} from './builder2-test-helpers.mjs';
import {createRequire} from 'node:module';
import path from 'node:path';
import fs from 'node:fs';
const req=createRequire(path.join(process.argv[2],'package.json'));
const {chromium}=req('playwright');
const out=process.argv[3] || 'artifacts/wp10-polish/after';
fs.mkdirSync(out,{recursive:true});
const origin=process.env.PULSE_PREVIEW_ORIGIN || 'http://127.0.0.1:5251';
const browser=await chromium.launch({channel:'msedge',headless:true});
const page=await browser.newPage({viewport:{width:1400,height:1000},deviceScaleFactor:1});
const checks=[],errors=[],remote=[];
page.on('pageerror',e=>errors.push(String(e)));
page.on('request',r=>{if(/^https?:/.test(r.url())&&!r.url().startsWith(origin+'/'))remote.push(r.url());});
const check=(name,value)=>{assert.ok(value,name);checks.push(name);console.log('PASS '+name);};
const field=p=>compatibleField(page,p);
const visit=async(mode,width,theme)=>{await page.goto(`${origin}/?mode=${mode}&width=${width}&theme=${theme}`);await page.locator('.pr-trigger').first().waitFor();};
const shot=name=>page.screenshot({path:path.join(out,name+'.png'),fullPage:true});
// Read computed paint colours, including alpha and nested surfaces, not token names.
const measure=async selector=>page.locator(selector).evaluate(root=>{
  const canvas=document.createElement('canvas');canvas.width=canvas.height=1;const c=canvas.getContext('2d',{willReadFrequently:true});
  const rgb=color=>{c.clearRect(0,0,1,1);c.fillStyle=color;c.fillRect(0,0,1,1);return [...c.getImageData(0,0,1,1).data].map((v,i)=>i===3?v/255:v);};
  const mix=(fg,bg)=>{const a=fg[3]+bg[3]*(1-fg[3]);return a?[0,1,2].map(i=>(fg[i]*fg[3]+bg[i]*bg[3]*(1-fg[3]))/a).concat(a):[0,0,0,0];};
  const surface=el=>{let bg=[0,0,0,0];for(let n=el;n&&bg[3]<.999;n=n.parentElement)bg=mix(bg,rgb(getComputedStyle(n).backgroundColor));return bg;};
  const lum=v=>v.slice(0,3).map(v=>{const c=v/255;return c<=.04045?c/12.92:((c+.055)/1.055)**2.4;}).reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);
  const ratio=(fg,bg)=>{const a=lum(mix(fg,bg)),b=lum(bg);return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);};
  const texts=[],icons=[];
  for(const el of root.querySelectorAll('*')){
    if(!el.checkVisibility()||!el.getBoundingClientRect().width||el.closest('svg'))continue;
    if([...el.childNodes].some(n=>n.nodeType===3&&n.textContent.trim())){
      const style=getComputedStyle(el);const color=rgb(style.color);color[3]*=Number(style.opacity);
      texts.push({text:el.textContent.slice(0,60),contrast:ratio(color,surface(el)),size:parseFloat(style.fontSize)});
    }
  }
  for(const el of root.querySelectorAll('.pr-brand'))icons.push({brand:el.dataset.brand,fill:getComputedStyle(el.firstElementChild).fill,accent:el.style.getPropertyValue('--pr-brand-accent'),contrast:ratio(rgb(getComputedStyle(el.firstElementChild).fill),surface(el.parentElement))});
  return {texts,icons};
});
try {
  for(const width of [900,1280,248])for(const theme of ['dark','light']){
    await visit('builder',width,theme);await authoring(page);
    const summaries=page.locator('.pr-builder summary');
    for(const label of ['Customize pieces','More source options','All appearance controls','Edit YAML']) {
      const summary=summaries.filter({hasText:new RegExp('^'+label+'$')});
      // Options start open so every choice is visible. (Edit YAML was opened by authoring() to load the definition.)
      if(label!=='Edit YAML')check(`${width} ${theme} ${label} open initially`,await summary.evaluate(e=>e.parentElement.open));
      if(await summary.evaluate(e=>e.parentElement.open))await summary.click();
      await summary.focus();await page.keyboard.press('Enter');
      check(`${width} ${theme} ${label} keyboard opens`,await summary.evaluate(e=>e.parentElement.open));
      await page.keyboard.press('Space');
      check(`${width} ${theme} ${label} keyboard closes`,!await summary.evaluate(e=>e.parentElement.open));
    }
    check(`${width} ${theme} YAML behind Show definition`,await summaries.filter({hasText:/^Edit YAML$/}).count()===1);
    const preview=page.locator('.pr-b2-preview');
    await page.locator('.pr-b2-workspace').evaluate(e=>e.scrollTop=0);
    const before=await preview.boundingBox();
    await page.locator('.pr-b2-workspace').evaluate(e=>e.scrollTop=300);
    const after=await preview.boundingBox();check(`${width} ${theme} single responsive scroll surface`,width>=670?Math.abs(before.y-after.y)<2:await preview.evaluate(e=>getComputedStyle(e).position==='static'));
    await page.locator('.pr-b2-workspace').evaluate(e=>e.scrollTop=0);
    await field('/icon').selectOption('brand');await field('/brand-search').fill('github');await page.waitForTimeout(600);
    await page.getByRole('button',{name:'GitHub',exact:true}).click();await page.waitForTimeout(650);
    check(`${width} ${theme} reselecting current brand keeps valid`,!await page.getByRole('button',{name:'Next',exact:true}).isDisabled());
    check(`${width} ${theme} body type >=13px`,await page.locator('.pr-builder').evaluate(e=>parseFloat(getComputedStyle(e).fontSize)>=13));
    const picker=await measure('.pr-builder');const bad=picker.texts.filter(x=>x.contrast<4.5||x.size<11.5);
    check(`${width} ${theme} all visible builder text AA ${JSON.stringify(bad)}`,bad.length===0);
    check(`${width} ${theme} picker brand >=3:1`,picker.icons.length>0&&picker.icons.every(x=>x.contrast>=3));
    if(width<=480)await page.getByRole('button',{name:'Expand preview',exact:true}).click();
    for(const appearance of ['dark','light']) {
      await previewTools(page,()=>field('/appearance').selectOption(appearance));
      const result=await measure('.pr-builder-preview');
      check(`${width} ${theme} preview ${appearance} text AA`,result.texts.every(x=>x.contrast>=4.5&&x.size>=11.5));
      check(`${width} ${theme} preview ${appearance} GitHub visible + brand accent retained`,result.icons.length===1&&result.icons[0].contrast>=3&&result.icons[0].accent==='#181717');
    }
    await previewTools(page,()=>field('/appearance').selectOption(theme));
    check(`${width} ${theme} persistent sample watermark`,await page.locator('.pr-builder-watermark').isVisible());
    check(`${width} ${theme} sample counts are integers`,await page.locator('.pr-builder-preview .pr-number').evaluateAll(es=>es.length>0&&es.every(e=>/^[-−+\d,]+$/.test(e.dataset.valueText))));
    check(`${width} ${theme} no horizontal overflow`,await page.locator('.pr-shell').evaluate(e=>e.scrollWidth<=e.clientWidth+1));
    await shot(`builder-${width}-${theme}`);
    await visit('blocks',width,theme);await page.locator('[data-id=synthetic-gpu] .pr-trigger').click();
    // Use the actual bundled GitHub path, never network artwork or a mock square.
    const brand=await page.evaluate(async()=>{const r=await fetch('/builder-mock',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:'/brands',body:{q:'github'}})});return (await r.json()).brands.find(b=>b.slug==='github');});
    await page.evaluate(brand=>{const p=window.__pulseStatus.pulses.find(p=>p.id==='synthetic-gpu');p.icon_resolved={kind:'brand',...brand};window.__emitPulse('draft.updated');},brand);
    await page.waitForTimeout(150);
    const card=await measure('[data-id=synthetic-gpu]');
    check(`${width} ${theme} card brand >=3:1`,card.icons.length>0&&card.icons.every(x=>x.contrast>=3));
    check(`${width} ${theme} live card text AA`,card.texts.every(x=>x.contrast>=4.5));
    const geometry=()=>page.locator('[data-id=synthetic-gpu]').evaluate(e=>[e,...e.querySelectorAll('.pr-trigger,.pr-display,.pr-block,.pr-number')].map(n=>{const r=n.getBoundingClientRect();return [r.x,r.y,r.width,r.height];}));
    const baseline=await geometry();
    for(let tick=0;tick<3;tick++){
      const numbers=page.locator('[data-id=synthetic-gpu] .pr-number');
      const previous=await numbers.first().getAttribute('data-value-text');
      await page.evaluate(()=>window.__pulseTick());
      const observed=await (await page.waitForFunction(previous=>{
        const e=document.querySelector('[data-id=synthetic-gpu] .pr-number');
        if(e.dataset.valueText===previous||e.textContent===e.dataset.valueText)return false;
        const root=document.querySelector('[data-id=synthetic-gpu]');
        if(root.querySelector('.pr-beat')?.dataset.beat!=='true')return false;
        return {inFlight:true,beat:true,geometry:[root,...root.querySelectorAll('.pr-trigger,.pr-display,.pr-block,.pr-number')].map(n=>{const r=n.getBoundingClientRect();return [r.x,r.y,r.width,r.height];})};
      },previous)).jsonValue();
      check(`${width} ${theme} tick ${tick} count-up in flight`,observed.inFlight);
      check(`${width} ${theme} tick ${tick} new sample beat`,observed.beat);
      assert.deepEqual(observed.geometry,baseline,'no layout shift during tick');checks.push(`${width} ${theme} tick ${tick} no layout shift`);
      await page.waitForTimeout(700);
      check(`${width} ${theme} tick ${tick} exact engine strings at rest`,await numbers.evaluateAll(es=>es.every(e=>e.textContent===e.dataset.valueText&&e.getAttribute('aria-label')===e.dataset.valueText)));
    }
    for(const value of [9,10,1000]){
      await page.evaluate(value=>{const item=window.__pulseStatus.pulses.find(p=>p.id==='synthetic-gpu').display[0].items[0];item.value=value;item.value_text=value+' %';window.__emitPulse('draft.updated');},value);
      await page.waitForTimeout(800);
      assert.deepEqual(await geometry(),baseline,'digit boundary must not change layout');checks.push(`${width} ${theme} digit boundary ${value} stable`);
    }
    for(const setting of ['reduced','none']){
      if(setting==='reduced')await page.emulateMedia({reducedMotion:'reduce'});
      else await page.evaluate(()=>{window.__pulseStatus.pulses.find(p=>p.id==='synthetic-gpu').theme={motion:'none'};});
      await page.evaluate(()=>window.__pulseTick());await page.waitForTimeout(100);
      check(`${width} ${theme} ${setting} skips count-up`,await page.locator('[data-id=synthetic-gpu] .pr-number').evaluateAll(es=>es.every(e=>e.textContent===e.dataset.valueText)));
      if(setting==='reduced')await page.emulateMedia({reducedMotion:'no-preference'});
    }
    await shot(`cards-${width}-${theme}`);
  }
  check('zero renderer errors '+JSON.stringify(errors),errors.length===0);check('zero remote requests',remote.length===0);
  fs.writeFileSync(path.join(out,'polish-results.json'),JSON.stringify({checks:checks.length,errors,remote},null,2));
  console.log(`${checks.length} polish browser checks passed`);
}finally{await browser.close();}
