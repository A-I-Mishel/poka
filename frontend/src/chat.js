/* Pluto web client module: chat (hub: event wiring + dispatch).
 * Render lives in render.js, send/stream in send.js; this module owns
 * top-level listeners and re-exports the original chat.js surface so
 * app.js and other importers keep working unchanged.
 */
import { $, toast } from "./ui.js";
import { MAX_MSG_CHARS } from "./config.js";
import { S, chats, current, projects, savePrefs, setChats, setCurrent } from "./state.js";
import { req } from "./api.js";
import { ask } from "./auth.js";
import { openSection, showChat, openTitle } from "./panels.js";
import { decideApproval, copyText, speakText, renderChat, renderRecents, refreshProjects, refreshChats, downloadMarkdown, chatMarkdown, getCtxId, getProjId, msgEl, renderProjects, setActiveTier, renderModelDD, stopSpeaking, hydrateUploadImages } from "./render.js";
import { send, sendText, isStreaming, clearComposer, restoreComposer, uploadPending, streamInto } from "./send.js";

var chatCol = $("chatCol"), input = $("input");

$("sendBtn").addEventListener("click", send);
input.addEventListener("keydown", function (e) {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
});
var _inputRaf = null;
input.addEventListener("input", function () {
  if (_inputRaf) cancelAnimationFrame(_inputRaf);
  _inputRaf = requestAnimationFrame(function () {
    _inputRaf = null;
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 160) + "px";
  });
});
chatCol.addEventListener("click", async function (e) {
  var btn = e.target.closest("[data-act]");
  if (!btn) return;
  var msg = btn.closest(".msg");
  var i = msg._i;
  var act = btn.getAttribute("data-act");
  if (act === "approve" || act === "reject") { decideApproval(btn, act === "approve"); return; }
  if (act === "copy") { copyText(msg._raw); }
  else if (act === "speak") { speakText(msg._raw, btn); }
  else if (act === "edit") {
    if (isStreaming()) { toast("Wait for the current reply"); return; }
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
    if (isStreaming()) { toast("Wait for the current reply"); return; }
    var v = (msg.querySelector(".edit-ta").value || "").trim();
    if (!v) { renderChat(); return; }
    if (v.length > MAX_MSG_CHARS) {
      toast("Message is limited to " + MAX_MSG_CHARS + " characters; shorten it and save.");
      msg.querySelector(".edit-ta").focus();
      return; // keep the edit open so nothing is lost
    }
    /* Keep the edited message's attachments: truncate drops the message,
     * so carry its vaulted upload refs into the resend (no re-upload). */
    var prev = (typeof current !== "undefined" && current[i]) || {};
    var keep = Array.isArray(prev.attachments) ? prev.attachments : [];
    try {
      await req("/api/chats/truncate", { method: "POST", body: JSON.stringify({ index: i }) });
      toast("Resending…");
      sendText(v, [], keep);
    } catch (err) { toast("Edit failed: " + err.message); renderChat(); }
  }
  else if (act === "regen") {
    if (isStreaming()) { toast("Wait for the current reply"); return; }
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
      if (!$("viewPanel").classList.contains("hidden") && $("panelBody").getAttribute("data-section") === "research")
        openSection("research");
    } catch (err) { toast("Cannot save brief: " + err.message); }
  }
});
$("projRename").addEventListener("click", function () {
  $("projMenu").classList.add("hidden");
  var p = projects.filter(function (x) { return x && x.id === getProjId(); })[0];
  if (!p) return;
  ask("Rename project", p.name || "", async function (v) {
    if (!v) return;
    try {
      await req("/api/projects/" + getProjId(), { method: "PATCH", body: JSON.stringify({ name: v }) });
      await refreshProjects();
      toast("Renamed");
    } catch (err) { toast("Rename failed: " + err.message); }
  });
});
$("projContext").addEventListener("click", function () {
  $("projMenu").classList.add("hidden");
  if (!getProjId()) return;
  S.projectId = getProjId();
  savePrefs();
  renderProjects();
  openSection("project");
});
$("projArchive").addEventListener("click", async function () {
  $("projMenu").classList.add("hidden");
  if (!getProjId()) return;
  try {
    await req("/api/projects/" + getProjId() + "/archive", { method: "POST" });
    if (S.projectId === getProjId()) { S.projectId = null; savePrefs(); }
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
function debounce(fn, ms) { var t; return function () { var a = arguments, c = this; clearTimeout(t); t = setTimeout(function () { fn.apply(c, a); }, ms); }; }
$("sideSearch").addEventListener("input", debounce(renderRecents, 150));
$("ctxRename").addEventListener("click", function () {
  $("ctxMenu").classList.add("hidden");
  var c = chats.filter(function (x) { return x && x.id === getCtxId(); })[0];
  if (!c) return;
  ask("Rename chat", c.title || "", async function (v) {
    if (!v) return;
    try {
      var data = await req("/api/chats/" + getCtxId(), { method: "PATCH", body: JSON.stringify({ title: v }) });
      setChats(data.chats || chats);
      renderRecents();
      toast("Renamed");
    } catch (err) { toast("Rename failed: " + err.message); }
  });
});
$("ctxDelete").addEventListener("click", async function () {
  $("ctxMenu").classList.add("hidden");
  if (!getCtxId()) return;
  if (!window.confirm("Delete this chat? This cannot be undone.")) return;
  try {
    var data = await req("/api/chats/" + getCtxId(), { method: "DELETE" });
    setChats(data.chats || []);
    setCurrent(data.current || current);
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
    setChats(data.chats || []);
    setCurrent(data.current || []);
    if (data.warnings && data.warnings.length) toast(data.warnings[0]);
  } catch (err) { toast("Cannot start chat: " + err.message); return; }
  renderRecents();
  renderChat();
  showChat();
  if (window.innerWidth < 861) document.body.classList.add("folded");
  input.focus();
});
$("exportBtn").addEventListener("click", function () {
  var title = openTitle();
  downloadMarkdown(title, chatMarkdown(title, current));
  toast("Chat exported");
});
/* Export any archived chat without opening it (read-only endpoint). */
$("ctxExport").addEventListener("click", async function () {
  $("ctxMenu").classList.add("hidden");
  if (!getCtxId()) return;
  try {
    var data = await req("/api/chats/" + getCtxId() + "/messages");
    var title = (data && data.title) || "chat";
    downloadMarkdown(title, chatMarkdown(title, (data && data.messages) || []));
    toast("Chat exported");
  } catch (err) { toast("Export failed: " + err.message); }
});
$("modelBtn").addEventListener("click", function (e) {
  e.stopPropagation();
  renderModelDD();
  $("modelDD").classList.toggle("hidden");
});

export { msgEl, renderChat, refreshChats, refreshProjects, sendText, send, copyText, renderRecents, renderProjects, chatMarkdown, setActiveTier, renderModelDD, clearComposer, restoreComposer, uploadPending, streamInto, stopSpeaking, speakText, hydrateUploadImages };
