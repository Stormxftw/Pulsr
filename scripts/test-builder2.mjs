import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
import {compatibleField, disclose, addPiece, previewTools, pause} from './builder2-test-helpers.mjs';
const {chromium} = createRequire(path.join(process.argv[2],'package.json'))('playwright');
const out = process.argv[3];
fs.mkdirSync(out,{recursive:true});
const origin = process.env.PULSE_PREVIEW_ORIGIN || 'http://127.0.0.1:5392';
const browser = await chromium.launch({channel:'msedge',headless:true});
const page = await browser.newPage({viewport:{width:1420,height:1100},reducedMotion:'reduce'});
page.setDefaultTimeout(12000);
const errors=[], remote=[], checks=[];
page.on('pageerror',e=>errors.push(String(e)));
page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
page.on('request',r=>{if(/^https?:/.test(r.url())&&!r.url().startsWith(origin+'/'))remote.push(r.url());});
await page.route('**/*',r=>/^https?:/.test(r.request().url())&&!r.request().url().startsWith(origin+'/')?r.abort():r.continue());
const check=(name,value)=>{assert.ok(value,name);checks.push(name);console.log('PASS '+name);};
const button=name=>page.getByRole('button',{name,exact:true});
const field=p=>compatibleField(page,p);
const next=async()=>{await button('Next').click();await pause(page);};
const visit=async()=>{await page.goto(`${origin}/?mode=builder&width=900`);await button('New pulse').click();await pause(page);};
try {
  await visit();
  check('purpose-led creation',await page.getByRole('heading',{name:'What would you like to watch?'}).isVisible());
  check('all eleven sources visible on start, none folded',await page.locator('.pr-b2-template:visible').count()===11&&await page.locator('.pr-b2-start details:not([open])').count()===0);
  check('official Discord vector',await page.locator('.pr-b2-template [data-brand=discord] path').count()===1);
  check('no unchosen source continuation',await button('Next').isDisabled());
  await disclose(page,'Draft a request in chat');await page.getByRole('textbox',{name:'Describe it',exact:true}).fill('Community watch');await button('Insert unsent request').click();
  check('chat request remains unsent',await page.evaluate(()=>window.__pulseDraft.includes('Community watch')&&!window.__pulseRestCalls.some(c=>c.path.includes('/approve'))));
  for(const name of ['Discord server','Weather & air','Any website JSON']) {
    await visit();
    await page.locator('.pr-b2-template').filter({has:page.getByText(name,{exact:true})}).click();await pause(page);
    if(name==='Discord server')await field('/template/invite').fill('https://discord.gg/nousresearch');
    if(name==='Weather & air'){
      await field('/template/city').fill('Louisville');await pause(page);
      check('city typing performs no lookup',await page.evaluate(()=>!window.__builderLookups));
      check('lookup exact host disclosed',(await page.locator('.pr-b2-consent').innerText()).includes('geocoding-api.open-meteo.com'));
      check('lookup consent required',await button('Find').isDisabled());
      await field('/template/consent').check();await button('Find').click();await page.locator('.pr-b2-result').first().click();await pause(page);
      check('one lookup and consumed consent',await page.evaluate(()=>window.__builderLookups===1)&&!await field('/template/consent').isChecked());
    }
    if(name==='Any website JSON'){
      await field('/template/url').fill('https://example.org/metrics');await field('/template/metrics').fill('{"count":"/count"}');
      check('JSON has no invented test action',await button('Test once').count()===0);
      check('JSON never fetched preapproval',await page.evaluate(()=>!window.__pulseRestCalls.some(c=>c.path.includes('json-test'))));
    }
    await pause(page);check(name+' valid source',await button('Next').isEnabled());await next();
    check(name+' recommended layout selected',await page.locator('.pr-b2-layout[aria-pressed=true]').count()===1);
    check(name+' real layout thumbnails',await page.locator('.pr-b2-layout .pr-block').count()>=3);
    const before=await page.locator('.pr-b2-layout[aria-pressed=true]').innerText();
    await page.locator('.pr-b2-layout').filter({has:page.getByText('Gauge ring',{exact:true})}).click();
    check(name+' layout replacement confirmed',await page.getByRole('alertdialog').isVisible());await button('Keep editing').click();
    check(name+' declined change preserves layout',await page.locator('.pr-b2-layout[aria-pressed=true]').innerText()===before);
    await page.locator('.pr-b2-layout').filter({has:page.getByText('Gauge ring',{exact:true})}).click();await button('Discard changes').click();await pause(page);
    check(name+' gauge uses real renderer',await page.locator('.pr-builder-preview .pr-block[data-type=rings]').count()===1);
    await button('Edit preview piece 1').click();check(name+' inline selected inspector',await button('Shows').isVisible());
    const count=await page.locator('.pr-builder-block').count();await addPiece(page,'stat');check(name+' add piece',await page.locator('.pr-builder-block').count()===count+1);
    await button(`Move piece ${count+1} up`).click();await pause(page);check(name+' keyboard-selectable list',await page.locator('.pr-builder-block[data-selected=true]').count()===1);
    await button(`Remove piece ${count}`).click();await field('/title').fill(name+' custom');await pause(page);await disclose(page,'Edit YAML');
    const text=page.getByRole('textbox',{name:'Pulse definition',exact:true});await text.fill((await text.inputValue()).replace(name+' custom',name+' round trip'));await pause(page);await button('Apply definition').click();await pause(page);
    check(name+' YAML round trip',await field('/title').inputValue()===name+' round trip');
    await next();const summary=await page.locator('.pr-b2-review-summary').innerText();
    for(const label of ['Watches','Connects to','Check every','Requests per hour','Sign-in','No recurring checks start before you approve.'])check(name+' review '+label,summary.includes(label));
    await button('Review permissions').click();await page.locator('.pr-builder-review .pr-approval').waitFor();
    check(name+' readback',await page.evaluate(()=>window.__pulseRestCalls.some(c=>/^\/drafts\/pd_/.test(c.path))));
    check(name+' locked card',await page.locator('.pr-builder-review .pr-approval').evaluate(e=>!e.hasAttribute('style')&&!e.querySelector('.pr-themed,.pr-block')));
    check(name+' never auto approves',await page.evaluate(()=>!window.__pulseRestCalls.some(c=>c.path.endsWith('/approve'))));
  }
  await button('Back to Pulses').click();await page.locator('[data-id="builder-live"] .pr-trigger').click();await button('Edit pulse').click();await pause(page);
  check('edit starts at Design section',await page.getByRole('tab',{name:'2 Design',exact:true}).getAttribute('aria-selected')==='true');
  check('replacement promise',await page.locator('.pr-b2-running').innerText().then(t=>t.includes('keeps running until you approve')));
  check('no global Advanced preference',await page.getByRole('switch',{name:'Advanced',exact:true}).count()===0);
  await previewTools(page,()=>button('Cached').click());check('cached provenance distinct',await page.locator('.pr-builder-watermark').count()===0);
  await previewTools(page,()=>button('Sample').click());check('sample provenance restored',await page.locator('.pr-builder-watermark').isVisible());
  check('no remote requests',remote.length===0);check('zero console errors '+JSON.stringify(errors),errors.length===0);
  fs.writeFileSync(path.join(out,'builder2-results.json'),JSON.stringify({checks:checks.length,errors,remote,realSdk:true},null,2));console.log(`${checks.length} builder2 browser checks passed`);
} finally {await browser.close();}
