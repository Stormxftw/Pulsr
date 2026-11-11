import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
const {chromium}=createRequire(path.join(process.argv[2],'package.json'))('playwright');
const origin=process.env.PULSE_PREVIEW_ORIGIN || 'http://127.0.0.1:5392';
const out=process.argv[3];
fs.mkdirSync(out,{recursive:true});
const browser=await chromium.launch({channel:'msedge',headless:true});
const page=await browser.newPage({viewport:{width:1100,height:850},reducedMotion:'reduce'});
page.setDefaultTimeout(12000);
const checks=[],errors=[],remote=[];
page.on('pageerror',e=>errors.push(String(e)));
page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
page.on('request',r=>{if(/^https?:/.test(r.url())&&!r.url().startsWith(origin+'/'))remote.push(r.url());});
await page.route('**/*',r=>/^https?:/.test(r.request().url())&&!r.request().url().startsWith(origin+'/')?r.abort():r.continue());
const check=(name,value)=>{assert.ok(value,name);checks.push(name);console.log('PASS '+name);};
const button=name=>page.getByRole('button',{name,exact:true});
const field=p=>page.locator(`[data-field="${p}"]`).locator('input,textarea,[role=combobox]').first();
const wait=()=>page.waitForTimeout(700);
const disclose=async name=>{const s=page.locator('.pr-builder summary').filter({hasText:new RegExp('^'+name+'$')});if(!await s.evaluate(e=>e.parentElement.open))await s.click();};
const visit=async()=>{await page.goto(origin+'/?mode=builder&width=670');await button('New pulse').click();await wait();};
const select=async name=>{if(await button('Change template').isVisible())await button('Change template').click();await page.locator('.pr-b2-template').filter({has:page.getByText(name,{exact:true})}).click();await wait();};
const next=async()=>{await button('Next').click();await wait();};
const yaml=()=>page.getByRole('textbox',{name:'Pulse definition',exact:true});
const apply=async text=>{await disclose('Edit YAML');await yaml().fill(text);await wait();await button('Apply definition').click();await wait();};
const current=()=>page.evaluate(()=>window.__pulseRestCalls.filter(c=>c.path==='/layout-check'&&typeof c.body.definition==='object').at(-1)?.body.definition);
try {
  await visit();
  const sources=page.locator('.pr-b2-start .pr-b2-template');
  check('every source is listed on start, none folded away',await sources.count()===11&&await sources.evaluateAll(nodes=>nodes.every(n=>!n.closest('details')&&n.getBoundingClientRect().height>0))&&await page.locator('.pr-b2-start details:not([open])').count()===0);
  await select('Discord server');await field('/template/invite').fill('https://discord.gg/nousresearch');await wait();await next();
  check('every option section starts open',await page.locator('.pr-builder summary').evaluateAll(nodes=>nodes.filter(n=>!['Edit YAML','About this preview'].includes(n.textContent.trim())).every(n=>n.parentElement.open)));
  await disclose('Edit YAML');
  await apply((await yaml().inputValue())+'\nlink: https://example.org/detail\nalert: {ring_at_least: 70, notify: toast}\nx-owner: integrity-test\ntheme: {accent: "#8855cc"}\n');
  await field('/title').fill('Preserved custom design');await wait();const before=await current();
  const count=await page.evaluate(()=>window.__pulseRestCalls.filter(c=>c.path==='/builder/layouts').length);
  await button('Back').click();await next();
  assert.deepEqual(await current(),before);check('Back Next preserves every definition property',true);
  check('unchanged source never regenerates layouts',await page.evaluate(()=>window.__pulseRestCalls.filter(c=>c.path==='/builder/layouts').length)===count);
  await button('Back').click();await field('/template/invite').fill('https://discord.gg/hermes-agent');await wait();
  check('compatible source identifier change is lossless without confirmation',await page.getByRole('alertdialog').count()===0);
  await next();const changed=await current();assert.deepEqual(changed.display,before.display);
  for(const key of ['title','icon','link','alert','theme','x-owner'])assert.deepEqual(changed[key],before[key]);
  check('compatible source preserves custom pieces title icon link alert theme extensions',true);
  check('source binding changed',changed.feeds.main.params.invite==='hermes-agent');
  await page.locator('.pr-b2-layout').filter({has:page.getByText('Gauge ring',{exact:true})}).click();
  check('layout confirmation traps initial focus on safe choice',await button('Keep editing').evaluate(e=>e===document.activeElement));
  await page.keyboard.press('Escape');check('Escape cancels destructive layout change',await page.getByRole('alertdialog').count()===0);assert.deepEqual((await current()).display,before.display);
  await page.locator('.pr-b2-layout').filter({has:page.getByText('Gauge ring',{exact:true})}).click();await button('Discard changes').click();await wait();const replaced=await current();
  for(const key of ['title','icon','link','alert','theme','x-owner','feeds'])assert.deepEqual(replaced[key],changed[key]);
  check('confirmed layout replaces display only',replaced.display[0].type==='rings');
  await button('Back').click();await select('Game players (Steam)');await field('/template/name').fill('Counter');await wait();
  check('Steam typing never searches',await page.evaluate(()=>!window.__builderLookups));
  await field('/template/consent').check();await button('Find').click();await page.locator('.pr-b2-result').first().click();await wait();
  check('incompatible source change requires confirmation',await page.getByRole('alertdialog').isVisible());
  await button('Discard changes').click();await wait();
  const values=await page.evaluate(()=>window.__pulseRestCalls.filter(c=>c.path==='/builder/from-template').at(-1).body.values);
  check('Steam result projected to accepted fields only',Object.keys(values).every(k=>['appid','name'].includes(k))&&values.appid===730);
  await next();const steam=await current();for(const key of ['title','icon','link','alert','theme','x-owner'])assert.deepEqual(steam[key],before[key]);
  check('confirmed incompatible source preserves all nonbinding properties',true);
  await button('Back to Pulses').click();await button('Discard changes').click();check('confirmed dirty exit returns to Pulses',await button('New pulse').isVisible());
  for(const width of [320,480,670,1280]) {
    await page.setViewportSize({width:1450,height:520});await page.goto(`${origin}/?mode=builder&width=${width}`);await button('New pulse').click();await wait();await select('Hermes activity');await next();
    check(width+' short pane has one main scroll surface',await page.locator('.pr-b2-workspace').evaluate(e=>e.scrollHeight>e.clientHeight&&getComputedStyle(e).overflowY==='auto'));
    await disclose('Edit YAML');await yaml().fill('{broken');await wait();check(width+' invalid edits block continuation',await button('Next').isDisabled());
    await button('Back to Pulses').click();check(width+' incomplete YAML guarded',await page.getByRole('alertdialog').isVisible());await button('Keep editing').click();
    await button('Back to Pulses').click();await button('Discard changes').click();
  }
  const demos=process.env.PULSE_DEMO_DIR;
  if(!demos)throw Error('PULSE_DEMO_DIR is required for the five golden-pulse acceptance checks');
  // The frozen acceptance journeys. Other work may add demos to the shared
  // artifact directory; do not delete or adopt them here.
  const files=['1-hackathon-race.pulse.yaml','2-hermes-at-work.pulse.yaml','3-home-weather.pulse.yaml','4-live-players.pulse.yaml','5-pulse-rings-repo.pulse.yaml'];
  for(const file of files) assert.ok(fs.existsSync(path.join(demos,file)),`Missing golden pulse: ${file}`);
  for(const file of files) {
    await visit();await button('Start from YAML').click();await wait();
    check(file+' YAML starting path open',await yaml().isVisible());await apply(fs.readFileSync(path.join(demos,file),'utf8'));
    check(file+' valid real engine preview',await page.locator('.pr-builder-preview .pr-block,.pr-builder-preview .pr-orbit').count()>0&&await button('Next').isEnabled());
    await next();await button('Review permissions').click();await page.locator('.pr-builder-review .pr-approval').waitFor();
    check(file+' frozen approved-data readback',await page.evaluate(()=>window.__pulseRestCalls.some(c=>/^\/drafts\/pd_/.test(c.path))));
    check(file+' never auto approves',await page.evaluate(()=>!window.__pulseRestCalls.some(c=>c.path.endsWith('/approve'))));
    if(file.startsWith('3-'))check('golden weather every feed disclosed',await page.locator('.pr-builder-review .pr-feed-disclosure').count()===2);
  }
  check('zero console errors '+JSON.stringify(errors),errors.length===0);check('no remote requests',remote.length===0);
  fs.writeFileSync(path.join(out,'integrity-results.json'),JSON.stringify({checks:checks.length,errors,remote,goldenFiles:files},null,2));console.log(`${checks.length} integrity browser checks passed`);
} catch(e) {console.log(await page.locator('body').innerText());await page.screenshot({path:path.join(out,'integrity-failure.png')});throw e;}
finally {await browser.close();}
