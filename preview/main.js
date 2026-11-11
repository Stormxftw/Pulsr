import './host.css';
import {applyHostTheme} from './host-theme.js';
import React, {useState,useEffect} from 'react';
import {createRoot} from 'react-dom/client';
import {QueryClientProvider,queryClient,ThemeContext,builderRest,builderDefinition,host} from './sdk-mock.js';
import {sessionFixture, sessionRest} from './session-fixtures.js';
import pluginCurrent, {friendlyError,sortPulses,sanitizeCustomCss,displayStyle} from '../desktop/plugin.js';
import baselinePlugin from 'virtual:pulse-baseline';
import builderBaseline from 'virtual:pulse-builder-baseline';
const plugin=new URLSearchParams(location.search).has('builder-baseline')?builderBaseline:new URLSearchParams(location.search).has('baseline')?baselinePlugin:pluginCurrent;
// The pinned legacy build read --ui-bg, which real Hermes never defines; give only that
// historical render the editor surface it assumed so legacy pixels compare like for like.
if(new URLSearchParams(location.search).has('baseline')&&!new URLSearchParams(location.search).has('builder-baseline'))document.documentElement.style.setProperty('--ui-bg','var(--ui-bg-editor)');
import {displayFixture,tickDisplay} from './display-fixtures.js';
import {groupsFixture,layoutRest} from './groups-fixtures.js';
const params = new URLSearchParams(location.search);
const mode = params.get('mode') || 'hero';
const blockMode=['blocks','block-states','styles','live-blocks'].includes(mode);
const seed = await (await fetch('/ui-fixture/'+(mode === 'groups' ? 'twelve' : blockMode ? 'hero' : ['builder','sessions','offline','remote-icon','failed-approval','unconfirmed-approval'].includes(mode) ? 'pending' : mode))).json();
const fixture=blockMode?displayFixture(mode,seed):seed;
if(mode==='builder'){fixture.as_of=Date.now()/1000;const out=await builderRest('/builder/preview',{body:{definition:builderDefinition}},fixture);fixture.pulses=[{...out,kind:'mcp.tool',state:'active',ring:{score:0,warming:false,components:[]},capsule:{label:'Connector counts'},history:[]}];fixture.drafts=[];}
const icons = await (await fetch('/recorded-icons')).json();
const iconKeys=['nousresearch','nvidiadeveloper','typesafe','6EbMcWJHdb','ollama'];
if(['hero','old-backend','twelve','states'].includes(mode)){fixture.features.import_yaml=false;fixture.features.import_discord=false;} // Explicit disabled-feature scenario.
fixture.pulses.forEach((p,i)=>{const known={'nous-discord':'nousresearch','typescript':'typesafe','hugging-face':'6EbMcWJHdb'};p.icon_data=p.kind==='discord.invite'?icons[known[p.id] || iconKeys[i%iconKeys.length]]:null;});
if(mode==='remote-icon')fixture.pulses.forEach(p=>p.icon_data='https://invalid.example/icon.png');
const layoutSeed=mode==='groups'?groupsFixture(fixture,params.has('forty')?40:12):{version:1,groups:[],ungrouped:[...fixture.pulses].map(p=>({pulse:p,key:p.id})).sort(sortPulses).map(r=>({pulse:r.pulse.id}))};
if(mode==='groups' && params.has('sessions')) {
  const ids=['session:one','session:two'];
  fixture.pulses.push(...ids.map((id,i)=>({...structuredClone(fixture.pulses[i]),id,title:i?'Tool review chat':'Research chat'})));
  layoutSeed.groups.push({id:'hermes-sessions',title:'Hermes sessions',collapsed:false,children:ids.map(pulse=>({pulse}))});
}
let samplingReads=0;
window.__pulseRestCalls=[];
window.__pulseFriendlyError=friendlyError;
window.__pulseSort=sortPulses;
window.__pulseStatus=fixture;
sessionFixture(mode, params, fixture);
window.__sanitizePulseCss=sanitizeCustomCss;
window.__displayPulseStyle=displayStyle;
window.__pulseTick=()=>{tickDisplay(window.__pulseStatus);window.__emitPulse('draft.updated');};
window.__pulseCustomCss=params.has('css')?'.pr-block { border-color: rebeccapurple; }':'';
const contributions=[],handlers=new Map(),disposers=[];
window.__disposePulse=()=>disposers.forEach(fn=>fn());
window.__emitPulse=event=>handlers.get('plugin.pulse-rings.'+event)?.({payload:{}});
const storage=new Map();
const ctx={
  register:c=>contributions.push(c),onDispose:fn=>disposers.push(fn),onEvent:(event,fn)=>{handlers.set(event,fn);return()=>handlers.delete(event);},
  storage:{get:(key,fallback)=>storage.get(key)??fallback,set:(key,value)=>storage.set(key,value)},
  os:{writeClipboard:async text=>{window.__pulseClipboard=text;return true;},openExternal:async url=>{window.__pulseExternal=url;return true;}},
  rest:async(path,opts={})=>{
    window.__pulseRestCalls.push({path,method:opts.method || 'GET',body:opts.body,profile:host.state.profile.get()});
    if(params.has('delay'))await new Promise(resolve=>setTimeout(resolve,Number(params.get('delay'))));
    if(mode==='offline')throw new Error('Fixture backend is offline');
    const status=window.__pulseStatus;
    const sessionResult=sessionRest(path,opts,status);
    if(sessionResult!==undefined)return sessionResult;
    const layoutResult=await layoutRest(path,opts,status,layoutSeed,`${mode}:${params.get('case') || 'default'}:${params.has('forty')}:${host.state.profile.get()}`);
    if(layoutResult!==undefined)return layoutResult;
    const builderResult=await builderRest(path,opts,status);
    if(builderResult!==undefined)return builderResult;
    if(path==='/custom.css' || path==='/custom.css?format=json'){if(!params.has('css'))throw new Error('404');return window.__pulseCustomCss;}
    if(path==='/settings'){
      if(opts.method==='PUT'){
        if(opts.body.confirm!==true || typeof opts.body.background_collection!=='boolean')throw Error('Explicit boolean confirmation required');
        if(window.__settingsError)throw Error('Collection setting was not saved');
        if(window.__settingsDelay)await new Promise(resolve=>setTimeout(resolve,window.__settingsDelay));
        status.collection={...status.collection,mode:opts.body.background_collection?'background':'viewed'};
      }
      return {background_collection:status.collection?.mode==='background',show_sessions:false,writable:true};
    }
    if(path==='/status' || path==='/status?poll=0'){
      if(mode==='sampling' && samplingReads++>0){
        const hot=await (await fetch('/ui-fixture/approval')).json();
        status.drafts=hot.drafts;
      }
      return structuredClone(status);
    }
    const decision=path.match(/^\/drafts\/(pd_[a-f0-9]{10})\/(approve|reject)$/);
    if(decision){
      if(mode==='failed-approval')throw new Error('Approval was not saved. Try again.');
      if(mode==='unconfirmed-approval')return {status:'approved'};
      const draft=status.drafts.find(d=>d.id===decision[1]);
      if(!draft)throw new Error('Draft not found or expired');
      if(decision[2]==='approve'){
        if(mode==='builder') {
          const row=await builderRest('/builder/preview',{body:{definition:draft.definition,mode:'sample',seed:0}},status);
          status.pulses=status.pulses.filter(p=>p.id!==draft.definition.id);
          status.pulses.push({...row,sample:false,state:'active',kind:Object.values(draft.definition.feeds || {main:draft.definition.source})[0].kind,ring:{score:0,warming:false,components:[]},capsule:{label:'Local approval fixture'},history:[],budget:draft.budget});
        } else {
          status.pulses=status.pulses.filter(p=>p.id!==draft.preview?.id);
          status.pulses.push(draft.preview || {id:draft.definition.id,title:draft.definition.title,kind:draft.definition.source.kind,state:'warming',ring:{score:0,warming:true,components:[]},capsule:{label:'Sampling…',fill:null,caption:'Learning baseline'},history:[],budget:draft.budget});
        }
      }
      status.drafts=status.drafts.filter(d=>d.id!==draft.id);
      return {status:decision[2]==='approve'?'approved':'rejected'};
    }
    const opening=path.match(/^\/pulses\/([^/]+)\/open-app$/);
    if(opening && opts.method==='POST'){
      if(opts.body?.confirm!==true)throw new Error('Explicit confirmation required');
      if(window.__openAppError)throw new Error(window.__openAppError);
      const pulse=status.pulses.find(p=>p.id===decodeURIComponent(opening[1]));
      if(!pulse?.open_app?.name)throw new Error('409 This pulse has no app to open on this PC.');
      return {opened:pulse.open_app.name};
    }
    if(path.startsWith('/icons/'))return {icon_data:icons.nousresearch};
    if(mode==='builder' && path.endsWith('/definition'))return {definition:builderDefinition};
    if(path.endsWith('/definition'))return {yaml:'pulse: 1\nid: '+path.split('/')[2]+'\ntitle: Example pulse\nsource: {kind: discord.invite, params: {invite: nousresearch}}\n'};
    if(opts.method==='PATCH'){
      const pulse=status.pulses.find(p=>p.id===decodeURIComponent(path.split('/').pop()));
      pulse.state=opts.body.paused?'paused':'active';return {ok:true};
    }
    if(opts.method==='DELETE'){status.pulses=status.pulses.filter(p=>p.id!==decodeURIComponent(path.split('/').pop()));return {ok:true};}
    if(path==='/drafts' && opts.method==='POST'){
      const seed=await (await fetch('/ui-fixture/pending')).json();
      if(mode==='builder'){const checked=await builderRest('/layout-check',opts,status);const d={...seed.drafts[0],origin:{kind:'session',surface:'desktop'},created_ts:Date.now()/1000,id:'pd_'+(0xabcdef1233+(window.__builderDraftSerial=(window.__builderDraftSerial||0)+1)).toString(16),definition:checked.normalized,disclosure:await builderRest('/fixture-disclosure',{body:{definition:checked.normalized}},status),budget:checked.budget,preview:null,preview_state:'after_approval',preview_calls:0,yaml:checked.yaml,replaces:opts.body.replaces,expires_ts:Date.now()/1000+604800};status.drafts.push(d);return {draft_id:d.id};}
      status.drafts.push(seed.drafts[0]);return {draft_id:seed.drafts[0].id};
    }
    if(path==='/migrate/discord-pulse'){
      const plan=status.import_plan;
      if(opts.method!=='POST')return structuredClone(plan);
      if(window.__importDelay)await new Promise(resolve=>setTimeout(resolve,window.__importDelay));
      if(window.__importStale)throw new Error('409 Import plan changed. Cancel and review again.');
      if(window.__importUnconfirmed)return {completed:true};
      if(opts.body?.consent!==true || opts.body?.token!==plan.token)throw new Error('Explicit consent/token required');
      status.migration={available:false,completed:true};
      for(const id of plan.ids)status.pulses.push({id,title:id,kind:'discord.invite',state:'warming',ring:{score:0,warming:true,unknown:true,components:[]},capsule:{label:'Sample after approval',fill:null,caption:'Learning baseline'},history:[],budget:plan.budget});
      return {completed:true,recommendation:plan.recommendation};
    }
    throw new Error('Unmocked REST route: '+path);
  }
};
plugin.register(ctx);
if(mode==='live-blocks'){const timer=setInterval(()=>window.__pulseTick(),1600);disposers.push(()=>clearInterval(timer));}
window.__pulseContributions=contributions;
const pane=contributions.find(c=>c.area==='panes');
const directive=contributions.find(c=>c.data?.name==='pulse-rings-draft');
const chip=contributions.find(c=>c.area==='statusBar.right');
const width=Number(params.get('width') || 248);
document.documentElement.style.setProperty('--preview-width',width+'px');
function App(){
  const [theme,setTheme]=useState(params.get('theme') || 'dark');
  const [workspace,setWorkspace]=useState(null);
  useEffect(()=>{const fn=e=>setWorkspace(e.detail);window.addEventListener('pulse-workspace',fn);return()=>window.removeEventListener('pulse-workspace',fn);},[]);
  applyHostTheme(theme);
  document.documentElement.classList.toggle('light',theme==='light');
  document.documentElement.classList.toggle('dark',theme==='dark');
  // The real stylesheet owns both the host palette and SDK aliases.

  document.body.style.background = 'var(--ui-bg-editor)';
  document.body.style.color = 'var(--ui-text-primary)';

  const cardMode=mode==='approval' || mode==='sampling' || mode==='arbitrary-host' || params.has('card');
  const id=params.get('id') || fixture.drafts[0]?.id || 'pd_0123456789';
  return React.createElement(ThemeContext.Provider,{value:theme},
    React.createElement('header',{className:'preview-top'},React.createElement('span',null,'PULSR / UI LAB'),React.createElement('button',{id:'theme',onClick:()=>setTheme(theme==='dark'?'light':'dark')},'Toggle theme')),
    React.createElement('main',{className:cardMode?'preview-card-scene':'preview-pane-scene'},
      React.createElement('div',{className:'preview-caption'},cardMode?'PROPOSED BY HERMES':'RIGHT PANE · '+width+' PX'),
      React.createElement('div',{id:'surface',className:cardMode?'preview-chat':'preview-frame'},cardMode?directive.data.render({attrs:{id},sessionId:'preview-session'}):pane.render())),
    params.has('chip')?React.createElement('div',{className:'preview-chip'},chip.render()):null,
    workspace?React.createElement('div',{className:'preview-workspace',style:{width:360,margin:'20px auto',border:'1px solid var(--ui-stroke-secondary)'}},workspace.render()):null,
    React.createElement('details',{className:'preview-draft'},React.createElement('summary',null,'Review draft · unsent request'),React.createElement('pre',{id:'draft','aria-label':'Preview composer draft',style:{whiteSpace:'pre-wrap',font:'12px/1.6 ui-monospace,monospace',overflowWrap:'anywhere'}})),
    React.createElement('footer',null,blockMode?'HAND-AUTHORED SYNTHETIC DISPLAY ROWS · NOT ENGINE OUTPUT · NOT LIVE HERMES':'ENGINE-GENERATED · DISCORD & DRAFT GITHUB RECORDED / OTHER INPUTS SYNTHETIC · NOT LIVE HERMES',React.createElement('br'),'Actual plugin component. Local-only requests.'));
}
const root=createRoot(document.getElementById('root'));
window.__unmountPulse=()=>root.unmount();
root.render(React.createElement(QueryClientProvider,{client:queryClient},React.createElement(App)));
