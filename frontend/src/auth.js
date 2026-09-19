/* Pluto web client module: auth (account UI + session network; post-login refresh via hooks).
 * Split from the vanilla-JS monolith; behavior preserved.
 */
import { $, toast } from "./ui.js";
import { escHtml } from "./markdown.js";
import { apiUrl, AUTH_SEEN_KEY } from "./config.js";
import { S, AUTH_MODE, savePrefs } from "./state.js";
import { authHeaders } from "./auth-store.js";

var _authHooks = {};
export function setAuthHooks(h) { _authHooks = h || {}; }

export var ACCT = { username: "" };
/* ---------- account (login session; chats+memory follow the user id) ---------- */
function renderLoginBtn() {
  var b = $("loginBtn");
  if (!b) return;
  b.classList.toggle("hidden", !!ACCT.username);
}
function renderAcct() {
  var mode = AUTH_MODE === "private" ? "Private" : "Open";
  var who = ACCT.username ? ACCT.username + " · " : "";
  $("acctModel").textContent = who + (S.model || "No model") + " · " + mode;
  renderLoginBtn();
}
async function refreshMe() {
  ACCT.username = "";
  /* Direct fetch (not req()): req() would pop a nested login dialog on
   * 401, and a stale/revoked/wiped cookie session must not loop the
   * dialog on every call. The session is an HttpOnly cookie (never in
   * JS); a 401 here just means logged-out. */
  try {
    var res = await fetch(apiUrl("/api/auth/me"), { headers: authHeaders(), credentials: "include" });
    if (res.status === 401) {
      ACCT.username = "";
      renderAcct();
      return;
    }
    if (!res.ok) throw new Error(res.statusText);
    var me = await res.json();
    ACCT.username = (me && me.username) || "";
  } catch (e) {
    /* Network failure: report logged-out until the next successful
     * check (the cookie may still be good). */
    ACCT.username = "";
  }
  renderAcct();
}
async function authCall(path, body) {
  var res;
  try {
    res = await fetch(apiUrl(path), {
      method: "POST",
      headers: Object.assign({ "Content-Type": "application/json" }, authHeaders()),
      credentials: "include",
      body: JSON.stringify(body)
    });
  } catch (e) {
    throw new Error("Cannot reach the Pluto API. " + e.message);
  }
  if (!res.ok) {
    var detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (e) {}
    throw new Error(detail);
  }
  return await res.json();
}
var authResolve = null;
function authDismissed() {
  try { return localStorage.getItem(AUTH_SEEN_KEY) === "1"; } catch (e) { return true; }
}
function markAuthSeen() {
  try { localStorage.setItem(AUTH_SEEN_KEY, "1"); } catch (e) {}
}
function showAuth(title) {
  $("authTitle").textContent = title || "Log in to Pluto";
  $("authErr").classList.add("hidden");
  $("authErr").textContent = "";
  $("authHint").textContent = "";
  $("authDlg").classList.remove("hidden");
  setTimeout(function () { $("authUser").focus(); }, 30);
}
function hideAuth() {
  $("authDlg").classList.add("hidden");
  $("authPass").value = "";
}
/* Promise form: used by every auth wall (boot, 401s, uploads) so the
 * login dialog — not a bare token prompt — is what logged-out users see. */
function authAsync(title) {
  return new Promise(function (resolve) {
    authResolve = resolve;
    showAuth(title);
  });
}
function settleAuth(ok) {
  hideAuth();
  markAuthSeen();
  if (authResolve) {
    var r = authResolve;
    authResolve = null;
    r(ok ? true : null);
  }
}
async function authSubmit(path) {
  var u = $("authUser").value.trim();
  var p = $("authPass").value;
  var err = $("authErr");
  err.classList.add("hidden");
  if (!/^[A-Za-z0-9_.-]{3,32}$/.test(u)) {
    err.textContent = "Username must be 3-32 characters: letters, digits, _, ., -.";
    err.classList.remove("hidden");
    return;
  }
  if (p.length < 8) {
    err.textContent = "Password must be at least 8 characters.";
    err.classList.remove("hidden");
    return;
  }
  if (path.indexOf("signup") > -1) {
    var hint = pwHint(p, u);
    if (hint) {
      err.textContent = hint;
      err.classList.remove("hidden");
      return;
    }
  }
  err.classList.add("hidden");
  try {
    // Server sets the HttpOnly pluto_session cookie; the JSON token is
    // ignored by the browser client (non-browser clients may use it as
    // Bearer). Success = cookie present, so re-read /me for the name.
    await authCall(path, { username: u, password: p });
    await refreshMe();
    settleAuth(true);
    toast("Signed in as " + (ACCT.username || "you"));
    try { if (_authHooks.onSessionChangedToast) await _authHooks.onSessionChangedToast(); } catch (e) {}
  } catch (e) {
    var msg = String((e && e.message) || "Sign in failed.");
    if (path.indexOf("signup") > -1 && msg.toLowerCase().indexOf("taken") > -1) {
      msg += " Try Log in with that name instead.";
    } else if (path.indexOf("login") > -1 && msg.toLowerCase().indexOf("invalid username or password") > -1) {
      msg += " If the server was just redeployed without persistent storage, the account no longer exists — sign up again.";
    }
    err.textContent = msg;
    err.classList.remove("hidden");
  }
}
async function signOut() {
  try { await fetch(apiUrl("/api/auth/logout"), { method: "POST", headers: Object.assign({ "Content-Type": "application/json" }, authHeaders()), credentials: "include", body: "{}" }); } catch (e) {}
  ACCT.username = "";
  renderAcct();
  toast("Signed out");
  try { if (_authHooks.onSessionChanged) await _authHooks.onSessionChanged(); } catch (e) {}
}
/* ---------- password strength hint (mirrors services/accounts rules) ---------- */
function pwHint(p, u) {
  p = String(p || "");
  u = String(u || "").trim().toLowerCase();
  if (!p) return "";
  if (p.length < 8) return "Password needs at least 8 characters.";
  if (u && (p.toLowerCase() === u || p.toLowerCase().indexOf(u) > -1)) {
    return "Password must not contain your username.";
  }
  var classes = [/[a-z]/, /[A-Z]/, /[0-9]/, /[^A-Za-z0-9]/].filter(function (re) {
    return re.test(p);
  }).length;
  if (classes < 3) return "Weak — mix 3 of: a-z, A-Z, 0-9, symbols.";
  return "";
}
/* ---------- account dialog (sessions + change password) ---------- */
function openAcct() {
  if (!ACCT.username) { showAuth("Log in to Pluto"); return; }
  $("acctName").textContent = "Signed in as " + ACCT.username;
  $("acctCur").value = "";
  $("acctNew").value = "";
  $("acctConfirm").value = "";
  $("acctPassErr").classList.add("hidden");
  $("acctPassErr").textContent = "";
  $("acctSessions").textContent = "Loading…";
  $("acctDlg").classList.remove("hidden");
  setTimeout(function () { $("acctClose").focus(); }, 30);
  loadSessions();
}
function hideAcct() {
  $("acctDlg").classList.add("hidden");
  $("acctCur").value = "";
  $("acctNew").value = "";
  $("acctConfirm").value = "";
}
async function loadSessions() {
  var box = $("acctSessions");
  try {
    var res = await fetch(apiUrl("/api/auth/sessions"), { headers: authHeaders(), credentials: "include" });
    if (!res.ok) throw new Error(res.statusText);
    var data = await res.json();
    var list = (data && data.sessions) || [];
    if (!list.length) { box.textContent = "No active sessions."; return; }
    box.innerHTML = list.map(function (s) {
      var when = "";
      try { when = new Date(s.created * 1000).toLocaleString(); } catch (e) { when = ""; }
      var dev = s.agent ? escHtml(s.agent) : "Unknown device";
      return "<div>" + (s.current ? '<span class="now">This device</span> · ' : "")
        + escHtml(when) + " · " + dev + "</div>";
    }).join("");
  } catch (e) {
    box.textContent = "Could not load sessions.";
  }
}
async function submitPasswordChange() {
  var cur = $("acctCur").value;
  var nw = $("acctNew").value;
  var cf = $("acctConfirm").value;
  var err = $("acctPassErr");
  err.classList.add("hidden");
  if (!cur) { err.textContent = "Enter your current password."; err.classList.remove("hidden"); return; }
  if (nw !== cf) { err.textContent = "New passwords do not match."; err.classList.remove("hidden"); return; }
  var hint = pwHint(nw, ACCT.username);
  if (hint) { err.textContent = hint; err.classList.remove("hidden"); return; }
  try {
    var res = await fetch(apiUrl("/api/auth/change-password"), {
      method: "POST",
      headers: Object.assign({ "Content-Type": "application/json" }, authHeaders()),
      credentials: "include",
      body: JSON.stringify({ current_password: cur, new_password: nw })
    });
    if (!res.ok) {
      var detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch (e) {}
      throw new Error(detail);
    }
    await res.json();
    hideAcct();
    toast("Password changed — other devices signed out");
  } catch (e) {
    err.textContent = String((e && e.message) || "Could not change password.");
    err.classList.remove("hidden");
  }
}
async function signOutEverywhere() {
  try {
    await fetch(apiUrl("/api/auth/logout-all"), { method: "POST", headers: Object.assign({ "Content-Type": "application/json" }, authHeaders()), credentials: "include", body: "{}" });
  } catch (e) {
    toast("Could not sign out everywhere: " + e.message);
    return;
  }
  hideAcct();
  await signOut();
}
/* ---------- generic dialog (promise form) ---------- */
var dlgCb = null;
function ask(title, val, cb) {
  $("dlgTitle").textContent = title;
  $("dlgInput").value = val || "";
  $("dlg").classList.remove("hidden");
  dlgCb = cb;
  setTimeout(function () { $("dlgInput").focus(); $("dlgInput").select(); }, 30);
}
function askAsync(title, val) {
  return new Promise(function (resolve) {
    ask(title, val, function (v) { resolve(v); });
  });
}
$("dlgOk").addEventListener("click", function () {
  var v = $("dlgInput").value.trim();
  $("dlg").classList.add("hidden");
  if (dlgCb) dlgCb(v);
  dlgCb = null;
});
$("dlgCancel").addEventListener("click", function () {
  $("dlg").classList.add("hidden");
  if (dlgCb) dlgCb(null);
  dlgCb = null;
});
$("dlgInput").addEventListener("keydown", function (e) {
  if (e.key === "Enter") $("dlgOk").click();
  if (e.key === "Escape") $("dlgCancel").click();
});
$("accountBtn").addEventListener("click", function () {
  openAcct();
});
if ($("loginBtn")) $("loginBtn").addEventListener("click", function () {
  if (ACCT.username) return;
  showAuth("Log in to Pluto");
});
$("authCancel").addEventListener("click", function () { settleAuth(null); });
$("authTokenBtn").addEventListener("click", function () {
  // Legacy access-token entry is retired with HttpOnly cookies: access
  // tokens are now sent via Authorization header by non-browser clients
  // only. Browsers use account cookies; point users at login instead.
  hideAuth();
  toast("Use Log in / Sign up — browser sessions are cookies now.");
  settleAuth(null);
});
$("authLogin").addEventListener("click", function () { authSubmit("/api/auth/login"); });
$("authSignup").addEventListener("click", function () { authSubmit("/api/auth/signup"); });
$("authPass").addEventListener("input", function () {
  var h = pwHint($("authPass").value, $("authUser").value);
  $("authHint").textContent = h;
});
$("authPass").addEventListener("keydown", function (e) {
  if (e.key === "Enter") authSubmit("/api/auth/login");
  if (e.key === "Escape") settleAuth(null);
});
$("authUser").addEventListener("keydown", function (e) {
  if (e.key === "Enter") authSubmit("/api/auth/login");
  if (e.key === "Escape") settleAuth(null);
});
$("acctClose").addEventListener("click", function () { hideAcct(); });
$("acctSignOut").addEventListener("click", function () { hideAcct(); signOut(); });
$("acctLogoutAll").addEventListener("click", function () { signOutEverywhere(); });
$("acctSavePass").addEventListener("click", function () { submitPasswordChange(); });

export { renderLoginBtn, renderAcct, refreshMe, authCall, authDismissed, markAuthSeen, showAuth, hideAuth, authAsync, settleAuth, authSubmit, signOut, signOutEverywhere, pwHint, openAcct, hideAcct, loadSessions, submitPasswordChange, ask, askAsync };
