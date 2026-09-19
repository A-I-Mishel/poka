/* Pluto web client module: api (fetch client; 401 flow via hooks wired in app.js).
 * Sessions are HttpOnly cookies: every request uses credentials:"include"
 * so the browser attaches pluto_session automatically. No Bearer tokens
 * are stored in JS (see auth-store.js).
 */
import { apiUrl, API_BASE } from "./config.js";
import { authHeaders } from "./auth-store.js";
import { toast } from "./ui.js";

var _apiHooks = {};
export function setApiHooks(h) { _apiHooks = h || {}; }

/* ---------- api client ---------- */
async function readDetail(res) {
  // Real Responses always have .text(); minimal test doubles may only
  // have .json() — support both so neither path crashes.
  try {
    if (typeof res.text === "function") {
      var txt = await res.text();
      if (txt) {
        try { return (JSON.parse(txt)).detail || null; } catch (e) { return null; }
      }
      return null;
    }
    var body = await res.json();
    return (body && body.detail) || null;
  } catch (e) {
    return null;
  }
}
async function readBody(res) {
  // Empty-body safe (204 No Content): "" -> null instead of SyntaxError.
  try {
    if (typeof res.text === "function") {
      var t = await res.text();
      return t ? JSON.parse(t) : null;
    }
    return await res.json();
  } catch (e) {
    throw new Error("Bad server response.");
  }
}
async function req(path, init, retried) {
  var opts = init || {};
  var headers = Object.assign({ "Content-Type": "application/json" }, authHeaders(), opts.headers || {});
  // ponytail: 120s abort — Render free sleeps + Deep+PPTX runs exceed 30s
  var timeoutId = null, ctrl = null;
  if (!opts.signal && typeof AbortSignal !== "undefined" && AbortSignal.timeout) {
    try { opts.signal = AbortSignal.timeout(120000); } catch (e) {}
  } else if (!opts.signal) {
    ctrl = new AbortController();
    opts.signal = ctrl.signal;
    timeoutId = setTimeout(function () { try { ctrl.abort(); } catch (e) {} }, 120000);
  }
  var res;
  try {
    res = await fetch(apiUrl(path), Object.assign({}, opts, { headers: headers, credentials: "include" }));
  } catch (e) {
    if (timeoutId) clearTimeout(timeoutId);
    if (e && (e.name === "AbortError" || e.name === "TimeoutError")) throw new Error("Pluto is waking up (Render sleeps) or the reply is long — wait a minute and retry.");
    throw new Error("Cannot reach the Pluto API (" + (API_BASE || "same origin") + "). " + e.message);
  }
  if (timeoutId) clearTimeout(timeoutId);
  if (res.status === 401 && !retried) {
    /* Cookie session is dead (logout, expiry, server data reset without
     * a persistent disk). Prompt once via the login dialog; Cancel
     * continues logged-out (visitor vault in open mode). */
    if (!_apiHooks.onUnauthorized) throw new Error("Authentication required.");
    var ok = await _apiHooks.onUnauthorized("Log in to continue");
    if (!ok) throw new Error("Authentication required.");
    try { if (_apiHooks.onSessionRefreshed) await _apiHooks.onSessionRefreshed(); } catch (e) {}
    return req(path, init, true);
  }
  if (!res.ok) {
    var detail = (await readDetail(res)) || res.statusText;
    throw new Error(detail);
  }
  return await readBody(res);
}
/* ---------- raw client (no 401 dialog) ----------
 * Same timeout/credentials/authHeaders as req(), but never pops the
 * login dialog: auth flows (refreshMe, login/signup, logout, sessions)
 * and upload/stream paths handle 401 themselves (a stale cookie must
 * report logged-out, not loop a nested dialog). Callers check
 * res.status / res.ok directly. */
async function rawReq(path, init, timeoutMs) {
  var opts = init || {};
  var headers = Object.assign({ "Content-Type": "application/json" }, authHeaders(), opts.headers || {});
  var ms = timeoutMs || 30000;
  var ctrl = null, timeoutId = null;
  if (!opts.signal && typeof AbortSignal !== "undefined" && AbortSignal.timeout) {
    try { opts.signal = AbortSignal.timeout(ms); } catch (e) { opts.signal = undefined; }
  }
  if (!opts.signal) {
    ctrl = new AbortController();
    opts.signal = ctrl.signal;
    timeoutId = setTimeout(function () { try { ctrl.abort(); } catch (e) {} }, ms);
  }
  var res;
  try {
    res = await fetch(apiUrl(path), Object.assign({}, opts, { headers: headers, credentials: "include" }));
  } catch (e) {
    if (e && (e.name === "AbortError" || e.name === "TimeoutError")) throw new Error("Request timed out — retry.");
    throw new Error("Cannot reach the Pluto API (" + (API_BASE || "same origin") + "). " + e.message);
  } finally {
    if (timeoutId) clearTimeout(timeoutId);
  }
  return res;
}
function authedDownload(url, filename) {
  fetch(apiUrl(url), { headers: authHeaders(), credentials: "include" }).then(function (res) {
    if (!res.ok) throw new Error(res.statusText);
    return res.blob();
  }).then(function (blob) {
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename || "download";
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 2000);
  }).catch(function (e) { toast("Download failed: " + e.message); });
}

export { req, rawReq, authedDownload };
