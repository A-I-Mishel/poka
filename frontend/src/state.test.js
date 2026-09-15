import { beforeEach, describe, expect, it } from "vitest";

import { S, defaultPrefs, loadPrefs, savePrefs } from "./state.js";

function memoryStorage() {
  const m = new Map();
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => void m.set(k, String(v)),
    removeItem: (k) => void m.delete(k),
  };
}

describe("state prefs", () => {
  beforeEach(() => {
    delete globalThis.localStorage;
  });

  it("has safe defaults without storage", () => {
    expect(defaultPrefs()).toMatchObject({
      theme: "dark",
      mode: "fast",
      model: "",
      projectId: null,
    });
    expect(loadPrefs().theme).toBe("dark");
  });

  it("round-trips through storage", () => {
    globalThis.localStorage = memoryStorage();
    const prev = S.theme;
    S.theme = "light";
    try {
      savePrefs();
      expect(loadPrefs().theme).toBe("light");
    } finally {
      S.theme = prev;
      savePrefs();
      delete globalThis.localStorage;
    }
  });

  it("ignores corrupt storage", () => {
    globalThis.localStorage = {
      getItem: () => "{not json",
      setItem: () => {},
      removeItem: () => {},
    };
    try {
      expect(loadPrefs().mode).toBe("fast");
    } finally {
      delete globalThis.localStorage;
    }
  });
});
