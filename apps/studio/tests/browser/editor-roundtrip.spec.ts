import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, type FrameLocator, type Page } from "playwright/test";

interface Harness {
  testSnapshot(): { buffer: string; editor: string | null; dirty: boolean };
  testSetEditorValue(value: string): void;
  testSanitizeSvgDataUrl(value: string): string | null;
}

interface FixtureHarness {
  simulateExit(reason?: string): void;
  requestLog: string[];
}

declare global {
  interface Window {
    __QBANK_STUDIO_TEST__: Harness;
    __QBANK_STUDIO_FIXTURE__: FixtureHarness;
  }
}

const source = readFileSync(resolve("fixtures/roundtrip/all-features.md"), "utf8");

async function waitForEditor(page: Page): Promise<void> {
  await expect.poll(() => page.evaluate(() => window.__QBANK_STUDIO_TEST__.testSnapshot().editor !== null)).toBe(true);
}

function preview(page: Page): FrameLocator {
  return page.frameLocator("#secure-preview");
}

test.beforeEach(async ({ page }) => {
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.hostname === "127.0.0.1" || url.hostname === "localhost") await route.continue();
    else await route.abort("blockedbyclient");
  });
  await page.goto("/?fixture=1");
  await page.getByRole("option", { name: /Round-trip/ }).click();
  await expect(page.locator("#document-title")).toContainText("Round-trip 合成样例");
  await waitForEditor(page);
});

test("Vditor source projection preserves the authoritative Markdown byte sequence", async ({ page }) => {
  await page.getByRole("button", { name: /源码/ }).click();
  await waitForEditor(page);
  const snapshot = await page.evaluate(() => window.__QBANK_STUDIO_TEST__.testSnapshot());
  expect(snapshot.buffer).toBe(source);
  expect(snapshot.editor).not.toBe(source);
  expect(snapshot.dirty).toBe(false);
});

test("mode changes retain front matter, delimiters, comments and indentation", async ({ page }) => {
  await page.getByRole("button", { name: /即时/ }).click();
  await waitForEditor(page);
  await page.getByRole("button", { name: /分栏/ }).click();
  await waitForEditor(page);
  const snapshot = await page.evaluate(() => window.__QBANK_STUDIO_TEST__.testSnapshot());
  expect(snapshot.buffer).toContain("schema_version: '1.0'");
  expect(snapshot.buffer).toContain("<!-- comment must survive -->");
  expect(snapshot.buffer).toContain("   - 缩进子项");
  expect(snapshot.buffer).toContain("\\(a+b\\)");
  expect(snapshot.buffer).toContain("qbank-asset:diagram-1");
});

test("offline MathJax renders valid formulas and isolates the invalid formula", async ({ page }) => {
  await expect(preview(page).locator('[data-math="a+b"]')).toBeVisible();
  await expect.poll(() => preview(page).locator("[data-math]").evaluateAll(
    (nodes) => nodes.some((node) => node.getAttribute("data-math") === "\\qop(x)"),
  )).toBe(true);
  await expect(preview(page).locator(".qbank-display-math[data-math]").first()).toBeVisible();
  await expect.poll(() => preview(page).locator("[data-math]").evaluateAll(
    (nodes) => nodes.some((node) => node.getAttribute("data-math")?.includes("\\begin{matrix}")),
  )).toBe(true);
  await expect.poll(() => preview(page).locator("[data-math]").evaluateAll(
    (nodes) => nodes.some((node) => node.getAttribute("data-math")?.includes("\\begin{split}")),
  )).toBe(true);
  await expect(preview(page).locator("mjx-container").first()).toBeVisible();
  expect(await preview(page).locator("mjx-container").count()).toBeGreaterThan(1);
  await expect(preview(page).locator("body")).toContainText("其后文本必须继续显示");
  const localError = preview(page).locator(".vditor-reset--error[data-math]").first();
  await expect(localError).toBeVisible();
  await expect(localError).toContainText("Missing close brace");
});

test("dirty clears when content returns to the saved snapshot", async ({ page }) => {
  const projection = await page.evaluate(() => window.__QBANK_STUDIO_TEST__.testSnapshot().editor as string);
  await page.evaluate((value) => window.__QBANK_STUDIO_TEST__.testSetEditorValue(`${value}\nchanged`), projection);
  await expect.poll(() => page.evaluate(() => window.__QBANK_STUDIO_TEST__.testSnapshot().dirty)).toBe(true);
  await page.evaluate((value) => window.__QBANK_STUDIO_TEST__.testSetEditorValue(value), projection);
  await expect.poll(() => page.evaluate(() => window.__QBANK_STUDIO_TEST__.testSnapshot().dirty)).toBe(false);
  expect(await page.evaluate(() => window.__QBANK_STUDIO_TEST__.testSnapshot().buffer)).toBe(source);
});

test("logical asset preview is derived without replacing source reference", async ({ page }) => {
  await expect(preview(page).locator("img").first()).toBeVisible();
  const snapshot = await page.evaluate(() => window.__QBANK_STUDIO_TEST__.testSnapshot());
  expect(snapshot.buffer).toContain("qbank-asset:diagram-1");
});

test("contained local asset references receive safe preview bindings", async ({ page }) => {
  const source = await page.evaluate(
    () => window.__QBANK_STUDIO_TEST__.testSnapshot().editor ?? "",
  );
  await page.evaluate(
    (value) => window.__QBANK_STUDIO_TEST__.testSetEditorValue(
      `${value}\n\n![local fixture](assets/images/local.svg)`,
    ),
    source,
  );
  await expect(preview(page).locator('img[alt="local fixture"]')).toBeVisible();
  await expect(page.locator(".asset-local")).toContainText("本地资源");
  expect(await page.evaluate(() => window.__QBANK_STUDIO_TEST__.testSnapshot().buffer))
    .toContain("assets/images/local.svg");
});

test("formula context menu copies the original TeX", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"], {
    origin: "http://127.0.0.1:1420",
  });
  const formula = preview(page).locator('[data-math="a+b"]').first();
  await formula.click({ button: "right" });
  await page.getByRole("button", { name: "复制原始 TeX" }).click();
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe("a+b");
});

test("a stale slow question load cannot overwrite a newer selection", async ({ page }) => {
  await page.getByRole("option", { name: /Slow generation sample/ }).click();
  await page.getByRole("option", { name: /Round-trip/ }).click();
  await expect(page.locator("#document-title")).toContainText("Round-trip");
  await page.waitForTimeout(260);
  const snapshot = await page.evaluate(() => window.__QBANK_STUDIO_TEST__.testSnapshot());
  expect(snapshot.buffer).toContain("TEST-ROUNDTRIP-0001");
  expect(snapshot.buffer).not.toContain("TEST-SLOW-0002");
});

test("paste and drop create logical assets without rewriting prior source", async ({ page }) => {
  await page.locator("#editor-frame").evaluate((element) => {
    const transfer = new DataTransfer();
    transfer.items.add(new File([new Uint8Array([137, 80, 78, 71])], "paste.png", { type: "image/png" }));
    element.dispatchEvent(new ClipboardEvent("paste", { bubbles: true, cancelable: true, clipboardData: transfer }));
  });
  await expect.poll(() => page.evaluate(
    () => window.__QBANK_STUDIO_TEST__.testSnapshot().buffer.includes("qbank-asset:figure-1"),
  )).toBe(true);
  await page.locator("#editor-frame").evaluate((element) => {
    const transfer = new DataTransfer();
    transfer.items.add(new File([new Uint8Array([137, 80, 78, 71, 2])], "drop.png", { type: "image/png" }));
    element.dispatchEvent(new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer: transfer }));
  });
  await expect.poll(() => page.evaluate(
    () => window.__QBANK_STUDIO_TEST__.testSnapshot().buffer.includes("qbank-asset:figure-2"),
  )).toBe(true);
  expect(await page.evaluate(() => window.__QBANK_STUDIO_FIXTURE__.requestLog.filter(
    (method) => method === "asset.create",
  ).length)).toBe(2);
});

test("sidecar exit disables mutations and preserves unsaved text", async ({ page }) => {
  const projection = await page.evaluate(() => window.__QBANK_STUDIO_TEST__.testSnapshot().editor as string);
  await page.evaluate((value) => window.__QBANK_STUDIO_TEST__.testSetEditorValue(`${value}\nunsaved`), projection);
  await expect.poll(() => page.evaluate(() => window.__QBANK_STUDIO_TEST__.testSnapshot().dirty)).toBe(true);
  await page.evaluate(() => window.__QBANK_STUDIO_FIXTURE__.simulateExit("synthetic crash"));
  await expect(page.locator("#connection-status")).toHaveText("sidecar 已停止");
  await expect(page.locator("#toast-region")).toContainText("未保存内容仍保留");
  await expect(page.locator("#save")).toBeDisabled();
  expect(await page.evaluate(() => window.__QBANK_STUDIO_TEST__.testSnapshot().buffer)).toContain("unsaved");
});
