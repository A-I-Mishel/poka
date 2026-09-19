import { beforeEach, describe, expect, it } from "vitest";

import { authHeaders, clearToken, getToken, getVisitor, setToken } from "./auth-store.js";

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

  it("persists the Bearer fallback token for cross-site cookie blocks", () => {
    setToken("pluto_abc123");
    expect(getToken()).toBe("pluto_abc123");
    expect(store.getItem("pluto_token")).toBe("pluto_abc123");
    clearToken();
    expect(getToken()).toBe("");
    expect(store.getItem("pluto_token")).toBe(null);
  });

  it("clears legacy tokens but keeps the fallback token", () => {
    store.setItem("poka_token", "legacy-1");
    setToken("pluto_fallback");
    expect(getToken()).toBe("pluto_fallback");
    expect(store.getItem("poka_token")).toBe(null);
    expect(store.getItem("pluto_token")).toBe("pluto_fallback");
    clearToken();
  });

  it("mints a stable 128-bit visitor id", () => {
    const v1 = getVisitor();
    expect(v1).toMatch(/^[0-9a-f]{32}$/);
    expect(getVisitor()).toBe(v1);
  });

  it("builds session headers (visitor + CSRF, Bearer fallback when set)", () => {
    clearToken();
    const anon = authHeaders();
    expect(anon.Authorization).toBe(undefined);
    expect(anon["X-Pluto-Csrf"]).toBe("1");
    expect(anon["X-Pluto-Visitor"]).toMatch(/^[0-9a-f]{32}$/);
    setToken("pluto_abc123");
    const authed = authHeaders();
    expect(authed.Authorization).toBe("Bearer pluto_abc123");
    expect(authed["X-Pluto-Csrf"]).toBe("1");
    clearToken();
  });
});
