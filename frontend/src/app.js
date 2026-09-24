/* Pluto web client module: app (wiring: hooks, shortcuts, init; all features live in modules).
 * Split from the vanilla-JS monolith; behavior preserved.
 */

import { $, openOverlay, trapTab, toast } from "./ui.js";
import { API_BASE } from "./config.js";
import { S, TIERS, savePrefs, setPref, setTIERS, setAuthMode } from "./state.js";
import { req, setApiHooks } from "./api.js";
import { ACCT, refreshMe, authAsync, authDismissed, setAuthHooks, initAuth } from "./auth.js";
import { renderProjects, renderRecents, renderChat, refreshProjects, refreshChats, openChatById, setActiveTier, stopSpeaking, initChat } from "./chat.js";
import { parseHash, isSyncedHash } from "./route.js";
import { applyTheme, setMode, setWeb, updatePlaceholder, placeThumb, webBtn, initPanels } from "./panels.js";
import { closeAttachMenu, closeCamera, camModal, initComposer } from "./composer.js";
import { initRender } from "./render.js";
import { initSend } from "./send.js";

/* Module init first: every feature module grabs its DOM refs and
 * registers listeners here (not at import time), so modules stay
 * importable without a DOM and boot order is explicit. */
initRender();
initSend();
initAuth();
initPanels();
initComposer();
initChat();

/* Global error banner: additive listener (never clobbers other
 * handlers), guards a missing banner node. */
window.addEventListener("error", function (e) {
  var b = document.getElementById("errBanner");
  if (!b) return;
  b.style.display = "block";
  b.textContent = "Error: " + (e && e.message ? e.message : "unknown") + " (line " + (e && e.lineno ? e.lineno : "?") + ")";
});

async function _refreshAllSilent() {
  try { await refreshProjects(); } catch (e) {}
  try { await refreshChats(); } catch (e) {}
}
async function _refreshAllToastChats() {
  try { await refreshProjects(); } catch (e) {}
  try { await refreshChats(); } catch (e) { toast("Cannot load chats: " + e.message); }
}
setApiHooks({
  onUnauthorized: function (title) { return authAsync(title); },
  onSessionRefreshed: async function () {
    try { await refreshMe(); } catch (e) {}
    await _refreshAllSilent();
  },
});
setAuthHooks({
  onSessionChanged: _refreshAllSilent,
  onSessionChangedToast: _refreshAllToastChats,
});

/* ---------- shortcuts ---------- */
document.addEventListener("keydown", function (e) {
  if (e.key === "Tab") {
    var ov = openOverlay();
    if (ov) trapTab(e, ov);
    return;
  }
  if (e.key === "Escape") {
    stopSpeaking();
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
  if (e.key === "?" && !typing) { e.preventDefault(); $("keys").classList.remove("hidden"); setTimeout(function () { $("keysClose").focus(); }, 30); }
});
$("keysBtn").addEventListener("click", function () { $("keys").classList.remove("hidden"); setTimeout(function () { $("keysClose").focus(); }, 30); });
$("keysClose").addEventListener("click", function () { $("keys").classList.add("hidden"); });
/* ---------- init (server-driven) ---------- */
applyTheme();
document.body.classList.toggle("folded", window.innerWidth < 861 ? true : !!S.folded);
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
    setTIERS((health && health.tiers) || []);
    setAuthMode((health && health.auth_mode) || "open");
  } catch (err) {
    var b = $("errBanner");
    b.style.display = "block";
    b.textContent = "Pluto API unreachable (" + (API_BASE || "same origin") + "): " + err.message;
    toast("API unreachable — is the backend running?");
    return;
  }
  if (TIERS.indexOf(S.model) < 0) setPref("model", TIERS[0] || "");
  savePrefs();
  setActiveTier(S.model, false);
  try { await refreshMe(); } catch (err) {}
  if (!ACCT.username && !authDismissed()) {
    /* Logged out: show the login dialog once so the account entry
     * point is visible; Cancel/Escape dismisses it for good and the
     * footer button reopens it anytime. */
    try { await authAsync("Log in to Pluto"); } catch (err) {}
    try { await refreshMe(); } catch (err) {}
  }
  try { await refreshProjects(); } catch (err) { toast("Cannot load projects: " + err.message); }
  try { await refreshChats(); } catch (err) { toast("Cannot load chats: " + err.message); }
  /* Hash deep-links: `#/chats/<id>` adopts the archived chat (back /
   * forward / reload / shared URL). Stale ids fail quietly home. */
  async function openFromHash(quiet) {
    var r = null;
    try { r = parseHash(window.location.hash); } catch (e) { r = null; }
    if (r && r.kind === "chat") {
      await openChatById(r.id, { sync: false, quiet: !!quiet });
    }
  }
  try { await openFromHash(true); } catch (err) {}
  window.addEventListener("hashchange", function () {
    try {
      if (isSyncedHash(window.location.hash)) return;
      openFromHash(false);
    } catch (e) {}
  });
})();
