// @ts-check
/* Pluto web client module: route (hash deep-links; pure, testable in node).
 *
 * No framework: the open conversation has no client id until archived,
 * so `#/chats/<id>` means "adopt archived chat <id> as current" (the
 * same POST /api/chats/open the recents list uses). `#/` (or anything
 * unrecognized) is the home view. IDs are 16-hex (see
 * services/storage/ids.py is_valid_id); anything else never fires the
 * API and falls back home.
 */

/** @param {*} id */
function chatHash(id) {
  var s = String(id == null ? "" : id);
  return /^[0-9a-fA-F]{16}$/.test(s) ? "#/chats/" + s : "#/";
}
/** @param {*} h */
function parseHash(h) {
  var s = String(h || "");
  if (s.charAt(0) === "#") s = s.slice(1);
  var m = /^\/chats\/([^/]+)\/?$/.exec(s);
  if (m) {
    var id = "";
    try { id = decodeURIComponent(m[1]); } catch (e) { id = ""; }
    if (/^[0-9a-fA-F]{16}$/.test(id)) return { kind: "chat", id: id };
  }
  return { kind: "home", id: "" };
}
var _lastSynced = "";
/** @param {*} id */
function syncHashForChat(id) {
  var want = chatHash(id);
  _lastSynced = want;
  try {
    if (typeof window !== "undefined" && window.location && window.location.hash !== want) {
      window.location.hash = want;
    }
  } catch (e) {}
  return want;
}
/** @param {*} h */
function isSyncedHash(h) {
  return String(h || "") === _lastSynced;
}

export { chatHash, parseHash, syncHashForChat, isSyncedHash };
