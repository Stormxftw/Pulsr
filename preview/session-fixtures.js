// Synthetic local session feed. No live session ids, titles or tool contents.
export function sessionFixture(mode, params, fixture) {
  window.__sessionMode = mode === 'sessions';
  window.__showSessions = mode === 'sessions' && !params.has('off');
  window.__sessionRows = [];
  window.__sessionTitles = [];
  if (mode !== 'sessions') return;
  fixture.pulses = [];
  fixture.drafts = [];
  const now = Date.now() / 1000;
  window.__sessionRows = [
    {id:'session:' + 'a'.repeat(64), session_id:'working-session', state:'Working', tool_calls_turn:7, tool_calls_total:42, last_activity_ts:now - 2, finished_ts:null},
    {id:'session:' + 'b'.repeat(64), session_id:'idle-session', state:'Idle', tool_calls_turn:0, tool_calls_total:18, last_activity_ts:now - 92, finished_ts:null},
    {id:'session:' + 'c'.repeat(64), session_id:'done-session', state:'Done', tool_calls_turn:12, tool_calls_total:64, last_activity_ts:now - 180, finished_ts:now - 180},
  ];
  window.__sessionTitles = [
    {id:'working-session', title:'Building something thoughtful'},
    {id:'idle-session', title:'A quieter moment'},
    {id:'done-session', title:'All the little details, finished'},
  ];
  window.__sessionTool = () => {
    const row = window.__sessionRows[0];
    row.tool_calls_turn++;
    row.tool_calls_total++;
    row.last_activity_ts = Date.now() / 1000;
    window.__emitPulse('sessions.updated');
  };
  window.__sessionDone = () => {
    Object.assign(window.__sessionRows[0], {state:'Done', finished_ts:Date.now() / 1000, last_activity_ts:Date.now() / 1000});
    window.__setSessionBusy({});
    window.__emitPulse('sessions.updated');
  };
}
export function sessionRest(path, opts, status) {
  if (!window.__sessionMode) return undefined;
  if (path === '/sessions') {
    if (window.__sessionReadError) throw Error('Synthetic session observer unavailable');
    return structuredClone({show_sessions:window.__showSessions, sessions:window.__showSessions ? window.__sessionRows : [], group:window.__showSessions ? {id:'hermes-sessions', title:'Hermes sessions'} : null});
  }
  if (path !== '/settings') return undefined;
  if (opts.method === 'PUT') {
    if (opts.body?.show_sessions === undefined) return undefined;
    if (opts.body.confirm !== true || typeof opts.body.show_sessions !== 'boolean') throw Error('Strict confirmation required');
    if (window.__sessionSettingsError) throw Error('Session setting was not saved');
    if (window.__sessionSettingsDelay) return new Promise(resolve => setTimeout(() => {window.__showSessions = opts.body.show_sessions; resolve({show_sessions:window.__showSessions});}, window.__sessionSettingsDelay));
    window.__showSessions = opts.body.show_sessions;
  }
  return {show_sessions:window.__showSessions, background_collection:status.collection?.mode === 'background', writable:true};
}
