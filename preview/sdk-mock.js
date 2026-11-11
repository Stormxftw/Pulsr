import {createContext, useContext, useSyncExternalStore} from 'react';
import {QueryClient} from '@tanstack/react-query';
export {useQuery, useQueryClient, QueryClientProvider} from '@tanstack/react-query';
export const queryClient = new QueryClient({defaultOptions:{queries:{retry:false,gcTime:0}}});
export const PALETTE_AREA = 'palette';
export const TRANSCRIPT_DIRECTIVE_AREA = 'transcriptDirective';
export const STATUSBAR_AREAS = {right:'statusBar.right'};
// Builder lab: only pure routes reach Python. MCP is an explicit local fixture,
// never a real connector or network dispatch. These results are not live data.
import {builder2Mock} from './builder2-mock.js';
export async function builderRest(path, opts = {}, status) {
  const base = path.split('?')[0];
  const bridged = ['/layout-check', '/builder/preview', '/builder/templates', '/builder/from-template', '/builder/layouts', '/brands', '/catalog', '/fixture-disclosure'];
  if (!bridged.includes(base)) {
    const guided = await builder2Mock(path, opts, (route, options) => builderRest(route, options, status));
    if (guided !== undefined) return guided;
  }
  if (bridged.includes(base)) {
    const response = await fetch('/builder-mock', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({path:base, body:base==='/brands'?{q:new URLSearchParams(path.split('?')[1]).get('q') || ''}:opts.body || {}})});
    if (!response.ok) throw Error('Pure builder bridge failed');
    const result = await response.json();
    // Deliberate local policy fixture, never production policy or dispatch.
    if (base === '/fixture-disclosure') for (const row of result.feeds) if (row.mcp) row.mcp = {...row.mcp, read_only:row.params.tool === 'read_counts', reason:null};
    return result;
  }

  if (path === '/builder/mcp-tools') return {tools:[{server:'probe',tool:'read_counts',read_only:true,reason:null},{server:'probe',tool:'write_counts',read_only:false,reason:'MCP tool is not marked read-only.'}],reason:null};
  if (path === '/builder/mcp-test-call') {
    if (opts.body.confirm !== true || opts.body.tool !== 'read_counts') throw Error('Read-only test refused');
    window.__mcpTestDispatches = (window.__mcpTestDispatches || 0) + 1;
    if (window.__mcpTestDelay) await new Promise(resolve => setTimeout(resolve, window.__mcpTestDelay));
    return {body:{used:42,limit:500,nested:{'a/b':[7,true,'9']}},text:'',truncated:false,numeric:[{pointer:'/used',value:42},{pointer:'/limit',value:500},{pointer:'/nested/a~1b/0',value:7}],calls:1,persisted:false};
  }
  const draft = path.match(/^\/drafts\/(pd_[a-f0-9]{10})$/);
  if (draft) return structuredClone(status.drafts.find(d=>d.id===draft[1]));
  return undefined;
}
export const builderDefinition = {pulse:1,id:'builder-live',title:'Connector health',icon:{brand:'github'},feeds:{main:{kind:'mcp.tool',params:{server:'probe',tool:'read_counts',args:{},metrics:{used:'/used',limit:'/limit'}},every:'15m'}},display:[{type:'rings',rings:[{value:'main.used',label:'API calls',max:'main.limit'}]},{type:'stat',value:'main.used',label:'Calls',show:'both'}]};
export const ThemeContext = createContext('dark');
export const useTheme = () => ({renderedMode:useContext(ThemeContext)});
export const atom = value => ({get:()=>value,subscribe:()=>()=>{}});
export const useValue = atom => useSyncExternalStore(atom.subscribe || (()=>()=>{}), atom.get, atom.get);
let visible = true, profile = 'preview';
const profileListeners = new Set();
window.__setPulseProfile = value => {profile=value;profileListeners.forEach(fn=>fn());};
const listeners = new Set();
window.__setPaneVisible = value => {visible=value;listeners.forEach(fn=>fn());};
let sessionBusy = {}, sessionRuntime = null, sessionStored = null;
const sessionBusyListeners = new Set();
window.__setSessionBusy = value => {sessionBusy=value;sessionBusyListeners.forEach(fn=>fn());};
window.__setSessionFocus = (runtime, stored) => {sessionRuntime=runtime;sessionStored=stored;sessionBusyListeners.forEach(fn=>fn());};
const sessionSubscribe = fn => {sessionBusyListeners.add(fn);return()=>sessionBusyListeners.delete(fn);};
export const host = {
  state:{focusedSessionId:{get:()=>sessionRuntime,subscribe:sessionSubscribe},focusedStoredSessionId:{get:()=>sessionStored,subscribe:sessionSubscribe},busyBySession:{get:()=>sessionBusy,subscribe:sessionSubscribe},profile:{get:()=>profile,subscribe:fn=>{profileListeners.add(fn);return()=>profileListeners.delete(fn);}}},
  request:async(method,params)=>{(window.__sessionRequests ||= []).push({method,params});if(window.__sessionListError)throw Error('Session list unavailable');return {sessions:window.__sessionTitles || []};},
  openSession:async(id,opts)=>{window.__focusedSession={id,...opts};},
  navigate:path=>{window.__sessionNavigation=path;},
  paneVisibility:()=>({get:()=>visible,subscribe:fn=>{listeners.add(fn);return()=>listeners.delete(fn);}}),
  composer:{insertText:async(_sid,text)=>{window.__pulseDraft=text;document.getElementById('draft').textContent='UNSENT DRAFT\n'+text;return true;},focus:()=>{window.__pulseComposerFocused=true;}},
  notify:value=>{window.__pulseNotification=value;(window.__pulseNotifications ||= []).push(value);},
  openWorkspace:(id,opts)=>{window.__pulseWorkspace={id,title:opts.title};window.dispatchEvent(new CustomEvent('pulse-workspace',{detail:{id,...opts}}));return()=>window.dispatchEvent(new CustomEvent('pulse-workspace',{detail:null}));}
};
export {Button} from './builder2-sdk.js';
export {Tip} from './builder2-sdk.js';

export {Input, Switch, SegmentedControl, Select, SelectTrigger, SelectValue, SelectContent, SelectItem, Popover, PopoverTrigger, PopoverContent} from './builder2-sdk.js';
