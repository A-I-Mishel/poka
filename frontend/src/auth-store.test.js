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

  it("returns empty token when logged out", () => {
    expect(getToken()).toBe("");
  });

  it("round-trips tokens", () => {
    setToken("abc");
    expect(getToken()).toBe("abc");
    setToken("");
    expect(getToken()).toBe("");
  });

  it("migrates the legacy token once", () => {
    store.setItem("poka_token", "legacy-1");
    expect(getToken()).toBe("legacy-1");
    expect(store.getItem("pluto_token")).toBe("legacy-1");
    expect(store.getItem("poka_token")).toBe(null);
  });

  it("mints a stable 128-bit visitor id", () => {
    const v1 = getVisitor();
    expect(v1).toMatch(/^[0-9a-f]{32}$/);
    expect(getVisitor()).toBe(v1);
  });

  it("builds auth headers", () => {
    setToken("t");
    const h = authHeaders();
    expect(h.Authorization).toBe("Bearer t");
    expect(h["X-Pluto-Visitor"]).toMatch(/^[0-9a-f]{32}$/);
  });
});
