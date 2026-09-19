// @ts-check
/* Pluto web client module: markdown (pure message rendering; testable in node).
 * Split from the vanilla-JS monolith; behavior preserved.
 */
import { esc } from "./ui.js";

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
function escHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
}
/* ---------- markdown (message content only, always escaped first) ---------- */
function md(t) {
  var s = esc(t);
  var stash = [];
  function hold(html) { var k = "\u0001" + stash.length + "\u0001"; stash.push(html); return k; }
  /* fenced code: language hint becomes a class; content stays verbatim */
  s = s.replace(/```([^\n`]*)\n?([\s\S]*?)```/g, function (m, lang, c) {
    var cls = lang ? ' class="lang-' + String(lang).replace(/[^\w-]/g, "") + '"' : "";
    return hold("<pre><code" + cls + ">" + c.replace(/\n$/, "") + "</code></pre>");
  });
  /* inline code — stashed so later passes never touch code contents */
  s = s.replace(/`([^`\n]+)`/g, function (m, c) { return hold("<code>" + c + "</code>"); });
  /* links: only https/http/mailto; target=_blank + noopener */
  s = s.replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)\]"'<>]+|mailto:[^\s)\]"'<>]+)\)/g,
    function (m, txt, url) {
      return '<a href="' + url + '" target="_blank" rel="noopener noreferrer">' + txt + "</a>";
    });
  /* bare URLs autolink (after links so already-built hrefs are untouched) */
  s = s.replace(/(^|[\s(\[])(https?:\/\/[^\s)\]"'<>]+)/g,
    function (m, pre, url) {
      return pre + '<a href="' + url + '" target="_blank" rel="noopener noreferrer">' + url + "</a>";
    });
  /* headings (longest first so #### stays a 4th-level heading) */
  s = s.replace(/^######\s+(.+)$/gm, "<h6>$1</h6>");
  s = s.replace(/^#####\s+(.+)$/gm, "<h5>$1</h5>");
  s = s.replace(/^####\s+(.+)$/gm, "<h4>$1</h4>");
  s = s.replace(/^###\s+(.+)$/gm, "<h3>$1</h3>");
  s = s.replace(/^##\s+(.+)$/gm, "<h2>$1</h2>");
  s = s.replace(/^#\s+(.+)$/gm, "<h2>$1</h2>");
  /* inline emphasis */
  s = s.replace(/\*\*([^*\n]+)\*\*/g, "<b>$1</b>");
  s = s.replace(/~~([^~\n]+)~~/g, "<s>$1</s>");
  s = s.replace(/(^|\s)\*([^*\n]+)\*(?=\s|$|[.,;:!?)])/g, "$1<em>$2</em>");
  /* block-level pass: paragraphs, and lists (only when a chunk is a list) */
  return s.split(/\n{2,}/).map(function (p) {
    if (/^\u0001\d+\u0001$/.test(p)) return p; // stashed code block — restored below
    if (/^\s*(?:-|\*|[0-9]+\.)\s+\S/m.test(p)) {
      var lis = p.split(/\n/).map(function (line) {
        return "<li>" + line.replace(/^\s*(?:-|\*|[0-9]+\.)\s+/, "") + "</li>";
      }).join("");
      return /^\s*[0-9]+\./.test(p) ? "<ol>" + lis + "</ol>" : "<ul>" + lis + "</ul>";
    }
    return "<p>" + p.replace(/\n/g, "<br>") + "</p>";
  }).join("").replace(/\u0001(\d+)\u0001/g, function (m, i) { return stash[Number(i)]; });
}

export { escHtml, PLANET_SVG, planet, IC, ic, artIcon, md };
