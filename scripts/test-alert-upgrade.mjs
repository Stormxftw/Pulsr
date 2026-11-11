// Refs #70: baseline-generated upgrade records. No browser, network, or user storage.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const out=process.argv[3];fs.mkdirSync(out,{recursive:true});
const baseline=fs.readFileSync(path.join(root,'tests/fixtures/alert-effect-f876f09.txt'),'utf8');
const source=fs.readFileSync(path.join(root,'desktop/plugin.js'),'utf8');
const start=source.indexOf('    if (!visible || detailView) return;');
const end=source.indexOf('  }, [data, ctx, visible, detailView, profile]);',start);
assert.ok(start>=0&&end>start,'actual candidate alert effect found');
const candidate=source.slice(start,end),checks=[];
const check=(name,ok)=>{checks.push({name,ok});console.log(`${ok?'PASS':'FAIL'} ${name}`);assert.ok(ok,name);};
function fixture(){const state=new Map(),notices=[];return {state,notices,run(body,now,active,profile='A',reason='waiting_on_you: 1'){
 const data={as_of:now,pulses:[{id:'same',title:'Same pulse',alert:{active,reason,notify:'toast'}}]};
 vm.runInNewContext('(function(){'+body+'})()',{data,visible:true,detailView:false,profile,seconds:()=>now,ctx:{storage:{get:(key,fallback)=>state.has(key)?state.get(key):fallback,set:(key,value)=>state.set(key,value)}},host:{notify:value=>notices.push(value)}});
}};}
try {
 const active=fixture();active.run(baseline,1000,true,'A');
 check('baseline generated a real legacy notification record',active.notices.length===1&&active.state.has('alerted:same:waiting_on_you: 1'));
 active.run(candidate,1010,true,'B');
 check('unowned legacy active state cannot suppress another profile',active.notices.length===2);
 active.run(candidate,1020,true,'B','waiting_on_you: 2');active.run(candidate,4000,true,'B','waiting_on_you: 3');
 check('new profile continuous alert never re-fires on value/time changes',active.notices.length===2);
 active.run(candidate,4010,true,'A');
 check('first observation in each profile has its own new-format gate',active.notices.length===3);
 const inactive=fixture();inactive.run(baseline,1000,true);inactive.run(baseline,1010,false);
 check('baseline inactive transition really loses its pointer',inactive.state.get('alerted-reason:same')===null);
 const legacyRecords=()=>JSON.stringify([...inactive.state].filter(([key])=>key.startsWith('alerted:')||key.startsWith('alerted-reason:')));
 const legacyBefore=legacyRecords();
 inactive.run(candidate,1020,true);
 check('upgrade policy explicitly resets unowned legacy state once',inactive.notices.length===2);
 inactive.run(candidate,1030,false);inactive.run(candidate,1040,true,'A','waiting_on_you: 2');
 check('new-format thirty-minute throttle holds after reset',inactive.notices.length===2);
 inactive.run(candidate,3000,false);inactive.run(candidate,3001,true,'A','waiting_on_you: 3');
 check('later genuine edge can notify after new gate expires',inactive.notices.length===3);
 const before=inactive.notices.length;inactive.run(candidate,3010,true,'A','waiting_on_you: 4');
 check('persistent remount-like execution reuses the stable gate',inactive.notices.length===before);
 const legacyKeys=[...inactive.state.keys()].filter(key=>key.startsWith('alerted:')||key.startsWith('alerted-reason:'));
 check('candidate adds no per-value legacy keys',legacyKeys.length===2);
 check('candidate leaves existing legacy records untouched',legacyRecords()===legacyBefore);
 check('candidate keeps exactly one new-format record per profile and pulse',[...inactive.state.keys()].filter(key=>key.startsWith('alert-state:')).join()==='alert-state:A:same');
 // Disclosed tradeoff: the unowned legacy timestamp (1000) is not carried over.
 const quiet=fixture();quiet.run(baseline,1000,true);quiet.run(candidate,1010,false);
 check('inactive first observation initializes the new gate silently',quiet.notices.length===1&&quiet.state.has('alert-state:A:same'));
 quiet.run(candidate,1020,true);
 check('first new-format edge is not throttled by the unowned legacy timestamp',quiet.notices.length===2);
 quiet.run(candidate,1030,false);quiet.run(candidate,1040,true,'A','waiting_on_you: 2');
 check('reset is bounded to one notification; the next edge inside thirty minutes is throttled',quiet.notices.length===2);
} finally {fs.writeFileSync(path.join(out,'results.json'),JSON.stringify({checks,policy:'One-time reset: no automatic adoption of profileless legacy state. At most one first-seen notification per profile/pulse, then stable rising-edge throttle.'},null,2));}
console.log(`${checks.length} alert upgrade checks passed`);
