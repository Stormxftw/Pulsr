// Refs #98: the approval card's Parameters line breaks between parameters, not inside them.
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
const page = await browser.newPage({viewport:{width:1280,height:1100}});
const checks=[], errors=[], remote=[];
page.on('pageerror', e=>errors.push(String(e)));
page.on('console',m=>{if(['error','warning'].includes(m.type())&&!m.text().includes('[vite]'))errors.push(m.text());});
page.on('request',r=>{if(/^https?:/.test(r.url())&&!r.url().startsWith(origin+'/'))remote.push(r.url());});
await page.route('**/*',route=>/^https?:/.test(route.request().url())&&!route.request().url().startsWith(origin+'/')?route.abort():route.continue());
const check=(name,value)=>{assert.ok(value,name);checks.push(name);console.log('PASS '+name);};
// One retry: the first navigation after a cold preview-server start can exceed the timeout.
const visit=async(mode,theme='dark')=>{for(let attempt=0;;attempt++){try{await page.goto(`${origin}/?mode=${mode}&width=320&theme=${theme}`);await page.locator('.pr-approval').first().waitFor();await page.waitForTimeout(300);return;}catch(error){if(attempt)throw error;}}};
// How each Parameters line is laid out: its text, its lines, the lines that end inside a
// word, and whether every host and repository value sits whole on one line.
const layout=()=>page.evaluate(()=>[...document.querySelectorAll('.pr-feed-disclosure p')].filter(p=>p.textContent.startsWith('Parameters: ')).map(p=>{
  const text=p.textContent,object=JSON.parse(text.slice('Parameters: '.length));
  const sorted=value=>JSON.stringify(value,(key,v)=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.keys(v).sort().map(k=>[k,v[k]])):v);
  const lines=[];let last=null,node;const walker=document.createTreeWalker(p,NodeFilter.SHOW_TEXT);
  while((node=walker.nextNode()))for(let i=0;i<node.length;i++){const r=document.createRange();r.setStart(node,i);r.setEnd(node,i+1);const top=Math.round(r.getBoundingClientRect().top);if(top!==last){lines.push('');last=top;}lines[lines.length-1]+=node.data[i];}
  const box=p.getBoundingClientRect();
  const strings=[];JSON.stringify(object,(key,v)=>{if(typeof v==='string')strings.push(v);return v;});
  const whole=strings.flatMap(v=>{try{return /^https:/.test(v)?[new URL(v).host]:/^[\w.-]+\/[\w.-]+$/.test(v)?[v]:[];}catch{return [];}});
  const pairs=Object.keys(object).sort().map(k=>JSON.stringify(k)+':'+sorted(object[k]));
  const range=document.createRange();range.selectNodeContents(p);
  return {text,canonical:'Parameters: '+sorted(object),lines,pairs:pairs.length,breaks:p.querySelectorAll('wbr').length,
    midWord:lines.slice(0,-1).filter(line=>!/[,\/?&=\s-]$/.test(line)),
    brokenNames:whole.filter(name=>!lines.some(line=>line.includes(name))),whole:whole.length,
    inside:[...range.getClientRects()].every(r=>r.right<=box.right+0.5&&r.left>=box.left-0.5),
    cardFits:(card=>card.scrollWidth<=card.clientWidth+1)(p.closest('.pr-approval'))};}));
try {
  for (const [mode,expectPairs] of [['approval',5],['arbitrary-host',2]]) {
    await visit(mode);
    const rows=await layout();
    check(`${mode}: one Parameters line per feed`,rows.length>=1&&rows[0].pairs===expectPairs);
    for (const row of rows) {
      check(`${mode}: the disclosed text is the exact canonical JSON, unchanged`,row.text===row.canonical);
      check(`${mode}: a break point follows every parameter but the last`,row.breaks===row.pairs-1);
      check(`${mode}: no line ends inside a word (${row.midWord.join(' | ')||'none'})`,row.midWord.length===0);
      check(`${mode}: the host or repository being approved is whole on one line (${row.brokenNames.join(' | ')||'none'})`,row.whole>=1&&row.brokenNames.length===0);
      check(`${mode}: the line stays inside the card`,row.inside&&row.cardFits);
    }
    await page.locator('.pr-approval').first().screenshot({path:path.join(out,`params-${mode}.png`)});
  }
  await visit('approval','light');
  check('light theme: same layout rule holds',(await layout()).every(row=>row.midWord.length===0&&row.brokenNames.length===0&&row.text===row.canonical));
  check('no remote requests',remote.length===0);
  check('no runtime warnings',errors.length===0);
  fs.writeFileSync(path.join(out,'approval-wrap-results.json'),JSON.stringify({checks,errors,remote},null,2));
  console.log(`${checks.length} approval-wrap browser checks passed`);
} finally {await browser.close();}
