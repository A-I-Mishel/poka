/* Pluto web client module: state (prefs + shared server state; sole owner of mutable globals).
 * Split from the vanilla-JS monolith; behavior preserved.
 */
import { PREFS_KEY, LEGACY_PREFS_KEY } from "./config.js";

/* ---------- prefs (local only: theme/mode/selection) ---------- */
function defaultPrefs() {
  return { theme: "dark", folded: false, mode: "fast", web: false, model: "", projectId: null, recentsCollapsed: false, moreCollapsed: false };
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
export const S = loadPrefs();
function savePrefs() {
  try { localStorage.setItem(PREFS_KEY, JSON.stringify(S)); } catch (e) {}
}

/* ---------- server state ---------- */
var TIERS = [];
var AUTH_MODE = "open";
var chats = [];    /* archived records {id,title,messages,project_id} */
var current = [];  /* open conversation messages */
var projects = []; /* [{id,name}] */

export function setTIERS(v) { TIERS = v; }
export function setAuthMode(v) { AUTH_MODE = v; }
export function setChats(v) { chats = v; }
export function setCurrent(v) { current = v; }
export function setProjects(v) { projects = v; }

export { defaultPrefs, loadPrefs, savePrefs, TIERS, AUTH_MODE, chats, current, projects };
