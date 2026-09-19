import { beforeEach, describe, expect, it } from "vitest";

import { authHeaders, getToken, getVisitor, setToken } from "./auth-store.js";

function memoryStorage(seed = {}) {
  const m = new Map(Object.entries(seed));
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => void m.set(k, String(v)),
    removeItem: (k) => void m.delete(k),
    _map: m,
  };
}

describe("auth-store", () => {
  let store;
  beforeEach(() => {
    store = memoryStorage();
    globalThis.localStorage = store;
  });

  it("never persists sessions in JS (HttpOnly cookie mode)", () => {
    setToken("abc");
    expect(getToken()).toBe("");
    expect(store.getItem("pluto_token")).toBe(null);
    expect(store.getItem("poka_token")).toBe(null);
  });

  it("clears legacy tokens once", () => {
    store.setItem("poka_token", "legacy-1");
    store.setItem("pluto_token", "legacy-2");
    expect(getToken()).toBe("");
    expect(store.getItem("pluto_token")).toBe(null);
    expect(store.getItem("poka_token")).toBe(null);
  });

  it("mints a stable 128-bit visitor id", () => {
    const v1 = getVisitor();
    expect(v1).toMatch(/^[0-9a-f]{32}$/);
    expect(getVisitor()).toBe(v1);
  });

  it("builds cookie-session headers (visitor + CSRF, no Bearer)", () => {
    const h = authHeaders();
    expect(h.Authorization).toBe(undefined);
    expect(h["X-Pluto-Csrf"]).toBe("1");
    expect(h["X-Pluto-Visitor"]).toMatch(/^[0-9a-f]{32}$/);
  });
});
