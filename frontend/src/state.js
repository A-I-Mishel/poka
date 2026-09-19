// @ts-check
/* Pluto web client module: state (prefs + shared server state; sole owner of mutable globals).
 * Split from the vanilla-JS monolith; behavior preserved.
 */
import { PREFS_KEY, LEGACY_PREFS_KEY } from "./config.js";

/* ---------- prefs (local only: theme/mode/selection) ---------- */
function defaultPrefs() {
  return { theme: "dark", folded: false, mode: "fast", web: false, model: "", projectId: null, recentsCollapsed: false, moreCollapsed: false };
}
/**
 * Known pref keys (single source for setPref typing).
 * @typedef {"theme"|"folded"|"mode"|"web"|"model"|"projectId"|"recentsCollapsed"|"moreCollapsed"} PrefKey
 */
function loadPrefs() {
  var p = defaultPrefs();
  try {
    var raw = localStorage.getItem(PREFS_KEY) || localStorage.getItem(LEGACY_PREFS_KEY);
    if (raw) {
      /** @type {Object<string, *>} */
      var parsed = JSON.parse(raw);
      /** @type {Object<string, *>} */
      var assignable = p;
      Object.keys(p).forEach(function (k) {
        if (parsed[k] !== undefined) assignable[k] = parsed[k];
      });
    }
  } catch (e) {}
  return p;
}
export const S = loadPrefs();
function savePrefs() {
  try { localStorage.setItem(PREFS_KEY, JSON.stringify(S)); } catch (e) {}
}

/* ---------- pref writes (single funnel: assign + persist + notify) ----------
 * Direct `S.x = v` mutation still works, but new code should use
 * setPref() so future subscribers (badge, title, panels) update without
 * each writer remembering every render call. */
/** @type {Array<function(PrefKey, *): void>} */
var _prefSubs = [];
/** @param {function(PrefKey, *): void} fn */
function subscribe(fn) {
  if (typeof fn === "function") _prefSubs.push(fn);
  return function () {
    _prefSubs = _prefSubs.filter(function (f) { return f !== fn; });
  };
}
/**
 * @param {PrefKey} key
 * @param {*} value
 */
function setPref(key, value) {
  /* S has a fixed inferred shape (good for readers); write through a
   * record view so a union key does not collapse to never. */
  /** @type {Object<string, *>} */
  var record = S;
  record[key] = value;
  savePrefs();
  _prefSubs.forEach(function (fn) {
    try { fn(key, value); } catch (e) {}
  });
}

/* ---------- server state ---------- */
var TIERS = [];
var AUTH_MODE = "open";
var chats = [];    /* archived records {id,title,messages,project_id} */
var current = [];  /* open conversation messages */
var projects = []; /* [{id,name}] */

/** @param {*} v */
export function setTIERS(v) { TIERS = v; }
/** @param {*} v */
export function setAuthMode(v) { AUTH_MODE = v; }
/** @param {*} v */
export function setChats(v) { chats = v; }
/** @param {*} v */
export function setCurrent(v) { current = v; }
/** @param {*} v */
export function setProjects(v) { projects = v; }

export { defaultPrefs, loadPrefs, savePrefs, setPref, subscribe, TIERS, AUTH_MODE, chats, current, projects };
