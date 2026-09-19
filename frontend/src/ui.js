// @ts-check
/* Pluto web client module: ui (DOM helpers, formatting, toasts; no app imports).
 * Split from the vanilla-JS monolith; behavior preserved.
 */
/** @param {string} id */
function $(id) { return document.getElementById(id); }
/* ---------- misc helpers ---------- */
/* esc(): text-node only — does NOT escape quotes. NEVER use inside
 * double/single-quoted attributes (data-*, title, value). Use
 * escapeAttr() there instead, otherwise `"` breaks out (self-XSS). */
/** @param {*} s */
function esc(s) { return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
/** @type {Object<string, string>} */
var _ATTR_ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
/* escapeAttr(): safe for double-quoted attribute values. */
/** @param {*} s */
function escapeAttr(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
    return _ATTR_ESCAPES[c];
  });
}
/* enc(): encode one dynamic URL path segment (server IDs, names).
 * IDs are 16-hex so this is a no-op for well-formed values — it only
 * neutralizes `../` or quote-breaking payloads if one ever arrives. */
/** @param {*} s */
function enc(s) { return encodeURIComponent(String(s == null ? "" : s)); }
/* isSafeHttpUrl(): only http(s) links may become clickable hrefs.
 * Server-provided source URLs render via innerHTML/md(); without this
 * a `javascript:` URL would execute on click (stored XSS via search). */
/** @param {*} u */
function isSafeHttpUrl(u) {
  return /^\s*https?:\/\//i.test(String(u || ""));
}
/** @param {*} ts */
function fmtTime(ts) {
  if (!ts) return "";
  try {
    var d = new Date(ts);
    if (isNaN(d.getTime())) return "";
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch (e) { return ""; }
}
/** @param {*} ts */
function fmtDay(ts) {
  try {
    var d = ts ? new Date(ts) : new Date();
    if (isNaN(d.getTime())) d = new Date();
    return d.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
  } catch (e) { return ""; }
}
/** @param {*} v */
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
/** @param {*} b */
function fmtSize(b) {
  if (!(b >= 0)) return "";
  if (b < 1024) return b + " B";
  if (b < 1048576) return (b / 1024).toFixed(1) + " KB";
  return (b / 1048576).toFixed(1) + " MB";
}
/** @type {Object<string, number>} */
var _toastSeen = {};
/** @param {string} msg */
function toast(msg) {
  var key = String(msg || "").slice(0, 120);
  var now = Date.now();
  // Dedupe + cap: refresh-loop failures must not flood #toasts.
  if (_toastSeen[key] && now - _toastSeen[key] < 3000) return;
  _toastSeen[key] = now;
  var host = $("toasts");
  if (!host) return;
  while (host.children.length >= 5 && host.firstChild) host.removeChild(host.firstChild);
  var t = document.createElement("div");
  t.className = "toast";
  t.setAttribute("role", "status");
  t.textContent = msg;
  host.appendChild(t);
  setTimeout(function () { t.style.opacity = "0"; t.style.transition = "opacity .3s"; }, 2200);
  setTimeout(function () { t.remove(); }, 2600);
}
var DIALOG_IDS = ["camModal", "dlg", "authDlg", "acctDlg", "keys"];
function openOverlay() {
  for (var i = 0; i < DIALOG_IDS.length; i++) {
    var el = $(DIALOG_IDS[i]);
    if (el && !el.classList.contains("hidden")) return el;
  }
  return null;
}
/**
 * @param {*} e
 * @param {*} overlay
 */
function trapTab(e, overlay) {
  var f = overlay.querySelectorAll("button, input, textarea, select, a[href], [tabindex]");
  var vis = [];
  for (var i = 0; i < f.length; i++) {
    var el = f[i];
    if (el.disabled) continue;
    var rect = null;
    try { rect = el.getBoundingClientRect(); } catch (err) { rect = null; }
    var style = null;
    try { style = window.getComputedStyle(el); } catch (err) { style = null; }
    if (rect && (rect.width === 0 && rect.height === 0)) continue;
    if (style && (style.display === "none" || style.visibility === "hidden")) continue;
    vis.push(el);
  }
  if (!vis.length) { e.preventDefault(); return; }
  var first = vis[0], last = vis[vis.length - 1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
}

export { $, esc, escapeAttr, enc, isSafeHttpUrl, fmtTime, fmtDay, fmtStamp, fmtSize, toast, DIALOG_IDS, openOverlay, trapTab };
