import { expect, test } from "playwright/test";

declare global {
  interface Window {
    __QBANK_STUDIO_FIXTURE__: {
      simulateExit(reason?: string): void;
      requestLog: string[];
    };
  }
}

test.beforeEach(async ({ page }) => {
  await page.goto("/?fixture=1");
  await expect(page.getByRole("option", { name: /Round-trip/ })).toBeVisible();
});

test("saved view restores complete visible filters and remains editable", async ({ page }) => {
  await page.locator("#saved-view-select").selectOption("光学复核");
  await expect(page.locator("#subject-filter")).toHaveValue("physics");
  await expect(page.locator("#status-filter")).toHaveValue("reviewed");
  await expect(page.locator("#result-count")).toContainText("1 题");
  await expect(page.locator("#filter-chips")).toContainText("+ optics");

  await page.locator(".filter-chip", { hasText: "+ optics" }).click();
  await expect(page.locator("#saved-view-select option:checked")).toContainText("已修改");
  await expect(page.locator("#result-count")).toContainText("1 题");
});

test("clear filters returns once to all questions and keeps all entry visible", async ({ page }) => {
  await page.locator("#saved-view-select").selectOption("光学复核");
  await page.locator("#advanced-filters").evaluate((element: HTMLDetailsElement) => {
    element.open = true;
  });
  await page.locator("#clear-filters").click();
  await expect(page.locator("#saved-view-select")).toHaveValue("all");
  await expect(page.locator("#result-count")).toContainText("2 题");
  await expect(page.locator("#filter-chips")).toBeEmpty();
  await expect(page.locator("#saved-view-select option").first()).toHaveText("全部题目");
});

test("tag tri-state is accessible and zero-count registered tag remains visible", async ({ page }) => {
  await page.locator("#advanced-filters").evaluate((element: HTMLDetailsElement) => {
    element.open = true;
  });
  const tag = page.locator(".tag-filter", { hasText: "零计数标签" });
  await expect(tag).toBeVisible();
  await expect(tag).toHaveAttribute("aria-label", /未选择/);
  await tag.click();
  await expect(tag).toHaveAttribute("aria-label", /包含/);
  await expect(page.locator("#result-count")).toContainText("0 题");
  await tag.click();
  await expect(tag).toHaveAttribute("aria-label", /排除/);
});

test("tag merge input uses protocol-backed autocomplete", async ({ page }) => {
  await page.locator("#advanced-filters").evaluate((element: HTMLDetailsElement) => {
    element.open = true;
  });
  await page.getByRole("button", { name: "管理标签" }).click();
  await page.getByRole("button", { name: "合并" }).first().click();
  const input = page.locator("#text-action-primary");
  await input.fill("round");
  await expect(page.locator("#text-action-tag-suggestions option")).not.toHaveCount(0);
  await expect.poll(() => page.evaluate(
    () => window.__QBANK_STUDIO_FIXTURE__.requestLog.includes("taxonomy.suggest"),
  )).toBe(true);
  await page.locator("#text-action-dialog").getByRole("button", { name: "取消" }).click();
});

test("batch bar appears only for explicit selection and uses selected IDs", async ({ page }) => {
  await expect(page.locator("#batch-bar")).toBeHidden();
  await page.getByRole("checkbox", { name: /选择 Round-trip/ }).check();
  await expect(page.locator("#batch-bar")).toBeVisible();
  await expect(page.locator("#batch-summary")).toHaveText("已选择 1 道题");
  await page.locator("#batch-status").click();
  await page.locator("#text-action-primary").fill("reviewed");
  await page.locator("#text-action-dialog button[value=confirm]").click();
  await expect.poll(() => page.evaluate(() =>
    window.__QBANK_STUDIO_FIXTURE__.requestLog.includes("question.bulkUpdate"),
  )).toBe(true);
  await page.locator("#batch-clear").click();
  await expect(page.locator("#batch-bar")).toBeHidden();
});

test("overview cells create real filters", async ({ page }) => {
  await page.locator("#advanced-filters").evaluate((element: HTMLDetailsElement) => {
    element.open = true;
  });
  await page.locator("#tag-overview").click();
  await expect(page.locator("#tag-overview-dialog")).toBeVisible();
  await page.locator("#tag-overview-content button", { hasText: "光学" }).first().click();
  await expect(page.locator("#filter-chips")).toContainText("+ optics");
  await expect(page.locator("#result-count")).toContainText("1 题");
});
