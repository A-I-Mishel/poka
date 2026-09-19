/* Pluto web client module: render (message bubbles, recents, projects,
 * models, export, speech, approvals UI; no send/stream logic).
 * Split from chat.js; behavior preserved. Module-local DOM refs point at
 * the same shared nodes as other modules (see panels.js precedent).
 */
import { $, toast, esc, fmtTime, fmtDay } from "./ui.js";
import { md, planet } from "./markdown.js";
import { apiUrl } from "./config.js";
import { S, TIERS, chats, current, projects, savePrefs, setChats, setCurrent, setProjects } from "./state.js";
import { req, authedDownload } from "./api.js";
import { authHeaders } from "./auth-store.js";
import { renderAcct } from "./auth.js";
import { showChat, openTitle } from "./panels.js";

var chatCol = $("chatCol"), chatScroll = $("chatScroll"), chatTitle = $("chatTitle");
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

function getCtxId() { return ctxId; }
function getProjId() { return projId; }

export { chipForAttachment, rememberApprovalTokens, approvalTokenFor, decideApproval, msgEl, hydrateUploadImages, versionGroup, renderChat, maybeScroll, scrollBottom, refreshChats, refreshProjects, copyText, legacyCopy, stopSpeaking, speakable, speakText, renderRecents, renderProjects, chatMarkdown, downloadMarkdown, setActiveTier, renderModelDD, getCtxId, getProjId };
