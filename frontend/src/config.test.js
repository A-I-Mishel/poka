import { describe, expect, it } from "vitest";

import {
  API_BASE,
  AUTH_SEEN_KEY,
  LEGACY_PREFS_KEY,
  LEGACY_TOKEN_KEY,
  MAX_MSG_CHARS,
  PREFS_KEY,
  TOKEN_KEY,
  VISITOR_KEY,
  apiUrl,
} from "./config.js";

describe("config", () => {
  it("exposes stable storage keys", () => {
    expect(TOKEN_KEY).toBe("pluto_token");
    expect(LEGACY_TOKEN_KEY).toBe("poka_token");
    expect(VISITOR_KEY).toBe("pluto_visitor");
    expect(PREFS_KEY).toBe("pluto.v1");
    expect(LEGACY_PREFS_KEY).toBe("poka.v1");
    expect(AUTH_SEEN_KEY).toBe("pluto_auth_seen");
  });
  it("caps messages at the backend limit", () => {
    expect(MAX_MSG_CHARS).toBe(20000);
  });
  it("builds same-origin URLs when no env is set", () => {
    expect(API_BASE).toBe("");
    expect(apiUrl("/api/health")).toBe("/api/health");
  });
});
