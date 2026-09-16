/* Pluto web client module: api (fetch client; 401 flow via hooks wired in app.js).
 * Split from the vanilla-JS monolith; behavior preserved.
 */
import { apiUrl, API_BASE } from "./config.js";
import { authHeaders, setToken } from "./auth-store.js";
import { toast } from "./ui.js";

var _apiHooks = {};
export function setApiHooks(h) { _apiHooks = h || {}; }

/* ---------- api client ---------- */
async function req(path, init, retried) {
  var opts = init || {};
  var headers = Object.assign({ "Content-Type": "application/json" }, authHeaders(), opts.headers || {});
  var hadToken = !!headers.Authorization;
  var res;
  // ponytail: 30s abort so hung Render cold-start fails fast vs hanging UI
  var timeoutId = null, ctrl = null;
  if (!opts.signal && typeof AbortSignal !== "undefined" && AbortSignal.timeout) {
    try { opts.signal = AbortSignal.timeout(30000); } catch (e) {}
  } else if (!opts.signal) {
    ctrl = new AbortController();
    opts.signal = ctrl.signal;
    timeoutId = setTimeout(function () { try { ctrl.abort(); } catch (e) {} }, 30000);
  }
  try {
    res = await fetch(apiUrl(path), Object.assign({}, opts, { headers: headers }));
  } catch (e) {
    if (timeoutId) clearTimeout(timeoutId);
    if (e && e.name === "AbortError") throw new Error("Request timed out after 30s.");
    throw new Error("Cannot reach the Pluto API (" + (API_BASE || "same origin") + "). " + e.message);
  }
  if (timeoutId) clearTimeout(timeoutId);
  if (res.status === 401 && !retried) {
    /* A 401 with a presented token means that token is dead (revoked,
     * or the server lost data/accounts.json after a restart without a
     * persistent disk). Drop it before prompting: otherwise Cancel leaves
     * the known-bad token behind and every later request 401-loops back
     * into the dialog, which feels like "login never works, I must sign
     * up again". After clearing, Cancel continues logged-out (visitor
     * vault in open mode); a successful login stores the fresh token. */
    if (hadToken) setToken("");
    if (!_apiHooks.onUnauthorized) throw new Error("Authentication required.");
    var tok = await _apiHooks.onUnauthorized("Log in to continue");
    if (!tok) throw new Error("Authentication required.");
    setToken(tok);
    try { if (_apiHooks.onSessionRefreshed) await _apiHooks.onSessionRefreshed(); } catch (e) {}
    return req(path, init, true);
  }
  if (!res.ok) {
    var detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (e) {}
    throw new Error(detail);
  }
  return await res.json();
}
function authedDownload(url, filename) {
  fetch(apiUrl(url), { headers: authHeaders() }).then(function (res) {
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

export { req, authedDownload };
