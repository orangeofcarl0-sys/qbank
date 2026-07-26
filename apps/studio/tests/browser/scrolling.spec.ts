import { expect, test, type FrameLocator, type Page } from "playwright/test";

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

async function loadLongDocument(page: Page, preview: FrameLocator): Promise<void> {
  await page.evaluate(() => {
    const candidate = window as Window & {
      __QBANK_STUDIO_TEST__: {
        testSnapshot(): { editor: string | null };
        testSetEditorValue(value: string): void;
      };
    };
    const source = candidate.__QBANK_STUDIO_TEST__.testSnapshot().editor ?? "";
    const paragraphs = Array.from(
      { length: 80 },
      (_, index) => `Long synthetic paragraph ${index + 1}: wheel and scrollbar acceptance.`,
    ).join("\n\n");
    candidate.__QBANK_STUDIO_TEST__.testSetEditorValue(`${source}\n\n${paragraphs}`);
  });
  await expect(preview.locator("body")).toContainText("Long synthetic paragraph 80");
}

test("source and preview expose stable scrollbars and keep wheel input in the pointed pane", async ({
  page,
}) => {
  await page.goto("/?fixture=1");
  await page.getByRole("option", { name: /Round-trip/ }).click();
  await waitForEditor(page);
  const preview = page.frameLocator("#secure-preview");
  await loadLongDocument(page, preview);
  expect(
    await page.locator(".workspace").evaluate(
      (element) => element.scrollHeight === element.clientHeight,
    ),
  ).toBe(true);

  const source = page.locator(".vditor-sv").first();
  await expect
    .poll(() => source.evaluate((element) => element.scrollHeight > element.clientHeight))
    .toBe(true);
  const sourceStyle = await source.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      gutter: style.scrollbarGutter,
      overscroll: style.overscrollBehaviorY,
      width: style.scrollbarWidth,
    };
  });
  expect(sourceStyle).toEqual({
    gutter: "stable",
    overscroll: "contain",
    width: "thin",
  });

  await source.hover();
  await page.mouse.wheel(0, 640);
  await expect.poll(() => source.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
  const sourcePosition = await source.evaluate((element) => element.scrollTop);

  const previewStyle = await preview.locator("html").evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      gutter: style.scrollbarGutter,
      overscroll: style.overscrollBehaviorY,
      width: style.scrollbarWidth,
    };
  });
  expect(previewStyle).toEqual({
    gutter: "stable",
    overscroll: "contain",
    width: "thin",
  });
  await page.locator("#secure-preview").hover();
  await page.mouse.wheel(0, 640);
  await expect
    .poll(() => preview.locator("html").evaluate((element) => element.scrollTop))
    .toBeGreaterThan(0);
  expect(await source.evaluate((element) => element.scrollTop)).toBe(sourcePosition);
});

test("navigation and Inspector retain visible independent scroll regions at compact height", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1480, height: 460 });
  await page.goto("/?fixture=1");
  await page.getByRole("option", { name: /Round-trip/ }).click();
  await waitForEditor(page);
  await page.locator("#advanced-filters").evaluate((element: HTMLDetailsElement) => {
    element.open = true;
  });

  const filters = page.locator(".advanced-filters");
  const questions = page.locator(".question-list");
  await questions.evaluate((element) => {
    const rows = [...element.querySelectorAll(".question-row-shell")];
    for (let copy = 0; copy < 12; copy += 1) {
      for (const row of rows) element.append(row.cloneNode(true));
    }
  });
  const inspector = page.locator(".inspector");
  for (const region of [filters, questions, inspector]) {
    await expect
      .poll(() => region.evaluate((element) => element.scrollHeight > element.clientHeight))
      .toBe(true);
    expect(
      await region.evaluate((element) => {
        const style = getComputedStyle(element);
        return [style.scrollbarGutter, style.overscrollBehaviorY, style.scrollbarWidth];
      }),
    ).toEqual(["stable", "contain", "thin"]);
    await region.hover();
    await page.mouse.wheel(0, 520);
    await expect.poll(() => region.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
  }
});
