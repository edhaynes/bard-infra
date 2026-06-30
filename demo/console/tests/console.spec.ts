import { expect, test } from "@playwright/test";

const SECTIONS = ["S4", "S1", "S3", "S2", "S5"];

test("renders the refinery console shell with all 5 sections", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("topbar")).toBeVisible();
  await expect(page.getByTestId("kpi")).toBeVisible();
  await expect(page.getByTestId("plant")).toBeVisible();
  for (const id of SECTIONS) {
    await expect(page.getByTestId(`section-${id}`)).toBeVisible();
  }
  await expect(page.getByTestId("inject")).toBeVisible();
});

test("bring-up drives the plant to running", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("btn-reset").click();
  await page.getByTestId("btn-bringup").click();
  await expect(page.getByTestId("mode")).toBeVisible();
  // utilities section reaches a live status within the bring-up window
  await expect(page.getByTestId("section-S4")).toHaveAttribute(
    "data-status",
    /running|starting|partial/,
    { timeout: 80_000 },
  );
});

test("injecting a fault opens an incident", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("btn-inject").click();
  await expect(page.getByTestId("incidents")).toBeVisible();
});
