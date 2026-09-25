import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "playwright/test";

// Editors normalize newlines to LF on load; compare against LF so the baseline
// also passes on Windows checkouts where Git may produce CRLF working files.
const source = readFileSync(resolve("fixtures/roundtrip/all-features.md"), "utf8").replace(/\r\n/g, "\n");

test("ByteMD minimal baseline retains the same source bytes on load", async ({ page }) => {
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.hostname === "127.0.0.1" || url.hostname === "localhost") await route.continue();
    else await route.abort("blockedbyclient");
  });
  await page.goto("/bytemd-comparison.html");
  await expect.poll(() => page.evaluate(() => window.__BYTEMD_COMPARISON__?.getValue() ?? null)).toBe(source);
});
