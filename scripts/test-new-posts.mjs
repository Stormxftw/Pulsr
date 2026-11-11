// New posts: a web.feed pulse shows what was published, not just how many. The collapsed row
// leads with the latest headline; the card lists the newest posts across the cell.
// Real engine and parser rows (qa-feed-status.py) -> real renderer; no network.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import {compatibleField,pause,review} from './builder2-test-helpers.mjs';
const req=createRequire(path.join(process.argv[2],'package.json'));
const {chromium}=req('playwright');
const origin=process.env.PULSE_PREVIEW_ORIGIN || 'http://127.0.0.1:5571';
const out=process.argv[3];fs.mkdirSync(out,{recursive:true});
const NOW=1794189600; // 2026-11-09 02:00 UTC
const rows=JSON.parse(execFileSync(process.env.PULSE_BUILDER_PYTHON || 'python',['scripts/qa-feed-status.py'],{encoding:'utf8'}));
const busy=rows.find(p=>p.id==='posts-busy');
// The same reading from a backend that predates new-posts cells: no `posts` field.
const older={...structuredClone(busy),id:'posts-older',title:'Older backend · releases'};delete older.posts;
// A backend is never trusted with markup or link schemes: this row bypasses the parser on purpose.
const hostile=structuredClone(busy);hostile.id='posts-hostile';hostile.title='Hostile · feed';
hostile.posts.posts[0]={...hostile.posts.posts[0],title:'<img src=x onerror="window.__pwned=1"> <b>bold</b> &amp; text',link:'javascript:window.__pwned=2'};
hostile.posts.posts[1]={...hostile.posts.posts[1],link:'http://plain.example/post'};
const browser=await chromium.launch({channel:'msedge',headless:true});
const page=await browser.newPage({viewport:{width:900,height:2600},timezoneId:'UTC',locale:'en-US',reducedMotion:'reduce'});
const checks=[],errors=[],remote=[];
const check=(name,value)=>{assert.ok(value,name);checks.push(name);console.log('PASS '+name);};
page.on('pageerror',e=>errors.push(String(e)));
page.on('console',m=>{if(['error','warning'].includes(m.type())&&!m.text().includes('[vite]'))errors.push(m.text());});
await page.route('**/*',r=>{if(/^https?:/.test(r.request().url())&&!r.request().url().startsWith(origin+'/')){remote.push(r.request().url());return r.abort();}return r.continue();});
await page.route('**/ui-fixture/hero',async r=>{const response=await r.fetch();const seed=await response.json();seed.pulses=[...structuredClone(rows),structuredClone(older),structuredClone(hostile)];seed.drafts=[];seed.as_of=NOW;await r.fulfill({json:seed});});
// One retry: the first navigation after a cold preview-server start can exceed the timeout.
const visit=async(width,theme='dark')=>{for(let attempt=0;;attempt++){try{await page.goto(`${origin}/?mode=hero&width=${width}&theme=${theme}&case=rows`);await page.locator('.pr-row').first().waitFor();return;}catch(error){if(attempt)throw error;}}};
const row=id=>page.locator(`[data-id="${id}"]`);
// Visible text on one line; the separator dot is normalised because flex items break lines in innerText.
const words=async locator=>(await locator.innerText()).replace(/\s+/g,' ').replace(/ ?· ?/g,' · ').trim();
// Rows are opened one at a time: the pane keeps a single row expanded.
const open=async id=>{const trigger=row(id).locator('.pr-trigger');if(await trigger.getAttribute('aria-expanded')!=='true'){await trigger.click();await row(id).locator('.pr-details').waitFor();}await page.mouse.move(880,2500);await page.waitForTimeout(200);};
const box=locator=>locator.evaluate(node=>{const r=node.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height};});
// Text drawn wider than its box, to the fraction of a pixel (scrollWidth rounds).
const clipped=locator=>locator.evaluateAll(nodes=>nodes.filter(node=>{const range=document.createRange();range.selectNodeContents(node);const text=range.getBoundingClientRect(),b=node.getBoundingClientRect();return text.width>0&&(text.right>b.right+0.5||text.left<b.left-0.5);}).map(node=>node.className+': '+node.textContent));
const contrast=locator=>locator.evaluate(el=>{
  const rgb=value=>{const pen=document.createElement('canvas').getContext('2d',{willReadFrequently:true});pen.fillStyle='#000';pen.fillStyle=value;pen.fillRect(0,0,1,1);return [...pen.getImageData(0,0,1,1).data];};
  const lum=([r,g,b])=>{const f=v=>{v/=255;return v<=0.03928?v/12.92:((v+0.055)/1.055)**2.4;};return 0.2126*f(r)+0.7152*f(g)+0.0722*f(b);};
  const over=(top,under)=>{const a=top[3]/255;return [0,1,2].map(i=>top[i]*a+under[i]*(1-a));};
  let bg=[0,0,0,0];for(let e=el;e;e=e.parentElement){const c=rgb(getComputedStyle(e).backgroundColor);if(c[3]){bg=bg[3]?[...over(bg,c),255]:c;if(c[3]===255)break;}}
  if(!bg[3])bg=[255,255,255,255];const ink=over(rgb(getComputedStyle(el).color),bg),hi=Math.max(lum(ink),lum(bg)),lo=Math.min(lum(ink),lum(bg));return (hi+0.05)/(lo+0.05);});
try{
  await visit(320);
  // --- the collapsed row says what was posted ---
  const line=row('posts-busy').locator('.pr-trigger .pr-posts-line');
  check('busy: the row leads with the count of new posts and the latest headline',/^2 new · Lantern 2\.4: offline mode/.test(await words(line)));
  check('busy: the headline stays on one line and is cut with an ellipsis',(await box(line)).height<=20&&await line.locator('.pr-posts-latest').evaluate(e=>e.scrollWidth>e.clientWidth&&getComputedStyle(e).textOverflow==='ellipsis'));
  check('busy: the headline uses the row, not a corner of it',(await box(line)).width>=(await box(row('posts-busy').locator('.pr-trigger'))).width*0.6);
  check('busy: the full headline is in the tooltip',(await line.locator('.pr-posts-latest').getAttribute('title')).endsWith('for every platform'));
  check('busy: a pill on the title line counts new posts',await words(row('posts-busy').locator('.pr-inbox-count'))==='2'&&/2 new posts in the last 24 hours/.test(await row('posts-busy').locator('.pr-inbox-count').getAttribute('title')));
  check('busy: no change score on a posts row',!/Change \d+\/100/.test(await words(row('posts-busy').locator('.pr-trigger'))));
  check('busy: the accessible name carries the same reading',/2 new posts; latest 2h 10m ago/.test(await row('posts-busy').locator('.pr-trigger').getAttribute('aria-label')));
  check('quiet: without new posts the row gives the age of the last one and its headline',await words(row('posts-quiet').locator('.pr-trigger .pr-posts-line'))==='3d 2h ago · What we learned moving the workshop');
  check('quiet: no pill',await row('posts-quiet').locator('.pr-inbox-count').count()===0);
  check('undated: a feed without dates counts posts and still shows the headline',await words(row('posts-undated').locator('.pr-trigger .pr-posts-line'))==='2 posts · Faster search');
  check('empty: an empty feed says so',await words(row('posts-empty').locator('.pr-trigger .pr-posts-line'))==='No posts yet');
  check('posts rows ask for no attention',await page.locator('.pr-row[data-id^="posts-"][data-attention="notice"]').count()===0);
  await page.screenshot({path:path.join(out,'collapsed-320.png'),clip:{x:0,y:0,width:900,height:520}});
  // --- the card lists the newest posts across the cell ---
  await open('posts-busy');
  const card=row('posts-busy').locator('.pr-details .pr-posts');
  check('card: headline is the count of new posts',await words(card.locator('.pr-posts-head'))==='2 new in the last 24 hours');
  const items=card.locator('.pr-posts-list > li');
  check('card: six posts are listed, newest first',await items.count()===6&&(await words(items.nth(1))).startsWith('New: Lantern 2.3.2 fixes a crash on startup'));
  check('card: posts from the last 24 hours are marked',JSON.stringify(await items.evaluateAll(n=>n.map(e=>e.dataset.new)))===JSON.stringify(['true','true','false','false','false','false']));
  check('card: ages read 2h, 19h, 3d, 5d, 9d, 2w',JSON.stringify(await card.locator('.pr-post-age').allInnerTexts())===JSON.stringify(['2h','19h','3d','5d','9d','2w']));
  const list=await box(card.locator('.pr-posts-list'));
  const ages=await card.locator('.pr-post-age').evaluateAll(n=>n.map(e=>e.getBoundingClientRect().right));
  check('card: ages form a column at the right edge',ages.every(right=>Math.abs(right-list.right)<=1));
  const titles=await card.locator('.pr-post-title').evaluateAll(n=>n.map(e=>e.getBoundingClientRect().width));
  check(`card: titles take the width of the cell (${Math.round(Math.min(...titles))}px of ${Math.round(list.width)}px)`,titles.every(w=>w>=list.width*0.75));
  const first=card.locator('.pr-post-title').first();
  const clamp=await first.evaluate(e=>({line:parseFloat(getComputedStyle(e).lineHeight),height:e.getBoundingClientRect().height,full:e.scrollHeight}));
  check('card: a long title wraps onto a second line instead of being cut at one',clamp.height>clamp.line*1.5&&clamp.height<=clamp.line*2+1);
  check('card: an https post is a button; an http one is plain text',await items.nth(0).locator('button.pr-post').count()===1&&await items.nth(3).locator('button').count()===0&&(await words(items.nth(3))).startsWith('Lantern 2.3: shared folders'));
  await items.nth(1).locator('button.pr-post').click();
  await page.mouse.move(880,2500); // leave no hover state in the captures
  check('card: a post opens its own https link in the browser',await page.evaluate(()=>window.__pulseExternal)==='https://lantern.example/releases/2-3-2');
  check('card: the tooltip names the host it opens',/opens lantern\.example$/.test(await items.nth(1).locator('button.pr-post').getAttribute('title')));
  check('card: the foot gives the week, the feed size and the feed title',await words(card.locator('.pr-posts-foot'))==='4 this week · 12 in the feed · Lantern releases');
  check('card: it replaces the trend, lines and usual-sentence',await row('posts-busy').locator('.pr-details .pr-spark, .pr-details .pr-trend, .pr-details .pr-normal').count()===0&&(await row('posts-busy').locator('.pr-details .pr-lines').innerText()).trim()==='');
  check('card: titles and ages are readable',await contrast(first)>=4.5&&await contrast(card.locator('.pr-post-title').nth(3))>=4.5&&await contrast(card.locator('.pr-post-age').first())>=4.5);
  await row('posts-busy').screenshot({path:path.join(out,'busy-320.png')});
  await open('posts-quiet');
  const quiet=row('posts-quiet').locator('.pr-details .pr-posts');
  check('quiet card: says nothing is new and when the last post was',await words(quiet.locator('.pr-posts-head'))==='No new posts · last 3d 2h ago');
  check('quiet card: nothing is marked new; a feed shown in full does not repeat its size',await quiet.locator('li[data-new="true"]').count()===0&&await words(quiet.locator('.pr-posts-foot'))==='1 this week · Harbor & Pine journal');
  await row('posts-quiet').screenshot({path:path.join(out,'quiet-320.png')});
  await open('posts-undated');
  const undated=row('posts-undated').locator('.pr-details .pr-posts');
  check('undated card: says the feed carries no dates and shows no ages',await words(undated.locator('.pr-posts-head'))==='2 posts · this feed carries no dates'&&await undated.locator('.pr-post-age').count()===0&&await undated.locator('.pr-posts-list > li').count()===2);
  await open('posts-empty');
  const empty=row('posts-empty').locator('.pr-details .pr-posts');
  check('empty card: one line, no list',await words(empty.locator('.pr-posts-head'))==='No posts yet'&&await empty.locator('.pr-posts-list').count()===0);
  // --- a designed pulse keeps its blocks; the list follows them ---
  await open('posts-designed');
  const designed=row('posts-designed');
  check('designed: the row still leads with the headline',/^2 new · Lantern 2\.4/.test(await words(designed.locator('.pr-trigger .pr-posts-line'))));
  check('designed: its own blocks come first and the list follows without a second headline',await designed.locator('.pr-details .pr-display .pr-block[data-type="stat"]').count()===2&&await designed.locator('.pr-details .pr-posts-head').count()===0
    &&(await box(designed.locator('.pr-details .pr-posts'))).top>=(await box(designed.locator('.pr-details .pr-display'))).bottom-1&&await designed.locator('.pr-details .pr-posts-list > li').count()===6);
  await designed.screenshot({path:path.join(out,'designed-320.png')});
  // --- untrusted text and links ---
  await open('posts-hostile');
  const bad=row('posts-hostile');
  check('hostile: markup in a title is drawn as text',await bad.locator('.pr-posts img, .pr-posts b, .pr-trigger img[src="x"]').count()===0&&(await bad.locator('.pr-post-title').first().innerText()).includes('<img src=x onerror="window.__pwned=1"> <b>bold</b> &amp; text'));
  check('hostile: a javascript: or http: link is never clickable',await bad.locator('.pr-posts-list > li').nth(0).locator('button').count()===0&&await bad.locator('.pr-posts-list > li').nth(1).locator('button').count()===0);
  check('hostile: nothing ran',await page.evaluate(()=>window.__pwned)===undefined);
  // --- an older backend is unchanged ---
  check('older backend: the row renders as a plain metric',await row('posts-older').locator('.pr-posts-line').count()===0&&/2 new · 24h/.test(await words(row('posts-older').locator('.pr-trigger'))));
  await open('posts-older');
  check('older backend: no posts card',await row('posts-older').locator('.pr-details .pr-posts').count()===0);
  // --- widths and themes ---
  for(const [width,theme] of [[231,'dark'],[400,'dark'],[320,'light']]){
    await visit(width,theme);
    const tag=`${width} ${theme}`;
    check(`${tag}: collapsed rows fit`,(await clipped(page.locator('.pr-row[data-id^="posts-"] .pr-posts-lead'))).length===0&&await page.locator('.pr-shell').evaluate(e=>e.scrollWidth<=e.clientWidth+1));
    check(`${tag}: collapsed headline is one line`,(await box(row('posts-busy').locator('.pr-trigger .pr-posts-line'))).height<=20);
    for(const id of ['posts-busy','posts-designed','posts-quiet']){
      await open(id);
      const details=row(id).locator('.pr-details');
      check(`${tag}: ${id} card fits`,(await clipped(details.locator('.pr-posts-head, .pr-posts-head strong, .pr-post-age, .pr-posts-foot > span'))).length===0&&await page.locator('.pr-shell').evaluate(e=>e.scrollWidth<=e.clientWidth+1));
      check(`${tag}: ${id} titles stay inside the cell`,await details.locator('.pr-post-title').evaluateAll(n=>n.every(e=>{const lh=parseFloat(getComputedStyle(e).lineHeight);return e.clientHeight<=lh*2+1&&e.getBoundingClientRect().right<=e.closest('.pr-posts-list').getBoundingClientRect().right+0.5;})));
      if(id==='posts-busy'&&width===231){
        const tight=await details.locator('.pr-post-title').first().evaluate(e=>({line:parseFloat(getComputedStyle(e).lineHeight),height:e.getBoundingClientRect().height,full:e.scrollHeight}));
        check('231 dark: a title too long for two lines is cut at two',tight.height<=tight.line*2+1&&tight.full>tight.height+4);
      }
      if(id==='posts-busy'){
        check(`${tag}: titles and ages are readable`,await contrast(details.locator('.pr-post-title').first())>=4.5&&await contrast(details.locator('.pr-post-title').nth(3))>=4.5&&await contrast(details.locator('.pr-post-age').first())>=4.5&&await contrast(details.locator('.pr-posts-foot'))>=4.5);
        await row(id).screenshot({path:path.join(out,`busy-${width}-${theme}.png`)});
      }
    }
  }
  // --- the builder offers it; nothing is fetched before approval ---
  await page.goto(`${origin}/?mode=builder&width=320&theme=dark`);
  await page.getByRole('button',{name:'New pulse',exact:true}).click();
  const releases=page.locator('.pr-b2-template').filter({has:page.getByText('GitHub releases',{exact:true})});
  await releases.waitFor();await releases.click();
  await compatibleField(page,'/template/repo').fill('NousResearch/hermes-agent');await pause(page);
  check('builder: GitHub releases takes a repository name and says which host it will read',/main: New posts · github\.com · every 30 minutes/.test(await page.locator('.pr-b2-controls').innerText())&&await page.getByRole('button',{name:'Next',exact:true}).isEnabled());
  await page.getByRole('button',{name:'Change template',exact:true}).click();
  const tile=page.locator('.pr-b2-template').filter({has:page.getByText('New posts (RSS / Atom)',{exact:true})});
  await tile.waitFor();
  check('builder: New posts is offered among the first sources, not under More sources',await tile.evaluate(e=>!e.closest('details')));
  await tile.click();
  const form=await page.locator('.pr-b2-controls').innerText();
  check('builder: the form says titles are shown, not sent to the model, and that it fetches nothing',form.includes('Post titles are shown in the pane and never sent to the model')&&form.includes('never fetches the address'));
  await compatibleField(page,'/template/url').fill('http://example.org/feed.xml');await pause(page);
  check('builder: a plain http address is refused',await page.getByRole('button',{name:'Next',exact:true}).isDisabled());
  await compatibleField(page,'/template/url').fill('https://example.org/feed.xml');await pause(page);
  await page.getByRole('button',{name:'Next',exact:true}).click();
  await page.locator('.pr-builder-preview .pr-block').first().waitFor({state:'attached'});
  check('builder: the preview is labelled as a sample',await page.locator('.pr-builder-watermark').isVisible());
  await page.screenshot({path:path.join(out,'builder-posts.png'),clip:{x:0,y:0,width:900,height:900}});
  await review(page);
  const approval=await page.locator('.pr-builder-review .pr-approval').innerText();
  const wanted=['example.org','2 req/h','post titles','never sent to the model'];
  check('approval: names the host, the rate and what is shown'+(wanted.every(t=>approval.includes(t))?'':' — missing '+wanted.filter(t=>!approval.includes(t)).join(', ')+' in: '+approval.replace(/\s+/g,' ').slice(0,900)),wanted.every(t=>approval.includes(t)));
  check('approval: the draft is a web.feed pulse on the default 30 minute cadence',await page.evaluate(()=>{const d=window.__pulseStatus.drafts.at(-1).definition;const f=Object.values(d.feeds)[0];return f.kind==='web.feed'&&f.params.url==='https://example.org/feed.xml'&&f.every==='30m';}));
  check('approval: nothing was fetched and nothing was approved',await page.evaluate(()=>window.__pulseStatus.drafts.at(-1).preview_calls===0&&!window.__pulseRestCalls.some(c=>c.path.endsWith('/approve'))));
  await page.screenshot({path:path.join(out,'review-posts.png'),clip:{x:0,y:0,width:900,height:1400}});
  check('no remote requests',remote.length===0);
  check('no runtime warnings',errors.length===0);
  fs.writeFileSync(path.join(out,'new-posts-results.json'),JSON.stringify({checks,errors,remote},null,2));
  console.log(`${checks.length} new-posts browser checks passed`);
}finally{if(errors.length)console.log('ERRORS '+JSON.stringify(errors).slice(0,600));await browser.close();}
