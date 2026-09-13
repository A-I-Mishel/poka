/* Pluto web client (vanilla JS + Vite).
 *
 * Configuration is never hardcoded:
 * - API origin comes from the Vite env `VITE_API_URL` (set in the hosting
 *   dashboard) and falls back to same-origin `/api` (local dev via the
 *   Vite proxy, or single-server mode where the API serves this UI).
 * - Model list comes from `GET /api/health` (tiers actually configured).
 * - Access token lives in localStorage (`pluto_token`, legacy `poka_token`
 *   migrated once) and is only ever sent as an Authorization header.
 *   The token is either a login session (POST /api/auth/signup + /login)
 *   or an operator-issued access token — the server tells them apart.
 * - Logged-out browsers also send a stable `X-Pluto-Visitor` id
 *   (`pluto_visitor`) so open-mode chats persist across requests.
 * - Every list, label count, and panel row is server data or derived from it.
 */

window.onerror = function (m, s, l) {
  var b = document.getElementById("errBanner");
  b.style.display = "block";
  b.textContent = "Error: " + m + " (line " + l + ")";
};
function $(id) { return document.getElementById(id); }

/* ---------- config (env-driven, never hardcoded) ---------- */
var API_BASE = "";
try {
  var _envUrl = (import.meta.env && import.meta.env.VITE_API_URL) || "";
  API_BASE = String(_envUrl).replace(/\/+$/, "");
} catch (e) { API_BASE = ""; }
function apiUrl(path) { return API_BASE + path; }

/* ---------- token (localStorage, legacy migration) ---------- */
var TOKEN_KEY = "pluto_token";
var LEGACY_TOKEN_KEY = "poka_token";
function getToken() {
  try {
    var t = localStorage.getItem(TOKEN_KEY) || "";
    if (t) return t;
    var legacy = localStorage.getItem(LEGACY_TOKEN_KEY) || "";
    if (legacy) {
      localStorage.setItem(TOKEN_KEY, legacy);
      localStorage.removeItem(LEGACY_TOKEN_KEY);
      return legacy;
    }
  } catch (e) {}
  return "";
}
function setToken(t) {
  try {
    if (t) localStorage.setItem(TOKEN_KEY, t);
    else localStorage.removeItem(TOKEN_KEY);
  } catch (e) {}
}
function authHeaders() {
  var h = {};
  var t = getToken();
  if (t) h.Authorization = "Bearer " + t;
  var v = getVisitor();
  if (v) h["X-Pluto-Visitor"] = v;
  return h;
}

/* ---------- visitor (stable per-browser id for logged-out use) ----------
 * Without this, open-mode requests without a token each mint a fresh
 * server-side id, so chats saved by one request are unreadable by the
 * next and the conversation vanishes after every reply. Accounts still
 * win whenever a Bearer token is present. */
var VISITOR_KEY = "pluto_visitor";
function getVisitor() {
  try {
    var v = localStorage.getItem(VISITOR_KEY) || "";
    if (!/^[A-Za-z0-9_.-]{8,64}$/.test(v)) {
      var bytes = null;
      try {
        bytes = (window.crypto && window.crypto.getRandomValues)
          ? window.crypto.getRandomValues(new Uint8Array(16)) : null;
      } catch (e) { bytes = null; }
      if (bytes) {
        v = Array.prototype.map.call(bytes, function (b) {
          return ("0" + b.toString(16)).slice(-2);
        }).join("");
      } else {
        v = "v" + Date.now().toString(36) + Math.floor(Math.random() * 1e9).toString(36);
      }
      localStorage.setItem(VISITOR_KEY, v);
    }
    return v;
  } catch (e) { return ""; }
}

/* ---------- account (login session; chats+memory follow the user id) ---------- */
var ACCT = { username: "" };
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
  if (!getToken()) { renderAcct(); return; }
  try {
    var me = await req("/api/auth/me");
    ACCT.username = (me && me.username) || "";
  } catch (e) { ACCT.username = ""; }
  renderAcct();
}
async function authCall(path, body) {
  var res;
  try {
    res = await fetch(apiUrl(path), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
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
var AUTH_SEEN_KEY = "pluto_auth_seen";
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
function settleAuth(token) {
  hideAuth();
  markAuthSeen();
  if (authResolve) {
    var r = authResolve;
    authResolve = null;
    r(token);
  }
}
async function authSubmit(path) {
  var u = $("authUser").value.trim();
  var p = $("authPass").value;
  var err = $("authErr");
  err.classList.add("hidden");
  try {
    var out = await authCall(path, { username: u, password: p });
    setToken(out.token);
    ACCT.username = out.username || "";
    settleAuth(out.token);
    renderAcct();
    toast("Signed in as " + (out.username || "you"));
    try { await refreshProjects(); } catch (e) {}
    try { await refreshChats(); } catch (e) { toast("Cannot load chats: " + e.message); }
  } catch (e) {
    err.textContent = e.message;
    err.classList.remove("hidden");
  }
}
async function signOut() {
  try { await req("/api/auth/logout", { method: "POST", body: "{}" }); } catch (e) {}
  setToken("");
  ACCT.username = "";
  renderAcct();
  toast("Signed out");
  try { await refreshProjects(); } catch (e) {}
  try { await refreshChats(); } catch (e) {}
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

/* ---------- api client ---------- */
async function req(path, init, retried) {
  var opts = init || {};
  var headers = Object.assign({ "Content-Type": "application/json" }, authHeaders(), opts.headers || {});
  var res;
  try {
    res = await fetch(apiUrl(path), Object.assign({}, opts, { headers: headers }));
  } catch (e) {
    throw new Error("Cannot reach the Pluto API (" + (API_BASE || "same origin") + "). " + e.message);
  }
  if (res.status === 401 && !retried) {
    var tok = await authAsync("Log in to continue");
    if (!tok) throw new Error("Authentication required.");
    setToken(tok);
    try { await refreshMe(); } catch (e) {}
    try { await refreshProjects(); } catch (e) {}
    try { await refreshChats(); } catch (e) {}
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

/* ---------- prefs (local only: theme/mode/selection) ---------- */
var PREFS_KEY = "pluto.v1";
var LEGACY_PREFS_KEY = "poka.v1";
function defaultPrefs() {
  return { theme: "dark", folded: false, mode: "fast", web: false, model: "", projectId: null };
}
function loadPrefs() {
  var p = defaultPrefs();
  try {
    var raw = localStorage.getItem(PREFS_KEY) || localStorage.getItem(LEGACY_PREFS_KEY);
    if (raw) {
      var parsed = JSON.parse(raw);
      Object.keys(p).forEach(function (k) {
        if (parsed[k] !== undefined) p[k] = parsed[k];
      });
    }
  } catch (e) {}
  return p;
}
var S = loadPrefs();
function savePrefs() {
  try { localStorage.setItem(PREFS_KEY, JSON.stringify(S)); } catch (e) {}
}

/* ---------- server state ---------- */
var TIERS = [];
var AUTH_MODE = "open";
var chats = [];    /* archived records {id,title,messages,project_id} */
var current = [];  /* open conversation messages */
var projects = []; /* [{id,name}] */

/* ---------- misc helpers ---------- */
function esc(s) { return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
function fmtTime(ts) {
  if (!ts) return "";
  try {
    var d = new Date(ts);
    if (isNaN(d.getTime())) return "";
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch (e) { return ""; }
}
function fmtDay(ts) {
  try {
    var d = ts ? new Date(ts) : new Date();
    if (isNaN(d.getTime())) d = new Date();
    return d.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
  } catch (e) { return ""; }
}
function fmtStamp(v) {
  if (v === null || v === undefined || v === "") return "";
  try {
    var ms = Number(v);
    var d = new Date(ms < 1e12 ? ms * 1000 : ms);
    if (isNaN(d.getTime())) return String(v);
    return d.toLocaleDateString([], { month: "short", day: "numeric" }) + " · " +
      d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch (e) { return ""; }
}
function fmtSize(b) {
  if (!(b >= 0)) return "";
  if (b < 1024) return b + " B";
  if (b < 1048576) return (b / 1024).toFixed(1) + " KB";
  return (b / 1048576).toFixed(1) + " MB";
}
function toast(msg) {
  var t = document.createElement("div");
  t.className = "toast";
  t.textContent = msg;
  $("toasts").appendChild(t);
  setTimeout(function () { t.style.opacity = "0"; t.style.transition = "opacity .3s"; }, 2200);
  setTimeout(function () { t.remove(); }, 2600);
}
var PLANET_SVG = '<svg width="SIZE" height="SIZE" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="6"/><ellipse cx="12" cy="12" rx="10" ry="3.8" transform="rotate(-20 12 12)"/><circle cx="10.2" cy="10.4" r="0.7" fill="currentColor" stroke="none"/></svg>';
function planet(size) { return PLANET_SVG.split("SIZE").join(size); }

/* ---------- icons ---------- */
var IC = {
  doc: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"><path d="M15 2H7a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7z"/><path d="M14 2v5h5"/></svg>',
  down: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5M12 15V3"/></svg>',
  open: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"><path d="M15 3h6v6M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg>',
  flask: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"><path d="M10 2v7.3M14 9.3V2M8.5 2h7"/><path d="M14 9.3a6.5 6.5 0 1 1-4 0M5.5 16h13"/></svg>',
  cpu: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"><rect x="5" y="5" width="14" height="14" rx="2"/><rect x="9.5" y="9.5" width="5" height="5"/></svg>',
  chart: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M12 20v-9M18 20V5M6 20v-5"/></svg>',
  code: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"><path d="m16 18 6-6-6-6M8 6l-6 6 6 6"/></svg>',
  image: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="9" cy="9" r="1.8"/><path d="m21 15-4.5-4.5L6 21"/></svg>'
};
function ic(n) { return '<div class="card-ic">' + IC[n] + "</div>"; }
function artIcon(kind) {
  var k = String(kind || "").toLowerCase();
  if (k.indexOf("image") > -1 || k.indexOf("png") > -1 || k.indexOf("jpg") > -1) return "image";
  if (k.indexOf("code") > -1 || k.indexOf("html") > -1 || k.indexOf("js") > -1) return "code";
  if (k.indexOf("chart") > -1 || k.indexOf("csv") > -1) return "chart";
  return "doc";
}

/* ---------- markdown (message content only, always escaped first) ---------- */
function md(t) {
  var s = esc(t);
  s = s.replace(/```([\s\S]*?)```/g, function (m, c) {
    return "<pre><code>" + c.replace(/^\n|\n$/g, "") + "</code></pre>";
  });
  s = s.replace(/`([^`\n]+)`/g, "<code>$1</code>");
  s = s.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
  return s.split(/\n{2,}/).map(function (p) {
    return p.indexOf("<pre") === 0 ? p : "<p>" + p.replace(/\n/g, "<br>") + "</p>";
  }).join("");
}

/* ---------- chat render ---------- */
var chatCol = $("chatCol"), chatScroll = $("chatScroll"), chatTitle = $("chatTitle"),
  backBtn = $("backBtn"), panelBody = $("panelBody"),
  viewChat = $("viewChat"), viewPanel = $("viewPanel");

function openTitle() {
  for (var i = 0; i < current.length; i++) {
    if (current[i] && current[i].role === "user" && String(current[i].content || "").trim())
      return String(current[i].content).trim().slice(0, 60);
  }
  return "New chat";
}
function chipForAttachment(a) {
  var c = document.createElement("div");
  c.className = "chip art-chip";
  c.title = a.name || "attachment";
  var kind = String(a.kind || "");
  if (kind !== "pdf" && kind !== "csv" && a.id) {
    var im = document.createElement("img");
    im.setAttribute("data-up", a.id);
    im.alt = "";
    c.appendChild(im);
  } else {
    var ex = (String(a.name || "").split(".").pop() || "").toLowerCase();
    var b = document.createElement("span");
    b.className = "ext";
    b.textContent = ex.slice(0, 4).toUpperCase() || "FILE";
    c.appendChild(b);
  }
  var n = document.createElement("span");
  n.className = "name";
  n.textContent = a.name || "file";
  c.appendChild(n);
  c.addEventListener("click", function () {
    if (a.id) authedDownload("/api/uploads/" + a.id + "/file", a.name || "file");
  });
  return c;
}
function msgEl(m, idx) {
  var w = document.createElement("div");
  w._i = idx;
  w._raw = String((m && m.content) || "");
  if (m && m.role === "user") {
    w.className = "msg user";
    if (m.attachments && m.attachments.length) {
      var ca = document.createElement("div");
      ca.className = "chips";
      m.attachments.forEach(function (a) { ca.appendChild(chipForAttachment(a)); });
      w.appendChild(ca);
    }
    var b = document.createElement("div");
    b.className = "bubble";
    b.textContent = String(m.content || "");
    w.appendChild(b);
    var mt = document.createElement("div");
    mt.className = "meta";
    mt.innerHTML = "<span>" + esc(fmtTime(m.time)) + '</span><button data-act="copy">Copy</button><button data-act="edit">Edit</button>';
    w.appendChild(mt);
  } else {
    w.className = "msg ai";
    var mark = document.createElement("div");
    mark.className = "mark-p";
    mark.innerHTML = planet(13);
    w.appendChild(mark);
    var body = document.createElement("div");
    body.className = "ai-body";
    var bd = document.createElement("div");
    bd.className = "body";
    bd.innerHTML = md(String((m && m.content) || ""));
    body.appendChild(bd);
    if (m && m.artifacts && m.artifacts.length) {
      var ac = document.createElement("div");
      ac.className = "chips";
      m.artifacts.forEach(function (a) {
        var chip = document.createElement("div");
        chip.className = "chip art-chip";
        chip.title = "Download " + (a.name || "file");
        var badge = document.createElement("span");
        badge.className = "ext";
        badge.textContent = (String(a.name || "").split(".").pop() || "").toLowerCase().slice(0, 4).toUpperCase() || "FILE";
        var nm = document.createElement("span");
        nm.className = "name";
        nm.textContent = a.name || "file";
        chip.appendChild(badge);
        chip.appendChild(nm);
        chip.addEventListener("click", function () {
          authedDownload("/api/artifacts/" + a.id + "/download", a.name || "file");
        });
        ac.appendChild(chip);
      });
      body.appendChild(ac);
    }
    if (m && m.sources && m.sources.length) {
      var sr = document.createElement("div");
      sr.className = "src-row";
      m.sources.slice(0, 6).forEach(function (s) {
        if (!s || !s.url) return;
        var a = document.createElement("a");
        a.href = s.url;
        a.target = "_blank";
        a.rel = "noopener";
        a.textContent = s.domain || s.title || s.url;
        a.title = s.title || s.url;
        sr.appendChild(a);
      });
      body.appendChild(sr);
    }
    var mt2 = document.createElement("div");
    mt2.className = "meta";
    var metaHtml = "<span>" + esc(fmtTime(m.time)) + "</span>";
    if (m && m.model) metaHtml += "<span> · " + esc(m.model) + "</span>";
    metaHtml += '<button data-act="copy">Copy</button><button data-act="regen">Regenerate</button><button data-act="brief">Brief</button>';
    mt2.innerHTML = metaHtml;
    body.appendChild(mt2);
    if (m && m.fallback && m.fallback.requested && m.model && m.fallback.requested !== m.model) {
      var fb = document.createElement("div");
      fb.className = "fb-note";
      fb.textContent = "\u24D8 " + m.fallback.requested + " " + (m.fallback.reason || "unavailable") + " \u2014 answered by " + m.model;
      body.appendChild(fb);
    }
    w.appendChild(body);
  }
  return w;
}
function hydrateUploadImages() {
  chatCol.querySelectorAll("img[data-up]").forEach(function (im) {
    var id = im.getAttribute("data-up");
    fetch(apiUrl("/api/uploads/" + id + "/file"), { headers: authHeaders() }).then(function (res) {
      if (!res.ok) throw new Error("gone");
      return res.blob();
    }).then(function (blob) {
      im.src = URL.createObjectURL(blob);
    }).catch(function () { im.remove(); });
  });
}
/* Regenerated replies: the backend appends each fresh answer, so a
 * run of consecutive assistant messages is one reply's versions.
 * Rendered as a single bubble with a ‹ 1/2 › switcher (latest shown
 * by default); actions apply to the visible version via its index. */
var verSel = {};
function versionGroup(start, end) {
  var n = end - start;
  var key = "v" + start + "x" + n;
  var pos = verSel[key];
  if (!(pos >= 0 && pos < n)) pos = n - 1;
  verSel[key] = pos;
  var wrap = document.createElement("div");
  wrap.className = "ver-group";
  var holder = document.createElement("div");
  wrap.appendChild(holder);
  var lab = null, prev = null, next = null;
  function paint() {
    if (!lab) return;
    lab.textContent = (verSel[key] + 1) + "/" + n;
    prev.disabled = verSel[key] === 0;
    next.disabled = verSel[key] === n - 1;
  }
  function show(p) {
    verSel[key] = p;
    holder.innerHTML = "";
    holder.appendChild(msgEl(current[start + p], start + p));
    paint();
  }
  show(pos);
  if (n > 1) {
    var bar = document.createElement("div");
    bar.className = "ver-bar";
    prev = document.createElement("button");
    prev.textContent = "‹";
    prev.title = "Previous version";
    lab = document.createElement("span");
    next = document.createElement("button");
    next.textContent = "›";
    next.title = "Next version";
    prev.addEventListener("click", function () { if (verSel[key] > 0) show(verSel[key] - 1); });
    next.addEventListener("click", function () { if (verSel[key] < n - 1) show(verSel[key] + 1); });
    paint();
    bar.appendChild(prev);
    bar.appendChild(lab);
    bar.appendChild(next);
    wrap.appendChild(bar);
  }
  return wrap;
}
function renderChat() {
  chatTitle.textContent = openTitle();
  chatCol.innerHTML = "";
  if (!current.length) {
    chatCol.innerHTML = '<div class="empty"><div class="mark">' + planet(20) + "</div><div>Start a new conversation</div></div>";
    return;
  }
  var day = document.createElement("div");
  day.className = "day";
  day.textContent = fmtDay(current[0] && current[0].time);
  chatCol.appendChild(day);
  var seen = {};
  var i = 0;
  while (i < current.length) {
    var m = current[i];
    if (m && m.role === "assistant") {
      var j = i + 1;
      while (j < current.length && current[j] && current[j].role === "assistant") j++;
      if (j - i > 1) {
        seen["v" + i + "x" + (j - i)] = true;
        chatCol.appendChild(versionGroup(i, j));
        i = j;
        continue;
      }
    }
    chatCol.appendChild(msgEl(m, i));
    i++;
  }
  Object.keys(verSel).forEach(function (k) { if (!seen[k]) delete verSel[k]; });
  hydrateUploadImages();
  scrollBottom(true);
}
function maybeScroll() {
  if (chatScroll.scrollHeight - chatScroll.scrollTop - chatScroll.clientHeight < 140) scrollBottom();
}
function scrollBottom() { chatScroll.scrollTop = chatScroll.scrollHeight; }
$("scrollBtn").addEventListener("click", function () { scrollBottom(); });
chatScroll.addEventListener("scroll", function () {
  var far = chatScroll.scrollHeight - chatScroll.scrollTop - chatScroll.clientHeight > 250;
  $("scrollBtn").classList.toggle("hidden", !far);
});

/* ---------- refresh from server ---------- */
async function refreshChats() {
  var data = await req("/api/chats");
  chats = (data && data.chats) || [];
  current = (data && data.current) || [];
  renderRecents();
  renderChat();
}
async function refreshProjects() {
  var data = await req("/api/projects");
  projects = Array.isArray(data) ? data : [];
  if (S.projectId && !projects.some(function (p) { return p && p.id === S.projectId; })) S.projectId = null;
  renderProjects();
}

/* ---------- send (real SSE stream) ---------- */
var input = $("input"), attachments = $("attachments");
var pendingFiles = [];
var streaming = false;
var streamAbort = null;
function sendBtnToStop(on) {
  $("icoSend").classList.toggle("hidden", on);
  $("icoStop").classList.toggle("hidden", !on);
}
function clearComposer() {
  input.value = "";
  input.style.height = "auto";
  attachments.innerHTML = "";
  pendingFiles.forEach(function (f) { if (f._preview) URL.revokeObjectURL(f._preview); });
  pendingFiles = [];
}
async function uploadPending() {
  var out = [];
  for (var i = 0; i < pendingFiles.length; i++) {
    var form = new FormData();
    form.append("file", pendingFiles[i]);
    var res = await fetch(apiUrl("/api/uploads"), { method: "POST", headers: authHeaders(), body: form });
    if (res.status === 401) {
      var tok2 = await authAsync("Log in to continue");
      if (!tok2) throw new Error("Authentication required.");
      setToken(tok2);
      try { await refreshMe(); } catch (e) {}
      return uploadPending();
    }
    if (!res.ok) {
      var detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch (e) {}
      throw new Error(detail);
    }
    out.push(await res.json());
  }
  return out;
}
function streamInto(bodyEl, onMeta) {
  return new Promise(function (resolve, reject) {
    var controller = new AbortController();
    streamAbort = controller;
    var payload = {
      content: streamInto._text,
      upload_ids: streamInto._ids,
      project_id: S.projectId || null,
      deep_mode: S.mode === "deep",
      force_search: !!S.web,
      active_tier: S.model || null
    };
    fetch(apiUrl("/api/chat/stream"), {
      method: "POST",
      headers: Object.assign({ "Content-Type": "application/json" }, authHeaders()),
      body: JSON.stringify(payload),
      signal: controller.signal
    }).then(function (res) {
      if (!res.ok || !res.body) throw new Error("Stream failed: " + res.statusText);
      var reader = res.body.getReader();
      var decoder = new TextDecoder();
      var buf = "";
      var result = null;
      function pump() {
        return reader.read().then(function (step) {
          if (step.done) {
            if (!result) throw new Error("Stream ended without a result.");
            resolve(result);
            return;
          }
          buf += decoder.decode(step.value, { stream: true });
          var parts = buf.split("\n\n");
          buf = parts.pop() || "";
          parts.forEach(function (part) {
            var line = part.trim();
            if (line.indexOf("data: ") !== 0) return;
            var evt;
            try { evt = JSON.parse(line.slice(6)); } catch (e) { return; }
            if (evt.type === "meta" && onMeta) onMeta(evt);
            else if (evt.type === "token") bodyEl.innerHTML = md(evt.text) + '<span class="caret"></span>';
            else if (evt.type === "reset") bodyEl.innerHTML = '<span class="dots"><i></i><i></i><i></i></span>';
            else if (evt.type === "status") bodyEl.innerHTML = '<span class="dots"><i></i><i></i><i></i></span> ' + esc(evt.text || "");
            else if (evt.type === "done") result = evt.result;
            else if (evt.type === "error") throw new Error(evt.detail || "Stream error");
          });
          maybeScroll();
          return pump();
        });
      }
      return pump();
    }).catch(reject);
  });
}
async function sendText(text, files) {
  var atts = files || [];
  if (!text && !atts.length) return;
  if (atts.length > 5) { toast("At most 5 files per message."); return; }
  var uploaded = [];
  if (atts.length) {
    try { uploaded = await uploadPending(); }
    catch (e) { toast("Upload failed: " + e.message); return; }
  }
  var empty = chatCol.querySelector(".empty");
  if (empty) empty.remove();
  /* optimistic user bubble (server state replaces it on refresh) */
  var um = { role: "user", content: text || "(attachment)", time: new Date().toISOString(), attachments: uploaded };
  chatCol.appendChild(msgEl(um, current.length));
  hydrateUploadImages();
  scrollBottom(true);
  var tmp = document.createElement("div");
  tmp.className = "msg ai";
  tmp.innerHTML = '<div class="mark-p">' + planet(13) + '</div><div class="ai-body"><div class="body"><span class="dots"><i></i><i></i><i></i></span></div></div>';
  chatCol.appendChild(tmp);
  scrollBottom(true);
  streaming = true;
  sendBtnToStop(true);
  streamInto._text = text || "(attachment)";
  streamInto._ids = uploaded.map(function (a) { return a.id; });
  try {
    var result = await streamInto(tmp.querySelector(".body"), function (meta) {
      if (meta && meta.active_tier) setActiveTier(meta.active_tier, true, meta.fallback && meta.fallback.reason);
    });
    if (result && result.warnings && result.warnings.length) toast(result.warnings[0]);
    if (result && result.active_tier) setActiveTier(result.active_tier, true, result.fallback && result.fallback.reason);
    await refreshChats();
    if (!$("viewPanel").classList.contains("hidden") && panelBody.getAttribute("data-section") === "artifacts")
      openSection("artifacts");
  } catch (e) {
    if (e && e.name === "AbortError") {
      try { await refreshChats(); } catch (ignored) { tmp.remove(); }
    } else {
      tmp.querySelector(".body").innerHTML = "<p>Error: " + esc(e.message) + "</p>";
      toast("Send failed: " + e.message);
    }
  } finally {
    streaming = false;
    streamAbort = null;
    sendBtnToStop(false);
  }
}
function send() {
  if (streaming) {
    if (streamAbort) streamAbort.abort();
    return;
  }
  var text = input.value.trim();
  var files = pendingFiles.slice();
  if (!text && !files.length) return;
  clearComposer();
  sendText(text, files);
}
$("sendBtn").addEventListener("click", send);
input.addEventListener("keydown", function (e) {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
});
input.addEventListener("input", function () {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 160) + "px";
});

/* ---------- message actions ---------- */
function copyText(t) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(t).then(function () { toast("Copied"); }, function () { legacyCopy(t); });
  } else legacyCopy(t);
}
function legacyCopy(t) {
  var ta = document.createElement("textarea");
  ta.value = t;
  document.body.appendChild(ta);
  ta.select();
  try { document.execCommand("copy"); toast("Copied"); } catch (e) { toast("Copy failed"); }
  ta.remove();
}
chatCol.addEventListener("click", async function (e) {
  var btn = e.target.closest("[data-act]");
  if (!btn) return;
  var msg = btn.closest(".msg");
  var i = msg._i;
  var act = btn.getAttribute("data-act");
  if (act === "copy") { copyText(msg._raw); }
  else if (act === "edit") {
    if (streaming) { toast("Wait for the current reply"); return; }
    var old = msg._raw;
    msg.innerHTML = "";
    var ta = document.createElement("textarea");
    ta.className = "edit-ta";
    ta.value = old;
    var acts = document.createElement("div");
    acts.className = "edit-actions";
    var cn = document.createElement("button");
    cn.className = "edit-cancel";
    cn.title = "Cancel (Esc)";
    cn.textContent = "✕";
    cn.setAttribute("data-act", "cancel");
    var sv = document.createElement("button");
    sv.className = "edit-save";
    sv.title = "Save & resend (Enter)";
    sv.setAttribute("data-act", "save");
    sv.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M12 19V5"/><path d="m5 12 7-7 7 7"/></svg>';
    acts.appendChild(cn);
    acts.appendChild(sv);
    msg.appendChild(ta);
    msg.appendChild(acts);
    ta.focus();
    ta.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); sv.click(); }
      if (ev.key === "Escape") { ev.stopPropagation(); cn.click(); }
    });
  }
  else if (act === "cancel") { renderChat(); }
  else if (act === "save") {
    if (streaming) { toast("Wait for the current reply"); return; }
    var v = (msg.querySelector(".edit-ta").value || "").trim();
    if (!v) { renderChat(); return; }
    try {
      await req("/api/chats/truncate", { method: "POST", body: JSON.stringify({ index: i }) });
      toast("Resending…");
      sendText(v, []);
    } catch (err) { toast("Edit failed: " + err.message); renderChat(); }
  }
  else if (act === "regen") {
    if (streaming) { toast("Wait for the current reply"); return; }
    var bd = msg.querySelector(".body");
    bd.innerHTML = '<span class="dots"><i></i><i></i><i></i></span>';
    try {
      await req("/api/chat/regenerate", {
        method: "POST",
        body: JSON.stringify({
          index: i, project_id: S.projectId || null,
          deep_mode: S.mode === "deep", force_search: !!S.web,
          active_tier: S.model || null
        })
      });
      await refreshChats();
    } catch (err) {
      toast("Regenerate failed: " + err.message);
      try { await refreshChats(); } catch (ignored) { renderChat(); }
    }
  }
  else if (act === "brief") {
    try {
      await req("/api/briefs", {
        method: "POST",
        body: JSON.stringify({ index: i, project_id: S.projectId || null })
      });
      toast("Saved to Research");
      if (!$("viewPanel").classList.contains("hidden") && panelBody.getAttribute("data-section") === "research")
        openSection("research");
    } catch (err) { toast("Cannot save brief: " + err.message); }
  }
});

/* ---------- recents / projects ---------- */
var ctxId = null;
function renderRecents() {
  var f = $("sideSearch").value.toLowerCase();
  var el = $("recentList");
  el.innerHTML = "";
  chats.forEach(function (c) {
    var title = String((c && c.title) || "Untitled");
    if (f && title.toLowerCase().indexOf(f) < 0) return;
    var d = document.createElement("div");
    d.className = "recent";
    d.setAttribute("data-id", c.id);
    var sp = document.createElement("span");
    sp.textContent = title;
    var kb = document.createElement("button");
    kb.className = "kebab";
    kb.textContent = "⋯";
    kb.title = "Options";
    d.appendChild(sp);
    d.appendChild(kb);
    d.addEventListener("click", async function (e) {
      if (e.target === kb) return;
      try {
        var data = await req("/api/chats/open", { method: "POST", body: JSON.stringify({ id: c.id }) });
        chats = data.chats || [];
        current = data.current || [];
        renderRecents();
        renderChat();
        showChat();
      } catch (err) { toast("Cannot open chat: " + err.message); }
      if (window.innerWidth < 861) document.body.classList.add("folded");
    });
    kb.addEventListener("click", function (e) {
      e.stopPropagation();
      ctxId = c.id;
      var r = kb.getBoundingClientRect();
      var m = $("ctxMenu");
      m.classList.remove("hidden");
      m.style.left = Math.min(r.left, window.innerWidth - 170) + "px";
      m.style.top = Math.min(r.bottom + 6, window.innerHeight - 90) + "px";
    });
    el.appendChild(d);
  });
}
var projId = null;
function renderProjects() {
  var el = $("projList");
  el.innerHTML = "";
  function addRow(id, name) {
    var wrap = document.createElement("div");
    wrap.className = "prow";
    var b = document.createElement("button");
    b.className = "nav" + ((S.projectId || null) === id ? " active" : "");
    b.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"><path d="M20 20a2 2 0 0 0 2-2v16a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7z"/></svg>';
    b.appendChild(document.createTextNode(name));
    b.addEventListener("click", function () {
      S.projectId = id;
      savePrefs();
      renderProjects();
      toast(id ? "Project: " + name : "Project: Personal");
      if (window.innerWidth < 861) document.body.classList.add("folded");
    });
    wrap.appendChild(b);
    if (id) {
      var kb = document.createElement("button");
      kb.className = "kebab";
      kb.textContent = "⋯";
      kb.title = "Project options";
      kb.addEventListener("click", function (e) {
        e.stopPropagation();
        projId = id;
        var r = kb.getBoundingClientRect();
        var m = $("projMenu");
        m.classList.remove("hidden");
        m.style.left = Math.min(r.left, window.innerWidth - 170) + "px";
        m.style.top = Math.min(r.bottom + 6, window.innerHeight - 120) + "px";
      });
      wrap.appendChild(kb);
    }
    el.appendChild(wrap);
  }
  addRow(null, "Personal");
  projects.forEach(function (p) { if (p && p.id) addRow(p.id, p.name || "Untitled"); });
}
$("projRename").addEventListener("click", function () {
  $("projMenu").classList.add("hidden");
  var p = projects.filter(function (x) { return x && x.id === projId; })[0];
  if (!p) return;
  ask("Rename project", p.name || "", async function (v) {
    if (!v) return;
    try {
      await req("/api/projects/" + projId, { method: "PATCH", body: JSON.stringify({ name: v }) });
      await refreshProjects();
      toast("Renamed");
    } catch (err) { toast("Rename failed: " + err.message); }
  });
});
$("projContext").addEventListener("click", function () {
  $("projMenu").classList.add("hidden");
  if (!projId) return;
  S.projectId = projId;
  savePrefs();
  renderProjects();
  openSection("project");
});
$("projArchive").addEventListener("click", async function () {
  $("projMenu").classList.add("hidden");
  if (!projId) return;
  try {
    await req("/api/projects/" + projId + "/archive", { method: "POST" });
    if (S.projectId === projId) { S.projectId = null; savePrefs(); }
    await refreshProjects();
    toast("Project archived");
  } catch (err) { toast("Archive failed: " + err.message); }
});
$("addProjBtn").addEventListener("click", function () {
  ask("New project name", "", async function (v) {
    if (!v) return;
    try {
      var rec = await req("/api/projects", { method: "POST", body: JSON.stringify({ name: v }) });
      await refreshProjects();
      if (rec && rec.id) { S.projectId = rec.id; savePrefs(); renderProjects(); }
      toast('Project "' + v + '" added');
    } catch (err) { toast("Cannot create project: " + err.message); }
  });
});
$("sideSearch").addEventListener("input", renderRecents);
$("ctxRename").addEventListener("click", function () {
  $("ctxMenu").classList.add("hidden");
  var c = chats.filter(function (x) { return x && x.id === ctxId; })[0];
  if (!c) return;
  ask("Rename chat", c.title || "", async function (v) {
    if (!v) return;
    try {
      var data = await req("/api/chats/" + ctxId, { method: "PATCH", body: JSON.stringify({ title: v }) });
      chats = data.chats || chats;
      renderRecents();
      toast("Renamed");
    } catch (err) { toast("Rename failed: " + err.message); }
  });
});
$("ctxDelete").addEventListener("click", async function () {
  $("ctxMenu").classList.add("hidden");
  if (!ctxId) return;
  try {
    var data = await req("/api/chats/" + ctxId, { method: "DELETE" });
    chats = data.chats || [];
    current = data.current || current;
    renderRecents();
    renderChat();
    toast("Chat deleted");
  } catch (err) { toast("Delete failed: " + err.message); }
});
document.addEventListener("click", function (e) {
  if (!$("ctxMenu").contains(e.target)) $("ctxMenu").classList.add("hidden");
  if (!$("projMenu").contains(e.target)) $("projMenu").classList.add("hidden");
  if (!$("modelDD").contains(e.target) && !$("modelBtn").contains(e.target)) $("modelDD").classList.add("hidden");
});

/* ---------- new chat / export ---------- */
$("newChatBtn").addEventListener("click", async function () {
  try {
    var data = await req("/api/chats/new", {
      method: "POST",
      body: JSON.stringify({ project_id: S.projectId || null, chat_id: null })
    });
    chats = data.chats || [];
    current = data.current || [];
  } catch (err) { toast("Cannot start chat: " + err.message); return; }
  renderRecents();
  renderChat();
  showChat();
  if (window.innerWidth < 861) document.body.classList.add("folded");
  input.focus();
});
$("exportBtn").addEventListener("click", function () {
  var title = openTitle();
  var lines = ["# " + title, ""];
  current.forEach(function (m) {
    lines.push("**" + (m.role === "user" ? "You" : "Pluto") + "** · " + (fmtTime(m.time) || ""));
    if (m.attachments && m.attachments.length)
      lines.push("_Attachments: " + m.attachments.map(function (a) { return a.name; }).join(", ") + "_");
    lines.push(String(m.content || ""), "");
    if (m.sources && m.sources.length) {
      lines.push("Sources:");
      m.sources.forEach(function (s) { lines.push("- " + (s.title || s.url) + " (" + s.url + ")"); });
      lines.push("");
    }
  });
  var blob = new Blob([lines.join("\n")], { type: "text/markdown" });
  var a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = (title.replace(/[^\w\- ]+/g, "").trim() || "chat") + ".md";
  a.click();
  setTimeout(function () { URL.revokeObjectURL(a.href); }, 500);
  toast("Chat exported");
});

/* ---------- models (server-driven) ---------- */
var _lastFallbackKey = "";
var _lastFallbackAt = 0;
function setActiveTier(tier, fromServer, reason) {
  if (tier && TIERS.indexOf(tier) > -1 && !fromServer) {
    S.model = tier;
    savePrefs();
    _lastFallbackKey = "";
  } else if (fromServer && tier && TIERS.indexOf(tier) > -1 && S.model && tier !== S.model) {
    /* Cascade fallback: S.model is the preferred tier (selector/footer),
       tier is the tier that actually answered (per-message "time · tier"
       label + persistent notice). Preference is kept so the next turn
       retries it. Works for every model: reason comes from the failed
       tier's classified error (rate-limited, timed out, ...). */
    var why = reason || "unavailable";
    var key = S.model + ">" + tier + ">" + why;
    var now = Date.now();
    if (key !== _lastFallbackKey || now - _lastFallbackAt > 5000) {
      _lastFallbackKey = key;
      _lastFallbackAt = now;
      toast("Preferred " + S.model + " " + why + " — answered by " + tier);
    }
  }
  $("modelName").textContent = S.model || "…";
  renderAcct();
}
function renderModelDD() {
  var dd = $("modelDD");
  dd.innerHTML = "";
  if (!TIERS.length) {
    var b = document.createElement("button");
    b.textContent = "No models configured";
    b.disabled = true;
    dd.appendChild(b);
    return;
  }
  TIERS.forEach(function (m) {
    var btn = document.createElement("button");
    btn.textContent = (m === S.model ? "✓ " : "") + m;
    if (m === S.model) btn.className = "on";
    btn.addEventListener("click", function () {
      S.model = m;
      savePrefs();
      setActiveTier(m, false);
      dd.classList.add("hidden");
      toast("Model: " + m);
    });
    dd.appendChild(btn);
  });
}
$("modelBtn").addEventListener("click", function (e) {
  e.stopPropagation();
  renderModelDD();
  $("modelDD").classList.toggle("hidden");
});
$("accountBtn").addEventListener("click", function () {
  if (ACCT.username) {
    ask("Signed in as " + ACCT.username + ". Type OUT to sign out", "", function (v) {
      if (v !== null && v.trim().toUpperCase() === "OUT") signOut();
    });
    return;
  }
  /* Logged out (with or without a stale operator token): always open
   * the real login dialog — it has Log in, Sign up, and Use token. */
  showAuth("Log in to Pluto");
});
if ($("loginBtn")) $("loginBtn").addEventListener("click", function () {
  if (ACCT.username) return;
  showAuth("Log in to Pluto");
});
$("authCancel").addEventListener("click", function () { settleAuth(null); });
$("authTokenBtn").addEventListener("click", function () {
  hideAuth();
  ask("Access token (empty clears it)", "", function (v) {
    if (v === null) { settleAuth(null); return; }
    setToken(v);
    refreshMe();
    toast(v ? "Token saved" : "Token cleared");
    settleAuth(v || null);
  });
});
$("authLogin").addEventListener("click", function () { authSubmit("/api/auth/login"); });
$("authSignup").addEventListener("click", function () { authSubmit("/api/auth/signup"); });
$("authPass").addEventListener("keydown", function (e) {
  if (e.key === "Enter") authSubmit("/api/auth/login");
  if (e.key === "Escape") settleAuth(null);
});
$("authUser").addEventListener("keydown", function (e) {
  if (e.key === "Enter") authSubmit("/api/auth/login");
  if (e.key === "Escape") settleAuth(null);
});

/* ---------- theme ---------- */
function applyTheme() {
  document.documentElement.setAttribute("data-theme", S.theme);
  $("icoMoon").classList.toggle("hidden", S.theme === "light");
  $("icoSun").classList.toggle("hidden", S.theme !== "light");
}
$("themeBtn").addEventListener("click", function () {
  S.theme = S.theme === "dark" ? "light" : "dark";
  savePrefs();
  applyTheme();
});

/* ---------- view switching ---------- */
function setActiveNav(el) {
  var a = document.querySelectorAll(".nav.active,.recent.active");
  for (var i = 0; i < a.length; i++) a[i].classList.remove("active");
  if (el) el.classList.add("active");
}
async function openSection(name) {
  var def = SECTIONS[name];
  if (!def) return;
  viewChat.classList.add("hidden");
  viewPanel.classList.remove("hidden");
  backBtn.classList.remove("hidden");
  chatTitle.textContent = def.title;
  panelBody.setAttribute("data-section", name);
  panelBody.innerHTML = '<div class="sub" style="margin-top:16px">Loading…</div>';
  setActiveNav(document.querySelector('.nav[data-section="' + name + '"]'));
  try {
    panelBody.innerHTML = await def.render();
  } catch (err) {
    panelBody.innerHTML = '<div class="sub" style="margin-top:16px">Could not load: ' + esc(err.message) + "</div>";
  }
}
function showChat() {
  viewPanel.classList.add("hidden");
  viewChat.classList.remove("hidden");
  backBtn.classList.add("hidden");
  panelBody.setAttribute("data-section", "");
  chatTitle.textContent = openTitle();
  setActiveNav(null);
}
backBtn.addEventListener("click", showChat);
document.querySelectorAll("[data-section]").forEach(function (btn) {
  btn.addEventListener("click", function () {
    openSection(btn.getAttribute("data-section"));
    if (window.innerWidth < 861) document.body.classList.add("folded");
  });
});

/* ---------- panels (all server data) ---------- */
function allMessages() {
  var out = [];
  chats.forEach(function (c) {
    (c.messages || []).forEach(function (m) { out.push(m); });
  });
  current.forEach(function (m) { out.push(m); });
  return out;
}
function showWfResult(out) {
  var box = $("wfResult");
  var status = String((out && out.status) || "?");
  if (!box) { toast("Workflow " + status); return; }
  var html = '<div class="card"><div class="g"><div class="t">Status: ' + esc(status) + "</div>" +
    ((out && out.error) ? '<div class="s">' + esc(String(out.error)) + "</div>" : "") + "</div></div>";
  html += ((out && out.steps) || []).map(function (s, i) {
    var o = String((s && s.output) || "");
    if (o.length > 500) o = o.slice(0, 500) + "…";
    return '<div class="card"><div class="g"><div class="t">Step ' + (i + 1) + ": " + esc(String((s && s.tool) || "?")) + "</div>" +
      '<div class="s">' + esc(o) + "</div></div></div>";
  }).join("");
  box.innerHTML = html;
}
var SECTIONS = {
  research: {
    title: "Research",
    render: async function () {
      var briefs = await req("/api/briefs");
      if (!Array.isArray(briefs)) briefs = [];
      var rows = briefs.map(function (x) {
        var title = x.query || x.title || "Untitled brief";
        var nsrc = (x.sources || []).length;
        var sub = (fmtStamp(x.created) ? fmtStamp(x.created) + " · " : "") + nsrc + " source" + (nsrc === 1 ? "" : "s");
        return '<div class="card" data-title="' + esc(String(title).toLowerCase()) + '" data-bid="' + esc(x.id) + '">' + ic("flask") +
          '<div class="g"><div class="t">' + esc(title) + '</div><div class="s">' + esc(sub) + "</div></div>" +
          '<span class="pill">Saved</span>' +
          '<button class="row-btn" data-brief="docx" title="Download Word document">' + IC.down + "</button>" +
          '<button class="row-btn" data-brief="del" title="Delete">✕</button></div>';
      }).join("");
      if (!briefs.length) rows = '<div class="sub" style="margin-top:16px">No saved research yet. Answers with web sources can be saved here via the Brief button.</div>';
      return "<h2>Research</h2><div class=\"sub\">Saved research briefs with cited sources.</div>" +
        '<input class="input panel-input" id="researchFilter" type="text" placeholder="Filter research…">' +
        '<div class="cards" id="researchList">' + rows + "</div>";
    }
  },
  workflows: {
    title: "Workflows",
    render: async function () {
      var list = [];
      try {
        var data = await req("/api/workflows");
        if (data && Array.isArray(data.workflows)) list = data.workflows;
      } catch (e) {
        return "<h2>Workflows</h2><div class=\"sub\">Cannot load workflows: " + esc(e.message) + "</div>";
      }
      var rows = list.map(function (w) {
        var nsteps = (w.steps || []).length;
        var sub = nsteps + " step" + (nsteps === 1 ? "" : "s") + (w.description ? " · " + w.description : "");
        return '<div class="card" data-wfid="' + esc(w.id) + '">' + ic("flask") +
          '<div class="g"><div class="t">' + esc(w.name || "Untitled") + '</div><div class="s">' + esc(sub) + "</div></div>" +
          '<button class="row-btn second" data-wfrun="' + esc(w.id) + '" title="Run">▶</button>' +
          '<button class="row-btn" data-wfdel="' + esc(w.id) + '" title="Delete">✕</button></div>';
      }).join("");
      if (!list.length) rows = '<div class="sub" style="margin-top:16px">No workflows yet. Save a fixed tool sequence below and run it anytime.</div>';
      return "<h2>Workflows</h2><div class=\"sub\">Saved tool pipelines. Steps are JSON with {{input}} and {{steps.N.output}} templates; send_gmail is blocked.</div>" +
        '<div class="cards" id="wfList">' + rows + "</div>" +
        "<h2 style=\"margin-top:22px\">New workflow</h2>" +
        '<input class="input panel-input" id="wfName" type="text" placeholder="Name">' +
        '<input class="input panel-input" id="wfDesc" type="text" placeholder="Description (optional)">' +
        '<textarea class="notes-ta" id="wfSteps" placeholder="Steps JSON array"></textarea>' +
        '<div class="notes-actions"><button class="btn solid" id="wfSave">Save workflow</button></div>' +
        '<div id="wfResult"></div>';
    }
  },
  project: {
    title: "Project",
    render: async function () {
      var p = null;
      projects.forEach(function (x) { if (x && x.id === S.projectId) p = x; });
      if (!p) return "<h2>Project</h2><div class=\"sub\">Select a project first.</div>";
      var text = "";
      try {
        text = (await req("/api/projects/" + p.id + "/context")).text || "";
      } catch (e) {
        return "<h2>" + esc(p.name || "Project") + "</h2><div class=\"sub\">Cannot load context: " + esc(e.message) + "</div>";
      }
      return "<h2>" + esc(p.name || "Project") + "</h2><div class=\"sub\">Context is sent with every message in this project.</div>" +
        '<textarea class="notes-ta" id="projCtxTa" data-projid="' + esc(p.id) + '">' + esc(text) + "</textarea>" +
        '<div class="notes-actions"><button class="btn solid" id="projCtxSave">Save context</button></div>';
    }
  },
  memory: {
    title: "Memory",
    render: async function () {
      var notes = "";
      var facts = [];
      try { notes = (await req("/api/memory/notes")).text || ""; } catch (e) {}
      try {
        var f = await req("/api/memory/facts");
        facts = Array.isArray(f) ? f : [];
      } catch (e) {}
      var rows = facts.map(function (m, i) {
        var label = String((m && m.value) || "");
        var sub = m && m.type ? String(m.type) : "";
        return '<div class="card">' + ic("cpu") +
          '<div class="g"><div class="t">' + esc(label) + "</div>" + (sub ? '<div class="s">' + esc(sub) + "</div>" : "") + "</div>" +
          '<button class="forget" data-fact="' + i + '">Forget</button></div>';
      }).join("");
      if (!facts.length) rows = '<div class="sub" style="margin-top:16px">Nothing remembered yet.</div>';
      return "<h2>Memory</h2><div class=\"sub\">Things Pluto remembers across conversations.</div>" +
        '<textarea class="notes-ta" id="notesTa" placeholder="Memory notes…">' + esc(notes) + "</textarea>" +
        '<div class="notes-actions"><button class="btn solid" id="notesSave">Save notes</button></div>' +
        '<div class="cards">' + rows + "</div>";
    }
  },
  files: {
    title: "Files",
    render: async function () {
      var list = await req("/api/uploads");
      if (!Array.isArray(list)) list = [];
      var rows = list.map(function (f) {
        return '<div class="card" data-up="' + esc(f.id) + '">' + ic("doc") +
          '<div class="g"><div class="t">' + esc(f.name) + '</div><div class="s">' + esc(f.kind || "file") + "</div></div>" +
          '<button class="row-btn" title="Download">' + IC.down + "</button></div>";
      }).join("");
      if (!list.length) rows = '<div class="sub" style="margin-top:16px">No files yet. Attach one from the composer.</div>';
      return "<h2>Files</h2><div class=\"sub\">Documents shared in this workspace.</div><div class=\"cards\">" + rows + "</div>";
    }
  },
  artifacts: {
    title: "Artifacts",
    render: async function () {
      var list = await req("/api/artifacts");
      if (!Array.isArray(list)) list = [];
      var rows = list.map(function (a) {
        return '<div class="art" data-art="' + esc(a.id) + '" data-name="' + esc(a.name || "file") + '"><div class="th">' + IC[artIcon(a.kind)] + "</div>" +
          '<div class="b"><div class="t">' + esc(a.name || "file") + '</div><div class="s">' + esc(a.sub || a.kind || "") + "</div></div>" +
          '<button class="row-btn second" data-regen="' + esc(a.id) + '" title="Regenerate">↻</button>' +
          '<button class="row-btn" data-delart="' + esc(a.id) + '" title="Delete">✕</button></div>';
      }).join("");
      if (!list.length) rows = '<div class="sub" style="margin-top:16px">No artifacts yet. Ask Pluto to build a presentation or document.</div>';
      return "<h2>Artifacts</h2><div class=\"sub\">Generated documents, code, and visuals. Click to download.</div><div class=\"grid\">" + rows + "</div>";
    }
  },
  sources: {
    title: "Sources",
    render: async function () {
      var seen = {};
      var items = [];
      allMessages().forEach(function (m) {
        (m.sources || []).forEach(function (s) {
          if (!s || !s.url || seen[s.url]) return;
          seen[s.url] = true;
          items.push(s);
        });
      });
      var rows = items.map(function (x) {
        var label = x.title || x.url;
        return '<div class="card"><div class="card-ic">' + esc(String(label).charAt(0).toUpperCase()) + "</div>" +
          '<div class="g"><div class="t">' + esc(label) + '</div><div class="s">' + esc(x.domain || x.url) + "</div></div>" +
          '<button class="row-btn" data-open="' + esc(x.url) + '" title="Open">' + IC.open + "</button></div>";
      }).join("");
      if (!items.length) rows = '<div class="sub" style="margin-top:16px">No cited sources yet. Use Search for answers with citations.</div>';
      return "<h2>Sources</h2><div class=\"sub\">Cited sources from your conversations.</div><div class=\"cards\">" + rows + "</div>";
    }
  },
  stats: {
    title: "Stats",
    render: async function () {
      var msgs = allMessages();
      var uploads = [];
      var arts = [];
      try { uploads = (await req("/api/uploads")) || []; } catch (e) {}
      try { arts = (await req("/api/artifacts")) || []; } catch (e) {}
      if (!Array.isArray(uploads)) uploads = [];
      if (!Array.isArray(arts)) arts = [];
      var days = [], counts = [];
      for (var d = 6; d >= 0; d--) {
        var day = new Date();
        day.setHours(0, 0, 0, 0);
        day.setDate(day.getDate() - d);
        var next = new Date(day.getTime() + 86400000);
        var n = 0;
        msgs.forEach(function (m) {
          var t = new Date(m.time).getTime();
          if (!isNaN(t) && t >= day.getTime() && t < next.getTime()) n++;
        });
        days.push(day.toLocaleDateString([], { weekday: "short" }));
        counts.push(n);
      }
      var max = Math.max.apply(null, counts.concat([1]));
      var bh = counts.map(function (v) {
        return '<i style="height:' + Math.max(3, Math.round((v / max) * 100)) + '%" title="' + v + ' messages"></i>';
      }).join("");
      var dh = days.map(function (x) { return "<div>" + x + "</div>"; }).join("");
      var nchats = chats.length + (current.length ? 1 : 0);
      return "<h2>Stats</h2><div class=\"sub\">Your usage over the last 7 days.</div>" +
        '<div class="stats"><div class="stat"><b>' + msgs.length + "</b><span>Messages</span></div>" +
        '<div class="stat"><b>' + nchats + "</b><span>Chats</span></div>" +
        '<div class="stat"><b>' + uploads.length + "</b><span>Files</span></div>" +
        '<div class="stat"><b>' + arts.length + "</b><span>Artifacts</span></div></div>" +
        '<div class="chart"><h4>Messages per day</h4><div class="bars">' + bh + '</div><div class="days">' + dh + "</div></div>";
    }
  }
};

/* panel interactions (delegated) */
panelBody.addEventListener("click", async function (e) {
  var rm = e.target.closest("[data-fact]");
  if (rm) {
    try {
      await req("/api/memory/facts", { method: "DELETE", body: JSON.stringify({ ref: rm.getAttribute("data-fact") }) });
      rm.closest(".card").remove();
      toast("Forgotten");
    } catch (err) { toast("Forget failed: " + err.message); }
    return;
  }
  if (e.target.closest("#notesSave")) {
    try {
      await req("/api/memory/notes", { method: "PUT", body: JSON.stringify({ text: $("notesTa").value }) });
      toast("Notes saved");
    } catch (err) { toast("Save failed: " + err.message); }
    return;
  }
  var up = e.target.closest("[data-up]");
  if (up) {
    var card = up.closest(".card");
    var nm = card ? card.querySelector(".t").textContent : "file";
    authedDownload("/api/uploads/" + up.getAttribute("data-up") + "/file", nm);
    return;
  }
  var rg = e.target.closest("[data-regen]");
  if (rg) {
    e.stopPropagation();
    try {
      await req("/api/artifacts/" + rg.getAttribute("data-regen") + "/regenerate", { method: "POST" });
      toast("Regenerated");
      openSection("artifacts");
    } catch (err) { toast("Regenerate failed: " + err.message); }
    return;
  }
  var da = e.target.closest("[data-delart]");
  if (da) {
    e.stopPropagation();
    try {
      await req("/api/artifacts/" + da.getAttribute("data-delart"), { method: "DELETE" });
      toast("Artifact deleted");
      openSection("artifacts");
    } catch (err) { toast("Delete failed: " + err.message); }
    return;
  }
  var art = e.target.closest("[data-art]");
  if (art) {
    authedDownload("/api/artifacts/" + art.getAttribute("data-art") + "/download", art.getAttribute("data-name") || "file");
    return;
  }
  var bb = e.target.closest("[data-brief]");
  if (bb) {
    var bid = bb.closest(".card").getAttribute("data-bid");
    if (bb.getAttribute("data-brief") === "del") {
      try {
        await req("/api/briefs/" + bid, { method: "DELETE" });
        toast("Brief deleted");
        openSection("research");
      } catch (err) { toast("Delete failed: " + err.message); }
    } else {
      try {
        var meta = await req("/api/briefs/" + bid + "/docx", { method: "POST" });
        if (meta && meta.id) authedDownload("/api/artifacts/" + meta.id + "/download", meta.name || "brief.docx");
        else toast("Document queued — see Artifacts");
      } catch (err) { toast("Export failed: " + err.message); }
    }
    return;
  }
  var op = e.target.closest("[data-open]");
  if (op) {
    window.open(op.getAttribute("data-open"), "_blank", "noopener");
    return;
  }
  if (e.target.closest("#wfSave")) {
    var wname = ($("wfName").value || "").trim();
    var wdesc = ($("wfDesc").value || "").trim();
    var wsteps;
    try {
      wsteps = JSON.parse($("wfSteps").value || "[]");
      if (!Array.isArray(wsteps)) throw new Error("not an array");
    } catch (err) { toast("Steps must be a JSON array"); return; }
    try {
      await req("/api/workflows", { method: "POST", body: JSON.stringify({ name: wname, description: wdesc, steps: wsteps }) });
      toast("Workflow saved");
      openSection("workflows");
    } catch (err) { toast("Save failed: " + err.message); }
    return;
  }
  var wr = e.target.closest("[data-wfrun]");
  if (wr) {
    e.stopPropagation();
    var wid = wr.closest(".card").getAttribute("data-wfid");
    ask("Run input (empty for none)", "", async function (v) {
      if (v === null) return;
      try {
        var out = await req("/api/workflows/" + wid + "/run", { method: "POST", body: JSON.stringify({ input: v || "" }) });
        showWfResult(out);
      } catch (err) { toast("Run failed: " + err.message); }
    });
    return;
  }
  var wd = e.target.closest("[data-wfdel]");
  if (wd) {
    e.stopPropagation();
    var did = wd.closest(".card").getAttribute("data-wfid");
    try {
      await req("/api/workflows/" + did, { method: "DELETE" });
      toast("Workflow deleted");
      openSection("workflows");
    } catch (err) { toast("Delete failed: " + err.message); }
    return;
  }
  if (e.target.closest("#projCtxSave")) {
    var ta = $("projCtxTa");
    try {
      await req("/api/projects/" + ta.getAttribute("data-projid") + "/context", { method: "PUT", body: JSON.stringify({ text: ta.value }) });
      toast("Context saved");
    } catch (err) { toast("Save failed: " + err.message); }
    return;
  }
});
panelBody.addEventListener("input", function (e) {
  if (e.target.id === "researchFilter") {
    var q = e.target.value.toLowerCase();
    panelBody.querySelectorAll("#researchList .card").forEach(function (c) {
      c.style.display = c.getAttribute("data-title").indexOf(q) > -1 ? "" : "none";
    });
  }
});
$("moreToggle").addEventListener("click", function () {
  var c = $("moreItems").classList.toggle("collapsed");
  $("moreToggle").classList.toggle("collapsed", c);
});
$("foldBtn").addEventListener("click", function () {
  document.body.classList.toggle("folded");
  if (window.innerWidth > 860) {
    S.folded = document.body.classList.contains("folded");
    savePrefs();
  }
});
$("backdrop").addEventListener("click", function () { document.body.classList.add("folded"); });

/* ---------- attachments ---------- */
var composer = $("composer"), attachWrap = $("attachWrap"), attachMenu = $("attachMenu"),
  photoInput = $("photoInput"), docInput = $("docInput");
function addChip(file) {
  if (file.type && file.type.indexOf("image/") === 0) {
    file._preview = URL.createObjectURL(file);
  }
  var chip = document.createElement("div");
  chip.className = "chip";
  if (file._preview) {
    var im = document.createElement("img");
    im.src = file._preview;
    chip.appendChild(im);
  } else {
    var ex = (file.name.split(".").pop() || "").toLowerCase();
    var badge = document.createElement("span");
    badge.className = "ext";
    badge.textContent = ex.slice(0, 4).toUpperCase() || "FILE";
    chip.appendChild(badge);
  }
  var n = document.createElement("span");
  n.className = "name";
  n.textContent = file.name;
  n.title = file.name;
  var s = document.createElement("span");
  s.className = "size";
  s.textContent = fmtSize(file.size);
  var x = document.createElement("button");
  x.className = "chip-x";
  x.textContent = "✕";
  x.title = "Remove";
  x.addEventListener("click", function () {
    if (file._preview) URL.revokeObjectURL(file._preview);
    pendingFiles = pendingFiles.filter(function (p) { return p !== file; });
    chip.remove();
  });
  chip.appendChild(n);
  chip.appendChild(s);
  chip.appendChild(x);
  attachments.appendChild(chip);
  pendingFiles.push(file);
}
function addFiles(list) { for (var i = 0; i < list.length; i++) addChip(list[i]); }
function closeAttachMenu() { attachMenu.classList.remove("open"); }
$("attachBtn").addEventListener("click", function (e) {
  e.stopPropagation();
  attachMenu.classList.toggle("open");
});
document.addEventListener("click", function (e) {
  if (!attachWrap.contains(e.target)) closeAttachMenu();
});
attachMenu.querySelectorAll("button").forEach(function (opt) {
  opt.addEventListener("click", function () {
    closeAttachMenu();
    var k = opt.getAttribute("data-attach");
    if (k === "camera") openCamera();
    if (k === "photos") photoInput.click();
    if (k === "files") docInput.click();
  });
});
photoInput.addEventListener("change", function () { addFiles(photoInput.files); photoInput.value = ""; });
docInput.addEventListener("change", function () { addFiles(docInput.files); docInput.value = ""; });

/* ---------- camera ---------- */
var camModal = $("camModal"), camVideo = $("camVideo"), camCanvas = $("camCanvas"),
  camError = $("camError"), camShot = $("camShot"), camRetake = $("camRetake"),
  camUse = $("camUse"), camCancel = $("camCancel"), camStream = null, shotTaken = false;
function openCamera() {
  camModal.classList.remove("hidden");
  camError.classList.add("hidden");
  camCanvas.classList.add("hidden");
  camVideo.classList.remove("hidden");
  camRetake.classList.add("hidden");
  camUse.classList.add("hidden");
  camShot.classList.remove("hidden");
  camShot.disabled = false;
  shotTaken = false;
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    camVideo.classList.add("hidden");
    camShot.disabled = true;
    camError.textContent = "Camera is not supported in this browser.";
    camError.classList.remove("hidden");
    return;
  }
  navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment", width: { ideal: 1280 }, height: { ideal: 960 } }, audio: false })
    .then(function (st) { camStream = st; camVideo.srcObject = st; })
    .catch(function () {
      camStream = null;
      camVideo.classList.add("hidden");
      camShot.disabled = true;
      camError.textContent = "Camera unavailable — permission denied or no device found.";
      camError.classList.remove("hidden");
    });
}
function stopCamera() {
  if (camStream) { var t = camStream.getTracks(); for (var i = 0; i < t.length; i++) t[i].stop(); }
  camStream = null;
  camVideo.srcObject = null;
}
function closeCamera() { stopCamera(); camModal.classList.add("hidden"); }
camShot.addEventListener("click", function () {
  if (!camStream) return;
  var w = camVideo.videoWidth, h = camVideo.videoHeight;
  if (!w || !h) return;
  camCanvas.width = w;
  camCanvas.height = h;
  camCanvas.getContext("2d").drawImage(camVideo, 0, 0, w, h);
  shotTaken = true;
  camCanvas.classList.remove("hidden");
  camVideo.classList.add("hidden");
  camShot.classList.add("hidden");
  camRetake.classList.remove("hidden");
  camUse.classList.remove("hidden");
});
camRetake.addEventListener("click", function () {
  shotTaken = false;
  camCanvas.classList.add("hidden");
  camVideo.classList.remove("hidden");
  camRetake.classList.add("hidden");
  camUse.classList.add("hidden");
  camShot.classList.remove("hidden");
});
camUse.addEventListener("click", function () {
  if (!shotTaken) return;
  camCanvas.toBlob(function (blob) {
    if (blob) addFiles([new File([blob], "photo-" + Date.now() + ".png", { type: "image/png" })]);
    closeCamera();
    toast("Photo attached");
  }, "image/png");
});
camCancel.addEventListener("click", closeCamera);
camModal.addEventListener("click", function (e) { if (e.target === camModal) closeCamera(); });

/* ---------- drag & drop ---------- */
var dragDepth = 0;
composer.addEventListener("dragenter", function (e) { e.preventDefault(); dragDepth++; composer.classList.add("dragover"); });
composer.addEventListener("dragover", function (e) { e.preventDefault(); });
composer.addEventListener("dragleave", function () { dragDepth--; if (dragDepth <= 0) { dragDepth = 0; composer.classList.remove("dragover"); } });
composer.addEventListener("drop", function (e) {
  e.preventDefault();
  dragDepth = 0;
  composer.classList.remove("dragover");
  addFiles(e.dataTransfer.files);
  toast("Attached");
});

/* ---------- toggles ---------- */
var modeToggle = $("modeToggle"), thumb = modeToggle.querySelector(".seg-thumb"),
  modeBtns = modeToggle.querySelectorAll("button"), webBtn = $("webSearchBtn");
function updatePlaceholder() {
  var deep = S.mode === "deep", web = webBtn.classList.contains("active");
  if (deep) input.placeholder = "Ask something complex — take your time…";
  else if (web) input.placeholder = "Search the web or ask anything…";
  else input.placeholder = "Message Pluto…";
}
function placeThumb() {
  var btn = modeToggle.querySelector("button.active");
  if (!btn) return;
  var tr = modeToggle.getBoundingClientRect(), br = btn.getBoundingClientRect();
  thumb.style.width = br.width + "px";
  thumb.style.transform = "translateX(" + (br.left - tr.left - modeToggle.clientLeft) + "px)";
}
function setMode(mode, skipSave) {
  S.mode = mode;
  if (!skipSave) savePrefs();
  modeToggle.setAttribute("data-mode", mode);
  modeBtns.forEach(function (b) { b.classList.toggle("active", b.getAttribute("data-mode") === mode); });
  updatePlaceholder();
  placeThumb();
}
modeBtns.forEach(function (b) {
  b.addEventListener("click", function () { setMode(b.getAttribute("data-mode")); });
});
function setWeb(on) {
  S.web = on;
  savePrefs();
  webBtn.classList.toggle("active", on);
  webBtn.setAttribute("aria-pressed", on ? "true" : "false");
  updatePlaceholder();
}
webBtn.addEventListener("click", function () { setWeb(!webBtn.classList.contains("active")); });

/* ---------- mic ---------- */
$("micBtn").addEventListener("click", function () {
  var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { toast("Voice input not supported here"); return; }
  try {
    var r = new SR();
    $("micBtn").classList.add("active");
    toast("Listening…");
    r.onresult = function (e) { input.value += e.results[0][0].transcript; input.focus(); };
    r.onend = function () { $("micBtn").classList.remove("active"); };
    r.onerror = function () { toast("Mic error or denied"); };
    r.start();
  } catch (e) { toast("Mic unavailable"); }
});

/* ---------- shortcuts ---------- */
document.addEventListener("keydown", function (e) {
  if (e.key === "Escape") {
    closeAttachMenu();
    $("ctxMenu").classList.add("hidden");
    $("projMenu").classList.add("hidden");
    $("modelDD").classList.add("hidden");
    $("dlg").classList.add("hidden");
    $("keys").classList.add("hidden");
    if (!camModal.classList.contains("hidden")) closeCamera();
    return;
  }
  var typing = e.target.tagName === "TEXTAREA" || e.target.tagName === "INPUT";
  if (e.altKey && e.code === "KeyM") { e.preventDefault(); setMode(S.mode === "fast" ? "deep" : "fast"); }
  if (e.altKey && e.code === "KeyS") { e.preventDefault(); setWeb(!webBtn.classList.contains("active")); }
  if (e.ctrlKey && e.code === "KeyK") { e.preventDefault(); $("sideSearch").focus(); }
  if (e.key === "?" && !typing) { e.preventDefault(); $("keys").classList.remove("hidden"); }
});
$("keysBtn").addEventListener("click", function () { $("keys").classList.remove("hidden"); });
$("keysClose").addEventListener("click", function () { $("keys").classList.add("hidden"); });

/* ---------- init (server-driven) ---------- */
applyTheme();
document.body.classList.toggle("folded", innerWidth < 861 ? true : !!S.folded);
setMode(S.mode || "fast", true);
setWeb(!!S.web);
renderProjects();
renderRecents();
renderChat();
updatePlaceholder();
placeThumb();
window.addEventListener("resize", placeThumb);

(async function boot() {
  try {
    var health = await req("/api/health");
    TIERS = (health && health.tiers) || [];
    AUTH_MODE = (health && health.auth_mode) || "open";
  } catch (err) {
    var b = $("errBanner");
    b.style.display = "block";
    b.textContent = "Pluto API unreachable (" + (API_BASE || "same origin") + "): " + err.message;
    toast("API unreachable — is the backend running?");
    return;
  }
  if (TIERS.indexOf(S.model) < 0) S.model = TIERS[0] || "";
  savePrefs();
  setActiveTier(S.model, false);
  try { await refreshMe(); } catch (err) {}
  if (!getToken() && !authDismissed()) {
    /* Logged out: show the login dialog once so the account entry
     * point is visible; Cancel/Escape dismisses it for good and the
     * footer button reopens it anytime. */
    try { await authAsync("Log in to Pluto"); } catch (err) {}
    try { await refreshMe(); } catch (err) {}
  }
  try { await refreshProjects(); } catch (err) { toast("Cannot load projects: " + err.message); }
  try { await refreshChats(); } catch (err) { toast("Cannot load chats: " + err.message); }
})();
