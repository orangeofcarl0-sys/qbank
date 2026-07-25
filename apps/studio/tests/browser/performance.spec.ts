import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, type Page } from "playwright/test";

const output = resolve("build/productization/editor-performance.json");

async function waitForEditor(page: Page): Promise<void> {
  await expect
    .poll(() => page.evaluate(() => {
      const candidate = window as Window & {
        __QBANK_STUDIO_TEST__: { testSnapshot(): { editor: string | null } };
      };
      return candidate.__QBANK_STUDIO_TEST__.testSnapshot().editor !== null;
    }))
    .toBe(true);
}

test("formula rendering and continuous editing remain bounded", async ({ page, context, browserName }) => {
  test.setTimeout(180_000);
  await page.route("**/*", async (route) => {
    const host = new URL(route.request().url()).hostname;
    if (host === "127.0.0.1" || host === "localhost") await route.continue();
    else await route.abort("blockedbyclient");
  });
  await page.goto("/?fixture=1");
  await page.getByRole("option", { name: /Round-trip/ }).click();
  await waitForEditor(page);
  const originalEditor = await page.evaluate(() => {
    const candidate = window as Window & {
      __QBANK_STUDIO_TEST__: { testSnapshot(): { editor: string | null } };
    };
    return candidate.__QBANK_STUDIO_TEST__.testSnapshot().editor ?? "";
  });

  const formulaCount = 80;
  await page.evaluate((count) => {
    const candidate = window as Window & {
      __QBANK_STUDIO_TEST__: {
        testSnapshot(): { editor: string | null };
        testSetEditorValue(value: string): void;
      };
      __QBANK_PERFORMANCE_STARTED__?: number;
    };
    const base = candidate.__QBANK_STUDIO_TEST__.testSnapshot().editor ?? "";
    const formulas = Array.from(
      { length: count },
      (_, index) => `$$\\sum_{k=0}^{${index + 4}} \\frac{x_k^2}{${index + 1}+k}=y_${index}$$`,
    ).join("\n\n");
    candidate.__QBANK_PERFORMANCE_STARTED__ = performance.now();
    candidate.__QBANK_STUDIO_TEST__.testSetEditorValue(`${base}\n\n## Dense formula benchmark\n\n${formulas}`);
  }, formulaCount);
  await expect
    .poll(() => page.frameLocator("#secure-preview").locator("mjx-container").count(), { timeout: 30_000 })
    .toBeGreaterThanOrEqual(formulaCount);
  const formulaRenderMs = await page.evaluate(
    () => {
      const candidate = window as Window & { __QBANK_PERFORMANCE_STARTED__?: number };
      return performance.now() - (candidate.__QBANK_PERFORMANCE_STARTED__ ?? performance.now());
    },
  );

  const session = await context.newCDPSession(page);
  await page.evaluate((source) => {
    const candidate = window as Window & {
      __QBANK_STUDIO_TEST__: { testSetEditorValue(value: string): void };
    };
    candidate.__QBANK_STUDIO_TEST__.testSetEditorValue(source);
  }, originalEditor);
  await page.waitForTimeout(1_000);
  await session.send("Performance.enable");
  await session.send("HeapProfiler.collectGarbage");
  const beforeMetrics = await session.send("Performance.getMetrics");
  const metric = (metrics: { name: string; value: number }[], name: string): number =>
    metrics.find((item) => item.name === name)?.value ?? 0;
  const heapBefore = metric(beforeMetrics.metrics, "JSHeapUsedSize");
  const edits = 500;
  const marker = ` continuous-edit-${"x".repeat(edits)}`;
  const editor = page.locator(".vditor-sv").first();
  await editor.focus();
  await page.keyboard.press("Control+End");
  const inputStarted = Date.now();
  await page.keyboard.type(marker);
  const inputMs = Date.now() - inputStarted;
  await expect
    .poll(() => page.evaluate((characters) => {
      const candidate = window as Window & {
        __QBANK_STUDIO_TEST__: { testSnapshot(): { buffer: string } };
      };
      const buffer = candidate.__QBANK_STUDIO_TEST__.testSnapshot().buffer;
      const markerIndex = buffer.lastIndexOf("continuous-edit-");
      if (markerIndex < 0) return false;
      const normalized = buffer.slice(markerIndex).replaceAll(/\s/g, "");
      return normalized === `continuous-edit-${"x".repeat(characters)}`;
    }, edits), { timeout: 30_000 })
    .toBe(true);
  await expect(page.frameLocator("#secure-preview").locator("body")).toContainText(
    `continuous-edit-${"x".repeat(24)}`,
    { timeout: 30_000 },
  );
  await page.waitForTimeout(1_000);
  await session.send("HeapProfiler.collectGarbage");
  const afterMetrics = await session.send("Performance.getMetrics");
  const heapAfter = metric(afterMetrics.metrics, "JSHeapUsedSize");
  const heapGrowth = heapAfter - heapBefore;
  const domNodes = await page.locator("*").count();
  await session.detach();

  const payload = {
    method: "Playwright Chromium fixture mode with all non-local requests blocked",
    browser: browserName,
    denseFormula: {
      formulas: formulaCount,
      renderMs: Math.round(formulaRenderMs * 1000) / 1000,
    },
    continuousEditing: {
      inputEvents: marker.length,
      payloadCharacters: edits,
      inputMs,
      heapBeforeBytes: heapBefore,
      heapAfterBytes: heapAfter,
      heapGrowthBytes: heapGrowth,
      domNodes,
      settledPreview: true,
    },
  };
  mkdirSync(resolve("build/productization"), { recursive: true });
  writeFileSync(output, `${JSON.stringify(payload, null, 2)}\n`, "utf8");

  expect(formulaRenderMs).toBeLessThan(30_000);
  expect(heapGrowth).toBeLessThan(64 * 1024 * 1024);
});
