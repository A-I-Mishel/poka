import { describe, expect, it } from "vitest";
import { chatHash, parseHash } from "./route.js";

var ID = "0123456789abcdef";

describe("route", () => {
  it("builds chat hashes for 16-hex ids, home otherwise", () => {
    expect(chatHash(ID)).toBe("#/chats/" + ID);
    expect(chatHash("")).toBe("#/");
    expect(chatHash("../evil")).toBe("#/");
    expect(chatHash(null)).toBe("#/");
  });
  it("parses chat hashes, rejects garbage without firing the API", () => {
    expect(parseHash("#/chats/" + ID)).toEqual({ kind: "chat", id: ID });
    expect(parseHash("#/")).toEqual({ kind: "home", id: "" });
    expect(parseHash("")).toEqual({ kind: "home", id: "" });
    expect(parseHash("#/chats/../evil")).toEqual({ kind: "home", id: "" });
    expect(parseHash("#/chats/short")).toEqual({ kind: "home", id: "" });
    expect(parseHash("#/projects/abc")).toEqual({ kind: "home", id: "" });
  });
});
