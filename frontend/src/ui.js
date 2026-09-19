/* Pluto web client module: ui (DOM helpers, formatting, toasts; no app imports).
 * Split from the vanilla-JS monolith; behavior preserved.
 */
function $(id) { return document.getElementById(id); }
/* ---------- misc helpers ---------- */
/* esc(): text-node only — does NOT escape quotes. NEVER use inside
 * double/single-quoted attributes (data-*, title, value). Use
 * escapeAttr() there instead, otherwise `"` breaks out (self-XSS). */
function esc(s) { return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
/* escapeAttr(): safe for double-quoted attribute values. */
function escapeAttr(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
}
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
  t.setAttribute("role", "status");
  t.textContent = msg;
  $("toasts").appendChild(t);
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
function trapTab(e, overlay) {
  var f = overlay.querySelectorAll("button, input, textarea, select, a[href], [tabindex]");
  var vis = [];
  for (var i = 0; i < f.length; i++) {
    if (!f[i].disabled && f[i].offsetParent !== null) vis.push(f[i]);
  }
  if (!vis.length) { e.preventDefault(); return; }
  var first = vis[0], last = vis[vis.length - 1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
}

export { $, esc, escapeAttr, fmtTime, fmtDay, fmtStamp, fmtSize, toast, DIALOG_IDS, openOverlay, trapTab };
