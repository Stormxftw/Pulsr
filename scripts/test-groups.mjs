// WP15 groups: real plugin, local fixture transport, no network collectors.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
const req = createRequire(path.join(process.argv[2], 'package.json'));
const {chromium} = req('playwright');
const origin = process.env.PULSE_PREVIEW_ORIGIN || 'http://127.0.0.1:5401';
const out = process.argv[3];
fs.mkdirSync(out, {recursive:true});
const browser = await chromium.launch({channel:'msedge',headless:true});
const page = await browser.newPage({viewport:{width:1100,height:1500},reducedMotion:'reduce'});
const checks = [], failures = [], errors = [], remote = [];
page.on('pageerror', e => errors.push(String(e)));
page.on('console', m => {if (['error','warning'].includes(m.type())) errors.push(m.text());});
await page.route('**/*', r => {
  if (/^https?:/.test(r.request().url()) && !r.request().url().startsWith(origin + '/')) {remote.push(r.request().url());return r.abort();}
  return r.continue();
});
const check = (name, ok) => {checks.push(name);if(!ok)failures.push(name);console.log(`${ok?'PASS':'FAIL'} ${name}`);};
const idle = async () => {await page.waitForFunction(()=>document.querySelector('.pr-arrangement')?.getAttribute('aria-busy')==='false');await page.waitForTimeout(100);};
const visit = async (name='main',width=320,theme='dark',extra='') => {
  await page.goto(`${origin}/?mode=groups&case=${name}&width=${width}&theme=${theme}${extra}`);
  await page.getByRole('button',{name:'Arrange',exact:true}).waitFor();await idle();
};
const list = id => page.locator(`[data-arr-list="${id}"]`).first();
const pulse = id => page.locator(`[data-arr-pulse="pulse-${id}"]`).first();
const order = async id => list(id).locator(':scope > [data-arr-pulse]').evaluateAll(es=>es.map(e=>e.dataset.arrPulse));
const arrange = async () => {await page.getByRole('button',{name:'Arrange',exact:true}).click();};
const drag = async (source,target,below=true,hold=false) => {
  await source.scrollIntoViewIfNeeded();
  const a = await source.boundingBox();
  await page.mouse.move(a.x+a.width/2,a.y+a.height/2);await page.mouse.down();
  await page.mouse.move(a.x+a.width/2+8,a.y+a.height/2+8,{steps:2});
  // Enlarged readable headers can put the old 3px-edge destination in the
  // autoscroll zone. Use a visible point in the intended half of the target;
  // if needed, exercise real edge autoscroll before measuring it again.
  let point;
  for(let attempt=0;attempt<60;attempt++){
    const b=await target.boundingBox(), pane=await page.locator('.pr-shell').boundingBox();
    const mid=b.y+b.height/2;
    const top=Math.max(b.y+3,pane.y+72,below?mid+1:-Infinity);
    const bottom=Math.min(b.y+b.height-3,pane.y+pane.height-48,below?Infinity:mid-1);
    if(top<=bottom){point={x:b.x+b.width/2,y:below?bottom:top};break;}
    await page.mouse.move(pane.x+pane.width/2,mid<pane.y+72?pane.y+8:pane.y+pane.height-8,{steps:4});
    await page.waitForTimeout(65);
  }
  assert.ok(point,'drag destination has a visible non-autoscrolling hit point');
  await page.mouse.move(point.x,point.y,{steps:12});
  await page.waitForTimeout(100);
  if(!hold){await page.mouse.up();await idle();}
};
const grip = id => pulse(id).locator('.pr-arr-grip');
const group = id => page.locator(`[data-group-id="${id}"]`).first();
const collapse = async id => {await group(id).locator(':scope > .pr-group-head .pr-group-toggle').click();await idle();};
const move = async (id,dest) => {
  await pulse(id).getByRole('button',{name:/^Move .* to…$/}).click();
  await page.getByLabel('Move to…',{exact:true}).selectOption(dest);
  await page.getByRole('button',{name:'Move pulse',exact:true}).click();await idle();
};
const shot = async name => {if(!name.startsWith('mid-drag'))await page.mouse.move(5,5);await page.screenshot({path:path.join(out,name+'.png'),fullPage:true});};
try {
  await visit();
  check('12 fixture pulses, one subgroup',await page.locator('[data-arr-pulse]').count()===12 && await page.locator('.pr-subgroup').count()===1);
  check('expanded header count and summary',/8 pulses · 3 in Developer tools/.test(await group('communities').locator('.pr-group-count').first().innerText()));
  await arrange();
  await drag(grip(1),pulse(3));
  check('pointer reorder within group',(await order('communities')).join(',')==='pulse-2,pulse-3,pulse-1,pulse-4,pulse-5');
  await drag(grip(1),pulse(6),false);
  check('pointer into subgroup',(await order('tools'))[0]==='pulse-1');
  await drag(grip(7),pulse(6),false);
  check('pointer reorder within subgroup',(await order('tools')).join(',')==='pulse-1,pulse-7,pulse-6,pulse-8');
  await drag(grip(7),pulse(6));
  await drag(grip(1),pulse(11));
  check('pointer out to ungrouped',(await order('')).includes('pulse-1') && !(await order('tools')).includes('pulse-1'));
  await drag(grip(11),pulse(9),false);
  check('pointer into second group',(await order('workspace'))[0]==='pulse-11');
  await drag(group('workspace').getByRole('button',{name:'Drag group Workspace'}),group('communities'),false);
  check('whole group reorder',await page.locator('.pr-arrangement > .pr-group').first().getAttribute('data-group-id')==='workspace');
  await group('workspace').locator(':scope > .pr-group-head .pr-group-toggle').press('Alt+ArrowDown');await idle();
  check('keyboard group reorder',await page.locator('.pr-arrangement > .pr-group').last().getAttribute('data-group-id')==='workspace');
  await pulse(11).locator('.pr-trigger').focus();await page.keyboard.press('Alt+ArrowDown');await idle();
  check('Alt Down moves within list',(await order('workspace')).join(',')==='pulse-9,pulse-11,pulse-10');
  await page.keyboard.press('Alt+ArrowUp');await idle();
  check('Alt Up retains focus and reverses move',(await order('workspace'))[0]==='pulse-11' && await pulse(11).locator('.pr-trigger').evaluate(e=>e===document.activeElement));
  await move(11,'tools');
  check('Move to subgroup',(await order('tools')).at(-1)==='pulse-11');
  await move(11,'');check('Move to Ungrouped',(await order('')).at(-1)==='pulse-11');
  const persisted = await page.evaluate(()=>window.__layoutRemote);
  await page.reload();await page.getByRole('button',{name:'Arrange',exact:true}).waitFor();await idle();
  check('persistence round trip',JSON.stringify(await page.evaluate(()=>window.__layoutRemote))===JSON.stringify(persisted));
  await arrange();
  const before = await order('communities');
  await drag(grip(2),pulse(5),true,true);
  check('insertion indicator visible',await page.locator('.pr-arr-indicator').isVisible());
  await page.keyboard.press('Escape');await page.mouse.up();await idle();
  check('Escape cancels pointer move',JSON.stringify(await order('communities'))===JSON.stringify(before));
  check('Escape removes ghost',!await page.locator('.pr-arr-ghost').isVisible());
  await page.evaluate(()=>{window.__layoutError=true;});
  await pulse(2).locator('.pr-trigger').press('Alt+ArrowDown');await idle();
  check('failed write rollback',JSON.stringify(await order('communities'))===JSON.stringify(before));
  check('quiet rollback toast',await page.evaluate(()=>window.__pulseNotification?.message.includes('previous order restored')));
  await page.evaluate(()=>{window.__layoutError=false;window.__layoutStale=true;});
  await pulse(2).locator('.pr-trigger').press('Alt+ArrowDown');await idle();
  check('stale write rolls back without retry',JSON.stringify(await order('communities'))===JSON.stringify(before));
  await page.evaluate(()=>{window.__layoutStale=false;const p=window.__pulseStatus.pulses.find(p=>p.id==='pulse-3');p.ring.score=99;p.capsule.label='123 measured';window.__emitPulse('draft.updated');});
  await page.waitForTimeout(400);
  check('source updates remain live without reordering arranged rows',(await pulse(3).locator('.pr-trigger').getAttribute('aria-label')).includes('123 measured') && JSON.stringify(await order('communities'))===JSON.stringify(before));
  await collapse('communities');
  check('collapsed circles count incl subgroup',await group('communities').locator('.pr-circle').count()===7);
  const grid = group('communities').locator(':scope > .pr-circle-grid');
  check('4 columns fixed',await grid.evaluate(e=>getComputedStyle(e).gridTemplateColumns.split(' ').length===4));
  check('subgroup has own labelled grid',await group('tools').locator('.pr-circle-grid').count()===1 && await group('tools').locator('.pr-group-toggle').innerText().then(t=>t.includes('Developer tools')));
  const circle = group('communities').locator('.pr-circle').first();
  await circle.hover();await page.waitForTimeout(350);
  check('collapsed hover same capsule tooltip',await page.getByRole('tooltip').innerText().then(t=>t.includes('TypeScript')&&t.includes('online')));
  await page.mouse.move(5,5);
  // Real SDK Tip requires keyboard modality AND :focus-visible; a pointer
  // hover followed by element.focus() is deliberately suppressed by the host.
  await group('communities').getByRole('button',{name:'Manage Communities',exact:true}).focus();
  await page.keyboard.press('Tab');
  check('collapsed circle reached by keyboard Tab',await circle.evaluate(e=>document.activeElement===e && e.matches(':focus-visible')));
  await page.waitForTimeout(350);
  check('collapsed focus tooltip',await page.getByRole('tooltip').count()===1);
  await circle.press('Enter');await idle();
  check('Enter expands pulse details',await group('communities').locator('.pr-details').count()>0 || await group('communities').getByRole('button',{name:'Pause',exact:true}).count()>0);
  await page.keyboard.press('Escape');
  await circle.click();await idle();
  check('pointer click below drag threshold still opens details',await group('communities').getByRole('button',{name:'Pause',exact:true}).count()>0);
  await page.keyboard.press('Escape');
  await drag(circle,group('workspace').locator('.pr-trigger').last());
  check('collapsed circle pointer drop',!(await order('communities')).includes('pulse-2') && (await order('workspace')).includes('pulse-2'));
  await move(2,'communities');
  await collapse('tools');
  check('subgroup header expands inherited collapsed state',await group('communities').locator('.pr-circle').count()===0);
  await collapse('tools');
  check('subgroup collapse independent',await group('tools').locator('.pr-circle').count()===3 && await group('communities').locator(':scope > .pr-group-list .pr-circle').count()===0);
  await collapse('tools');
  check('expand restores rows',await group('communities').locator('.pr-circle').count()===0);
  await page.getByRole('button',{name:'+ Group',exact:true}).click();await page.getByLabel('New group name').fill('Ideas');await page.getByRole('button',{name:'Create group',exact:true}).click();await idle();
  check('new group',await page.getByRole('button',{name:'Manage Ideas',exact:true}).count()===1);
  const ideas=await page.evaluate(()=>window.__layoutRemote.layout.groups.find(g=>g.title==='Ideas').id);
  await drag(grip(11),list(ideas));
  check('pointer drop into empty group',(await order(ideas)).join(',')==='pulse-11');
  await page.getByRole('button',{name:'Manage Ideas',exact:true}).click();await page.getByLabel('Group name',{exact:true}).fill('Reading');await page.getByRole('button',{name:'Rename',exact:true}).click();await idle();
  check('rename group',await page.getByRole('button',{name:'Manage Reading',exact:true}).count()===1);
  await page.getByRole('button',{name:'Manage Reading',exact:true}).click();await page.getByRole('button',{name:'New subgroup',exact:true}).click();await page.getByLabel('New subgroup name').fill('Later');await page.getByRole('button',{name:'Create group',exact:true}).click();await idle();
  check('new subgroup',await page.getByRole('button',{name:'Manage Later',exact:true}).count()===1);
  await page.getByRole('button',{name:'Manage Later',exact:true}).click();check('no second level subgroup control',await page.getByRole('button',{name:'New subgroup',exact:true}).count()===0);await page.getByRole('button',{name:'Cancel',exact:true}).click();
  await page.getByRole('button',{name:'Manage Reading',exact:true}).click();await page.getByRole('button',{name:'Delete group…',exact:true}).click();
  check('delete requires confirmation',await page.getByRole('alertdialog',{name:'Delete group'}).isVisible());
  await page.getByRole('button',{name:'Cancel',exact:true}).click();check('cancel preserves group',await page.getByRole('button',{name:'Manage Reading',exact:true}).count()===1);
  await page.getByRole('button',{name:'Manage Reading',exact:true}).click();await page.getByRole('button',{name:'Delete group…',exact:true}).click();await page.getByRole('button',{name:'Delete group',exact:true}).click();await idle();
  check('delete keeps all pulses',await page.locator('[data-arr-pulse]').count()===12 && await page.getByRole('button',{name:'Manage Reading',exact:true}).count()===0);
  await page.getByRole('button',{name:'Manage Workspace',exact:true}).click();await page.getByRole('button',{name:'Ungroup',exact:true}).click();await idle();
  check('ungroup keeps pulses',await page.locator('[data-arr-pulse]').count()===12 && (await order('')).includes('pulse-9'));
  await move(9,'@new');await page.getByLabel('New group name').fill('From move');await page.getByRole('button',{name:'Create group',exact:true}).click();await idle();
  check('Move to new group',await page.getByRole('button',{name:'Manage From move',exact:true}).count()===1);
  check('reduced motion no FLIP animations',await page.locator('.pr-arr-item').evaluateAll(es=>es.every(e=>e.getAnimations().length===0)));
  check('layout actions never approve or poll sources',await page.evaluate(()=>window.__pulseRestCalls.filter(c=>c.method==='PUT').every(c=>c.path==='/layout')));
  await page.evaluate(()=>window.__setPulseProfile('other'));
  await page.getByRole('button',{name:'Arrange',exact:true}).waitFor();await idle();
  check('profile switch isolates arrangement',await page.getByRole('button',{name:'Manage Workspace',exact:true}).count()===1 && await page.getByRole('button',{name:'Manage From move',exact:true}).count()===0);
  for (const theme of ['dark','light']) for (const width of [248,320,670]) {
    const key=`${width}-${theme}`;
    await visit('shots-'+key,width,theme);
    check(key+' expanded no horizontal overflow',await page.locator('.pr-shell').evaluate(e=>e.scrollWidth<=e.clientWidth+1));
    if(width!==248)await shot('expanded-'+key);
    await collapse('communities');await collapse('workspace');
    check(key+' collapsed four columns',await group('communities').locator(':scope > .pr-circle-grid').evaluate(e=>getComputedStyle(e).gridTemplateColumns.split(' ').length===4));
    check(key+' collapsed no horizontal overflow',await page.locator('.pr-shell').evaluate(e=>e.scrollWidth<=e.clientWidth+1));
    check(key+' wraps fifth circle',await group('communities').locator(':scope > .pr-circle-grid > .pr-arr-item').evaluateAll(es=>es[4].getBoundingClientRect().top>es[0].getBoundingClientRect().top));
    if(width!==248)await shot('collapsed-'+key);
    await arrange();
    await drag(group('communities').locator('.pr-circle').first(),group('workspace').locator('.pr-circle').last(),true,true);
    check(key+' drag indicator',await page.locator('.pr-arr-indicator').isVisible());
    check(key+' ghost does not cover insertion marker',await page.locator('.pr-arr-ghost').evaluate(e=>{const a=e.getBoundingClientRect(),b=e.parentElement.querySelector('.pr-arr-indicator').getBoundingClientRect();return a.right<=b.left || a.left>=b.right || a.bottom<=b.top || a.top>=b.bottom;}));
    if(width!==248)await shot('mid-drag-'+key);
    await page.keyboard.press('Escape');await page.mouse.up();
  }
  await visit('performance',320,'dark','&forty');await arrange();
  check('performance fixture 40 pulses',await page.locator('[data-arr-pulse]').count()===40);
  await page.emulateMedia({reducedMotion:'no-preference'});
  const baseline = await page.evaluate(()=>new Promise(resolve=>{const samples=[];let last;const start=performance.now();const step=t=>{if(last)samples.push(t-last);last=t;if(t-start<1200)requestAnimationFrame(step);else{samples.sort((a,b)=>a-b);resolve(samples[Math.floor(samples.length*.95)]||0);}};requestAnimationFrame(step);}));
  await page.evaluate(()=>{window.__frames=[];window.__rafActive=true;let previous=performance.now();const tick=now=>{window.__frames.push(now-previous);previous=now;if(window.__rafActive)requestAnimationFrame(tick);};requestAnimationFrame(tick);});
  await drag(grip(1),pulse(5),true,true);
  check('40-pulse frame sample uses an active drag',await page.locator('.pr-arr-indicator').isVisible());
  for(let i=0;i<30;i++){const r=await pulse(4).boundingBox();await page.mouse.move(r.x+30+(i%2)*90,r.y+10+(i%3)*8);await page.waitForTimeout(12);}
  await page.keyboard.press('Escape');await page.mouse.up();
  const perf=await page.evaluate(()=>{window.__rafActive=false;const a=window.__frames.slice(2).sort((a,b)=>a-b);return {frames:a.length,p95:a[Math.floor(a.length*.95)],max:Math.max(...a)};});
  perf.idleP95 = baseline;
  // Calibrate against the same browser's idle RAF: shared Windows/headless
  // scheduling can itself exceed 20ms. Retain both absolute measurements.
  perf.budget = Math.max(20, baseline + 8);
  fs.writeFileSync(path.join(out,'frame-times.json'),JSON.stringify(perf,null,2));
  check(`40-pulse drag p95 within max(20ms,idle+8ms) (${perf.p95?.toFixed(1)}ms drag, ${baseline.toFixed(1)}ms idle, ${perf.frames} frames)`,perf.frames>=20&&perf.p95<=perf.budget);
  await page.locator('.pr-shell').evaluate(e=>{e.style.height='360px';e.scrollTop=0;});
  const s=await grip(1).boundingBox(), edge=await page.locator('.pr-shell').boundingBox();
  await page.mouse.move(s.x+s.width/2,s.y+s.height/2);await page.mouse.down();await page.mouse.move(s.x+20,s.y+10);
  await page.mouse.move(edge.x+edge.width/2,edge.y+edge.height-8,{steps:8});await page.waitForTimeout(350);
  check('edge autoscroll advances short pane',await page.locator('.pr-shell').evaluate(e=>e.scrollTop>60));
  await page.keyboard.press('Escape');await page.mouse.up();
  await page.locator('.pr-shell').evaluate(e=>{e.style.height='';e.scrollTop=0;});
  await pulse(1).locator('.pr-trigger').press('Alt+ArrowDown');
  check('normal motion produces FLIP animation',await page.locator('.pr-arr-item').evaluateAll(es=>es.some(e=>e.getAnimations().length>0)));
  check('normal motion FLIP uses transform/opacity only',await page.locator('.pr-arr-item').evaluateAll(es=>es.flatMap(e=>e.getAnimations()).every(a=>a.effect.getKeyframes().every(k=>Object.keys(k).every(p=>['offset','easing','composite','computedOffset','transform','opacity'].includes(p))))));await idle();
  await page.waitForTimeout(220);
  await group('workspace').locator(':scope > .pr-group-head .pr-group-toggle').press('Alt+ArrowUp');
  check('whole group FLIP avoids double-animating its children',await group('workspace').evaluate(e=>e.getAnimations().length>0 && [...e.querySelectorAll('.pr-arr-item')].every(c=>c.getAnimations().length===0)));await idle();
  await visit('reserved',320,'dark','&sessions');await arrange();
  check('reserved sessions render inside reserved group',await group('hermes-sessions').locator('[data-arr-pulse^="session:"]').count()===2);
  check('sessions have no move handles',await group('hermes-sessions').locator('.pr-arr-actions').count()===0);
  await group('hermes-sessions').locator('.pr-trigger').first().press('Alt+ArrowDown');await idle();
  check('session keyboard moves stay locked',await page.evaluate(()=>window.__pulseRestCalls.filter(c=>c.method==='PUT').length===0));
  await move(1,'workspace');await pulse(1).getByRole('button',{name:/^Move .* to…$/}).click();
  check('ordinary pulses cannot target reserved group',await page.getByLabel('Move to…',{exact:true}).locator('option[value="hermes-sessions"]').count()===0);await page.getByRole('button',{name:'Cancel',exact:true}).click();
  await page.getByRole('button',{name:'Manage Hermes sessions',exact:true}).click();
  check('reserved group cannot ungroup/delete/nest',await page.getByRole('button',{name:'Ungroup',exact:true}).count()===0&&await page.getByRole('button',{name:'Delete group…',exact:true}).count()===0&&await page.getByRole('button',{name:'New subgroup',exact:true}).count()===0);
  await page.getByLabel('Group name',{exact:true}).fill('Chats');await page.getByRole('button',{name:'Rename',exact:true}).click();await idle();
  await collapse('hermes-sessions');check('renamed reserved group collapses to circles',await group('hermes-sessions').locator('.pr-circle').count()===2);
  await drag(group('hermes-sessions').getByRole('button',{name:'Drag group Chats',exact:true}),group('communities'),false);
  check('reserved group can be reordered',await page.locator('.pr-arrangement > .pr-group').first().getAttribute('data-group-id')==='hermes-sessions');
  await page.goto(`${origin}/?mode=hero&width=320&case=menu`);await page.locator('.pr-trigger').first().waitFor();
  await page.getByRole('button',{name:'Pulse options',exact:true}).click();await page.getByRole('button',{name:'Arrange pulses…',exact:true}).click();
  await page.getByRole('button',{name:'+ Group',exact:true}).waitFor({state:'visible'});
  check('untouched profiles expose arrangement via options',await page.getByRole('button',{name:'+ Group',exact:true}).isVisible());
  check('zero console errors/warnings',errors.length===0);check('zero remote requests',remote.length===0);
} catch(e) {failures.push(String(e.stack));console.error(e);await shot('failure');}
finally {
  fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({passed:checks.length-failures.filter(f=>checks.includes(f)).length,checks:checks.length,failures,errors,remote},null,2));
  await browser.close();
}
assert.equal(failures.length,0,failures.join('\n'));
console.log(`PASS ${checks.length} groups checks`);
