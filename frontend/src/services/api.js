// Every call goes to the FastAPI backend under /api, which proxies SAS RAM.
// Dev: Vite proxies /api to :8000. Production: same origin.
const API = '/api';

async function req(path, opts = {}) {
  const r = await fetch(`${API}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  noteSessionStamp(r, path);
  if (!r.ok) {
    const e = await r.json().catch(() => ({ detail: 'Connection error' }));
    throw new Error(e.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

export const getHealth = () => req('/health');
export const startDeviceAuth = () => req('/auth/device/start', { method: 'POST' });
export const pollDeviceAuth = () => req('/auth/device/poll', { method: 'POST' });
export const submitViyaCode = (code) =>
  req('/auth/viya/code', { method: 'POST', body: JSON.stringify({ code }) });

// Staying signed in: the backend keeps this browser's RAM session under an
// HttpOnly cookie and refreshes it in the background. After a sign-in it also
// hands the browser a copy of the session (the refresh token, not the access
// token); if the backend ever comes back without it (a redeploy on a fresh
// container), the browser hands the copy back and carries on.
const SESSION_KEY = 'ram_session_v1';
export const saveSession = (s) => { try { if (s) localStorage.setItem(SESSION_KEY, JSON.stringify(s)); } catch { /* private mode */ } };
export const loadSession = () => { try { const r = localStorage.getItem(SESSION_KEY); return r ? JSON.parse(r) : null; } catch { return null; } };
export const clearSession = () => { try { localStorage.removeItem(SESSION_KEY); } catch { /* ignore */ } };
export const restoreSession = (session) =>
  req('/auth/restore', { method: 'POST', body: JSON.stringify({ session }) });
// The identity provider may replace the refresh token whenever the backend
// renews the session, which would leave the saved copy holding a dead one.
// Every API response carries the session's current stamp (X-Session-Stamp);
// when it differs from the saved copy's, fetch a new copy.
let syncing = null;
const syncSession = (stamp) => {
  if (stamp == null || loadSession()?.stamp === stamp || syncing) return syncing || Promise.resolve();
  syncing = req('/auth/session')
    .then(({ session }) => { if (session) saveSession(session); })
    .catch(() => {})
    .finally(() => { syncing = null; });
  return syncing;
};
function noteSessionStamp(response, path) {
  if (path.startsWith('/auth/')) return;   // sign-in, restore and sign-out manage the copy themselves
  const stamp = response.headers.get('X-Session-Stamp');
  if (stamp != null) syncSession(Number(stamp));
}
// Sign this browser out of RAM: the backend revokes and forgets the session
// and drops the cookie; the saved copy goes too so nothing restores it.
export const signOut = async () => {
  clearSession();
  return req('/auth/signout', { method: 'POST' });
};

// Extract text from an uploaded file (multipart — no JSON headers)
export const extractAttachment = async (file) => {
  const fd = new FormData();
  fd.append('file', file);
  const r = await fetch(`${API}/extract`, { method: 'POST', body: fd });
  if (!r.ok) {
    const e = await r.json().catch(() => ({ detail: 'Upload failed' }));
    throw new Error(e.detail || `HTTP ${r.status}`);
  }
  return r.json();
};
export const getAgents = () => req('/agents');
export const getCollections = () => req('/collections');
export const getSessions = () => req('/sessions');
export const getSessionQueries = (sessionId) =>
  req(`/sessions/${encodeURIComponent(sessionId)}/queries`);

// Asks RAM to delete the session. RAM v1 has no such endpoint, so today this
// fails and the caller hides the conversation in this browser instead.
export const deleteSession = (sessionId) =>
  req(`/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' });

// target: { type: 'agent', id } or { type: 'collection', id }
// attachments: [{ name, text }] — extracted documents inlined into the query
// Returns { queryId, querySessionId, pollInterval, timeout, result? } —
// poll getQueryStatus until done unless `result` came back inline.
export const submitQuery = (content, target, querySessionId = null, attachments = null, language = 'en') =>
  req('/query', {
    method: 'POST',
    body: JSON.stringify({
      content,
      agentId: target.type === 'agent' ? target.id : null,
      collectionIds: target.type === 'collection' ? [target.id] : null,
      querySessionId,
      attachments,
      language,
    }),
  });

export const getQueryStatus = (queryId) => req(`/query/${encodeURIComponent(queryId)}`);

// Tool/LLM/retrieval calls RAM recorded for a query — also works mid-run
export const getQueryTrace = (queryId) => req(`/query/${encodeURIComponent(queryId)}/trace`);
