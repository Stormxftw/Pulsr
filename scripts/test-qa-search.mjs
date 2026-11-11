import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import fs from 'node:fs';
import path from 'node:path';
import {compatibleField, pause} from './builder2-test-helpers.mjs';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const {chromium}=createRequire(path.join(process.argv[2],'package.json'))('playwright');
const out=process.argv[3];fs.mkdirSync(out,{recursive:true});
const demo=process.argv[4] || path.join(root,'tests/fixtures/github/hackathon-race.pulse.yaml');
const fixtures=JSON.parse(execFileSync('uv',['run','--isolated','--no-project','--python','3.11','--with','jsonschema>=4,<5','--with','ruamel.yaml>=0.18,<0.19','python',path.join(root,'scripts/qa-search-fixtures.py'),demo],{encoding:'utf8',cwd:root,env:process.env}));
fs.writeFileSync(path.join(out,'engine-fixtures.json'),JSON.stringify(fixtures,null,2));
const origin=process.env.PULSE_PREVIEW_ORIGIN || 'http://127.0.0.1:5541';
const browser=await chromium.launch({channel:'msedge',headless:true});
const page=await browser.newPage({viewport:{width:1100,height:1000},reducedMotion:'reduce'});
page.setDefaultTimeout(15000);
const errors=[],remote=[],checks=[];
page.on('pageerror',e=>errors.push(String(e)));
page.on('request',r=>{if(/^https?:/.test(r.url())&&!r.url().startsWith(origin+'/'))remote.push(r.url());});
await page.route('**/*',r=>/^https?:/.test(r.request().url())&&!r.request().url().startsWith(origin+'/')?r.abort():r.continue());
const check=(name,ok)=>{assert.ok(ok,name);checks.push(name);console.log('PASS '+name);};
const button=name=>page.getByRole('button',{name,exact:true});
const visit=async(width=320,theme='dark')=>{await page.goto(`${origin}/?mode=hero&width=${width}&theme=${theme}`,{timeout:60000});await page.locator('.pr-row').first().waitFor();};
const inject=async key=>{await page.evaluate(({row,as_of})=>{window.__pulseStatus.pulses=[{...row,id:'catalog-prs'}];window.__pulseStatus.drafts=[];window.__pulseStatus.as_of=as_of;window.__emitPulse('draft.updated');},{row:fixtures.rows[key],as_of:fixtures.as_of});await page.waitForTimeout(300);};
const target=()=>page.locator('[data-id="catalog-prs"]');
const open=async()=>{if(await target().locator('.pr-trigger').getAttribute('aria-expanded')!=='true')await target().locator('.pr-trigger').click();};
const contained=()=>page.locator('.pr-shell').evaluate(root=>{const r=root.getBoundingClientRect();return root.scrollWidth<=root.clientWidth+1&&[...root.querySelectorAll('.pr-trigger,.pr-display,.pr-block,.pr-details')].filter(e=>e.getBoundingClientRect().width).every(e=>{const b=e.getBoundingClientRect();return b.left>=r.left-1&&b.right<=r.right+1;});});
try {
  for(const width of [320,480,670])for(const theme of ['dark','light']){
    await visit(width,theme);await inject('measured');await open();
    check(`${theme} ${width}: real hackathon demo has 173 and source-baseline score`,(await target().innerText()).includes('173')&&fixtures.rows.measured.display[0].ring.score===100);
    check(`${theme} ${width}: score stat spark are contained`,await contained()&&await target().locator('.pr-display .pr-block').count()===3);
    await page.screenshot({path:path.join(out,`demo-${theme}-${width}.png`),fullPage:true});
    await inject('error');
    check(`${theme} ${width}: failed source is unknown, no old 100 score`,fixtures.rows.error.ring.unknown&&!(await target().locator('.pr-stat__value').innerText()).match(/^173$/)&&await target().innerText().then(t=>t.includes('incomplete')));
    await page.screenshot({path:path.join(out,`error-${theme}-${width}.png`),fullPage:true});
  }
  await visit();await inject('million');await open();
  check('large counts have separators',(await target().innerText()).includes('1,234,567'));
  for(const [key,expected] of [['backoff','rate limited'],['credential','credential rejected'],['query','rejected'],['network','reach GitHub'],['stale','stale'],['warming','Not measured']]){
    await inject(key);await open();
    check(`${key} has a specific state message`,(await target().innerText()).toLowerCase().includes(expected.toLowerCase()));
    check(`${key} contains no raw or nonfinite tokens`,!(/NaN|undefined|Infinity|hours_since|total_count/.test(await target().innerText())));
  }
  await inject('zero_capsule');await open();
  await page.screenshot({path:path.join(out,'zero-capsule.png'),fullPage:true});
  check('measured zero is not endlessly learning',(await target().locator('.pr-capsule').getAttribute('title')).includes('Usual activity is zero')&&!(await target().innerText()).includes('Learning baseline'));
  await inject('singular_capsule');await open();
  check('one PR is singular',(await target().innerText()).includes('1 PR / 24h'));
  // Collapsed group uses the actual circle plus SDK hover/focus tooltip path.
  await page.goto(`${origin}/?mode=groups&width=320`,{timeout:60000});await page.locator('[data-group-id="communities"]').first().waitFor();
  await page.evaluate(row=>{window.__pulseStatus.pulses=window.__pulseStatus.pulses.map(p=>p.id==='pulse-2'?{...row,id:'pulse-2'}:p);window.__emitPulse('draft.updated');},fixtures.rows.measured);
  await page.locator('[data-group-id="communities"]').first().locator(':scope > .pr-group-head .pr-group-toggle').click();
  const circle=page.locator('[data-arr-pulse="pulse-2"] .pr-circle');await circle.waitFor();await circle.focus();await circle.hover();
  await page.getByRole('tooltip').first().waitFor();
  check('collapsed search circle tooltip has readable source context',(await page.getByRole('tooltip').first().innerText()).includes(fixtures.definition.title));
  await page.screenshot({path:path.join(out,'collapsed-tip.png'),fullPage:true});
  await page.goto(`${origin}/?mode=builder&width=900`,{timeout:60000});await button('New pulse').click();await pause(page);
  await page.locator('.pr-b2-template').filter({has:page.getByText('GitHub PRs/issues search',{exact:true})}).click();await pause(page);
  await compatibleField(page,'/template/repo').fill('NousResearch/hermes-agent');
  await compatibleField(page,'/template/title_contains').fill('plugin-catalog');
  await pause(page);await button('Next').click();
  await page.locator('.pr-builder-preview .pr-block[data-type=stat]').waitFor();
  await page.locator('.pr-builder-preview .pr-block[data-type=spark]').waitFor();
  check('builder default search preset shows a current count and trend',await page.locator('.pr-builder-preview .pr-block[data-type=stat]').count()===1&&await page.locator('.pr-builder-preview .pr-block[data-type=spark]').count()===1);
  await page.locator('.pr-b2-layout').filter({has:page.getByText('Change vs usual',{exact:true})}).click();
  // Layout replacement is an explicit, local authoring decision, not approval.
  await page.getByRole('alertdialog').getByRole('button',{name:'Discard changes',exact:true}).click();
  await page.locator('.pr-builder-preview .pr-display .pr-block[data-type=score]').waitFor();
  check('optional search comparison preset has a source-baseline score',await page.locator('.pr-builder-preview .pr-display .pr-block[data-type=score]').count()===1);
  await button('Next').click();await pause(page);await button('Review permissions').click();
  await page.locator('.pr-builder-review .pr-approval').waitFor();
  const approval=await page.locator('.pr-builder-review .pr-approval').innerText();
  check('approval discloses API host and conservative rounded search cost',approval.includes('api.github.com')&&approval.includes('≈5 req/h'));
  check('draft retains exact search budget and baseline interval',await page.evaluate(()=>window.__pulseStatus.drafts.some(d=>Math.abs(d.budget.req_per_hour-(4+1/6))<1e-9&&d.definition.feeds.main.params.baseline_days===14&&d.definition.feeds.main.every==='15m')));
  check('builder never approves without human action',await page.evaluate(()=>!window.__pulseRestCalls.some(c=>c.path.endsWith('/approve'))));
  await page.screenshot({path:path.join(out,'builder-approval.png'),fullPage:true});
  await button('Jump to Approve').click();
  check('approval action remains reachable in the scrolling review pane',await page.locator('.pr-builder-review .pr-card-actions button').first().evaluate(e=>{const b=e.getBoundingClientRect();return document.activeElement===e&&b.top>=0&&b.bottom<=innerHeight;}));
  await page.screenshot({path:path.join(out,'builder-approval-action.png'),fullPage:true});
  check('no remote requests or page errors',remote.length===0&&errors.length===0);
  fs.writeFileSync(path.join(out,'search-results.json'),JSON.stringify({checks:checks.length,errors,remote},null,2));
  console.log(`${checks.length} search browser checks passed`);
} finally {await browser.close();}
