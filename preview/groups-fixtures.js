// Local-only transport fixtures. Production validation/CAS is tested in Python.
export function groupsFixture(status, count = 12) {
  const titles = ['Hermes research', 'TypeScript', 'Hugging Face', 'NVIDIA', 'Ollama', 'Nous community', 'Build queue', 'Repository health', 'Local models', 'Review inbox', 'Release watch', 'Notes'];
  const seed = structuredClone(status.pulses);
  status.pulses = Array.from({length:count}, (_, i) => ({...structuredClone(seed[i % seed.length]), id:`pulse-${i + 1}`, title:titles[i % titles.length] + (i >= 12 ? ` ${i + 1}` : '')}));
  status.drafts = [];
  const ref = i => ({pulse:`pulse-${i}`});
  return {version:1, groups:[
    {id:'communities', title:'Communities', collapsed:false, children:[...Array.from({length:5}, (_, i)=>ref(i + 1)), {id:'tools',title:'Developer tools',collapsed:false,children:[ref(6),ref(7),ref(8)]}]},
    {id:'workspace',title:'Workspace',collapsed:false,children:[ref(9),ref(10)]},
  ], ungrouped:status.pulses.slice(10).map(p=>({pulse:p.id}))};
}

export async function layoutRest(path, opts, status, seed, scope) {
  if (path !== '/layout') return undefined;
  const key = `pulse-layout-fixture:${scope}`;
  let value = JSON.parse(sessionStorage.getItem(key) || 'null') || structuredClone(seed);
  const sessionRows = window.__sessionMode && window.__showSessions ? window.__sessionRows : [];
  const ids = new Set([...status.pulses, ...sessionRows].map(p => p.id)), seen = new Set();
  if (window.__sessionMode) {
    value.groups = value.groups.filter(g => g.id !== 'hermes-sessions' || window.__showSessions);
    if (window.__showSessions && !value.groups.some(g => g.id === 'hermes-sessions')) value.groups.push({id:'hermes-sessions', title:'Hermes sessions', collapsed:false, children:[]});
  }
  const prune = children => children.filter(c=>!c.pulse || ids.has(c.pulse)).map(c=>{
    if (c.pulse) seen.add(c.pulse); else c.children=prune(c.children);
    return c;
  });
  value.groups.forEach(g=>{g.children=prune(g.children);});
  value.ungrouped=prune(value.ungrouped);
  sessionRows.forEach(p=>{if(!seen.has(p.id))value.groups.find(g=>g.id==='hermes-sessions').children.push({pulse:p.id});});
  status.pulses.forEach(p=>{if(!seen.has(p.id))value.ungrouped.push({pulse:p.id});});
  const revision = async layout => [...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(layout))))].map(b=>b.toString(16).padStart(2,'0')).join('');
  if (opts.method === 'PUT') {
    if (window.__layoutDelay) await new Promise(resolve=>setTimeout(resolve,window.__layoutDelay));
    if (window.__layoutError) throw Error('Local layout disk write failed');
    if (window.__layoutStale || opts.body.revision !== await revision(value)) throw Error('409 Arrangement changed');
    value = structuredClone(opts.body.layout);
    sessionStorage.setItem(key, JSON.stringify(value));
  }
  const result = {layout:value, revision:await revision(value), customized:seed.groups.length>0 || sessionStorage.getItem(key)!==null};
  window.__layoutRemote = structuredClone(result);
  return result;
}
