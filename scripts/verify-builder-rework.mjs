// Reproducible offline regression gate; each suite keeps its own artifacts.
import fs from 'node:fs';
import path from 'node:path';
import {spawn} from 'node:child_process';
const host=process.argv[2], out=process.argv[3];
if(!host||!out)throw Error('Usage: node scripts/verify-builder-rework.mjs HERMES_SOURCE ARTIFACT_DIR');
fs.mkdirSync(out,{recursive:true});
const suites=['widget','blocks','builder','builder2','polish','background','security-ui','ui-nits','builder-rework','rework-journeys','rework-integrity'];
const results=[];
let cursor=0;
const run=async()=>{
  while(cursor<suites.length){
    const suite=suites[cursor++];
    const log=path.join(out,suite+'-final.log');
    const output=fs.createWriteStream(log);
    let text='';
    const child=spawn(process.execPath,['scripts/test-'+suite+'.mjs',host,['rework-journeys','rework-integrity'].includes(suite)?out:path.join(out,suite)],{env:process.env,stdio:['ignore','pipe','pipe']});
    for(const stream of [child.stdout,child.stderr])stream.on('data',chunk=>{text+=chunk;output.write(chunk);});
    const code=await new Promise((resolve,reject)=>{child.on('error',reject);child.on('close',resolve);});
    await new Promise(resolve=>output.end(resolve));
    const declared=text.match(/(\d+) (?:[a-z0-9-]+ )?browser checks passed/i);
    const printedChecks=(text.match(/^PASS /gm)||[]).length;
    const result={suite,code,checks:declared?Number(declared[1]):printedChecks,printedChecks,log};
    results.push(result);
    fs.writeFileSync(path.join(out,'browser-suite-results.json'),JSON.stringify(results,null,2));
    console.log(JSON.stringify(result));
  }
};
await Promise.all([run(),run()]);
results.sort((a,b)=>suites.indexOf(a.suite)-suites.indexOf(b.suite));
const report={suites:results.length,checks:results.reduce((n,r)=>n+r.checks,0),failed:results.filter(r=>r.code!==0),results};
fs.writeFileSync(path.join(out,'browser-suite-results.json'),JSON.stringify(report,null,2));
console.log(JSON.stringify({suites:report.suites,checks:report.checks,failed:report.failed.map(r=>r.suite)}));
if(report.failed.length)process.exitCode=1;
