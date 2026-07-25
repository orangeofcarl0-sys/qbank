import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  assetReferences,
  bodyForPreview,
  insertAssetReference,
  nextAssetId,
  rewriteAssetReferences,
  rewriteBackslashMathHtml,
} from "../src/markdown";

const fixture = readFileSync(resolve("fixtures/roundtrip/all-features.md"), "utf8");

describe("Markdown source boundary", () => {
  it("extracts preview body without mutating the authority buffer", () => {
    const body = bodyForPreview(fixture);
    expect(body).not.toMatch(/^---/);
    expect(body).toContain("<!-- comment must survive -->");
    expect(fixture).toContain("schema_version: '1.0'");
    expect(fixture).toContain("   - 缩进子项");
    expect(fixture).toContain("\\(a+b\\)");
    expect(fixture).toContain("qbank-asset:diagram-1");
  });

  it("rewrites logical assets only in a derived preview copy", () => {
    const preview = rewriteAssetReferences(fixture, new Map([["diagram-1", "data:image/svg+xml;base64,abc"]]));
    expect(preview).toContain("data:image/svg+xml;base64,abc");
    expect(fixture).toContain("qbank-asset:diagram-1");
    expect(assetReferences(fixture)).toEqual(["diagram-1"]);
  });

  it("inserts a stable reference without disturbing fixed sections", () => {
    const updated = insertAssetReference(fixture, "figure-2");
    expect(updated).toContain("![图形资产](qbank-asset:figure-2)");
    expect(updated.match(/^## /gm)).toHaveLength(6);
    expect(updated).toContain("<!-- comment must survive -->");
  });

  it("allocates deterministic asset IDs", () => {
    expect(nextAssetId(["figure-1", "figure-3"])).toBe("figure-2");
  });

  it("adapts backslash math delimiters without touching code", () => {
    const html = "<p>A (a+b) B</p><p>[<br>x^2<br>]</p><pre><code>\\(raw\\)</code></pre>";
    const source = "A \\(a+b\\) B\n\n\\[\nx^2\n\\]\n\n```\n\\(raw\\)\n```";
    const rewritten = rewriteBackslashMathHtml(html, source);
    expect(rewritten).toContain('<span class="language-math qbank-inline-math">a+b</span>');
    expect(rewritten).toContain('<div class="language-math qbank-display-math">x^2</div>');
    expect(rewritten).toContain("<pre><code>\\(raw\\)</code></pre>");
  });
});
