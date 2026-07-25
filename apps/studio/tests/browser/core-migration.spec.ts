import { expect, test } from "playwright/test";

declare global {
  interface Window {
    __QBANK_STUDIO_FIXTURE__: { simulateExit(reason?: string): void; requestLog: string[] };
  }
}

test.beforeEach(async ({ page }) => {
  await page.goto("/?fixture=1");
  await page.getByRole("option", { name: /Round-trip/ }).click();
  await expect(page.locator("#metadata-form input[name=title]")).toHaveValue("Round-trip 合成样例");
});

test("structured tags and provenance are saved through the protocol", async ({ page }) => {
  await page.locator('#metadata-form input[name="topics"]').fill("roundtrip, security");
  await page.locator('#metadata-form input[name="sourceType"]').fill("book");
  await page.locator('#metadata-form input[name="sourceReference"]').fill("Synthetic reference, p. 12");
  await page.getByRole("button", { name: "应用属性" }).click();
  await expect.poll(() => page.evaluate(() =>
    window.__QBANK_STUDIO_FIXTURE__.requestLog.includes("question.update"),
  )).toBe(true);
  await expect(page.locator("#toast-region")).toContainText("题目属性已保存");
});

test("explicit selection opens a paper, adjusts score and saves", async ({ page }) => {
  await page.getByRole("checkbox", { name: /选择 Round-trip/ }).check();
  await page.getByRole("button", { name: "试卷", exact: true }).click();
  const dialog = page.locator("#paper-dialog");
  await expect(dialog).toBeVisible();
  await dialog.locator("#paper-select").selectOption("papers/generated/synthetic-paper.yaml");
  await expect(dialog.locator(".paper-question-row")).toContainText("TEST-ROUNDTRIP-0001");
  await dialog.locator('.paper-question-row input[type="number"]').fill("8");
  await dialog.getByRole("button", { name: "保存顺序与分值" }).click();
  await expect.poll(() => page.evaluate(() =>
    window.__QBANK_STUDIO_FIXTURE__.requestLog.includes("paper.save"),
  )).toBe(true);
});

test("basic status and type filters are visible and keyboard reachable", async ({ page }) => {
  await page.locator("#advanced-filters").evaluate((element: HTMLDetailsElement) => {
    element.open = true;
  });
  await expect(page.locator("#status-filter")).toHaveAccessibleName("状态");
  await expect(page.locator("#type-filter")).toHaveAccessibleName("题型");
  await page.locator("#status-filter").selectOption("draft");
  await expect(page.locator("#result-count")).toHaveText("1 题");
});
