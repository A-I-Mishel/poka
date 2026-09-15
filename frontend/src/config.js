/* Pluto web client module: config (env-driven constants, never hardcoded).
 * Split from the vanilla-JS monolith; behavior preserved.
 */
export const TOKEN_KEY = "pluto_token";
export const LEGACY_TOKEN_KEY = "poka_token";
export const VISITOR_KEY = "pluto_visitor";
export const PREFS_KEY = "pluto.v1";
export const LEGACY_PREFS_KEY = "poka.v1";
export const AUTH_SEEN_KEY = "pluto_auth_seen";
/* Backend message cap (POST /api/chat schema). */
export const MAX_MSG_CHARS = 20000;

export var API_BASE = "";
try {
  var _envUrl = (import.meta.env && import.meta.env.VITE_API_URL) || "";
  API_BASE = String(_envUrl).replace(/\/+$/, "");
} catch (e) { API_BASE = ""; }
export function apiUrl(path) { return API_BASE + path; }
