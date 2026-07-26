import { expect, test } from "playwright/test";

test.beforeEach(async ({ page }) => {
  await page.goto("/?fixture=1");
  await page.getByRole("option", { name: /Round-trip/ }).click();
  await expect(page.locator("#document-title")).toContainText("Round-trip");
  await expect.poll(() =>
    page.evaluate(() => window.__QBANK_STUDIO_TEST__.testSnapshot().editor),
  ).not.toBeNull();
});

test("failed repository bootstrap preserves the complete active session", async ({ page }) => {
  const before = await page.evaluate(() => window.__QBANK_STUDIO_TEST__.testSnapshot());
  await page.evaluate(() =>
    (
      window.__QBANK_STUDIO_TEST__ as typeof window.__QBANK_STUDIO_TEST__ & {
        openRepository(root: string): Promise<void>;
      }
    ).openRepository("fixture://broken-bank"),
  );

  await expect(page.locator("#repository-name")).toHaveText("公开合成题库");
  await expect(page.locator("#document-title")).toContainText("Round-trip");
  await expect(page.locator("#result-count")).toHaveText("2 题");
  await expect(page.locator("#toast-region")).toContainText("synthetic repository bootstrap failure");
  expect(await page.evaluate(() => window.__QBANK_STUDIO_TEST__.testSnapshot())).toEqual(before);
});

test("successful repository activation clears every old document projection at once", async ({
  page,
}) => {
  await page.evaluate(() =>
    (
      window.__QBANK_STUDIO_TEST__ as typeof window.__QBANK_STUDIO_TEST__ & {
        openRepository(root: string): Promise<void>;
      }
    ).openRepository("fixture://alternate-bank"),
  );

  await expect(page.locator("#repository-name")).toHaveText("备用合成题库");
  await expect(page.locator("#repository-path")).toHaveText("点击复制完整路径");
  await expect(page.locator("#repository-path")).not.toContainText("fixture://");
  await expect(page.locator("#document-title")).toHaveText("选择一道题目");
  await expect(page.locator("#metadata-form")).toContainText("未加载");
  await expect(page.frameLocator("#secure-preview").locator("body")).toContainText(
    "选择一道题目",
  );
  await expect(page.locator("#result-count")).toHaveText("1 题");
});

test("slow question load removes the previous preview before asynchronous reads finish", async ({
  page,
}) => {
  await expect(page.frameLocator("#secure-preview").locator("body")).toContainText(
    "自定义宏",
  );
  await page.getByRole("option", { name: /Slow generation sample/ }).click();

  await expect(page.locator("#document-title")).toHaveText("TEST-SLOW-0002");
  await expect(page.locator("#secure-preview")).toHaveAttribute("aria-busy", "true");
  await expect(page.frameLocator("#secure-preview").locator("body")).toContainText(
    "正在加载 TEST-SLOW-0002",
  );
  await expect(page.frameLocator("#secure-preview").locator("body")).not.toContainText(
    "Round-trip",
  );
  await expect(page.locator("#document-title")).toHaveText("Slow generation sample");
  await expect(page.locator("#secure-preview")).toHaveAttribute("aria-busy", "false");
});

test("dirty asset creation can be cancelled without writes", async ({ page }) => {
  const source = await page.evaluate(
    () => window.__QBANK_STUDIO_TEST__.testSnapshot().editor ?? "",
  );
  await page.evaluate(
    (value) => window.__QBANK_STUDIO_TEST__.testSetEditorValue(`${value}\nunsaved`),
    source,
  );
  await expect.poll(() =>
    page.evaluate(() => window.__QBANK_STUDIO_TEST__.testSnapshot().dirty),
  ).toBe(true);
  await page.locator("#editor-frame").evaluate((element) => {
    const transfer = new DataTransfer();
    transfer.items.add(
      new File([new Uint8Array([137, 80, 78, 71])], "cancel.png", {
        type: "image/png",
      }),
    );
    element.dispatchEvent(
      new ClipboardEvent("paste", {
        bubbles: true,
        cancelable: true,
        clipboardData: transfer,
      }),
    );
  });
  const dialog = page.locator("#dirty-state-dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "取消" }).click();

  await expect(dialog).toBeHidden();
  expect(await page.evaluate(() =>
    window.__QBANK_STUDIO_FIXTURE__.requestLog.filter(
      (method) => method === "asset.create",
    ).length,
  )).toBe(0);
  expect(await page.evaluate(() => window.__QBANK_STUDIO_TEST__.testSnapshot().dirty)).toBe(
    true,
  );
});

for (const choice of ["放弃修改", "保存并继续"] as const) {
  test(`dirty asset creation continues only after ${choice}`, async ({ page }) => {
    const source = await page.evaluate(
      () => window.__QBANK_STUDIO_TEST__.testSnapshot().editor ?? "",
    );
    await page.evaluate(
      (value) => window.__QBANK_STUDIO_TEST__.testSetEditorValue(`${value}\nunsaved-choice`),
      source,
    );
    await expect.poll(() =>
      page.evaluate(() => window.__QBANK_STUDIO_TEST__.testSnapshot().dirty),
    ).toBe(true);
    await page.locator("#editor-frame").evaluate((element) => {
      const transfer = new DataTransfer();
      transfer.items.add(
        new File([new Uint8Array([137, 80, 78, 71, 1])], "choice.png", {
          type: "image/png",
        }),
      );
      element.dispatchEvent(
        new ClipboardEvent("paste", {
          bubbles: true,
          cancelable: true,
          clipboardData: transfer,
        }),
      );
    });
    await page.locator("#dirty-state-dialog").getByRole("button", { name: choice }).click();

    await expect.poll(() => page.evaluate(() =>
      window.__QBANK_STUDIO_FIXTURE__.requestLog.includes("asset.create"),
    )).toBe(true);
    const snapshot = await page.evaluate(() => window.__QBANK_STUDIO_TEST__.testSnapshot());
    expect(snapshot.buffer).toContain("qbank-asset:figure-1");
    expect(snapshot.buffer.includes("unsaved-choice")).toBe(choice === "保存并继续");
    expect(snapshot.dirty).toBe(false);
    if (choice === "保存并继续") {
      expect(await page.evaluate(() =>
        window.__QBANK_STUDIO_FIXTURE__.requestLog.includes("question.save"),
      )).toBe(true);
    }
  });
}
