/* Node smoke: import every frontend module with browser stubs.
 * Catches top-level ReferenceErrors, missing exports, and broken hook
 * wiring without a browser. Run: node smoke.mjs (exit non-zero on failure).
 */

function makeClassList() {
  return { add() {}, remove() {}, toggle() {}, contains() { return false; } };
}
function makeEl() {
  const el = {
    children: [],
    style: {},
    dataset: {},
    classList: makeClassList(),
    textContent: "",
    value: "",
    innerHTML: "",
    disabled: false,
    width: 0,
    height: 0,
    addEventListener() {},
    removeEventListener() {},
    appendChild(c) { el.children.push(c); return c; },
    remove() {},
    focus() {},
    click() {},
    select() {},
    querySelector() { return makeEl(); },
    querySelectorAll() { return []; },
    getAttribute() { return null; },
    setAttribute() {},
    getBoundingClientRect() { return { width: 0, height: 0, left: 0, top: 0 }; },
    getContext() { return { drawImage() {} }; },
    contains() { return false; },
    closest() { return null; },
  };
  return el;
}

const elsById = new Map();
function $(id) {
  if (!elsById.has(id)) elsById.set(id, makeEl());
  return elsById.get(id);
}

const store = new Map();
globalThis.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => void store.set(k, String(v)),
  removeItem: (k) => void store.delete(k),
};

let failures = 0;
function check(name, cond) {
  if (cond) {
    console.log("ok:", name);
  } else {
    failures += 1;
    console.error("FAIL:", name);
  }
}

// 1. Every module imports with NO document/window (only localStorage).
// Top-level DOM refs/listeners live in init*() — import must not throw.
const ui = await import("./src/ui.js");
const config = await import("./src/config.js");
const markdown = await import("./src/markdown.js");
const authStore = await import("./src/auth-store.js");
const state = await import("./src/state.js");
const api = await import("./src/api.js");
const auth = await import("./src/auth.js");
const panels = await import("./src/panels.js");
const composer = await import("./src/composer.js");
const render = await import("./src/render.js");
const send = await import("./src/send.js");
const chat = await import("./src/chat.js");
check("all modules import without DOM", true);

// 2. Install browser stubs, then run every init*() (wiring phase).
globalThis.document = {
  getElementById: $,
  createElement: () => makeEl(),
  querySelector: () => makeEl(),
  querySelectorAll: () => [],
  addEventListener() {},
  body: makeEl(),
  documentElement: makeEl(),
};
globalThis.window = { addEventListener() {} };
for (const [name, fn] of [
  ["initRender", render.initRender],
  ["initSend", send.initSend],
  ["initAuth", auth.initAuth],
  ["initPanels", panels.initPanels],
  ["initComposer", composer.initComposer],
  ["initChat", chat.initChat],
]) {
  try {
    fn();
    check(`init ${name} runs`, true);
  } catch (e) {
    check(`init ${name} runs (${e.message})`, false);
  }
}
// init is idempotent: second pass must not double-register.
try {
  render.initRender(); send.initSend(); auth.initAuth();
  panels.initPanels(); composer.initComposer(); chat.initChat();
  check("init functions idempotent", true);
} catch (e) {
  check(`init functions idempotent (${e.message})`, false);
}

// 2. Key exports exist and are callable.
for (const [mod, name, fn] of [
  [markdown, "md", markdown.md],
  [ui, "toast", ui.toast],
  [api, "req", api.req],
  [auth, "authAsync", auth.authAsync],
  [panels, "openSection", panels.openSection],
  [panels, "setMode", panels.setMode],
  [composer, "addChip", composer.addChip],
  [chat, "renderChat", chat.renderChat],
  [chat, "send", chat.send],
  [config, "apiUrl", config.apiUrl],
]) {
  void mod;
  check(`export ${name} is function`, typeof fn === "function");
}

// 3. State setters update live bindings.
state.setTIERS(["t1"]);
const state2 = await import("./src/state.js");
check("setTIERS live binding", state2.TIERS.join() === "t1");
state.setTIERS([]);

// 4. api 401 flow uses hooks (dependency inversion): first 401, then ok.
// Transport is cookie-first with a Bearer fallback (auth-store.js):
// the hook re-prompts login, then the retry succeeds with the fresh
// cookie attached by the browser — or the Bearer fallback when
// third-party cookies are blocked cross-site (Vercel + Render).
let calls = 0;
globalThis.fetch = async () => {
  calls += 1;
  if (calls === 1) {
    return { status: 401, ok: false, statusText: "Unauthorized" };
  }
  return { status: 200, ok: true, json: async () => ({ ok: true }) };
};
api.setApiHooks({
  onUnauthorized: async () => true,
  onSessionRefreshed: async () => {},
});
const out = await api.req("/api/chats", { method: "GET" });
check("401 hook retry succeeds", out && out.ok === true);
// Bearer fallback store: empty by default, round-trips when set (login
// persists the JSON token so /me succeeds even if cookies are blocked).
check("fallback token empty by default", authStore.getToken() === "");
authStore.setToken("pluto_smoke");
check("fallback token round-trips", authStore.getToken() === "pluto_smoke");
check("fallback token sent as Bearer", authStore.authHeaders().Authorization === "Bearer pluto_smoke");
authStore.clearToken();
check("fallback token clears", authStore.getToken() === "");
check("fetch called twice", calls === 2);

// 5. Pure rendering still correct through the module graph.
check("md via bundle", markdown.md("**x**").includes("<b>x</b>"));

if (failures) {
  console.error(`${failures} smoke failure(s)`);
  process.exit(1);
}
console.log("smoke: all green");
