import { beforeEach, describe, expect, it, vi } from "vitest";

// auth.js must import without a DOM (wiring lives in initAuth()).
import { authAsync, pwHint } from "./auth.js";

describe("pwHint (mirrors services/accounts rules)", () => {
  it("accepts a strong password", () => {
    expect(pwHint("Str0ng!pass", "alice")).toBe("");
  });
  it("rejects short passwords", () => {
    expect(pwHint("Ab1!", "alice")).toMatch(/8 characters/);
  });
  it("rejects passwords containing the username", () => {
    expect(pwHint("alice99!X", "alice")).toMatch(/username/);
    expect(pwHint("xxAlice99!x", "alice")).toMatch(/username/);
  });
  it("rejects weak character-class mixes", () => {
    expect(pwHint("alllowercase1", "bob")).toMatch(/Weak/);
  });
  it("handles empty input", () => {
    expect(pwHint("", "bob")).toBe("");
  });
});

describe("authAsync", () => {
  beforeEach(() => {
    vi.stubGlobal("document", {
      getElementById: () => ({
        textContent: "",
        classList: { add() {}, remove() {} },
        focus() {},
      }),
    });
    vi.stubGlobal("setTimeout", (fn) => 0);
  });
  it("returns a pending promise (dialog flow, no DOM crash)", () => {
    const p = authAsync("Log in");
    expect(typeof (p && p.then)).toBe("function");
    vi.unstubAllGlobals();
  });
});
