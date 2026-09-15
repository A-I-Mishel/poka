import { describe, expect, it } from "vitest";

import { artIcon, escHtml, ic, md, planet } from "./markdown.js";
import { esc } from "./ui.js";

describe("esc", () => {
  it("escapes angle brackets and amps", () => {
    expect(esc("<b>&</b>")).toBe("&lt;b&gt;&amp;&lt;/b&gt;");
  });
  it("coerces nullish to empty string", () => {
    expect(esc(null)).toBe("");
    expect(esc(undefined)).toBe("");
  });
});

describe("escHtml", () => {
  it("also escapes quotes", () => {
    expect(escHtml(`a"b'c`)).toBe("a&quot;b&#39;c");
  });
});

describe("md", () => {
  it("wraps plain text in a paragraph", () => {
    expect(md("hello")).toBe("<p>hello</p>");
  });
  it("never emits raw scripts (XSS-safe)", () => {
    const out = md('<script>alert(1)</script>');
    expect(out).not.toContain("<script>");
    expect(out).toContain("&lt;script&gt;");
  });
  it("renders headings", () => {
    expect(md("## Title")).toContain("<h2>Title</h2>");
  });
  it("renders bold and strikethrough", () => {
    expect(md("**hi**")).toContain("<b>hi</b>");
    expect(md("~~gone~~")).toContain("<s>gone</s>");
  });
  it("keeps fenced code verbatim with a language class", () => {
    const out = md("```js\nconst x = 1;\n```");
    expect(out).toContain("<pre><code");
    expect(out).toContain('class="lang-js"');
    expect(out).toContain("const x = 1;");
  });
  it("renders inline code", () => {
    expect(md("use `x()` here")).toContain("<code>x()</code>");
  });
  it("links http(s) with noopener", () => {
    const out = md("[docs](https://example.com)");
    expect(out).toContain('href="https://example.com"');
    expect(out).toContain('rel="noopener noreferrer"');
  });
  it("refuses javascript: URLs", () => {
    expect(md("[x](javascript:alert(1))")).not.toContain("<a");
  });
  it("renders lists", () => {
    const out = md("- a\n- b");
    expect(out).toContain("<ul>");
    expect(out).toContain("<li>a</li>");
  });
});

describe("icons", () => {
  it("sizes the planet mark", () => {
    expect(planet(13)).toContain('width="13"');
  });
  it("wraps card icons", () => {
    expect(ic("doc")).toContain("card-ic");
  });
  it("classifies attachments", () => {
    expect(artIcon("photo.png")).toBe("image");
    expect(artIcon("app.js")).toBe("code");
    expect(artIcon("data.csv")).toBe("chart");
    expect(artIcon("notes.txt")).toBe("doc");
  });
});
