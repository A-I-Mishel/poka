import { describe, expect, it } from "vitest";

import { enc, esc, escapeAttr, isSafeHttpUrl } from "./ui.js";

describe("enc", () => {
  it("leaves well-formed hex IDs untouched", () => {
    expect(enc("abc123def4567890")).toBe("abc123def4567890");
  });
  it("neutralizes traversal and quote-breaking payloads", () => {
    expect(enc("../../etc")).toBe("..%2F..%2Fetc");
    expect(enc(`a"b`)).toBe("a%22b");
  });
  it("coerces nullish to empty string", () => {
    expect(enc(null)).toBe("");
    expect(enc(undefined)).toBe("");
  });
});

describe("isSafeHttpUrl", () => {
  it("allows http and https", () => {
    expect(isSafeHttpUrl("https://example.com/x")).toBe(true);
    expect(isSafeHttpUrl("http://example.com")).toBe(true);
  });
  it("blocks javascript:, data: and relative URLs", () => {
    // Built via concatenation so the no-script-url rule stays honest
    // (no literal script URL anywhere in src, even in tests).
    expect(isSafeHttpUrl("javascript" + ":alert(1)")).toBe(false);
    expect(isSafeHttpUrl("JaVaScRiPt" + ":alert(1)")).toBe(false);
    expect(isSafeHttpUrl("data:text/html,<h1>x</h1>")).toBe(false);
    expect(isSafeHttpUrl("/api/chats")).toBe(false);
    expect(isSafeHttpUrl("")).toBe(false);
    expect(isSafeHttpUrl(null)).toBe(false);
  });
});

describe("esc vs escapeAttr discipline", () => {
  it("esc() does not quote-escape (text nodes only)", () => {
    expect(esc(`a"b`)).toBe(`a"b`);
  });
  it("escapeAttr() quote-escapes (attribute values)", () => {
    expect(escapeAttr(`a"b`)).toBe("a&quot;b");
  });
});
