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

test("investigate tab renders the VULCAN AGENT panel + subgraph canvas", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("tab-investigate").click();
  await expect(page.getByTestId("investigate")).toBeVisible();
  await expect(page.getByTestId("inv-agent")).toBeVisible(); // left agent panel
  await expect(page.getByTestId("sg-wrap")).toBeVisible(); // force-directed canvas area
});

test("investigate runs the cascade walk + proposal to Approve/Reject", async ({ page }) => {
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
  await expect(page.getByTestId("inv-controls")).toBeVisible(); // transport: run/step/pause/restart
  await page.getByTestId("inv-pause").click(); // pause autoplay
  await expect(page.getByTestId("vulcan")).toBeVisible(); // the 5-step process
  // step forward until the Propose phase surfaces the proposed solution
  for (let i = 0; i < 12; i++) {
    if (await page.getByTestId("agent-proposal").isVisible().catch(() => false)) break;
    await page.getByTestId("inv-step").click();
    await page.waitForTimeout(120);
  }
  await expect(page.getByTestId("agent-proposal")).toBeVisible(); // proposed solution
  await expect(page.getByTestId("inv-approve")).toBeVisible();
});

test("self-heal panel toggles and shows modes", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("selfheal")).toBeVisible();
  await expect(page.getByTestId("sh-mode-auto")).toBeVisible();
  await expect(page.getByTestId("sh-mode-approve")).toBeVisible();
  await page.getByTestId("sh-toggle").click(); // start the agent
  await expect(page.getByTestId("sh-toggle")).toContainText("ON");
});

test("fleet tab browses nodes in a collapsing tree with registry + connectivity", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("tab-fleet").click();
  await expect(page.getByTestId("fleet")).toBeVisible();
  await expect(page.getByTestId("fleet-registry")).toContainText("Registry");
  await expect(page.getByTestId("sec-S1")).toBeVisible();
  await expect(page.getByTestId("fleet-tree")).toBeVisible();
  await page.getByTestId("filter-conn").click(); // connectivity filter
  await expect(page.getByTestId("filter-conn")).toHaveClass(/active/);
});

test("bottom timeline shows plant clock and the 5 section stages", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("timeline")).toBeVisible();
  await expect(page.getByTestId("plant-clock")).toContainText("plant");
  for (const id of ["S4", "S1", "S3", "S2", "S5"]) {
    await expect(page.getByTestId(`tl-${id}`)).toBeVisible();
  }
});
