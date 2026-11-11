import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import path from 'node:path';
import fs from 'node:fs';
const req = createRequire(path.join(process.argv[2], 'package.json'));
const {chromium} = req('playwright');
const out = process.argv[3];
fs.mkdirSync(out, {recursive:true});
const origin = process.env.PULSE_PREVIEW_ORIGIN || 'http://127.0.0.1:5261';
const browser = await chromium.launch({channel:'msedge',headless:true});
const page = await browser.newPage({viewport:{width:640,height:1400}});
const checks=[], errors=[], remote=[];
page.on('pageerror', e=>errors.push(String(e)));
page.on('console',m=>{if(['error','warning'].includes(m.type())&&!m.text().includes('[vite]'))errors.push(m.text());});
page.on('request',r=>{if(/^https?:/.test(r.url())&&!r.url().startsWith(origin+'/'))remote.push(r.url());});
await page.route('**/*',route=>/^https?:/.test(route.request().url())&&!route.request().url().startsWith(origin+'/')?route.abort():route.continue());
const check=(name,value)=>{assert.ok(value,name);checks.push(name);console.log('PASS '+name);};
// One retry: the first navigation after a cold preview-server start can exceed the timeout.
const visit=async(mode,width=248)=>{for(let attempt=0;;attempt++){try{await page.goto(`${origin}/?mode=${mode}&width=${width}`);await page.locator('.pr-row, .pr-circle').first().waitFor();return;}catch(error){if(attempt)throw error;}}};
const strip=()=>page.locator('.pr-attention');
const shown=()=>page.locator('.pr-row').evaluateAll(rows=>rows.filter(r=>r.getClientRects().length).map(r=>r.dataset.id));
const order=()=>page.locator('.pr-row').evaluateAll(rows=>rows.map(r=>r.dataset.id).join(','));
const writes=()=>page.evaluate(()=>window.__pulseRestCalls.filter(c=>c.method&&c.method!=='GET').length);
const fits=()=>page.locator('.pr-shell').evaluate(e=>e.scrollWidth<=e.clientWidth+1);
const tinted=id=>page.locator(`[data-id=${id}] > .pr-trigger`).evaluate(e=>getComputedStyle(e).backgroundColor!=='rgba(0, 0, 0, 0)');
try {
  await visit('states');
  const kinds=await page.locator('.pr-row').evaluateAll(rows=>Object.fromEntries(rows.map(r=>[r.dataset.id,r.dataset.attention])));
  check('every row declares whether it needs the owner',Object.values(kinds).every(k=>['none','alert','problem','review'].includes(k)));
  check('alert, unrecoverable source and pending draft need the owner',kinds['catalog-prs']==='alert'&&kinds.error==='problem'&&kinds.unsupported==='problem'&&kinds.pd_0123456789==='review');
  check('automatic retry, stale cache and manual pause do not',kinds.backoff==='none'&&kinds.stale==='none'&&kinds.paused==='none'&&kinds.learning==='none');
  check('strip counts each kind in plain words',await strip().locator('.pr-attention-text').textContent()==='1 alert · 2 problems · 1 to review');
  check('strip is an unpressed toggle named for what it does',await strip().getAttribute('aria-pressed')==='false'&&await strip().getAttribute('aria-label')==='Only show what needs you: 1 alert · 2 problems · 1 to review');
  check('a source problem sets the strip tone',await strip().getAttribute('data-kind')==='problem');
  check('alerting row is tinted, quiet row is not',await tinted('catalog-prs')&&!await tinted('zero'));
  const before=await order(), writesBefore=await writes();
  await page.screenshot({path:path.join(out,'attention-off-248.png'),fullPage:true});
  await strip().click();
  check('lens keeps only rows that need the owner',JSON.stringify(await shown())===JSON.stringify(['pd_0123456789','catalog-prs','error','unsupported']));
  check('lens says how much it hides and how to leave',await strip().getAttribute('aria-pressed')==='true'&&await strip().textContent().then(t=>t.includes('Showing 4 of 11')&&t.includes('Show all')));
  await page.screenshot({path:path.join(out,'attention-on-248.png'),fullPage:true});
  await strip().focus();await page.keyboard.press('Space');
  check('keyboard leaves the lens and every row returns',await strip().getAttribute('aria-pressed')==='false'&&(await shown()).length===11);
  check('lens never reorders the saved arrangement',before===await order());
  check('lens never writes to the backend',writesBefore===await writes());
  await strip().click();
  await page.evaluate(()=>{const s=window.__pulseStatus;s.drafts=[];s.pulses=s.pulses.filter(p=>!p.alert?.active&&!['error','unsupported_version'].includes(p.state));window.__emitPulse('draft.updated');});
  await page.waitForFunction(()=>!document.querySelector('.pr-attention'));
  check('strip disappears and the lens releases when nothing needs the owner',await page.locator('.pr-shell').getAttribute('data-lens')===null&&(await shown()).length===7);
  for(const width of [176,200,231,248,320]){
    await visit('states',width);
    check(`${width}px: strip fits and no text is cut`,await fits()&&await strip().locator('.pr-attention-text').evaluate(e=>e.scrollWidth<=e.clientWidth+1));
  }
  await visit('states',56);
  check('rings-only rail carries no strip',await strip().count()===0);
  await visit('hero',231);
  check('below 240px the title gets the line, not the score text',await page.locator('.pr-score').evaluateAll(es=>es.length>0&&es.every(e=>getComputedStyle(e).display==='none')));
  await page.screenshot({path:path.join(out,'attention-hero-231.png'),fullPage:true});
  await visit('hero',248);
  check('from 240px the score text is still shown',await page.locator('.pr-score').evaluateAll(es=>es.length>0&&es.every(e=>getComputedStyle(e).display!=='none')));
  const separators=()=>page.locator('.pr-measured-summary').evaluateAll(all=>all.filter(s=>s.children.length===2&&s.getClientRects().length).map(s=>{const [a,b]=s.children,sep=s.querySelector('.pr-summary-sep');if(!sep)return {id:s.closest('.pr-row')?.dataset.id,missing:true};const box=s.getBoundingClientRect(),dot=sep.getBoundingClientRect();const wrapped=b.getBoundingClientRect().top>a.getBoundingClientRect().top+4;return {id:s.closest('.pr-row')?.dataset.id,wrapped,shown:dot.left>=box.left+10.5,flush:Math.abs(b.getBoundingClientRect().left-a.getBoundingClientRect().left)<1};}));
  await visit('blocks',320);
  let seps=await separators();
  check('a comparison on the same line keeps its separator',seps.length>0&&seps.every(s=>!s.missing&&(s.wrapped||s.shown))&&seps.some(s=>!s.wrapped));
  await visit('blocks',176);
  seps=await separators();
  check('a comparison that wraps does not start its line with a separator',seps.some(s=>s.wrapped)&&seps.every(s=>!s.missing&&(!s.wrapped||(!s.shown&&s.flush))));
  // An ellipsis appears as soon as the text is wider than its box by any fraction of a
  // pixel, so compare the laid-out text with the box; scrollWidth rounds that away.
  const footer=()=>page.locator('.pr-foot > span').first().evaluate(e=>{const r=document.createRange();r.selectNodeContents(e);return {shown:[...e.childNodes].filter(n=>n.nodeType===3||getComputedStyle(n).display!=='none').map(n=>n.textContent).join(''),cut:r.getBoundingClientRect().width>e.getBoundingClientRect().width+0.01,title:e.title};});
  // The longest thing the footer can say: background mode and no known request rate.
  const worstFooter=async()=>{await page.evaluate(()=>{const s=window.__pulseStatus;s.collection={...(s.collection||{}),mode:'background'};for(const p of s.pulses)if(p.budget)delete p.budget.req_per_hour;window.__emitPulse('draft.updated');});await page.waitForTimeout(250);return footer();};
  await visit('hero',231);
  let foot=await footer();
  check('a narrow footer says it in fewer words instead of cutting off',!foot.cut&&/^While open · 0 tokens · ≈\d[\d,]* req\/h$/.test(foot.shown));
  check('the narrow footer keeps the full sentence in its tooltip',/^Collecting while open · 0 tokens · ≈\d[\d,]* req\/h · pulse\/1 · v/.test(foot.title));
  for(const width of [310,320,360]){
    await visit('hero',width);
    foot=await footer();
    check(`${width}px footer drops the format and version before it would be cut`,!foot.cut&&/^Collecting while open · 0 tokens · ≈\d[\d,]* req\/h$/.test(foot.shown)&&/ · pulse\/1 · v/.test(foot.title));
    foot=await worstFooter();
    check(`${width}px footer fits at its longest`,!foot.cut&&foot.shown==='Collecting in background · 0 tokens · unknown req/h');
  }
  await visit('hero',400);
  foot=await footer();
  check('a roomy footer keeps the full sentence',!foot.cut&&/^Collecting while open · 0 tokens · ≈\d[\d,]* req\/h · pulse\/1 · v/.test(foot.shown));
  foot=await worstFooter();
  check('a roomy footer fits at its longest',!foot.cut&&/^Collecting in background · 0 tokens · unknown req\/h · pulse\/1 · v/.test(foot.shown));
  await visit('groups',231);
  check('below 240px a measured value is never cut short',await page.locator('.pr-capsule > .pr-label').evaluateAll(es=>es.length>0&&es.every(e=>e.scrollWidth<=e.clientWidth+1)));
  check('below 240px a comparison is shown whole or not at all',await page.locator('.pr-capsule').evaluateAll(cs=>cs.every(c=>{const r=c.querySelector('.pr-ratio');if(!r)return true;const a=c.getBoundingClientRect(),b=r.getBoundingClientRect();const whole=b.left>=a.left-0.5&&b.right<=a.right+0.5&&b.top>=a.top-0.5&&b.bottom<=a.bottom+0.5;return whole||b.top>=a.bottom-1;})));
  check('a narrow toolbar drops its note and stays on one line',await page.locator('.pr-arr-scope').evaluate(e=>getComputedStyle(e).display==='none')&&await page.locator('.pr-arr-toolbar').first().evaluate(e=>e.getBoundingClientRect().height<=40));
  await visit('groups',320);
  check('a roomy toolbar keeps its note on one line',await page.locator('.pr-arr-scope').evaluate(e=>getComputedStyle(e).display!=='none')&&await page.locator('.pr-arr-toolbar').first().evaluate(e=>e.getBoundingClientRect().height<=40));
  await visit('groups',248);
  check('quiet pulses show no strip',await strip().count()===0);
  const target=await page.locator('.pr-group .pr-row').first().getAttribute('data-id');
  await page.evaluate(id=>{const p=window.__pulseStatus.pulses.find(x=>x.id===id);p.alert={active:true,reason:'Change intensity 90/100',notify:'none'};window.__emitPulse('draft.updated');},target);
  await strip().waitFor();
  check('one alert inside a group is counted',await strip().locator('.pr-attention-text').textContent()==='1 alert');
  const groupsBefore=await page.locator('.pr-group').count();
  await strip().click();
  check('lens keeps the group holding the alert and hides quiet groups',JSON.stringify(await shown())===JSON.stringify([target])&&await page.locator('.pr-group').evaluateAll(gs=>gs.filter(g=>g.getClientRects().length).length)===1&&groupsBefore>1);
  check('lens leaves no empty sub-group, toolbar or orphaned heading',await page.locator('.pr-subgroup, .pr-arr-toolbar').evaluateAll(es=>es.every(e=>!e.getClientRects().length)));
  await page.screenshot({path:path.join(out,'attention-groups-on-248.png'),fullPage:true});
  await strip().click();
  await page.locator('.pr-group').first().locator('.pr-group-toggle').first().click();
  await page.locator('.pr-circle').first().waitFor();
  check('rings-only groups mark each ring too',await page.locator('.pr-circle').evaluateAll(cs=>cs.length>0&&cs.every(c=>['none','alert','problem'].includes(c.dataset.attention))));
  if(await page.locator(`.pr-circle[data-attention=alert]`).count()){
    await strip().click();
    check('lens keeps only the alerting ring in a rings-only group',await page.locator('.pr-circle').evaluateAll(cs=>cs.filter(c=>c.getClientRects().length).length)===1);
    await strip().click();
  }
  check('no remote requests',remote.length===0);
  check('no runtime warnings',errors.length===0);
  fs.writeFileSync(path.join(out,'attention-results.json'),JSON.stringify({checks,errors,remote},null,2));
  console.log(`${checks.length} attention browser checks passed`);
} finally {await browser.close();}
