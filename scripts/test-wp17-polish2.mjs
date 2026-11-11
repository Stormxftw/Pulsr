// Renderer-only regressions, real SDK and synthetic local transport.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
const req = createRequire(path.join(process.argv[2], 'package.json'));
const {chromium} = req('playwright');
const out = process.argv[3];
fs.mkdirSync(out, {recursive:true});
const origin = process.env.PULSE_PREVIEW_ORIGIN || 'http://127.0.0.1:5471';
const browser = await chromium.launch({channel:'msedge',headless:true});
const page = await browser.newPage({viewport:{width:900,height:1200},reducedMotion:'reduce'});
const checks = [], errors = [];
page.on('pageerror', e => errors.push(String(e)));
await page.route('**/*', r => /^https?:/.test(r.request().url()) && !r.request().url().startsWith(origin + '/') ? r.abort() : r.continue());
const check = (name, ok) => {assert.ok(ok, name);checks.push(name);console.log('PASS ' + name);};
let serial = 0;
const visit = async (mode, width=320, theme='dark', extra='') => {
  await page.goto(`${origin}/?mode=${mode}&width=${width}&theme=${theme}&case=polish2-${++serial}${extra}`);
  await page.locator('.pr-arrangement[aria-busy="false"]').waitFor();
};
const shot = async name => {
  await page.screenshot({path:path.join(out, name + '.png'),fullPage:true});
  await page.locator('.pr-shell').screenshot({path:path.join(out, name + '-pane.png')});
};
try {
  await visit('blocks');
  await page.evaluate(() => {
    const p = window.__pulseStatus.pulses.find(p => p.id === 'synthetic-ebay');
    p.title = 'Hermes at work';
    p.display[0].items.forEach(i => {i.learning=true;i.fill=null;i.caption='Learning baseline';});
    window.__emitPulse('draft.updated');
  });
  await page.waitForTimeout(250);
  const row = page.locator('[data-id="synthetic-ebay"]');
  check('Hermes at work repeats shared learning caption only once', (await row.locator('.pr-trigger').innerText()).split('Learning baseline').length === 2);
  await row.locator('.pr-trigger').click();
  await page.evaluate(() => {
    const p = window.__pulseStatus.pulses.find(p => p.id === 'synthetic-ebay');
    p.display[0].label='Learning baseline';
    p.display[1].items.forEach(i => {i.learning=true;i.fill=null;i.caption='Learning baseline';});
    window.__emitPulse('draft.updated');
  });
  await page.waitForTimeout(250);
  check('expanded blocks dedupe repeated status captions and block label', (await row.locator('.pr-display').innerText()).split('Learning baseline').length === 2);
  await visit('block-states');
  for (const type of ['bar','bars','rings','score','stat','spark']) {
    const r = page.locator(`[data-id="${type}-unknown"]`);
    await r.locator('.pr-trigger').click();
    check(`${type} unknown reason is not repeated in each item`, await r.locator('.pr-display').evaluate(e => [...e.querySelectorAll('.pr-item')].every(i => (i.textContent.match(/Synthetic feed unavailable/g) || []).length <= 1)));
    if (type === 'rings') check('unknown hero shares one reason instead of repeating it per ring', (await r.locator('.pr-trigger').innerText()).split('Synthetic feed unavailable').length === 2);
  }
  await visit('blocks');
  await page.evaluate(() => {
    const p=window.__pulseStatus.pulses.find(p=>p.id==='synthetic-score');
    p.display=[p.display[0],{...structuredClone(p.display[0]),index:1}];
    window.__emitPulse('draft.updated');
  });
  await page.locator('[data-id="synthetic-score"] .pr-trigger').click();
  check('equal measured scores remain visible in both blocks', await page.locator('.pr-display .pr-caption').evaluateAll(es => es.filter(e=>/^(Change )?62(\/100)?$/.test(e.textContent)).length===2));
  await visit('hero');
  await page.evaluate(() => {
    window.__pulseStatus.pulses=window.__pulseStatus.pulses.slice(0,3);window.__emitPulse('draft.updated');
  });
  await page.waitForTimeout(250);
  check('hint respects four-pulse threshold', await page.locator('.pr-discovery').count()===0);
  for (const theme of ['dark','light']) for (const width of [320,670]) {
    await visit('twelve', width, theme);
    const shown = name => page.getByRole('button',{name,exact:true}).waitFor({state:'visible',timeout:5000}).then(() => true, () => false);
    check(`${theme} ${width} first-run hint discoverable`, await shown('Group pulses') && await shown('Show Hermes sessions'));
    check(`${theme} ${width} hint stays within pane on one calm line`, await page.locator('.pr-discovery').evaluate(e => e.scrollWidth <= e.clientWidth && e.getBoundingClientRect().height <= 40));
    await shot(`hint-${width}-${theme}`);
    await page.getByRole('button',{name:'Show Hermes sessions',exact:true}).click();
    check(`${theme} ${width} session hint opens settings, never consents`, await page.getByRole('switch',{name:/Show Hermes sessions/}).isVisible() && await page.evaluate(() => !window.__pulseRestCalls.some(c => c.method === 'PUT')));
    await page.getByRole('button',{name:'Pulse options',exact:true}).click();
    await page.getByRole('button',{name:'Group pulses',exact:true}).click();
    check(`${theme} ${width} group hint starts arranging`, await page.getByRole('button',{name:'Done arranging',exact:true}).isVisible());
    await page.getByRole('button',{name:'Done arranging',exact:true}).click();
    await page.getByRole('button',{name:'Dismiss pulse tips',exact:true}).click();
    check(`${theme} ${width} dismissed hint stays gone after rerender`, await page.locator('.pr-discovery').count() === 0);
    await page.evaluate(()=>window.__setPulseProfile('other'));
    await page.getByRole('button',{name:'Group pulses',exact:true}).waitFor();
    await page.evaluate(()=>window.__setPulseProfile('preview'));
    await page.locator('.pr-arrangement[aria-busy="false"]').waitFor();
    check(`${theme} ${width} dismissal persists across remount, isolated to profile`, await page.locator('.pr-discovery').count()===0);
    await visit('groups', width, theme);
    check(`${theme} ${width} existing groups hide first-run hint`, await page.locator('.pr-discovery').count()===0);
    const parent = page.locator('[data-group-id="communities"]');
    check(`${theme} ${width} count explains subgroup membership`, (await parent.locator('.pr-group-count').first().innerText()).includes('8 pulses · 3 in Developer tools'));
    await parent.locator(':scope > .pr-group-head .pr-group-toggle').click();
    await page.locator('.pr-arrangement[aria-busy="false"]').waitFor();
    check(`${theme} ${width} shared four-column geometry`, await parent.evaluate(e => {
      const grids = [...e.querySelectorAll('.pr-circle-grid')].map(g => ({rect:g.getBoundingClientRect(),cols:getComputedStyle(g).gridTemplateColumns}));
      return grids.length === 2 && grids.every(g => Math.abs(g.rect.x-grids[0].rect.x)<.1 && Math.abs(g.rect.width-grids[0].rect.width)<.1 && g.cols===grids[0].cols);
    }));
    check(`${theme} ${width} collapsed chevrons match aria state and metadata readable`, await parent.evaluate(e => [...e.querySelectorAll('.pr-group-toggle')].every(b => b.getAttribute('aria-expanded')==='false' && b.querySelector('.pr-group-chevron')?.textContent==='›') && [...e.querySelectorAll('.pr-group-count,.pr-group-title')].every(x => parseFloat(getComputedStyle(x).fontSize)>=12)));
    await shot(`groups-collapsed-${width}-${theme}`);
    await visit('sessions',width,theme);
    await page.locator('.pr-session[data-state="Working"]').waitFor();
    const done = page.locator('.pr-session[data-state="Done"]');
    check(`${theme} ${width} finished wording without duplicate activity age`, (await done.innerText()).includes('Finished 3m ago') && !(await done.innerText()).includes('Last activity') && !(await done.getAttribute('aria-label')).includes('Last activity'));
    check(`${theme} ${width} Idle stays a visible filled dot`, await page.locator('.pr-session[data-state="Idle"] .pr-session-center').evaluate(e=>Number(e.getAttribute('r'))>=2.5 && getComputedStyle(e).fill!=='none' && Number(getComputedStyle(e).opacity)>=.8));
    check(`${theme} ${width} static Working glyph distinct from Idle`, await page.locator('.pr-session[data-state="Working"] .pr-session-working').count() === 1 && await page.locator('.pr-session[data-state="Idle"] .pr-session-working').count() === 0);
    check(`${theme} ${width} session text at least 12px and AA`, await page.locator('#hermes-sessions').evaluate(root => {
      const canvas=document.createElement('canvas'),c=canvas.getContext('2d',{willReadFrequently:true});canvas.width=canvas.height=1;
      const lum=color=>{c.clearRect(0,0,1,1);c.fillStyle=color;c.fillRect(0,0,1,1);return [...c.getImageData(0,0,1,1).data].slice(0,3).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;}).reduce((n,v,i)=>n+v*[.2126,.7152,.0722][i],0);};
      const bg=lum(getComputedStyle(document.documentElement).getPropertyValue('--ui-bg-editor'));
      return [...root.querySelectorAll('.pr-session-meta,.pr-session-state,.pr-sessions-note')].every(e=>{const s=getComputedStyle(e),fg=lum(s.color);return parseFloat(s.fontSize)>=12&&(Math.max(bg,fg)+.05)/(Math.min(bg,fg)+.05)>=4.5;});
    }));
    await shot(`sessions-expanded-${width}-${theme}`);
    await page.locator('#hermes-sessions .pr-group-toggle').click();
    await page.locator('.pr-arrangement[aria-busy="false"]').waitFor();
    await shot(`sessions-collapsed-${width}-${theme}`);
  }
  await visit('sessions');
  await page.emulateMedia({reducedMotion:'no-preference'});
  await page.evaluate(() => window.__sessionDone());
  await page.waitForFunction(() => document.querySelector('.pr-session')?.dataset.state === 'Done');
  check('tick fades/scales complete check, never a dash', await page.locator('.pr-session-tick').first().evaluate(e => {const s=getComputedStyle(e),a=e.getAnimations()[0];return s.strokeDasharray==='none' && a?.effect.getKeyframes().every(f => !('strokeDashoffset' in f));}));
  check('no runtime errors', errors.length === 0);
  fs.writeFileSync(path.join(out,'polish2-results.json'),JSON.stringify({checks,errors},null,2));
  console.log(`${checks.length} polish2 checks passed`);
} finally {await browser.close();}
