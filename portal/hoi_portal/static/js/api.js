// Same-origin API client: session tokens (sessionStorage), serialized rotating refresh, friendly errors.
import { qs } from './ui.js';

const BASE = '/api/v1';
const KEY = 'uthp.session';
const PRIVATE = /^\/(business|officer|analytics|admin|auth\/me)/;

export class ApiError extends Error {
  constructor(status, message, data = null, retryAfter = null) {
    super(message);
    this.status = status;
    this.data = data;
    this.retryAfter = retryAfter;
  }
}

let mem = null;
function readSession() {
  if (mem) return mem;
  try { mem = JSON.parse(sessionStorage.getItem(KEY) || 'null'); } catch { mem = null; }
  return mem;
}
function writeSession(s) {
  mem = s;
  try { if (s) sessionStorage.setItem(KEY, JSON.stringify(s)); else sessionStorage.removeItem(KEY); } catch { /* storage blocked: memory only */ }
  window.dispatchEvent(new CustomEvent('session', { detail: s }));
}
function saveLogin(r) {
  writeSession({ access_token: r.access_token, refresh_token: r.refresh_token, expires_at: Date.now() + (r.expires_in || 1800) * 1000, user: r.user });
  return r.user;
}
export const session = () => readSession();
export const user = () => readSession()?.user || null;
export const role = () => user()?.role || null;
export const isOfficial = () => ['district_officer', 'state_admin'].includes(role());

let refreshing = null;
async function refresh() {
  // Refresh tokens rotate; never send the same one twice, so all callers share one in-flight refresh.
  if (!refreshing) {
    refreshing = (async () => {
      const s = readSession();
      if (!s?.refresh_token) throw new ApiError(401, 'Please sign in.');
      const r = await raw('/auth/refresh', { method: 'POST', body: { refresh_token: s.refresh_token } });
      saveLogin(r);
    })().catch((e) => {
      writeSession(null);
      window.dispatchEvent(new CustomEvent('auth-expired'));
      throw new ApiError(401, 'Your session has ended. Please sign in again.');
    }).finally(() => { refreshing = null; });
  }
  return refreshing;
}

async function raw(path, { method = 'GET', body, query, token } = {}) {
  const url = BASE + path + (query && qs(query) ? '?' + qs(query) : '');
  const headers = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (token) headers.Authorization = 'Bearer ' + token;
  let res;
  try {
    res = await fetch(url, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined, credentials: 'same-origin' });
  } catch {
    throw new ApiError(0, 'The portal service cannot be reached. Check your connection and try again.');
  }
  if (res.status === 204) return null;
  let data = null;
  try { data = await res.json(); } catch { data = null; }
  if (!res.ok) {
    let msg = (data && typeof data.detail === 'string' && data.detail) || `Request failed (${res.status}).`;
    let ra = null;
    if (res.status === 429) {
      ra = parseInt(res.headers.get('Retry-After') || '60', 10);
      msg = `Too many tries. Please wait about ${ra} seconds and try again.`;
    }
    if (res.status >= 500) msg = (data && data.detail) || 'The server had a problem. Please try again shortly.';
    throw new ApiError(res.status, msg, data, ra);
  }
  return data;
}

/** api('/path', {method, body, query}) - attaches the bearer token for private paths and refreshes once on 401. */
export async function api(path, opts = {}) {
  const needsAuth = opts.auth ?? PRIVATE.test(path);
  if (!needsAuth) return raw(path, opts);
  let s = readSession();
  if (!s) throw new ApiError(401, 'Please sign in to continue.');
  if (s.expires_at && s.expires_at - Date.now() < 60_000) {
    await refresh();
    s = readSession();
  }
  try {
    return await raw(path, { ...opts, token: s.access_token });
  } catch (e) {
    if (e.status !== 401) throw e;
    await refresh();
    return raw(path, { ...opts, token: readSession().access_token });
  }
}

// ------------------------------------------------------------------ auth
export async function login(username, password) {
  return saveLogin(await raw('/auth/login', { method: 'POST', body: { username, password } }));
}
export async function register(username, password) {
  return saveLogin(await raw('/auth/register', { method: 'POST', body: { username, password } }));
}
export async function demoLogin(username) {
  return saveLogin(await raw('/auth/demo/' + encodeURIComponent(username), { method: 'POST' }));
}
export async function logout() {
  const s = readSession();
  writeSession(null);
  if (s?.refresh_token) {
    try { await raw('/auth/logout', { method: 'POST', body: { refresh_token: s.refresh_token } }); } catch { /* already gone */ }
  }
}

// ------------------------------------------------------------------ cached vocabularies
let metaP = null;
export function meta() {
  if (!metaP) metaP = raw('/meta').catch((e) => { metaP = null; throw e; });
  return metaP;
}
let demoP = null;
export function demoAccounts() {
  if (!demoP) demoP = raw('/auth/demo-accounts').catch(() => { demoP = null; return []; });
  return demoP;
}
export const districtName = async (id) => (await meta()).districts.find((d) => d.id === id)?.name || id;
