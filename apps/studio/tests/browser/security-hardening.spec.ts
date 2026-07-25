import { expect, test } from "playwright/test";

declare global {
  interface Window {
    __QBANK_STUDIO_TEST__: {
      testSnapshot(): { buffer: string; editor: string | null; dirty: boolean };
      testSetEditorValue(value: string): void;
      testSanitizeSvgDataUrl(value: string): string | null;
    };
  }
}

test.beforeEach(async ({ page }) => {
  await page.route("**/*", async (route) => {
    const host = new URL(route.request().url()).hostname;
    if (host === "127.0.0.1" || host === "localhost") await route.continue();
    else await route.abort("blockedbyclient");
  });
  await page.goto("/?fixture=1");
  await page.getByRole("option", { name: /Round-trip/ }).click();
  await expect(page.frameLocator("#secure-preview").locator("body")).toContainText("自定义宏", {
    timeout: 20_000,
  });
});

test("preview uses a scriptless isolated frame without Tauri globals", async ({ page }) => {
  const frame = page.locator("#secure-preview");
  await expect(frame).toHaveAttribute("sandbox", "allow-same-origin");
  const preview = frame.contentFrame();
  await expect(preview.locator('meta[http-equiv="Content-Security-Policy"]')).toHaveAttribute(
    "content",
    /script-src 'none'/,
  );
  expect(await preview.locator("body").evaluate(() => {
    const candidate = window as Window & { __TAURI_INTERNALS__?: unknown };
    return candidate.__TAURI_INTERNALS__;
  })).toBeUndefined();
});

test("script, event handlers, active content, links and remote resources are removed", async ({ page }) => {
  await page.evaluate(() => {
    const current = window.__QBANK_STUDIO_TEST__.testSnapshot().editor ?? "";
    window.__QBANK_STUDIO_TEST__.testSetEditorValue(`${current}\n
<script>window.previewPwned=true</script>
<img src="https://attacker.invalid/x.png" onerror="window.previewPwned=true">
![remote](https://attacker.invalid/markdown.png)
<a href="javascript:window.previewPwned=true">bad link</a>
<iframe src="https://attacker.invalid/"></iframe>
<object data="data:text/html,bad"></object>
<svg onload="window.previewPwned=true"><foreignObject>bad</foreignObject><use href="https://attacker.invalid/x.svg#x"/></svg>`);
  });
  const preview = page.frameLocator("#secure-preview");
  await expect(preview.locator("body")).toContainText("已阻止不安全或远程图像");
  await expect(preview.locator("script,iframe,object,foreignObject,use")).toHaveCount(0);
  await expect(preview.locator('[href^="javascript:"], [src^="http"]')).toHaveCount(0);
  expect(await preview.locator("*").evaluateAll((nodes) => nodes.some((node) =>
    [...node.attributes].some((attribute) => attribute.name.toLowerCase().startsWith("on")),
  ))).toBe(false);
});

test("malicious SVG data URLs are reduced to inert SVG", async ({ page }) => {
  const result = await page.evaluate(() => {
    const raw = '<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><script>alert(1)</script><foreignObject><iframe src="https://x.invalid"></iframe></foreignObject><use href="javascript:alert(1)"/><rect width="10" height="10"/></svg>';
    return window.__QBANK_STUDIO_TEST__.testSanitizeSvgDataUrl(
      `data:image/svg+xml;base64,${btoa(raw)}`,
    );
  });
  expect(result).not.toBeNull();
  const decoded = Buffer.from(String(result).split(",")[1] ?? "", "base64").toString("utf8");
  expect(decoded).toContain("<rect");
  expect(decoded).not.toMatch(/script|foreignObject|iframe|onload|javascript:|<use/i);
});

test("oversized formulas are omitted only in the derived preview", async ({ page }) => {
  const oversized = "x".repeat(17 * 1024);
  await page.evaluate((formula) => {
    const current = window.__QBANK_STUDIO_TEST__.testSnapshot().editor ?? "";
    window.__QBANK_STUDIO_TEST__.testSetEditorValue(`${current}\n\n$$${formula}$$`);
  }, oversized);
  const preview = page.frameLocator("#secure-preview");
  await expect(preview.locator("body")).toContainText("公式超过 16 KiB 安全上限");
  expect(await page.evaluate(() => window.__QBANK_STUDIO_TEST__.testSnapshot().buffer)).toContain(oversized);
});
