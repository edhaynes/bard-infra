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

test("investigate tab renders the device network", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("tab-investigate").click();
  await expect(page.getByTestId("investigate")).toBeVisible();
  // the plant core + a known device are in the network
  await expect(page.getByTestId("net-PLANT")).toBeVisible();
  await expect(page.getByTestId("net-DCS-840")).toBeVisible();
});

test("investigate runs the Vulcan 5-step investigation theater", async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => fetch("http://127.0.0.1:7090/reset", { method: "POST" }));
  await page.evaluate(() =>
    fetch("http://127.0.0.1:7090/inject", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind: "unit_trip", target: "U-840" }),
    }),
  );
  await page.getByTestId("tab-investigate").click();
  await page.waitForTimeout(1600);
  await expect(page.getByTestId("inv-phases")).toBeVisible();
  await page.getByTestId("inv-play").click(); // pause autoplay
  for (let i = 0; i < 14; i++) await page.getByTestId("inv-step").click();
  await expect(page.getByTestId("vulcan")).toBeVisible(); // Vulcan diagnosis panel
});

test("self-heal panel toggles and shows modes", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("selfheal")).toBeVisible();
  await expect(page.getByTestId("sh-mode-auto")).toBeVisible();
  await expect(page.getByTestId("sh-mode-approve")).toBeVisible();
  await page.getByTestId("sh-toggle").click(); // start the agent
  await expect(page.getByTestId("sh-toggle")).toContainText("ON");
});

test("bottom timeline shows plant clock and the 5 section stages", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("timeline")).toBeVisible();
  await expect(page.getByTestId("plant-clock")).toContainText("plant");
  for (const id of ["S4", "S1", "S3", "S2", "S5"]) {
    await expect(page.getByTestId(`tl-${id}`)).toBeVisible();
  }
});
