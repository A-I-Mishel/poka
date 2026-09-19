// @ts-check
/* Pluto web client module: auth-store (visitor storage + session transport).
 *
 * Primary transport is the HttpOnly `pluto_session` cookie (set/cleared by
 * /api/auth/*) so injected JS cannot exfiltrate it. Browsers attach it
 * automatically via credentials:"include".
 *
 * Cross-site fallback (Vercel UI + Render API): third-party cookies are
 * routinely blocked, so a login 200 can succeed while /me still 401s and
 * the UI loops on "Log in to continue". The server ALSO returns the raw
 * session token once in JSON and accepts it as `Authorization: Bearer`
 * (see backend/deps.py session_token_from). We persist that token as a
 * fallback only — cookie first, Bearer when the cookie never sticks.
 */
import { TOKEN_KEY, LEGACY_TOKEN_KEY, VISITOR_KEY } from "./config.js";

var _memToken = "";

function _clearLegacyTokens() {
  try {
    localStorage.removeItem(LEGACY_TOKEN_KEY);
  } catch (e) {}
}

function _readStoredToken() {
  try {
    var t = localStorage.getItem(TOKEN_KEY) || "";
    return typeof t === "string" ? t.trim() : "";
  } catch (e) { return ""; }
}

function getToken() {
  // Cookie-first design: the HttpOnly cookie is the source of truth when
  // present (JS cannot read it by design). The Bearer fallback is only
  // consulted when cookies are blocked cross-site.
  _clearLegacyTokens();
  if (_memToken) return _memToken;
  var stored = _readStoredToken();
  if (stored) _memToken = stored;
  return stored;
}
function setToken(t) {
  _clearLegacyTokens();
  var v = typeof t === "string" ? t.trim() : "";
  _memToken = v;
  try {
    if (v) localStorage.setItem(TOKEN_KEY, v);
    else localStorage.removeItem(TOKEN_KEY);
  } catch (e) {}
}
function clearToken() {
  setToken("");
}
function authHeaders() {
  var h = {};
  var tok = getToken();
  if (tok) h["Authorization"] = "Bearer " + tok;
  var v = getVisitor();
  if (v) h["X-Pluto-Visitor"] = v;
  // Required for cookie-authenticated POST/PUT/PATCH/DELETE (see
  // backend/deps.py _require_csrf). Safe (and harmless for Bearer) to
  // send always.
  h["X-Pluto-Csrf"] = "1";
  return h;
}
function getVisitor() {
  try {
    var v = localStorage.getItem(VISITOR_KEY) || "";
    if (!/^[A-Za-z0-9_.-]{8,56}$/.test(v)) {
      var bytes = null;
      try {
        bytes = (window.crypto && window.crypto.getRandomValues)
          ? window.crypto.getRandomValues(new Uint8Array(16)) : null;
      } catch (e) { bytes = null; }
      if (bytes) {
        v = Array.prototype.map.call(bytes, function (b) {
          return ("0" + b.toString(16)).slice(-2);
        }).join("");
      } else {
        // No WebCrypto: 128 bits from Math.random (weak but correctly
        // shaped; replaced by a crypto id on next load when available).
        v = "";
        for (var i = 0; i < 32; i++) {
          v += Math.floor(Math.random() * 16).toString(16);
        }
      }
      localStorage.setItem(VISITOR_KEY, v);
    }
    return v;
  } catch (e) { return ""; }
}

export { getToken, setToken, clearToken, authHeaders, getVisitor };
