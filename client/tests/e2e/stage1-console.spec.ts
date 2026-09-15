import { expect, test } from "@playwright/test";

test("call experience is usable", async ({ page }, testInfo) => {
  await page.route("**/api/backend/health", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "ok" }),
    });
  });
  await page.route("**/api/agents", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        { id: "00000000-0000-0000-0000-000000000201", name: "Support", enabled: true },
      ]),
    });
  });

  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Who would you like to call?" })).toBeVisible();
  await expect(page.getByText("Ready to call")).toBeVisible();
  await expect(page.getByLabel("Agent")).toHaveValue("00000000-0000-0000-0000-000000000201");
  await expect(page.getByRole("button", { name: /Start call/ })).toBeEnabled();
  await expect(page.getByText("Recent calls")).toBeVisible();
  await expect(page.getByText("No calls yet today")).toBeVisible();

  await page.getByLabel("Phone number").fill("555-1234");
  await page.getByRole("button", { name: /Start call/ }).click();
  await expect(page.getByText("Call not started")).toBeVisible();
  await expect(page.getByText(/full number with country code/)).toBeVisible();

  await page.route("**/api/calls", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "00000000-0000-0000-0000-000000000101",
        status: "queued",
        provider_call_id: "CA00000000000000000000000000000101",
      }),
    });
  });
  await page.getByLabel("Phone number").fill("+14155552671");
  await page.getByRole("button", { name: /Start call/ }).click();
  await expect(page.getByText("Call started")).toBeVisible();
  await expect(page.getByText("+14155552671", { exact: true })).toBeVisible();

  const hasHorizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(hasHorizontalOverflow).toBe(false);

  await page.screenshot({ path: testInfo.outputPath("stage1-console.png"), fullPage: true });
});
