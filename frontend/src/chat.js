/* Pluto web client module: chat (render, send/stream, actions, recents, models).
 * Split from the vanilla-JS monolith; behavior preserved.
 */
import { $, toast, esc, fmtTime, fmtDay, fmtSize } from "./ui.js";
import { md, planet, ic, artIcon } from "./markdown.js";
import { apiUrl, MAX_MSG_CHARS } from "./config.js";
import { S, TIERS, chats, current, projects, savePrefs, setChats, setCurrent, setProjects } from "./state.js";
import { req, authedDownload } from "./api.js";
import { authHeaders } from "./auth-store.js";
import { renderAcct, refreshMe, authAsync, showAuth, signOut, ask } from "./auth.js";
import { openSection, showChat, openTitle } from "./panels.js";
import { addChip, getPendingFiles, clearPendingFiles } from "./composer.js";

/* ---------- chat render ---------- */
var chatCol = $("chatCol"), chatScroll = $("chatScroll"), chatTitle = $("chatTitle"),
  backBtn = $("backBtn"), panelBody = $("panelBody"),
  viewChat = $("viewChat"), viewPanel = $("viewPanel");
function chipForAttachment(a) {
  var c = document.createElement("div");
  c.className = "chip art-chip";
  c.title = a.name || "attachment";
  var kind = String(a.kind || "");
  if (kind === "image" && a.id) {
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
/* ---------- human approvals (irreversible tool actions) ---------- */
var approvalTokens = {};
var decidedApprovals = {};
function rememberApprovalTokens(list) {
  (list || []).forEach(function (a) {
    if (a && a.id && a.token) approvalTokens[a.id] = a.token;
  });
}
async function approvalTokenFor(id) {
  if (approvalTokens[id]) return approvalTokens[id];
  var list = await req("/api/approvals");
  var found = null;
  (list.approvals || []).forEach(function (a) {
    if (a && a.id && a.token) approvalTokens[a.id] = a.token;
    if (a && a.id === id) found = a;
  });
  return found && found.token;
}
async function decideApproval(btn, approve, retried) {
  var id = btn.getAttribute("data-id");
  if (!id) return;
  btn.disabled = true;
  try {
    var tok = await approvalTokenFor(id);
    if (!tok) { toast("Already decided or expired."); decidedApprovals[id] = 1; renderChat(); return; }
    var res = approve
      ? await req("/api/approvals/" + id + "/approve", { method: "POST", body: JSON.stringify({ token: tok }) })
      : await req("/api/approvals/" + id + "/reject", { method: "POST" });
    delete approvalTokens[id];
    decidedApprovals[id] = 1;
    if (approve && res && res.result) toast(String(res.result).slice(0, 200));
    else toast(approve ? "Approved and executed." : "Rejected.");
    renderChat();
  } catch (e) {
    var msg = String((e && e.message) || e);
    if (!retried && /expired|already used|not found/i.test(msg)) {
      delete approvalTokens[id];
      return decideApproval(btn, approve, true);
    }
    btn.disabled = false;
    toast("Approval failed: " + msg);
  }
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
    if (m && m.pending_approvals && m.pending_approvals.length) {
      var ap = document.createElement("div");
      ap.className = "chips";
      m.pending_approvals.forEach(function (p) {
        if (!p || !p.id || decidedApprovals[p.id]) return;
        var card = document.createElement("div");
        card.className = "chip appr-chip";
        card.title = "Needs your approval — nothing runs until you approve";
        var badge = document.createElement("span");
        badge.className = "ext";
        badge.textContent = "OK?";
        var nm = document.createElement("span");
        nm.className = "name";
        nm.textContent = String(p.tool || "action") + ": " + String(p.summary || "").slice(0, 120);
        var ok = document.createElement("button");
        ok.textContent = "Approve";
        ok.setAttribute("data-act", "approve");
        ok.setAttribute("data-id", p.id);
        var no = document.createElement("button");
        no.textContent = "Reject";
        no.setAttribute("data-act", "reject");
        no.setAttribute("data-id", p.id);
        card.appendChild(badge);
        card.appendChild(nm);
        card.appendChild(ok);
        card.appendChild(no);
        ap.appendChild(card);
      });
      if (ap.childNodes.length) body.appendChild(ap);
    }
    var mt2 = document.createElement("div");
    mt2.className = "meta";
    var metaHtml = "<span>" + esc(fmtTime(m.time)) + "</span>";
    if (m && m.model) metaHtml += "<span> · " + esc(m.model) + "</span>";
    metaHtml += '<button data-act="copy">Copy</button><button data-act="speak">Listen</button><button data-act="regen">Regenerate</button><button data-act="brief">Brief</button>';
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
var uploadBlobCache = {};
var liveUploadUrls = {};
var inflightImgs = {};
function hydrateUploadImages() {
  chatCol.querySelectorAll("img[data-up]").forEach(function (im) {
    var id = im.getAttribute("data-up");
    if (!id) return;
    function attach(blob) {
      if (liveUploadUrls[id]) URL.revokeObjectURL(liveUploadUrls[id]);
      var url = URL.createObjectURL(blob);
      liveUploadUrls[id] = url;
      im.src = url;
    }
    if (uploadBlobCache[id]) { attach(uploadBlobCache[id]); return; }
    if (inflightImgs[id]) return;
    inflightImgs[id] = true;
    fetch(apiUrl("/api/uploads/" + id + "/file"), { headers: authHeaders(), credentials: "include" }).then(function (res) {
      if (!res.ok) throw new Error("gone");
      return res.blob();
    }).then(function (blob) {
      uploadBlobCache[id] = blob;
      var keys = Object.keys(uploadBlobCache);
      if (keys.length > 50) delete uploadBlobCache[keys[0]];
      attach(blob);
    }).catch(function () { im.remove(); }).finally(function () { delete inflightImgs[id]; });
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
  stopSpeaking();
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
var _scrollRaf = null;
chatScroll.addEventListener("scroll", function () {
  if (_scrollRaf) return;
  _scrollRaf = requestAnimationFrame(function () {
    _scrollRaf = null;
    var far = chatScroll.scrollHeight - chatScroll.scrollTop - chatScroll.clientHeight > 250;
    $("scrollBtn").classList.toggle("hidden", !far);
  });
}, { passive: true });

/* ---------- refresh from server ---------- */
async function refreshChats() {
  var data = await req("/api/chats");
  setChats((data && data.chats) || []);
  setCurrent((data && data.current) || []);
  renderRecents();
  renderChat();
}
async function refreshProjects() {
  var data = await req("/api/projects");
  setProjects(Array.isArray(data) ? data : []);
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
async function uploadPending(files) {
  var list = files || getPendingFiles();
  var out = [];
  for (var i = 0; i < list.length; i++) {
    var form = new FormData();
    form.append("file", list[i]);
    var upHeaders = authHeaders();
    var res = await fetch(apiUrl("/api/uploads"), { method: "POST", headers: upHeaders, credentials: "include", body: form });
    if (res.status === 401) {
      var ok = await authAsync("Log in to continue");
      if (!ok) throw new Error("Authentication required.");
      try { await refreshMe(); } catch (e) {}
      return uploadPending(files);
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
      credentials: "include",
      body: JSON.stringify(payload),
      signal: controller.signal
    }).then(function (res) {
      if (!res.ok || !res.body) throw new Error("Stream failed: " + res.statusText);
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
  if (act === "approve" || act === "reject") { decideApproval(btn, act === "approve"); return; }
  if (act === "copy") { copyText(msg._raw); }
  else if (act === "speak") { speakText(msg._raw, btn); }
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

/* ---------- read aloud (free browser speechSynthesis, no backend) ----------
 * Per-message Listen button on assistant replies. Markdown is stripped to
 * speakable prose and capped so a long research answer cannot queue
 * minutes of speech. Any new send, chat switch, or second press stops. */
var speakingBtn = null;
function stopSpeaking() {
  try { if ("speechSynthesis" in window) window.speechSynthesis.cancel(); } catch (e) {}
  if (speakingBtn) {
    speakingBtn.textContent = "Listen";
    speakingBtn.classList.remove("active");
    speakingBtn = null;
  }
}
function speakable(raw) {
  var s = String(raw || "");
  s = s.replace(/```[\s\S]*?```/g, " code omitted ");
  s = s.replace(/\[([^\]]+)\]\([^)]+\)/g, "$1");
  s = s.replace(/[#>*`_~]/g, "");
  return s.replace(/\s+/g, " ").trim().slice(0, 4000);
}
function speakText(text, btn) {
  if (!("speechSynthesis" in window) || typeof SpeechSynthesisUtterance === "undefined") {
    toast("Speech not supported in this browser");
    return;
  }
  if (speakingBtn === btn) { stopSpeaking(); return; }
  var words = speakable(text);
  if (!words) { toast("Nothing to read"); return; }
  stopSpeaking();
  var u = new SpeechSynthesisUtterance(words);
  u.onend = function () { stopSpeaking(); };
  u.onerror = function () { stopSpeaking(); };
  speakingBtn = btn;
  btn.textContent = "Stop";
  btn.classList.add("active");
  try {
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(u);
  } catch (e) { stopSpeaking(); }
}

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
        setChats(data.chats || []);
        setCurrent(data.current || []);
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
function debounce(fn, ms) { var t; return function () { var a = arguments, c = this; clearTimeout(t); t = setTimeout(function () { fn.apply(c, a); }, ms); }; }
$("sideSearch").addEventListener("input", debounce(renderRecents, 150));
$("ctxRename").addEventListener("click", function () {
  $("ctxMenu").classList.add("hidden");
  var c = chats.filter(function (x) { return x && x.id === ctxId; })[0];
  if (!c) return;
  ask("Rename chat", c.title || "", async function (v) {
    if (!v) return;
    try {
      var data = await req("/api/chats/" + ctxId, { method: "PATCH", body: JSON.stringify({ title: v }) });
      setChats(data.chats || chats);
      renderRecents();
      toast("Renamed");
    } catch (err) { toast("Rename failed: " + err.message); }
  });
});
$("ctxDelete").addEventListener("click", async function () {
  $("ctxMenu").classList.add("hidden");
  if (!ctxId) return;
  if (!window.confirm("Delete this chat? This cannot be undone.")) return;
  try {
    var data = await req("/api/chats/" + ctxId, { method: "DELETE" });
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
function chatMarkdown(title, messages) {
  var lines = ["# " + title, ""];
  (messages || []).forEach(function (m) {
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
  return lines.join("\n");
}
function downloadMarkdown(title, text) {
  var blob = new Blob([text], { type: "text/markdown" });
  var a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = (String(title || "").replace(/[^\w\- ]+/g, "").trim() || "chat") + ".md";
  a.click();
  setTimeout(function () { URL.revokeObjectURL(a.href); }, 500);
}
$("exportBtn").addEventListener("click", function () {
  var title = openTitle();
  downloadMarkdown(title, chatMarkdown(title, current));
  toast("Chat exported");
});
/* Export any archived chat without opening it (read-only endpoint). */
$("ctxExport").addEventListener("click", async function () {
  $("ctxMenu").classList.add("hidden");
  if (!ctxId) return;
  try {
    var data = await req("/api/chats/" + ctxId + "/messages");
    var title = (data && data.title) || "chat";
    downloadMarkdown(title, chatMarkdown(title, (data && data.messages) || []));
    toast("Chat exported");
  } catch (err) { toast("Export failed: " + err.message); }
});

/* ---------- models (server-driven) ---------- */
var _lastFallbackKey = "";
var _lastFallbackAt = 0;
function setActiveTier(tier, fromServer, reason) {
  if (tier && TIERS.indexOf(tier) > -1 && !fromServer) {
    S.model = tier;
    savePrefs();
    _lastFallbackKey = "";
  } else if (fromServer && tier) {
    /* Header must show what actually answered (server truth), not the
       stale preference — e.g. preferred Gemma down, Groq answered, the
       badge must read Groq. The per-message "time · tier" label and
       fallback note already carry the same actual tier. */
    if (S.model && tier !== S.model) {
      var why = reason || "unavailable";
      var key = S.model + ">" + tier + ">" + why;
      var now = Date.now();
      if (key !== _lastFallbackKey || now - _lastFallbackAt > 5000) {
        _lastFallbackKey = key;
        _lastFallbackAt = now;
        toast("Preferred " + S.model + " " + why + " — answered by " + tier);
      }
    }
    if (S.model !== tier) {
      S.model = tier;
      savePrefs();
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

export { msgEl, renderChat, refreshChats, refreshProjects, sendText, send, copyText, renderRecents, renderProjects, chatMarkdown, setActiveTier, renderModelDD, clearComposer, restoreComposer, uploadPending, streamInto, stopSpeaking, speakText, hydrateUploadImages };
