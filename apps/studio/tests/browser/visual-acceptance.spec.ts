import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "playwright/test";

const screenshots = resolve("build/studio-prototype/screenshots");

test("capture deterministic light, dark, asset and formula states", async ({ page }) => {
  mkdirSync(screenshots, { recursive: true });
  await page.route("**/*", async (route) => {
    const host = new URL(route.request().url()).hostname;
    if (host === "127.0.0.1" || host === "localhost") await route.continue();
    else await route.abort("blockedbyclient");
  });
  await page.goto("/?fixture=1");
  await page.getByRole("option", { name: /Round-trip/ }).click();
  await expect(page.frameLocator("#secure-preview").locator("mjx-container").first()).toBeVisible();
  await expect(page.locator(".asset-card").first()).toBeVisible();
  await expect(page.locator("#preview-progress")).toBeHidden();

  await page.screenshot({ path: resolve(screenshots, "studio-light.png"), fullPage: true });
  await page.locator("#advanced-filters").evaluate((element: HTMLDetailsElement) => {
    element.open = true;
  });
  await page.locator("#saved-view-select").selectOption("光学复核");
  await expect(page.locator("#filter-chips")).toContainText("+ optics");
  await page.screenshot({
    path: resolve(screenshots, "studio-advanced-management.png"),
    fullPage: true,
  });
  await page.locator("#clear-filters").click();
  await page.locator("#advanced-filters").evaluate((element: HTMLDetailsElement) => {
    element.open = false;
  });
  await page.locator("#theme-toggle").click();
  await expect(page.locator(".app-shell")).toHaveAttribute("data-theme", "dark");
  await expect(page.locator("#preview-progress")).toBeHidden();
  await page.screenshot({ path: resolve(screenshots, "studio-dark.png"), fullPage: true });

  await page.locator(".asset-menu-button").first().click();
  await expect(page.locator(".asset-menu").first()).toBeVisible();
  await expect(page.locator("#preview-progress")).toBeHidden();
  await page.screenshot({ path: resolve(screenshots, "studio-asset-menu.png"), fullPage: true });

  await page.locator("#document-title").click();
  await expect(page.locator(".asset-menu").first()).toBeHidden();
  await page.frameLocator("#secure-preview").locator('[data-math="a+b"]').first().click({ button: "right" });
  await expect(page.locator(".formula-menu")).toBeVisible();
  await page.screenshot({ path: resolve(screenshots, "studio-formula-menu.png"), fullPage: true });
});

test("125 percent scaling keeps the editor workspace inside the window", async ({ browser }) => {
  mkdirSync(screenshots, { recursive: true });
  const context = await browser.newContext({
    viewport: { width: 1184, height: 720 },
    deviceScaleFactor: 1.25,
    colorScheme: "light",
  });
  const page = await context.newPage();
  await page.route("**/*", async (route) => {
    const host = new URL(route.request().url()).hostname;
    if (host === "127.0.0.1" || host === "localhost") await route.continue();
    else await route.abort("blockedbyclient");
  });
  await page.goto("/?fixture=1");
  await page.getByRole("option", { name: /Round-trip/ }).click();
  await expect(page.frameLocator("#secure-preview").locator("mjx-container").first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  await expect(page.locator("#metadata-form")).toBeVisible();
  await page.screenshot({ path: resolve(screenshots, "studio-light-125.png"), fullPage: true });
  await context.close();
});
