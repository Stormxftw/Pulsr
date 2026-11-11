import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../desktop/plugin.js',import.meta.url),'utf8');
const match=source.match(/export function capsuleMetric\(p\) \{[\s\S]*?\r?\n\}/);
assert.ok(match,'capsuleMetric remains an exported pure read-model formatter');
const code=match[0].replace('export ','');
const context=vm.createContext({Intl,Math});
vm.runInContext(code+'\nglobalThis.metric=capsuleMetric;',context);
let passed=0;
const eq=(a,b)=>{assert.equal(a,b);passed++;};
for (const name of ['hero','states','mcp']) {
  const fixture=JSON.parse(fs.readFileSync(new URL(`../tests/fixtures/ui/${name}.json`,import.meta.url),'utf8'));
  for (const row of fixture.pulses) {
    const m=context.metric(row), c=row.capsule;
    eq(m.label,c.label || 'Not measured');
    eq(m.caption,c.caption || 'Not measured');
    eq(m.fill,Number.isFinite(c.fill)?Math.max(0,Math.min(100,c.fill)):null);
  }
}
for (const fill of [null,undefined,NaN,Infinity,-10,0,45,100,150]) {
  const m=context.metric({capsule:{label:'0 items',caption:'Engine caption',fill}});
  eq(m.label,'0 items');eq(m.caption,'Engine caption');
  eq(m.fill,Number.isFinite(fill)?Math.max(0,Math.min(100,fill)):null);
}
const absent=context.metric({});
eq(absent.label,'Not measured');eq(absent.caption,'Not measured');eq(absent.fill,null);
console.log(`Capsule: ${passed} assertions passed (engine fixtures, zero, unknown, bounded drawing geometry; no score recomputation).`);
