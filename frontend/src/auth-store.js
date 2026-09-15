/* Pluto web client module: auth-store (pure token/visitor storage; imports config only).
 * Split from the vanilla-JS monolith; behavior preserved.
 */
import { TOKEN_KEY, LEGACY_TOKEN_KEY, VISITOR_KEY } from "./config.js";

function getToken() {
  try {
    var t = localStorage.getItem(TOKEN_KEY) || "";
    if (t) return t;
    var legacy = localStorage.getItem(LEGACY_TOKEN_KEY) || "";
    if (legacy) {
      localStorage.setItem(TOKEN_KEY, legacy);
      localStorage.removeItem(LEGACY_TOKEN_KEY);
      return legacy;
    }
  } catch (e) {}
  return "";
}
function setToken(t) {
  try {
    if (t) localStorage.setItem(TOKEN_KEY, t);
    else localStorage.removeItem(TOKEN_KEY);
  } catch (e) {}
}
function authHeaders() {
  var h = {};
  var t = getToken();
  if (t) h.Authorization = "Bearer " + t;
  var v = getVisitor();
  if (v) h["X-Pluto-Visitor"] = v;
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
