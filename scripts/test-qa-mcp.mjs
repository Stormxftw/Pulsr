import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import path from 'node:path';
import fs from 'node:fs';
const {chromium} = createRequire(path.join(process.argv[2], 'package.json'))('playwright');
const out = process.argv[3] || 'artifacts/qa/mcp';
fs.mkdirSync(out, {recursive:true});
const origin = process.env.PULSE_PREVIEW_ORIGIN || 'http://127.0.0.1:5561';
const browser = await chromium.launch({channel:'msedge',headless:true});
const page = await browser.newPage({viewport:{width:1200,height:1000},reducedMotion:'reduce'});
page.setDefaultTimeout(12000);
const errors = [], checks = [], failures = [];
page.on('pageerror', e => errors.push(String(e)));
await page.route('**/*', r => /^https?:/.test(r.request().url()) && !r.request().url().startsWith(origin + '/') ? r.abort() : r.continue());
const check = (name, value) => { checks.push({name,ok:!!value}); if (!value) failures.push(name); console.log((value?'PASS ':'FAIL ') + name); };
const button = name => page.getByRole('button',{name,exact:true});
const field = p => page.locator(`[data-field="${p}"]`).locator('input,textarea,[role=combobox]').first();
const settle = () => page.waitForTimeout(650);
async function setup(width=670, theme='dark') {
  await page.goto(`${origin}/?mode=builder&width=${width}&theme=${theme}`);
  await button('New pulse').click();
  
  await page.locator('.pr-b2-template').filter({has:page.getByText('MCP tool',{exact:true})}).click();
  await settle();
}
try {
  await setup();
  check('blank MCP setup has no undefined grant target', !/undefined|null/.test(await page.locator('.pr-b2-source').innerText()));
  const picker=page.getByRole('combobox',{name:'Choose a connected tool',exact:true});
  await picker.click();
  await page.getByRole('option',{name:'probe / write_counts · not available for unattended polling',exact:true}).click();
  await field('/template/consent').check();
  check('picker preserves exact names and explains write refusal', await field('/template/server').inputValue()==='probe' && await field('/template/tool').inputValue()==='write_counts' && (await page.locator('.pr-b2-source').innerText()).includes('not marked read-only') && await button('Test once').isDisabled());
  await picker.click();
  await page.getByRole('option',{name:'probe / read_counts · read-only',exact:true}).click();
  check('changing picked tool resets human test consent', !await field('/template/consent').isChecked());
  await page.locator('#surface').screenshot({path:path.join(out,'mcp-setup-picker.png')});
  await field('/template/server').fill('probe');
  await field('/template/tool').fill('read_counts');
  await field('/template/metrics').fill('{"used":"/used"}');
  await field('/template/args').fill('{}');
  await field('/template/args').fill('');
  await settle();
  check('empty optional MCP inputs mean an empty object', await button('Next').isEnabled());
  for (const invalid of ['{broken','[]','null','true']) {
    await field('/template/args').fill(invalid); await settle();
    check(`non-object MCP inputs rejected: ${invalid}`, await button('Next').isDisabled());
  }
  await field('/template/args').fill('   '); await settle();
  check('whitespace-only optional inputs match empty inputs', await button('Next').isEnabled());
  await field('/template/consent').check();
  await button('Test once').click();
  await button('Bind /used = 42').waitFor();
  check('one explicit dispatch; consent consumed', await page.evaluate(()=>window.__mcpTestDispatches===1) && !await field('/template/consent').isChecked());
  check('number strings and booleans cannot be bound', await page.getByRole('button',{name:/Bind .* = (?:9|true)$/}).count()===0);
  check('connected tool picker available in source setup', await page.getByRole('combobox',{name:'Choose a connected tool',exact:true}).count()===1);
  await button('Bind /used = 42').click();
  await settle();
  check('inspected numeric pointer becomes a valid metric', await button('Next').isEnabled());
  await field('/template/metrics').fill('{"used":"/used"}');
  await settle();
  await button('Next').click(); await settle();
  await button('Next').click(); await settle();
  await button('Review permissions').click();
  await page.locator('.pr-builder-review .pr-approval').waitFor();
  const approval=page.locator('.pr-builder-review .pr-approval');
  check('frozen MCP disclosure includes exact connector and cadence', await approval.innerText().then(t=>t.includes('probe')&&t.includes('read_counts')&&t.includes('4 req/h')&&t.includes('15m')&&t.includes('plugins.entries.pulse-rings.mcp_allowlist')));
  check('MCP has no automatic test or approval', await page.evaluate(()=>window.__mcpTestDispatches===1 && !window.__pulseRestCalls.some(c=>c.path.endsWith('/approve'))));
  for (const width of [320,480,670]) for (const theme of ['dark','light']) {
    await page.goto(`${origin}/?mode=mcp&width=${width}&theme=${theme}`);
    await page.locator('[data-id=mcp-queue] .pr-trigger').waitFor();
    await page.evaluate(()=>{window.__pulseStatus.drafts=[];window.__pulseStatus.pulses[0].title=('工具 / café — '+'Long name '.repeat(6)).slice(0,60);window.__emitPulse('draft.updated');});
    await settle();
    const trigger=page.locator('[data-id=mcp-queue] .pr-trigger');
    await trigger.waitFor(); await trigger.focus(); await settle();
    check(`${width} ${theme} collapsed keyboard summary`, !!await trigger.getAttribute('aria-label'));
    await trigger.click(); await settle();
    const details=page.locator('[data-id=mcp-queue] .pr-details');
    check(`${width} ${theme} MCP disclosure fits`, await details.evaluate(e=>e.scrollWidth<=e.clientWidth+1));
    check(`${width} ${theme} literal args never execute`, await details.locator('img').count()===0 && await page.evaluate(()=>!window.MCP_XSS));
    await page.screenshot({path:path.join(out,`mcp-${width}-${theme}.png`),fullPage:true});
    await page.evaluate(()=>{const p=window.__pulseStatus.pulses[0];p.state='needs_mcp_grant';p.mcp.hermes_allowed=false;p.feeds[0].state='needs_mcp_grant';window.__emitPulse('draft.updated');});
    await settle();
    check(`${width} ${theme} waiting grant summary and remedy`, (await trigger.getAttribute('aria-label')).includes('waiting for Hermes MCP grant') && (await details.innerText()).includes('plugins.entries.pulse-rings.mcp_allowlist'));
    await page.screenshot({path:path.join(out,`grant-${width}-${theme}.png`),fullPage:true});
    await setup(width,theme);
    await page.getByRole('combobox',{name:'Choose a connected tool',exact:true}).click();
    await page.getByRole('option',{name:'probe / write_counts · not available for unattended polling',exact:true}).click();
    check(`${width} ${theme} tool-picker setup fits`, await page.locator('.pr-b2-source').evaluate(e=>e.scrollWidth<=e.clientWidth+1));
    await page.locator('#surface').screenshot({path:path.join(out,`setup-${width}-${theme}.png`)});
  }
  check('no browser exceptions', errors.length===0);
  fs.writeFileSync(path.join(out,'qa-mcp-browser.json'),JSON.stringify({checks,errors,failures},null,2));
  assert.equal(failures.length,0, failures.join('; '));
} finally { await browser.close(); }
