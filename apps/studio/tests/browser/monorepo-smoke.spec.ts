import { expect, test } from "playwright/test";

declare global {
  interface Window {
    __QBANK_STUDIO_TEST__: {
      testSnapshot(): { buffer: string; editor: string | null; dirty: boolean };
      testSetEditorValue(value: string): void;
      testSanitizeSvgDataUrl(value: string): string | null;
    };
    __QBANK_STUDIO_FIXTURE__: {
      simulateExit(reason?: string): void;
      requestLog: string[];
    };
  }
}

test("open, edit, save, render formula and invoke an image action", async ({ page }) => {
  await page.goto("/?fixture=1");
  await page.getByRole("option", { name: /Round-trip/ }).click();
  await expect
    .poll(() => page.evaluate(() => window.__QBANK_STUDIO_TEST__.testSnapshot().editor))
    .not.toBeNull();

  const editor = await page.evaluate(
    () => window.__QBANK_STUDIO_TEST__.testSnapshot().editor as string,
  );
  await page.evaluate(
    (value) =>
      window.__QBANK_STUDIO_TEST__.testSetEditorValue(
        `${value}\n\n结构归并 smoke：\\(x^2+y^2\\)。`,
      ),
    editor,
  );
  await expect
    .poll(() => page.evaluate(() => window.__QBANK_STUDIO_TEST__.testSnapshot().dirty))
    .toBe(true);
  await page.locator("#save").click();
  await expect
    .poll(() =>
      page.evaluate(() =>
        window.__QBANK_STUDIO_FIXTURE__.requestLog.includes("question.save"),
      ),
    )
    .toBe(true);
  await expect
    .poll(() => page.evaluate(() => window.__QBANK_STUDIO_TEST__.testSnapshot().dirty))
    .toBe(false);
  await expect(page.frameLocator("#secure-preview").locator("mjx-container").last()).toBeVisible();

  await page.locator(".asset-menu-button").first().click();
  const imageAction = page.locator(".asset-menu button:not([disabled])").first();
  await expect(imageAction).toBeVisible();
  await imageAction.click();
  await expect
    .poll(() =>
      page.evaluate(() =>
        window.__QBANK_STUDIO_FIXTURE__.requestLog.some((method) =>
          method.startsWith("asset."),
        ),
      ),
    )
    .toBe(true);
});
