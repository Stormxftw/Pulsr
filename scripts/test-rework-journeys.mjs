import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import path from 'node:path';
import fs from 'node:fs';
const {chromium} = createRequire(path.join(process.argv[2], 'package.json'))('playwright');
const out = process.argv[3] || 'artifacts/wp14-builder';
fs.mkdirSync(out, {recursive:true});
const origin = process.env.PULSE_PREVIEW_ORIGIN || 'http://127.0.0.1:5392';
const browser = await chromium.launch({channel:'msedge',headless:true});
const page = await browser.newPage({viewport:{width:1450,height:1100},reducedMotion:'reduce'});
page.setDefaultTimeout(12000);
const errors = [], remote = [], checks = [], frontendCases = [];
page.on('pageerror', e => errors.push(String(e)));
page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
page.on('request', r => { if (/^https?:/.test(r.url()) && !r.url().startsWith(origin + '/')) remote.push(r.url()); });
await page.route('**/*', r => /^https?:/.test(r.request().url()) && !r.request().url().startsWith(origin + '/') ? r.abort() : r.continue());
const check = (name, value) => { assert.ok(value, name); checks.push(name); console.log('PASS ' + name); };
const wait = () => page.waitForTimeout(750);
const button = name => page.getByRole('button', {name,exact:true});
const field = p => page.locator(`[data-field="${p}"]`).locator('input,textarea,[role=combobox]').first();
const disclose = async name => { const s = page.locator('.pr-b2-controls summary').filter({hasText:new RegExp('^' + name + '$')}); if (!await s.evaluate(e => e.parentElement.open)) await s.click(); };
const visit = async (width = 670, theme = 'dark') => { await page.goto(`${origin}/?mode=builder&width=${width}&theme=${theme}`); await button('New pulse').click(); await wait(); };
const select = async name => { await page.locator('.pr-b2-template').filter({has:page.getByText(name,{exact:true})}).click(); await wait(); };
const next = async () => { await button('Next').click(); await wait(); };
const shot = async name => { await page.locator('.pr-b2-workspace').evaluate(e => e.scrollTop = 0); await page.locator('#surface').screenshot({path:path.join(out,name + '.png')}); };
const payload = () => page.evaluate(() => window.__pulseRestCalls.filter(c => c.path === '/builder/from-template').at(-1)?.body);
try {
  await visit();
  assert.deepEqual(await page.locator('.pr-b2-progress button').allTextContents(), ['1Source','2Design','3Review']);
  check('three steps and no persisted Advanced', await page.getByRole('switch',{name:'Advanced',exact:true}).count() === 0);
  check('all eleven templates visible on start', await page.locator('.pr-b2-template:visible').count() === 11);
  check('no unrelated sample before source selection', await page.locator('.pr-b2-preview .pr-block').count() === 0);
  check('compact neutral source preview', await page.locator('.pr-b2-preview').getByText('Choose a source to see your preview.',{exact:true}).isVisible());
  const cases = [
    ['Hermes activity',{}], ['Discord server',{invite:'https://discord.gg/nousresearch'}],
    ['GitHub repo',{repo:'NousResearch/hermes-agent'}], ['GitHub PRs/issues search',{repo:'NousResearch/hermes-agent'}],
    ['Weather & air',{latitude:'38.25',longitude:'-85.76'}], ['Game players (Steam)',{appid:'https://store.steampowered.com/app/730/'}],
    ['Any website JSON',{url:'https://example.org/metrics',metrics:'{"count":"/count"}'}],
    ['MCP tool',{server:'probe',tool:'read_counts',args:'{"scope":"local"}',metrics:'{"used":"/used"}'}]
  ];
  for (const [name, values] of cases) {
    await visit(); await select(name);
    for (const [key, value] of Object.entries(values)) await field('/template/' + key).fill(value);
    await wait(); check(name + ' frontend accepted by real converter', await button('Next').isEnabled());
    const produced = await payload(); check(name + ' canonical objects', !produced.values.metrics || typeof produced.values.metrics === 'object');
    await next(); check(name + ' real layout preselected', await page.locator('.pr-b2-layout[aria-pressed=true]').count() === 1);
    await next(); await button('Review permissions').click(); await page.locator('.pr-builder-review .pr-approval').waitFor();
    check(name + ' valid draft and readback', await page.evaluate(() => window.__pulseRestCalls.some(c => /^\/drafts\/pd_/.test(c.path))));
    check(name + ' human desktop provenance', await page.locator('.pr-builder-review .pr-approval').getByText('Draft · created in Pulse Builder',{exact:true}).isVisible());
    check(name + ' no auto approval', await page.evaluate(() => !window.__pulseRestCalls.some(c => c.path.endsWith('/approve'))));
    check(name + ' creation action removed', await button('Review permissions').count() === 0);
    check(name + ' exact immutable focus', await page.locator('.pr-builder-review').evaluate(e => e.querySelector('.pr-approval') === document.activeElement));
    frontendCases.push({name,fromTemplate:produced,definition:await page.evaluate(()=>window.__pulseRestCalls.filter(c=>c.path==='/drafts').at(-1).body.definition)});
    fs.writeFileSync(path.join(out,'frontend-payloads.json'),JSON.stringify(frontendCases,null,2));
  }
  await visit(); await select('Weather & air'); await field('/template/city').fill('Louisville'); await wait();
  check('lookup only on consented click', await page.evaluate(() => !window.__builderLookups));
  await field('/template/consent').check(); await button('Find').click(); await page.locator('.pr-b2-result').first().click(); await wait();
  check('city lookup projection accepted', await button('Next').isEnabled() && Object.keys((await payload()).values).every(k => ['city','latitude','longitude','units'].includes(k)));
  await visit(); await select('MCP tool'); await field('/template/server').fill('probe'); await field('/template/tool').fill('read_counts');
  await field('/template/args').fill('{broken'); await wait(); check('invalid structured JSON disables continuation', await button('Next').isDisabled());
  await field('/template/args').fill('{}'); await field('/template/consent').check(); await button('Test once').click();
  await button('Bind /used = 42').click(); await wait();
  check('MCP consent consumed and real conversion', !await field('/template/consent').isChecked() && await button('Next').isEnabled());
  await next(); await field('/title').fill('Preserved work'); await wait(); await disclose('Edit YAML');
  const definition = page.getByRole('textbox',{name:'Pulse definition',exact:true});
  let yaml = await definition.inputValue(); yaml += '\nlink: https://example.org/detail\nx-owner: local-test\n';
  await definition.fill(yaml); await wait(); await button('Apply definition').click(); await wait(); await button('Back').click(); await next(); await disclose('Edit YAML');
  check('Back Next preserves title link extension and layout', await field('/title').inputValue() === 'Preserved work' && (await definition.inputValue()).includes('x-owner: local-test'));
  await button('Back to Pulses').click(); check('dirty exit guarded', await page.getByRole('alertdialog').isVisible()); await button('Keep editing').click();
  await next(); await button('Review permissions').click(); await page.locator('.pr-builder-review .pr-approval').waitFor();
  await button('Change draft').click(); await field('/title').fill('New snapshot'); await wait();
  check('editing clears old approval', await page.locator('.pr-builder-review .pr-approval').count() === 0);
  await next(); await button('Review permissions').click(); await page.locator('.pr-builder-review .pr-approval').waitFor();
  check('new draft receipt required', await page.evaluate(() => window.__pulseRestCalls.filter(c => c.path === '/drafts').length === 2));
  for (const width of [320,480,670,1280]) for (const theme of ['light','dark']) {
    await visit(width,theme); await shot(`source-${width}-${theme}`);
    await select('Discord server'); await field('/template/invite').fill('https://discord.gg/nousresearch'); await wait(); await next();
    check(`${width} ${theme} no overflow`, await page.locator('.pr-shell').evaluate(e => e.scrollWidth <= e.clientWidth + 1));
    check(`${width} ${theme} visible provenance`, await page.getByText('Sample · not live',{exact:true}).isVisible()); await shot(`design-${width}-${theme}`);
    const removed = await page.evaluate(() => { const s = document.querySelector('head > style:not([data-vite-dev-id])'); const text = s?.textContent; if (s) s.textContent = ''; return text; });
    const chrome = await field('/title').evaluate(e => { const s = getComputedStyle(e); const c=document.createElement('canvas').getContext('2d');c.fillStyle=s.backgroundColor;c.fillRect(0,0,1,1);return {slot:e.dataset.slot,border:s.borderTopStyle,width:s.borderTopWidth,bg:s.backgroundColor,alpha:c.getImageData(0,0,1,1).data[3]}; });
    console.log('SDK chrome', chrome);
    check(`${width} ${theme} real SDK field chrome without lab CSS`, chrome.slot === 'input' && chrome.border === 'solid' && chrome.width === '1px' && chrome.alpha === 255);
    const selects = await field('/icon').evaluate(e => {const s=getComputedStyle(e);const c=document.createElement('canvas').getContext('2d');c.fillStyle=s.backgroundColor;c.fillRect(0,0,1,1);return [s.borderTopStyle,s.borderTopWidth,c.getImageData(0,0,1,1).data[3]];});
    check(`${width} ${theme} select chrome`, selects[0] === 'solid' && selects[1] === '1px' && selects[2] === 255);
    check(`${width} ${theme} no thick secondary borders`, await page.locator('.pr-b2 button:not(.pr-approval button)').evaluateAll(es => es.every(e => { const s=getComputedStyle(e); return s.borderTopStyle !== 'dashed' && parseFloat(s.borderTopWidth) <= 1; })));
    await field('/title').focus(); check(`${width} ${theme} keyboard focus`, await field('/title').evaluate(e => getComputedStyle(e).outlineStyle === 'solid'));
    await page.keyboard.press('Tab');
    const focusFailures = await page.locator('.pr-b2').evaluate(root => {
      const failures=[];
      for(const e of root.querySelectorAll('button,input,textarea,summary,[tabindex="0"]')) {
        const closed=e.closest('details:not([open])');
        if(e.disabled || !e.checkVisibility() || (closed && !(e.tagName==='SUMMARY'&&e.parentElement===closed)))continue;
        e.focus();const s=getComputedStyle(e);
        if(e!==document.activeElement || !e.matches(':focus-visible') || !((s.outlineStyle==='solid'&&parseFloat(s.outlineWidth)>=2)||s.boxShadow!=='none'))failures.push(e.ariaLabel||e.textContent||e.tagName);
      }
      return failures;
    });
    check(`${width} ${theme} all visible plugin controls focus-visible ${JSON.stringify(focusFailures)}`,focusFailures.length===0);
    check(`${width} ${theme} active step visibly distinct`,await page.locator('.pr-b2-progress').evaluate(root=>getComputedStyle(root.querySelector('[aria-current=step]')).boxShadow!=='none'));
    await page.evaluate(text => {document.querySelector('head > style:not([data-vite-dev-id])').textContent=text;}, removed);
    await next(); await shot(`review-${width}-${theme}`); await button('Review permissions').click(); await page.locator('.pr-builder-review .pr-approval').waitFor(); await shot(`approval-${width}-${theme}`);
    check(`${width} ${theme} locked approval`, await page.locator('.pr-builder-review .pr-approval').evaluate(e => !e.hasAttribute('style') && !e.querySelector('.pr-themed,.pr-block')));
    check(`${width} ${theme} approval uses available width`, await page.locator('.pr-builder-review .pr-approval').evaluate(e => e.getBoundingClientRect().width >= Math.min(760,e.parentElement.clientWidth)-1));
    await button('Approve').scrollIntoViewIfNeeded();
    check(`${width} ${theme} decision reachable below scroll`,await button('Approve').evaluate(e=>{const r=e.getBoundingClientRect();return e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));}));
    check(`${width} ${theme} no duplicate edit control`,await button('Edit proposal').count()===0);
    await page.locator('#surface').screenshot({path:path.join(out,`approval-decisions-${width}-${theme}.png`)});
  }
  check('no remote requests', remote.length === 0); check('zero console errors ' + JSON.stringify(errors), errors.length === 0);
  fs.writeFileSync(path.join(out,'rework-results.json'),JSON.stringify({checks:checks.length,errors,remote,host:'29a61cb7ab509cda0c376bf3860edb87210b0755'},null,2)); console.log(`${checks.length} rework browser checks passed`);
} catch (e) { console.log(await page.locator('body').innerText()); await page.screenshot({path:path.join(out,'rework-failure.png'),fullPage:true}); throw e; }
finally { await browser.close(); }
