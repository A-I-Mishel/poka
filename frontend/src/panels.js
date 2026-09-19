/* Pluto web client module: panels (view switching, server-data panels, mode toggles).
 * Split from the vanilla-JS monolith; behavior preserved.
 */
import { $, toast, esc, escapeAttr, enc, isSafeHttpUrl, fmtStamp } from "./ui.js";
import { ic, IC, artIcon } from "./markdown.js";
import { req, authedDownload } from "./api.js";
import { S, chats, current, projects, setPref } from "./state.js";
import { ask } from "./auth.js";

/* Module-local refs to shared elements. Grabbed in initPanels(), not
 * at import time, so this module imports cleanly without a DOM
 * (node/vitest/smoke phase 1). app.js calls initPanels() at boot. */
var backBtn = null, panelBody = null,
  viewChat = null, viewPanel = null,
  chatTitle = null;
var modeToggle = null, thumb = null, modeBtns = [],
  webBtn = null, input = null;
var _panelsInit = false;
function initPanels() {
  if (_panelsInit) return;
  _panelsInit = true;
  backBtn = $("backBtn"); panelBody = $("panelBody");
  viewChat = $("viewChat"); viewPanel = $("viewPanel");
  chatTitle = $("chatTitle");
  modeToggle = $("modeToggle");
  thumb = modeToggle && modeToggle.querySelector(".seg-thumb");
  modeBtns = (modeToggle && modeToggle.querySelectorAll("button")) || [];
  webBtn = $("webSearchBtn"); input = $("input");
  wireTheme();
  wireNav();
  wirePanel();
  wireToggles();
} /* end initPanels */

/* Chat title derived from the open conversation (moved here from chat.js
 * so panels stays the sole importer direction: chat -> panels). */
function openTitle() {
  for (var i = 0; i < current.length; i++) {
    if (current[i] && current[i].role === "user" && String(current[i].content || "").trim())
      return String(current[i].content).trim().slice(0, 60);
  }
  return "New chat";
}
/* ---------- theme ---------- */
function applyTheme() {
  document.documentElement.setAttribute("data-theme", S.theme);
  $("icoMoon").classList.toggle("hidden", S.theme === "light");
  $("icoSun").classList.toggle("hidden", S.theme !== "light");
}
function wireTheme() {
$("themeBtn").addEventListener("click", function () {
  setPref("theme", S.theme === "dark" ? "light" : "dark");
  applyTheme();
});
} /* end wireTheme */
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
function wireNav() {
backBtn.addEventListener("click", showChat);
document.querySelectorAll("[data-section]").forEach(function (btn) {
  btn.addEventListener("click", function () {
    openSection(btn.getAttribute("data-section"));
    if (window.innerWidth < 861) document.body.classList.add("folded");
  });
});
} /* end wireNav */

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
        return '<div class="card" data-title="' + escapeAttr(String(title).toLowerCase()) + '" data-bid="' + escapeAttr(x.id) + '">' + ic("flask") +
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
        return '<div class="card" data-wfid="' + escapeAttr(w.id) + '">' + ic("flask") +
          '<div class="g"><div class="t">' + esc(w.name || "Untitled") + '</div><div class="s">' + esc(sub) + "</div></div>" +
          '<button class="row-btn second" data-wfrun="' + escapeAttr(w.id) + '" title="Run">▶</button>' +
          '<button class="row-btn second" data-wfedit="' + escapeAttr(w.id) + '" title="Edit">✎</button>' +
          '<button class="row-btn second" data-wfdup="' + escapeAttr(w.id) + '" title="Duplicate">⧉</button>' +
          '<button class="row-btn" data-wfdel="' + escapeAttr(w.id) + '" title="Delete">✕</button></div>';
      }).join("");
      if (!list.length) rows = '<div class="sub" style="margin-top:16px">No workflows yet. Save a fixed tool sequence below and run it anytime.</div>';
      return "<h2>Workflows</h2><div class=\"sub\">Saved tool pipelines. Steps are JSON with {{input}} and {{steps.N.output}} templates; send_gmail is blocked.</div>" +
        '<div class="cards" id="wfList">' + rows + "</div>" +
        '<h2 style="margin-top:22px" id="wfFormTitle">New workflow</h2>' +
        '<input class="input panel-input" id="wfName" type="text" placeholder="Name">' +
        '<input class="input panel-input" id="wfDesc" type="text" placeholder="Description (optional)">' +
        '<textarea class="notes-ta" id="wfSteps" placeholder="Steps JSON array"></textarea>' +
        '<div class="notes-actions"><button class="btn solid" id="wfSave">Save workflow</button><button class="btn ghost" id="wfCancelEdit" style="display:none">Cancel edit</button></div>' +
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
        text = (await req("/api/projects/" + enc(p.id) + "/context")).text || "";
      } catch (e) {
        return "<h2>" + esc(p.name || "Project") + "</h2><div class=\"sub\">Cannot load context: " + esc(e.message) + "</div>";
      }
      return "<h2>" + esc(p.name || "Project") + "</h2><div class=\"sub\">Context is sent with every message in this project.</div>" +
        '<textarea class="notes-ta" id="projCtxTa" data-projid="' + escapeAttr(p.id) + '">' + esc(text) + "</textarea>" +
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
        return '<div class="card" data-up="' + escapeAttr(f.id) + '">' + ic("doc") +
          '<div class="g"><div class="t">' + esc(f.name) + '</div><div class="s">' + esc(f.kind || "file") + "</div></div>" +
          '<button class="row-btn" title="Download">' + IC.down + "</button>" +
          '<button class="row-btn" data-delup="' + escapeAttr(f.id) + '" title="Delete">✕</button></div>';
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
        var hint = (a.kind === "html") ? "HTML — download, then open in browser to run" : (a.sub || a.kind || "");
        return '<div class="art" data-art="' + escapeAttr(a.id) + '" data-name="' + escapeAttr(a.name || "file") + '"><div class="th">' + IC[artIcon(a.kind)] + "</div>" +
          '<div class="b"><div class="t">' + esc(a.name || "file") + '</div><div class="s">' + esc(hint) + "</div></div>" +
          '<button class="row-btn second" data-regen="' + escapeAttr(a.id) + '" title="Regenerate">↻</button>' +
          '<button class="row-btn" data-delart="' + escapeAttr(a.id) + '" title="Delete">✕</button></div>';
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
          '<button class="row-btn" data-open="' + escapeAttr(x.url) + '" title="Open">' + IC.open + "</button></div>";
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
/* Workflow edit mode (module scope: must survive across clicks). null =
 * creating; otherwise the id being updated. exitWfEdit also runs when the
 * workflows section re-renders, since the form DOM is rebuilt. */
var wfEditingId = null;
function exitWfEdit() {
  wfEditingId = null;
  var t = $("wfFormTitle"); if (t) t.textContent = "New workflow";
  var s = $("wfSave"); if (s) s.textContent = "Save workflow";
  var c = $("wfCancelEdit"); if (c) c.style.display = "none";
}
async function _onPanelClick(e) {
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
  var du = e.target.closest("[data-delup]");
  if (du) {
    e.stopPropagation();
    try {
      await req("/api/uploads/" + enc(du.getAttribute("data-delup")), { method: "DELETE" });
      toast("File deleted");
      openSection("files");
    } catch (err) { toast("Delete failed: " + err.message); }
    return;
  }
  var up = e.target.closest("[data-up]");
  if (up) {
    var card = up.closest(".card");
    var nm = card ? card.querySelector(".t").textContent : "file";
    authedDownload("/api/uploads/" + enc(up.getAttribute("data-up")) + "/file", nm);
    return;
  }
  var rg = e.target.closest("[data-regen]");
  if (rg) {
    e.stopPropagation();
    try {
      await req("/api/artifacts/" + enc(rg.getAttribute("data-regen")) + "/regenerate", { method: "POST" });
      toast("Regenerated");
      openSection("artifacts");
    } catch (err) { toast("Regenerate failed: " + err.message); }
    return;
  }
  var da = e.target.closest("[data-delart]");
  if (da) {
    e.stopPropagation();
    try {
      await req("/api/artifacts/" + enc(da.getAttribute("data-delart")), { method: "DELETE" });
      toast("Artifact deleted");
      openSection("artifacts");
    } catch (err) { toast("Delete failed: " + err.message); }
    return;
  }
  var art = e.target.closest("[data-art]");
  if (art) {
    authedDownload("/api/artifacts/" + enc(art.getAttribute("data-art")) + "/download", art.getAttribute("data-name") || "file");
    return;
  }
  var bb = e.target.closest("[data-brief]");
  if (bb) {
    var bid = bb.closest(".card").getAttribute("data-bid");
    if (bb.getAttribute("data-brief") === "del") {
      try {
        await req("/api/briefs/" + enc(bid), { method: "DELETE" });
        toast("Brief deleted");
        openSection("research");
      } catch (err) { toast("Delete failed: " + err.message); }
    } else {
      try {
        var meta = await req("/api/briefs/" + enc(bid) + "/docx", { method: "POST" });
        if (meta && meta.id) authedDownload("/api/artifacts/" + enc(meta.id) + "/download", meta.name || "brief.docx");
        else toast("Document queued — see Artifacts");
      } catch (err) { toast("Export failed: " + err.message); }
    }
    return;
  }
  var op = e.target.closest("[data-open]");
  if (op) {
    var _url = op.getAttribute("data-open") || "";
    /* data-open carries server-provided source URLs: only open http(s),
     * never javascript:/data: (stored-XSS gate for search results). */
    if (!isSafeHttpUrl(_url)) { toast("Blocked unsafe link."); return; }
    window.open(_url, "_blank", "noopener");
    return;
  }
  /* Workflow edit mode: null = creating; otherwise the id being updated. */
  if (e.target.closest("#wfCancelEdit")) {
    $("wfName").value = "";
    $("wfDesc").value = "";
    $("wfSteps").value = "";
    exitWfEdit();
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
      /* The form DOM is rebuilt on every section render; only PUT when the
       * visible form is genuinely in edit mode (title proves it). */
      var editing = wfEditingId && $("wfFormTitle") && $("wfFormTitle").textContent === "Edit workflow";
      if (editing) {
        await req("/api/workflows/" + enc(wfEditingId), { method: "PUT", body: JSON.stringify({ name: wname, description: wdesc, steps: wsteps }) });
        toast("Workflow updated");
      } else {
        wfEditingId = null;
        await req("/api/workflows", { method: "POST", body: JSON.stringify({ name: wname, description: wdesc, steps: wsteps }) });
        toast("Workflow saved");
      }
      exitWfEdit();
      openSection("workflows");
    } catch (err) { toast("Save failed: " + err.message); }
    return;
  }
  var wfe = e.target.closest("[data-wfedit]");
  if (wfe) {
    e.stopPropagation();
    var eid = wfe.closest(".card").getAttribute("data-wfid");
    try {
      var w = await req("/api/workflows/" + enc(eid));
      $("wfName").value = w.name || "";
      $("wfDesc").value = w.description || "";
      $("wfSteps").value = JSON.stringify(w.steps || [], null, 2);
      wfEditingId = eid;
      $("wfFormTitle").textContent = "Edit workflow";
      $("wfSave").textContent = "Update workflow";
      $("wfCancelEdit").style.display = "";
      $("wfFormTitle").scrollIntoView({ block: "nearest" });
      $("wfName").focus();
    } catch (err) { toast("Cannot load workflow: " + err.message); }
    return;
  }
  var wdu = e.target.closest("[data-wfdup]");
  if (wdu) {
    e.stopPropagation();
    var did2 = wdu.closest(".card").getAttribute("data-wfid");
    try {
      var src = await req("/api/workflows/" + enc(did2));
      await req("/api/workflows", { method: "POST", body: JSON.stringify({ name: String(src.name || "Workflow") + " (copy)", description: src.description || "", steps: src.steps || [] }) });
      toast("Workflow duplicated");
      openSection("workflows");
    } catch (err) { toast("Duplicate failed: " + err.message); }
    return;
  }
  var wr = e.target.closest("[data-wfrun]");
  if (wr) {
    e.stopPropagation();
    var wid = wr.closest(".card").getAttribute("data-wfid");
    ask("Run input (empty for none)", "", async function (v) {
      if (v === null) return;
      try {
        var out = await req("/api/workflows/" + enc(wid) + "/run", { method: "POST", body: JSON.stringify({ input: v || "" }) });
        showWfResult(out);
      } catch (err) { toast("Run failed: " + err.message); }
    });
    return;
  }
  var wd = e.target.closest("[data-wfdel]");
  if (wd) {
    e.stopPropagation();
    var did = wd.closest(".card").getAttribute("data-wfid");
    if (!window.confirm("Delete this workflow? This cannot be undone.")) return;
    try {
      await req("/api/workflows/" + enc(did), { method: "DELETE" });
      if (wfEditingId === did) exitWfEdit();
      toast("Workflow deleted");
      openSection("workflows");
    } catch (err) { toast("Delete failed: " + err.message); }
    return;
  }
  if (e.target.closest("#projCtxSave")) {
    var ta = $("projCtxTa");
    try {
      await req("/api/projects/" + enc(ta.getAttribute("data-projid")) + "/context", { method: "PUT", body: JSON.stringify({ text: ta.value }) });
      toast("Context saved");
    } catch (err) { toast("Save failed: " + err.message); }
    return;
  }
}
function _onPanelInput(e) {
  if (e.target.id === "researchFilter") {
    var q = e.target.value.toLowerCase();
    panelBody.querySelectorAll("#researchList .card").forEach(function (c) {
      c.style.display = c.getAttribute("data-title").indexOf(q) > -1 ? "" : "none";
    });
  }
}
function wirePanel() {
  panelBody.addEventListener("click", _onPanelClick);
  panelBody.addEventListener("input", _onPanelInput);
} /* end wirePanel */
function wireToggles() {
/* ponytail: MORE/RECENTS label-toggles, persisted */
  initMoreToggle();
  initRecentsToggle();
  initFold();
  initModeSwitch();
} /* end wireToggles */
function initMoreToggle() {
  var btn = $("moreToggle"), list = $("moreItems");
  if (!btn || !list) return;
  var collapsed = !!S.moreCollapsed;
  list.classList.toggle("collapsed", collapsed);
  btn.classList.toggle("collapsed", collapsed);
  btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
  btn.addEventListener("click", function () {
    var c = list.classList.toggle("collapsed");
    btn.classList.toggle("collapsed", c);
    btn.setAttribute("aria-expanded", c ? "false" : "true");
    setPref("moreCollapsed", c);
  });
}
/* ponytail: RECENTS collapsible like MORE, persisted */
function initRecentsToggle() { /* uses shared .label-toggle CSS */
  var btn = $("recentsToggle"), list = $("recentList");
  if (!btn || !list) return;
  var collapsed = !!S.recentsCollapsed;
  list.classList.toggle("collapsed", collapsed);
  btn.classList.toggle("collapsed", collapsed);
  btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
  btn.addEventListener("click", function () {
    var c = list.classList.toggle("collapsed");
    btn.classList.toggle("collapsed", c);
    btn.setAttribute("aria-expanded", c ? "false" : "true");
    setPref("recentsCollapsed", c);
  });
}
function initFold() {
$("foldBtn").addEventListener("click", function () {
  document.body.classList.toggle("folded");
  if (window.innerWidth > 860) {
    setPref("folded", document.body.classList.contains("folded"));
  }
});
$("backdrop").addEventListener("click", function () { document.body.classList.add("folded"); });
} /* end initFold */
function initModeSwitch() {
  modeBtns.forEach(function (b) {
    b.addEventListener("click", function () { setMode(b.getAttribute("data-mode")); });
  });
  webBtn.addEventListener("click", function () { setWeb(!webBtn.classList.contains("active")); });
} /* end initModeSwitch */
/* ---------- toggles (refs owned by initPanels, see module top) ---------- */
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
  if (!skipSave) setPref("mode", mode);
  else S.mode = mode;
  modeToggle.setAttribute("data-mode", mode);
  modeBtns.forEach(function (b) { b.classList.toggle("active", b.getAttribute("data-mode") === mode); });
  updatePlaceholder();
  placeThumb();
}
function setWeb(on) {
  setPref("web", on);
  webBtn.classList.toggle("active", on);
  webBtn.setAttribute("aria-pressed", on ? "true" : "false");
  updatePlaceholder();
}


export { initPanels, setActiveNav, openSection, showChat, openTitle, allMessages, showWfResult, exitWfEdit, applyTheme, updatePlaceholder, placeThumb, setMode, setWeb, webBtn };
