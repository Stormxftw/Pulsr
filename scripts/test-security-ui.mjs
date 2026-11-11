// Review-3 exploits, exercised through real pending/transcript/active components.
import assert from 'node:assert/strict';
import {authoring, review, applyDefinition} from './builder2-test-helpers.mjs';
import {createRequire} from 'node:module';
import path from 'node:path';
import fs from 'node:fs';
const req = createRequire(path.join(process.argv[2], 'package.json'));
const {chromium} = req('playwright');
const {PNG} = req('pngjs');
const samePixels = (a,b) => {const x=PNG.sync.read(a),y=PNG.sync.read(b);return x.width===y.width&&x.height===y.height&&x.data.every((v,i)=>Math.abs(v-y.data[i])<=2);};
const out = process.argv[3]; fs.mkdirSync(out, {recursive:true});
const origin = process.env.PULSE_PREVIEW_ORIGIN || 'http://127.0.0.1:5291';
const browser = await chromium.launch({channel:'msedge',headless:true});
const page = await browser.newPage({viewport:{width:800,height:2000},reducedMotion:'reduce'});
const checks=[], failures=[], errors=[], remote=[];
page.on('pageerror', e=>errors.push(String(e)));
page.on('console', message=>{if(['error','warning'].includes(message.type()))errors.push(message.text());});
await page.route('**/*',r=>{if(/^https?:/.test(r.request().url())&&!r.request().url().startsWith(origin+'/')){remote.push(r.request().url());return r.abort();}return r.continue();});
const check=(name,value)=>{checks.push(name);if(!value)failures.push(name);console.log(`${value?'PASS':'FAIL'} ${name}`);};
const visit=async query=>{await page.goto(origin+'/?'+query);await page.locator('.pr-approval,.pr-row').first().waitFor();};
const http={kind:'http_json',every:'5m',params:{url:'https://example.org/sensitive/export?all=true',metrics:{count:'/count'}}};
const connector={kind:'mcp.tool',every:'15m',params:{server:'private',tool:'read_data',args:{padding:'x'.repeat(600),tail:'<not-hidden>'},metrics:{count:'/count'}}};
const row=(name,f,req,hosts,target)=>({name,...f,req_per_hour:req,hosts,target,...(f.kind==='mcp.tool'?{mcp:{server:f.params.server,tool:f.params.tool,read_only:true,reason:null,args_full:JSON.stringify(f.params.args),transport:'via Hermes MCP connector (Hermes handles sign-in)'}}:{})});
const base={definition:{pulse:1,id:'review-approval',title:'Mixed endpoint review',icon:{url:'https://icons.example.org/p.png'},feeds:{http,connector},display:[{type:'bar',value:'http.count'}]},preview:null,preview_state:'after_approval',preview_calls:0,budget:{hosts:['example.org','icons.example.org'],req_per_hour:16},disclosure:{feeds:[row('http',http,12,['example.org'],http.params.url),row('connector',connector,4,[],'private/read_data')],icon_hosts:['icons.example.org']}};
const install=async(d)=>{await page.evaluate(d=>{Object.assign(window.__pulseStatus.drafts[0],d);window.__emitPulse('draft.updated');},d);await page.waitForTimeout(160);};
try {
  // The original probe's mixed, unsampled draft; all surfaces share the gate.
  for(const surface of ['pending','expanded','transcript']) {
    await visit('mode=pending&width=320'+(surface==='transcript'?'&card':''));await install(base);
    if(surface==='expanded')await page.locator('.pr-pending .pr-trigger').first().click();
    const card=page.locator('.pr-approval').first(); const text=await card.innerText();
    for(const token of ['http','http_json',http.params.url,'5m','12 req/h','connector','mcp.tool','private','read_data','15m','4 req/h','read-only','16 req/h','icons.example.org'])check(surface+' disclosure '+token,text.includes(token));
    check(surface+' approve enabled',!await card.getByRole('button',{name:'Approve',exact:true}).isDisabled());
    const full=card.getByText('Show full args',{exact:true});check(surface+' explicit full args expander',await full.count()===1);
    if(await full.count()){await full.click();check(surface+' full tail visible',(await card.innerText()).includes('<not-hidden>'));check(surface+' args are text',await card.locator('not-hidden').count()===0);}
  }
  for (const [name,feed,rate,hosts,target] of [['http',http,12,['example.org'],http.params.url],['connector',connector,4,[],'private/read_data']]) {
    await visit('mode=pending&width=320'); const d=structuredClone(base); d.definition.feeds={[name]:feed};d.disclosure.feeds=[row(name,feed,rate,hosts,target)];d.budget={hosts:[...hosts,'icons.example.org'],req_per_hour:rate};await install(d);
    const card=page.locator('.pr-approval').first();check(name+' only no-preview exact target',(await card.innerText()).includes(target));check(name+' only approve enabled',!await card.getByRole('button',{name:'Approve',exact:true}).isDisabled());
  }
  // A non-hero MCP feed must never inherit another feed's positive badge.
  await visit('mode=pending&width=320');
  const two=structuredClone(base);two.definition.feeds.second=structuredClone(connector);two.definition.feeds.second.params.server='other';two.definition.feeds.second.every='30m';two.disclosure.feeds.push(row('second',two.definition.feeds.second,2,[],'other/read_data'));two.disclosure.feeds[2].mcp.read_only=false;two.budget.req_per_hour=18;await install(two);
  check('second MCP independent policy gate',await page.locator('.pr-approval').getByRole('button',{name:'Approve',exact:true}).isDisabled());
  check('second MCP independent badge',(await page.locator('.pr-approval').innerText()).includes('other / read_data · policy unavailable'));
  // Builder handoff uses the same complete card, including long args.
  for(const tool of ['read_counts','write_counts']) {
    await visit('mode=builder&width=900');await authoring(page);

    const def=structuredClone(base.definition);def.id='builder-security';def.feeds.connector.params.server='probe';def.feeds.connector.params.tool=tool;
    await applyDefinition(page,def);
    await review(page);const card=page.locator('.pr-builder-review .pr-approval');await card.waitFor();const text=await card.innerText();
    for(const token of [http.params.url,'http_json','5m','12 req/h','mcp.tool','15m','4 req/h',tool,'icons.example.org'])check('builder '+tool+' '+token,text.includes(token));
    check('builder '+tool+' policy gate',await card.getByRole('button',{name:'Approve',exact:true}).isDisabled()===(tool==='write_counts'));
    await card.getByText('Show full args',{exact:true}).click();check('builder '+tool+' full args visible',(await card.innerText()).includes('<not-hidden>'));
  }
  // Every supported source has its exact target and source parameters.
  const kinds=[['github.repo',{repo:'NousResearch/hermes-agent'},'15m',8,['api.github.com'],'NousResearch/hermes-agent'],['github.search',{repo:'NousResearch/hermes-agent',type:'pr',title_contains:'security',label:'bug',window:'24h'},'15m',4.166666666666667,['api.github.com'],'NousResearch/hermes-agent'],['discord.invite',{invite:'nousresearch',voice:false},'10m',6,['discord.com','cdn.discordapp.com'],'nousresearch'],['hermes.activity',{scope:'profile'},'30s',0,[],'this profile']];
  for(const [kind,params,every,rate,hosts,target] of kinds){
    await visit('mode=pending&width=320');const f={kind,params,every};const d=structuredClone(base);d.definition.feeds={main:f};d.disclosure={feeds:[row('main',f,rate,hosts,target)],icon_hosts:['icons.example.org']};d.budget={hosts:[...hosts,'icons.example.org'],req_per_hour:rate};await install(d);
    const card=page.locator('.pr-approval').first();const text=await card.innerText();for(const token of [kind,target,every,...Object.values(params).map(String)])check(kind+' '+token,text.includes(token));check(kind+' approve enabled',!await card.getByRole('button',{name:'Approve',exact:true}).isDisabled());
  }
  const invalid={missingDisclosure:d=>delete d.disclosure,missingFeed:d=>d.disclosure.feeds.pop(),missingTarget:d=>delete d.disclosure.feeds[0].target,missingParams:d=>delete d.disclosure.feeds[0].params,malformedFeeds:d=>d.disclosure.feeds={},nullFeed:d=>d.disclosure.feeds[0]=null,unknownCadence:d=>{d.definition.feeds.http.every='unknown';d.disclosure.feeds[0].every='unknown';},missingKind:d=>delete d.disclosure.feeds[0].kind,missingCadence:d=>delete d.disclosure.feeds[0].every,missingRate:d=>delete d.disclosure.feeds[0].req_per_hour,unknownRate:d=>d.disclosure.feeds[0].req_per_hour=null,missingHosts:d=>delete d.disclosure.feeds[0].hosts,hiddenHttpHost:d=>{d.disclosure.feeds[0].hosts=[];d.budget.hosts=['icons.example.org'];},hiddenIconHost:d=>{d.disclosure.icon_hosts=[];d.budget.hosts=['example.org'];},duplicateFeed:d=>d.disclosure.feeds[1]=structuredClone(d.disclosure.feeds[0]),missingBudget:d=>delete d.budget,missingIconHosts:d=>delete d.disclosure.icon_hosts,policyMissing:d=>delete d.disclosure.feeds[1].mcp,policyFalse:d=>d.disclosure.feeds[1].mcp.read_only=false,policyUnknown:d=>delete d.disclosure.feeds[1].mcp.read_only,policyNotBoolean:d=>d.disclosure.feeds[1].mcp.read_only=1,missingFullArgs:d=>delete d.disclosure.feeds[1].mcp.args_full,changedParams:d=>d.disclosure.feeds[0].params={url:'https://else.example.org'},unknownKind:d=>d.disclosure.feeds[0].kind='unknown',wrongTotal:d=>d.budget.req_per_hour=1};
  for(const [name,mutate] of Object.entries(invalid)) {await visit('mode=pending&width=320');const d=structuredClone(base);mutate(d);await install(d);const card=page.locator('.pr-approval').first();check('fail closed '+name,await card.getByRole('button',{name:'Approve',exact:true}).isDisabled());check('reason '+name,/cannot approve/i.test(await card.innerText()));}
  // Exhaustive-token numeric parser matrix, including the exact review probes.
  await visit('mode=blocks&width=320&css');
  const bad=['box-shadow:0 0 0 1e9px red','box-shadow:0 0 0 999999Q red;filter:brightness(1)','box-shadow:0 0 99999px 64px red','box-shadow:0 0 0 10vw red','text-shadow:0 1e9px 0 red','filter:drop-shadow(1e9px 0 0 red)','filter:drop-shadow(0 0 999999Q red)','filter:'+Array(8).fill('drop-shadow(0 0 64px red)').join(' '),'margin:-999px','margin:1Q','padding:1vh','margin:100%','padding:100%','box-shadow:0 0 10% red','filter:drop-shadow(0 0 10vw red)','letter-spacing:1e2px','font-size:999rem','border-width:1e2px','padding:calc(1px + 2px)','padding:min(1px,2px)','margin:var(--x)','box-shadow:0 0 0 1/**/e9px red','box-shadow:0 0 0 1e1px red','padding:1e1px','font-size:2em','outline-offset:999999px'];
  for(const declaration of bad){const value=await page.evaluate(v=>window.__sanitizePulseCss('.pr-block {'+v+'}'),declaration);check('reject '+declaration,!value.includes(declaration.split(':')[0]+':'));}
  for(const declaration of ['color:#1e9','box-shadow:0 0 12px 4px red','text-shadow:1px 2px 3px rgb(1, 2, 3)','filter:drop-shadow(1px 2px 3px red) brightness(1)','padding:4px 8px','font-size:24px'])check('accept '+declaration,!!await page.evaluate(v=>window.__sanitizePulseCss('.pr-block {'+v+'}'),declaration));
  const reviewRules = [
    '.pr-block {background-image:image-set("https://evil.invalid/a.png" 1x)}',
    '.pr-block {background-image:-webkit-image-set(url(https://evil.invalid/a.png) 1x)}',
    '.pr-block {fill:src("https://evil.invalid/a")}',
    '.pr-block:has(.pr-approval) {color:red}',
    '.pr-block [data-slot] {color:red}',
    '.pr-block > button {color:red}',
    '.pr-block {color:r\\65 d}',
    '@media all {.pr-block{color:red}}',
    '.pr-block{color:red}'+' '.repeat(65537),
  ];
  for(const [i,css] of reviewRules.entries())check('review rule refused '+i,!await page.evaluate(v=>window.__sanitizePulseCss(v),css));
  const active=await page.evaluate(()=>window.__pulseStatus.pulses.find(p=>p.id==='synthetic-ebay'));
  for(const theme of ['dark','light']){
    await visit('mode=pending&width=320&css&theme='+theme);await page.evaluate(active=>{window.__pulseStatus.pulses.push(active);window.__emitPulse('draft.updated');},active);await page.waitForTimeout(180);await page.locator('.pr-pending .pr-trigger').first().click();
    await page.addStyleTag({content:'.preview-frame {height:1500px!important} *,*::before,*::after {animation:none!important;transition:none!important}'});
    await page.evaluate(()=>{document.querySelector('style[data-pulse-rings-custom]').textContent='';});
    const card=page.locator('.pr-approval').first();await card.scrollIntoViewIfNeeded();
    // Floor the bottom edge: ceil included a one-pixel strip of the adjacent
    // pending-row outline, whose subpixel antialiasing fluctuates on repaint.
    // Card interior, full buttons, hit targets and raw paint attacks stay tested.
    const clipFor=async locator=>locator.evaluate(e=>{const r=e.getBoundingClientRect();return {x:Math.floor(r.x),y:Math.floor(r.y),width:Math.ceil(r.right)-Math.floor(r.x),height:Math.floor(r.bottom)-Math.floor(r.y)};});
    const clip=await clipFor(card);const buttonClips=await Promise.all(['Approve','Reject'].map(name=>clipFor(card.getByRole('button',{name,exact:true}))));
    const capture=()=>page.screenshot({clip});
    const baseline=await page.screenshot({clip,path:path.join(out,theme+'-before.png')});
    const buttons=await Promise.all(buttonClips.map(clip=>page.screenshot({clip})));
    const attacks=[...bad,'box-shadow:'+Array(4).fill('0 0 64px 64px red').join(',' )+';filter:brightness(1)','margin:-8px;box-shadow:0 0 64px 64px red;filter:drop-shadow(0 0 64px red)','outline:999999px solid red;outline-offset:-999999px'];
    const payloads=[...attacks.map(decl=>'.pr-block {'+decl+'}'),...reviewRules];
    for(const [i,css] of payloads.entries()){
      await page.evaluate(v=>{document.querySelector('style[data-pulse-rings-custom]').textContent=window.__sanitizePulseCss(v);},css);
      const after=await capture();const unchanged=samePixels(baseline,after);if(!unchanged)fs.writeFileSync(path.join(out,`${theme}-failure-${i}.png`),after);check(theme+' approval pixels '+i,unchanged);
      for(const [j,name] of ['Approve','Reject'].entries()){const button=card.getByRole('button',{name,exact:true});check(theme+' '+name+' pixels '+i,samePixels(buttons[j],await page.screenshot({clip:buttonClips[j]})));check(theme+' '+name+' clickable '+i,await button.evaluate(e=>{const r=e.getBoundingClientRect();return e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));}));}
    }
    // Bypass the parser in this test only: independently prove containment of
    // the review's original paint payload even if a future value guard regresses.
    for(const [i,decl] of ['box-shadow:0 0 0 1e9px red','box-shadow:0 0 0 999999Q red;filter:brightness(1)','box-shadow:0 0 0 999999px red;filter:drop-shadow(0 0 999999px red)'].entries()) {
      await page.evaluate(v=>{document.querySelector('style[data-pulse-rings-custom]').textContent='.pr-shell .pr-pulse:not(.pr-pending) .pr-block {'+v+'}';},decl);
      check(theme+' raw paint containment '+i,samePixels(baseline,await capture()));
      for(const [j,name] of ['Approve','Reject'].entries())check(theme+' raw '+name+' pixels '+i,samePixels(buttons[j],await page.screenshot({clip:buttonClips[j]})));
    }
    await page.screenshot({clip,path:path.join(out,theme+'-after.png')});
    await page.screenshot({path:path.join(out,theme+'-mixed-scene.png'),fullPage:true});
    check(theme+' consent stacking and solid background',await card.evaluate(e=>{const s=getComputedStyle(e),p=getComputedStyle(e.closest('.pr-pending'));const opaque=color=>{const canvas=document.createElement('canvas');canvas.width=canvas.height=1;const c=canvas.getContext('2d');c.fillStyle=color;c.fillRect(0,0,1,1);return c.getImageData(0,0,1,1).data[3]===255;};return s.position==='relative'&&s.isolation==='isolate'&&s.zIndex==='1'&&opaque(s.backgroundColor)&&p.position==='relative'&&p.isolation==='isolate'&&p.zIndex==='1'&&opaque(p.backgroundColor);}));
    check(theme+' paint boundaries',await page.locator('.pr-pulse,.pr-block').evaluateAll(es=>es.length>0&&es.every(e=>getComputedStyle(e).contain.includes('paint')&&getComputedStyle(e).isolation==='isolate')));
  }
  check('no runtime errors',errors.length===0);check('no remote requests',remote.length===0);
} finally {fs.writeFileSync(path.join(out,'security-results.json'),JSON.stringify({checks:checks.length,failures,errors,remote},null,2));await browser.close();}
assert.equal(failures.length,0,failures.join('\n'));
