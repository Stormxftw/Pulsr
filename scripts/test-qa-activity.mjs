// Focused activity/session QA against the actual SDK preview renderer.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import path from 'node:path';
import fs from 'node:fs';
const req = createRequire(path.join(process.argv[2], 'package.json'));
const {chromium} = req('playwright');
const out = process.argv[3];
fs.mkdirSync(out, {recursive:true});
const origin = process.env.PULSE_PREVIEW_ORIGIN || 'http://127.0.0.1:5551';
const browser = await chromium.launch({channel:'msedge',headless:true});
const page = await browser.newPage({viewport:{width:850,height:1050}});
const checks = [], failures = [], errors = [], remote = [];
page.on('pageerror', e => errors.push(String(e)));
page.on('request', r => {if (/^https?:/.test(r.url()) && !r.url().startsWith(origin + '/')) remote.push(r.url());});
await page.route('**/*', r => /^https?:/.test(r.request().url()) && !r.request().url().startsWith(origin + '/') ? r.abort() : r.continue());
const check = (name, pass) => {checks.push(name); if (!pass) failures.push(name); console.log((pass ? 'PASS ' : 'FAIL ') + name);};
const working = () => page.locator('.pr-session').first();
async function update(patch) {
  await page.evaluate(patch => {Object.assign(window.__sessionRows[0], patch); window.__emitPulse('sessions.updated');}, patch);
  await page.waitForTimeout(400);
}
try {
  await page.goto(origin + '/?mode=sessions&width=320&case=qa-metadata');
  await working().waitFor();
  await update({tool_calls_turn:1,tool_calls_total:1234});
  check('singular tool and grouped total in row', (await working().innerText()).includes('1 tool this turn · 1,234 total'));
  check('singular tool and grouped total in accessible name', (await working().getAttribute('aria-label')).includes('1 tool this turn · 1,234 total'));
  await update({tool_calls_turn:0,tool_calls_total:0});
  check('known all-zero counts omit noise', !(await working().innerText()).includes('0 tools this turn') && !(await working().getAttribute('aria-label')).includes('0 total'));
  await update({tool_calls_turn:null,tool_calls_total:null});
  check('unknown counts remain explicitly unknown', (await working().innerText()).includes('Tool counts not yet observed'));
  await page.evaluate(() => {window.__sessionTitles[0].title = '   ';});
  await page.waitForTimeout(15500);
  check('whitespace title gets sensible fallback', (await working().locator('.pr-session-title').innerText()) === 'Untitled chat');
  await page.evaluate(() => {window.__sessionReadError = true; window.__emitPulse('sessions.updated');});
  await page.waitForTimeout(600);
  check('cached rows do not hide a failed session refresh', (await page.locator('#hermes-sessions').innerText()).includes('Session activity unavailable'));
  check('unavailable observer pauses cached working animation', await working().getAttribute('data-running') === 'false');
  await page.locator('#hermes-sessions .pr-group-toggle').click();
  await page.waitForTimeout(300);
  check('collapsed cached session still discloses observer failure', (await working().getAttribute('aria-label')).includes('Session activity unavailable'));
  await page.getByRole('button', {name:'Manage Hermes sessions',exact:true}).focus();
  await page.keyboard.press('Tab');
  await page.getByRole('tooltip').waitFor();
  await page.screenshot({path:path.join(out,'qa-sessions-observer-error-tip.png'),fullPage:true});
  await page.locator('#hermes-sessions .pr-group-toggle').click();
  await page.waitForTimeout(300);
  if (process.env.QA_RED_ONLY) assert.equal(failures.length,0,failures.join('\n'));
  await page.evaluate(() => {window.__sessionReadError = false; window.__sessionTitles[0].title = '长标题 · ' + 'thoughtful-work-'.repeat(30); window.__emitPulse('sessions.updated');});
  await update({tool_calls_turn:1234,tool_calls_total:1234567});
  await page.waitForTimeout(15500);
  for (const theme of ['dark','light']) for (const width of [320,480,670]) {
    await page.goto(`${origin}/?mode=sessions&width=${width}&theme=${theme}&case=qa-${theme}-${width}`);
    await working().waitFor();
    await update({tool_calls_turn:1234,tool_calls_total:1234567});
    await page.evaluate(() => {window.__sessionTitles[0].title = '长标题 · ' + 'thoughtful-work-'.repeat(20);});
    await page.waitForTimeout(15500);
    check(`sessions ${theme} ${width} no overflow`, await page.locator('.pr-shell').evaluate(e => e.scrollWidth <= e.clientWidth + 1));
    check(`sessions ${theme} ${width} no raw invalid values`, !/NaN|undefined|null/.test(await page.locator('#hermes-sessions').innerText()));
    await page.screenshot({path:path.join(out,`qa-sessions-${theme}-${width}.png`),fullPage:true});
    await page.locator('#hermes-sessions .pr-group-toggle').click();
    await page.waitForTimeout(300);
    await page.getByRole('button', {name:'Manage Hermes sessions',exact:true}).focus();
    await page.keyboard.press('Tab');
    await page.getByRole('tooltip').waitFor();
    check(`sessions ${theme} ${width} full focus tip`, (await page.getByRole('tooltip').innerText()).includes('1,234 tools this turn · 1,234,567 total'));
    await page.screenshot({path:path.join(out,`qa-sessions-tip-${theme}-${width}.png`),fullPage:true});
  }
  // Real Python sample-preview/layout-check output, not handwritten renderer values.
  const call = async (route, body) => {
    const response = await page.request.post(origin + '/builder-mock', {data:{path:route,body}});
    assert.equal(response.status(),200,await response.text());
    return response.json();
  };
  const template = await call('/builder/from-template', {template:'hermes',values:{}});
  check('activity template profile-only', template.ok && template.feeds.main.kind === 'hermes.activity' && template.feeds.main.params.scope === 'profile');
  const layouts = await call('/builder/layouts', {feeds:template.feeds,metrics:template.metrics.filter(m=>m.default_selected).map(m=>m.ref),title:'Hermes · 长标题 · local work'});
  const definition = layouts[0].definition;
  const layout = await call('/layout-check', {definition});
  check('activity zero remote budget', layout.ok && layout.budget.hosts.length === 0 && layout.budget.req_per_hour === 0);
  const disclosure = await call('/fixture-disclosure', {definition});
  fs.writeFileSync(path.join(out,'activity-builder-evidence.json'),JSON.stringify({template,layout,disclosure},null,2));
  for (const state of ['measured','learning','unknown']) {
    const preview = await call('/builder/preview', {definition,state});
    for (const theme of ['dark','light']) for (const width of [320,480,670]) {
      await page.goto(`${origin}/?mode=hero&width=${width}&theme=${theme}&case=qa-activity-${state}`);
      await page.locator('.pr-shell').waitFor();
      await page.evaluate(p => {window.__pulseStatus.pulses=[p]; window.__pulseStatus.drafts=[]; window.__emitPulse('draft.updated');}, preview);
      await page.locator('.pr-row').first().waitFor();
      await page.locator('.pr-row .pr-trigger').first().click();
      await page.waitForTimeout(200);
      check(`activity ${state} ${theme} ${width} no overflow`, await page.locator('.pr-shell').evaluate(e=>e.scrollWidth<=e.clientWidth+1));
      check(`activity ${state} ${theme} ${width} no invalid values`, !/NaN|undefined|null/.test(await page.locator('.pr-shell').innerText()));
      await page.screenshot({path:path.join(out,`qa-activity-${state}-${theme}-${width}.png`),fullPage:true});
    }
  }
  check('no remote requests', remote.length === 0);
  check('no runtime errors', errors.length === 0);
  fs.writeFileSync(path.join(out,'qa-activity-results.json'),JSON.stringify({checks,failures,errors,remote},null,2));
  assert.equal(failures.length,0,failures.join('\n'));
  console.log(`${checks.length} focused browser checks passed`);
} finally {await browser.close();}
