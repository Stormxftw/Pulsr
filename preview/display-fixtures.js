// Hand-authored synthetic status rows for DISPLAY.md §4.2/§4.3/§5.
// NOT engine output and NOT live eBay/GPU readings.
export const BLOCK_TYPES = ['score', 'rings', 'bar', 'bars', 'stat', 'spark'];
export const BLOCK_STATES = ['measured', 'learning', 'unknown', 'unavailable', 'over', 'under', 'degraded', 'stale'];
const now = 1794099600;
const emptyRing = {score:0,warming:false,unknown:true,components:[],baseline_samples:0,window_seconds:0};
const feed = (name, state = 'active') => ({name,kind:'mcp.tool@1',state,last_ok_ts:now,next_due:now+60,backoff_until:null,error:state==='error'?'Synthetic feed unavailable':null,budget:{hosts:[],req_per_hour:60}});
export function fixtureItem(state = 'measured', overrides = {}) {
  const row = {ref:'main.load',feed:'main',metric:'load',label:'Load',value:62,value_text:'62 %',unit:'%',unknown:false,reason:null,min:0,max:100,fill:62,over:false,under:false,learning:false,tone:'ok',ticks:[80,95],range:{min_form:'fixed',max_form:'fixed',window_seconds:604800,samples:8},caption:'62% of 100',style:{}};
  if (state==='learning') Object.assign(row,{fill:null,learning:true,caption:'Learning range · 2 samples',range:{min_form:'fixed',max_form:'auto',window_seconds:604800,samples:2}});
  if (state==='unknown' || state==='degraded') Object.assign(row,{value:null,value_text:null,unknown:true,reason:'Synthetic feed unavailable',fill:null,tone:null,ticks:[],caption:''});
  if (state==='unavailable') Object.assign(row,{max:null,fill:null,caption:'Range unavailable',range:{min_form:'fixed',max_form:'ref',window_seconds:604800,samples:8}});
  if (state==='over') Object.assign(row,{value:120,value_text:'120 %',fill:100,over:true,tone:'crit',caption:'120% of 100 · above max'});
  if (state==='under') Object.assign(row,{value:-10,value_text:'−10 %',fill:0,under:true,tone:'ok',caption:'-10% of 100 · below min'});
  return {...row,...overrides};
}
export function fixtureBlock(type, state = 'measured', index = 0) {
  const item = fixtureItem(state);
  const base = {type,index,label:type.toUpperCase(),style:{}};
  if (type==='score') return {...base,ring:{score:62,warming:state==='learning',unknown:state==='unknown'||state==='degraded',components:[{metric:'load',value:item.value,baseline:40,baseline_mode:'fixed',observed_seconds:7200,unknown:item.unknown,contribution:62,delta:22,reason:item.reason}],baseline_samples:8,window_seconds:7200}};
  if (['rings','bar','bars'].includes(type)) return {...base,...(type==='bars'?{scale:'shared'}:{}),items:type==='bar'?[item]:[item,fixtureItem(state,{ref:'main.memory',metric:'memory',label:'Memory'})],style:type==='rings'?{gap:3,cap:'round'}:{ticks:'zones',show_range:true}};
  if (type==='stat') return {...base,ref:'main.load',value:item.value,value_text:item.value_text,unit:'%',unknown:item.unknown,reason:item.reason,delta:state==='learning'||item.unknown?null:22,delta_text:state==='learning'||item.unknown?null:'+22 %',delta_vs:'usual',caption:state==='learning'?'Learning baseline':item.unknown?'': 'vs usual',style:{delta_colors:'neutral'}};
  return {...base,ref:'main.load',points:[34,40,null,52,38,61,58,62].map((value,i)=>({ts:now-(7-i)*600,value:item.unknown?null:value})),lo:item.unknown?null:34,hi:item.unknown?null:62,unknown:item.unknown,style:{fill:'area',dot:'last'}};
}
function pulse(id, title, blocks, state = 'active') {
  const firstItem = blocks.flatMap(b=>b.items || [])[0];
  return {id,title,kind:'mcp.tool',state,display:blocks,feeds:[feed('main'),...(state==='degraded'?[feed('other','error')]:[])],theme:null,
    ring:blocks.find(b=>b.type==='score')?.ring || {...emptyRing},capsule:firstItem?{label:`${firstItem.label} ${firstItem.value_text}`,fill:firstItem.fill,caption:firstItem.caption}:{label:title,fill:null,caption:''},lines:[],history:[],icon_data:null,last_ok_ts:now,next_due:now+60,backoff_until:null,error:null,alert:{active:false,reason:null,notify:'none'},budget:{hosts:[],req_per_hour:60}};
}
export function displayFixture(mode, legacyStatus) {
  const legacy = structuredClone(legacyStatus.pulses.find(p=>p.id==='nous-discord') || legacyStatus.pulses[0]);
  legacy.display=null; legacy.theme=null;
  legacy.feeds=[{name:'main',kind:legacy.kind,state:legacy.state,last_ok_ts:legacy.last_ok_ts,next_due:legacy.next_due,backoff_until:legacy.backoff_until,error:legacy.error,budget:legacy.budget}];
  const status = {...legacyStatus,as_of:now,pulses:[],drafts:[],features:{}};
  if (mode==='block-states') {
    status.pulses=BLOCK_TYPES.flatMap(type=>BLOCK_STATES.map(state=>pulse(`${type}-${state}`,`${type} · ${state}`,[fixtureBlock(type,state)],state==='degraded'||state==='stale'?state:'active')));
  } else {
    const ebay=pulse('synthetic-ebay','Store health · synthetic',[
      {...fixtureBlock('rings'),label:'Store health',items:[fixtureItem('measured',{ref:'limits.used',feed:'limits',metric:'used',label:'API calls',value:370,value_text:'370',unit:'',max:500,fill:74,tone:null,ticks:[],caption:'74% of limit',range:{min_form:'fixed',max_form:'ref',window_seconds:604800,samples:8}}),fixtureItem('measured',{ref:'orders.open',feed:'orders',metric:'open',label:'Open orders',value:12,value_text:'12',unit:'',max:25,fill:48,tone:null,ticks:[],caption:'auto 0–25 · 7d',range:{min_form:'fixed',max_form:'auto',window_seconds:604800,samples:8}})]},
      {...fixtureBlock('bars','measured',1),label:'Orders · shared scale',items:[fixtureItem('measured',{ref:'orders.open',feed:'orders',metric:'open',label:'Open',value:12,value_text:'12',unit:'',max:25,fill:48,tone:null,ticks:[],caption:'auto 0–25 · 7d'}),fixtureItem('measured',{ref:'orders.late',feed:'orders',metric:'late',label:'Late',value:3,value_text:'3',unit:'',max:25,fill:12,tone:'warn',ticks:[8,20],caption:'auto 0–25 · 7d'})]},
      {...fixtureBlock('stat','measured',2),label:'Late orders',ref:'orders.late',value:3,value_text:'3',unit:'',delta:1,delta_text:'+1'}]);
    ebay.feeds=[feed('limits'),feed('orders')];
    const gpu=pulse('synthetic-gpu','GPU monitor · synthetic',[
      {...fixtureBlock('bars'),label:'Hardware · independent scales',scale:'independent',items:[fixtureItem(),fixtureItem('measured',{ref:'main.memory',metric:'memory',label:'VRAM',value:7.1,value_text:'7.1 GB',unit:'GB',max:8,fill:88.75,tone:'warn',ticks:[80],caption:'89% of 8'}),fixtureItem('measured',{ref:'main.temp',metric:'temp',label:'Temperature',value:84,value_text:'84 °C',unit:'°C',fill:84,tone:'crit',ticks:[75,83],caption:'84% of 100'})]},
      {...fixtureBlock('spark','measured',1),label:'GPU trend'}]);
    status.pulses=[ebay,gpu,pulse('synthetic-score','Change intensity · synthetic',[fixtureBlock('score'),fixtureBlock('bar','measured',1)]),legacy];
    if (mode==='styles') {
      ebay.theme={accent:'#7c5cff',density:'roomy',radius:12,font:'rounded',motion:'calm'};
      ebay.display[0].style={color:'accent',color2:'warn',track:'muted',thickness:8,gap:2,cap:'flat',direction:'ccw',glow:2,text:'l',label:'above'};
      gpu.theme={accent:'#22aacc',density:'compact',font:'mono',motion:'none'};
      gpu.display[0].style={color:'accent',color2:'ok',radius:4,thickness:6,ticks:'zones',show_range:false};
    }
  }
  return status;
}
export function tickDisplay(status) {
  status.as_of++;
  const p=status.pulses.find(p=>p.id==='synthetic-gpu');
  if (!p) return;
  p.feeds[0].last_ok_ts++;
  p.last_ok_ts++;
  const item=p.display[0].items[0];
  item.value=item.value===62?71:62; item.value_text=item.value+' %'; item.fill=item.value; item.caption=item.value+'% of 100';
  const spark=p.display[1];spark.points.shift();spark.points.push({ts:status.as_of,value:item.value});spark.hi=71;
}
