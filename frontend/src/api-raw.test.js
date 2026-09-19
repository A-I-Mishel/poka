import { afterEach, describe, expect, it, vi } from "vitest";

import { rawReq, req, setApiHooks } from "./api.js";

function jsonRes(status, body) {
  return {
    status,
    ok: status >= 200 && status < 300,
    statusText: `status-${status}`,
    json: async () => body,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  setApiHooks({});
});

describe("rawReq (no 401 dialog)", () => {
  it("returns the raw response including 401 (caller decides)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonRes(401, { detail: "nope" })),
    );
    setApiHooks({
      onUnauthorized: async () => {
        throw new Error("dialog must not pop");
      },
    });
    const res = await rawReq("/api/auth/me");
    expect(res.status).toBe(401);
  });
  it("sends credentials:include with a timeout signal", async () => {
    const seen = {};
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url, opts) => {
        Object.assign(seen, opts);
        return jsonRes(200, { ok: true });
      }),
    );
    await rawReq("/api/auth/me");
    expect(seen.credentials).toBe("include");
    expect(Boolean(seen.signal)).toBe(true);
  });
  it("throws a friendly error on network failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("down");
      }),
    );
    await expect(rawReq("/api/auth/me")).rejects.toThrow(/Cannot reach/);
  });
});

describe("req still owns the 401 dialog flow", () => {
  it("retries once after the hook succeeds", async () => {
    let calls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        calls += 1;
        return calls === 1 ? jsonRes(401, {}) : jsonRes(200, { ok: true });
      }),
    );
    setApiHooks({ onUnauthorized: async () => true, onSessionRefreshed: async () => {} });
    const out = await req("/api/chats");
    expect(out).toEqual({ ok: true });
    expect(calls).toBe(2);
  });
});
