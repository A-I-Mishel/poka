/* Pluto web client module: auth-store (visitor storage + cookie-session headers).
 * Sessions live in an HttpOnly `pluto_session` cookie (set/cleared by
 * /api/auth/*) so injected JS cannot exfiltrate them. This module never
 * stores the session — getToken/setToken remain as migration shims that
 * clear any legacy localStorage token once, then report logged-out.
 */
import { TOKEN_KEY, LEGACY_TOKEN_KEY, VISITOR_KEY } from "./config.js";

function _clearLegacyTokens() {
  try {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(LEGACY_TOKEN_KEY);
  } catch (e) {}
}

function getToken() {
  // Migration shim: drop legacy Bearer tokens persisted before the
  // HttpOnly-cookie switch, then always report empty (cookie is the
  // source of truth; JS cannot read it by design).
  _clearLegacyTokens();
  return "";
}
function setToken() {
  // No-op by design (kept for call-site compat): the session cookie is
  // written by the server via Set-Cookie, not by JS.
  _clearLegacyTokens();
}
function authHeaders() {
  var h = {};
  var v = getVisitor();
  if (v) h["X-Pluto-Visitor"] = v;
  // Required for cookie-authenticated POST/PUT/PATCH/DELETE (see
  // backend/deps.py _require_csrf). Safe to send always.
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

export { getToken, setToken, authHeaders, getVisitor };
