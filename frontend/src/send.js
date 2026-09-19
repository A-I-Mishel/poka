/* Pluto web client module: send (composer, upload, SSE stream, send).
 * Split from chat.js; behavior preserved. Rendering primitives come
 * from render.js (one-way edge: send -> render -> panels).
 */
import { $, toast, esc } from "./ui.js";
import { md, planet } from "./markdown.js";
import { apiUrl } from "./config.js";
import { S, current } from "./state.js";
import { authAsync, refreshMe } from "./auth.js";
import { authHeaders } from "./auth-store.js";
import { openSection } from "./panels.js";
import { addChip, getPendingFiles, clearPendingFiles } from "./composer.js";
import { msgEl, hydrateUploadImages, scrollBottom, maybeScroll, rememberApprovalTokens, setActiveTier, refreshChats, stopSpeaking } from "./render.js";

/* DOM refs are grabbed in initSend(), not at import time, so this
 * module imports cleanly without a DOM (node/vitest/smoke phase 1). */
var panelBody = null, chatCol = null;
var input = null, attachments = null;
var _sendInit = false;
function initSend() {
  if (_sendInit) return;
  _sendInit = true;
  panelBody = $("panelBody"); chatCol = $("chatCol");
  input = $("input"); attachments = $("attachments");
}
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
  getPendingFiles().forEach(function (f) { if (f._preview) URL.revokeObjectURL(f._preview); });
  clearPendingFiles();
}
/* Restore a draft after a failed send (never clobbers anything the user
 * typed meanwhile; addChip regenerates image previews itself). */
function restoreComposer(text, files) {
  var restored = false;
  if (text && !input.value) { input.value = text; input.style.height = "auto"; restored = true; }
  var have = getPendingFiles().slice();
  (files || []).forEach(function (f) { if (have.indexOf(f) === -1) addChip(f); });
  if (restored || (files && files.length)) input.focus();
}
async function uploadPending(files, retried) {
  var list = files || getPendingFiles();
  var out = [];
  for (var i = 0; i < list.length; i++) {
    var form = new FormData();
    form.append("file", list[i]);
    var upHeaders = authHeaders();
    var res = await fetch(apiUrl("/api/uploads"), { method: "POST", headers: upHeaders, credentials: "include", body: form });
    if (res.status === 401 && !retried) {
      var ok = await authAsync("Log in to continue");
      if (!ok) throw new Error("Authentication required.");
      try { await refreshMe(); } catch (e) {}
      return uploadPending(files, true);
    }
    if (res.status === 401) throw new Error("Authentication required.");
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
      credentials: "include",
      body: JSON.stringify(payload),
      signal: controller.signal
    }).then(function (res) {
      if (res.status === 401) {
        return authAsync("Log in to continue").then(function (ok) {
          if (!ok) throw new Error("Authentication required.");
          try { if (typeof refreshMe === "function") return refreshMe().then(function () { throw new Error("Session refreshed — please resend."); }); } catch (e) {}
          throw new Error("Authentication required.");
        });
      }
      if (!res.ok || !res.body) {
        return res.text().then(function (t) {
          var detail = res.statusText;
          try { detail = (t && JSON.parse(t).detail) || detail; } catch (e) {}
          throw new Error("Stream failed: " + detail);
        });
      }
      var reader = res.body.getReader();
      var decoder = new TextDecoder();
      var buf = "";
      var result = null;
      var pendingText = null, raf = null;
      function flushToken() {
        raf = null;
        if (pendingText !== null) {
          bodyEl.innerHTML = md(pendingText) + '<span class="caret"></span>';
          pendingText = null;
          maybeScroll();
        }
      }
      function scheduleToken(t) {
        pendingText = t;
        if (raf) return;
        raf = requestAnimationFrame(flushToken);
      }
      function pump() {
        return reader.read().then(function (step) {
          if (step.done) {
            if (raf) { cancelAnimationFrame(raf); raf = null; }
            if (pendingText !== null) { bodyEl.innerHTML = md(pendingText) + '<span class="caret"></span>'; pendingText = null; }
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
            else if (evt.type === "token") scheduleToken(evt.text);
            else if (evt.type === "reset") { if (raf) { cancelAnimationFrame(raf); raf = null; pendingText = null; } bodyEl.innerHTML = '<span class="dots"><i></i><i></i><i></i></span>'; }
            else if (evt.type === "status") { if (raf) { cancelAnimationFrame(raf); raf = null; pendingText = null; } bodyEl.innerHTML = '<span class="dots"><i></i><i></i><i></i></span> ' + esc(evt.text || ""); }
            else if (evt.type === "done") result = evt.result;
            else if (evt.type === "error") throw new Error(evt.detail || "Stream error");
          });
          return pump();
        });
      }
      return pump();
    }).catch(reject);
  });
}
async function sendText(text, files, reuse) {
  if (streaming) return; // synchronous re-entry guard: no double submit
  stopSpeaking();
  streaming = true;
  sendBtnToStop(true);
  var atts = files || [];
  /* Edit flow passes already-vaulted attachments (reuse) so resends
   * reference the original upload IDs instead of re-uploading (which
   * would mint duplicate vault entries and waste quota). */
  var uploaded = Array.isArray(reuse) ? reuse.filter(function (a) {
    return a && a.id;
  }).map(function (a) {
    return { id: a.id, kind: a.kind || "document", name: a.name || "file" };
  }) : [];
  if (!text && !atts.length && !uploaded.length) { streaming = false; sendBtnToStop(false); return; }
  if (atts.length > 5) { toast("At most 5 files per message."); streaming = false; sendBtnToStop(false); return; }
  if (!uploaded.length && atts.length) {
    try { uploaded = await uploadPending(atts); }
    catch (e) { toast("Upload failed: " + e.message); streaming = false; sendBtnToStop(false); return; }
  }
  /* Commit point: uploads succeeded, so clear the composer. The draft is
   * stashed so a failed send can restore it (nothing lost on error). */
  var draftText = String(text || "").trim();
  var draftFiles = (atts || []).slice();
  clearComposer();
  var empty = chatCol.querySelector(".empty");
  if (empty) empty.remove();
  /* optimistic user bubble (server state replaces it on refresh) */
  var um = { role: "user", content: text || "(attachment)", time: new Date().toISOString(), attachments: uploaded };
  chatCol.appendChild(msgEl(um, current.length));
  hydrateUploadImages();
  scrollBottom(true);
  var tmp = document.createElement("div");
  tmp.className = "msg ai";
  tmp.setAttribute("aria-busy", "true");
  tmp.innerHTML = '<div class="mark-p">' + planet(13) + '</div><div class="ai-body"><div class="body"><span class="dots"><i></i><i></i><i></i></span></div></div>';
  chatCol.appendChild(tmp);
  scrollBottom(true);
  streamInto._text = text || "(attachment)";
  streamInto._ids = uploaded.map(function (a) { return a.id; });
  try {
    var result = await streamInto(tmp.querySelector(".body"), function (meta) {
      if (meta && meta.active_tier) setActiveTier(meta.active_tier, true, meta.fallback && meta.fallback.reason);
    });
    if (result && result.warnings && result.warnings.length) toast(result.warnings[0]);
    if (result) rememberApprovalTokens(result.pending_approvals);
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
    try { restoreComposer(draftText, draftFiles); } catch (ignored) {}
  } finally {
    try { tmp.removeAttribute("aria-busy"); } catch (ignored) {}
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
  var files = getPendingFiles().slice();
  if (!text && !files.length) return;
  sendText(text, files); /* composer clears only once committed in sendText */
}

function isStreaming() { return streaming; }

export { initSend, sendBtnToStop, clearComposer, restoreComposer, uploadPending, streamInto, sendText, send, isStreaming };
