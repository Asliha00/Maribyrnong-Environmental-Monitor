import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { STATE } from "./state";

/** UC2 dashboard against the production build and the SYNTHETIC fixture database. */
const SHOTS = join(import.meta.dirname, "..", "docs", "screenshots", "fixture");

test.use({ storageState: STATE.analyst });

/** Open the dashboard with the analyst session saved by auth.setup.ts (a real UI login). */
async function logIn(page: Page) {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Dashboard", level: 1 }),
  ).toBeVisible();
}

test("login → filter → chart renders", async ({ page }) => {
  await logIn(page);
  await page
    .getByLabel("Variable", { exact: true })
    .selectOption({ label: "PM2.5 (µg/m³)" });
  await page.getByRole("radio", { name: "Monthly" }).check();
  await page.getByLabel("From", { exact: true }).fill("2025-02-16");
  await page.getByLabel("To", { exact: true }).fill("2026-02-16");
  await page.getByRole("button", { name: "Apply Filter" }).click();

  await expect(
    page.getByRole("heading", { name: "PM2.5 over time" }),
  ).toBeVisible();
  const legend = page.getByRole("list", { name: "Legend" });
  await expect(legend).toContainText("FX-TR");
  await expect(legend).not.toContainText("FX-XS"); // does not measure PM2.5
  await expect(page.locator(".recharts-line-curve").first()).toBeVisible(); // lines drawn
  await expect(
    page.getByRole("region", { name: "Summary for the selection" }),
  ).toContainText("µg/m³");
  await expect(
    page.getByRole("heading", { name: /daily and seasonal pattern/ }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: /Threshold alerts/ }),
  ).toBeVisible();

  // Table view of the same data (accessibility)
  await page
    .getByRole("region", { name: /PM2.5 over time/ })
    .getByRole("button", { name: "table" })
    .click();
  await expect(
    page.getByRole("columnheader", { name: "FX-TR (µg/m³)" }),
  ).toBeVisible();
});

test("UC2 messages: invalid range and sensor not found", async ({ page }) => {
  await logIn(page);
  await page.getByLabel("From", { exact: true }).fill("2026-01-10");
  await page.getByLabel("To", { exact: true }).fill("2026-01-01");
  await page.getByRole("button", { name: "Apply Filter" }).click();
  await expect(page.getByRole("alert")).toHaveText(
    "Invalid date range selected.",
  );

  await page.getByLabel("Sensors", { exact: true }).fill("no-such-sensor");
  await expect(page.getByText("Sensor not found.")).toBeVisible();
  await page.getByLabel("Sensors", { exact: true }).fill("park");
  await page
    .getByRole("list", { name: "Matching sensors" })
    .getByRole("button", { name: /FX-PK/ })
    .click();
  await expect(
    page.getByRole("list", { name: "Chosen sensors" }),
  ).toContainText("FX-PK");
});

test("map marks unverified locations and opens the sensor panel", async ({
  page,
}) => {
  await logIn(page);
  await expect(page.locator(".leaflet-container")).toBeVisible();
  await expect(page.locator("path.leaflet-interactive")).toHaveCount(4); // four active fixture sensors
  await page.getByRole("button", { name: /FX-PK/ }).click();
  const panel = page.getByRole("region", { name: /Fixture Riverside Park/ });
  await expect(panel).toContainText("Location unverified");
  await expect(panel).toContainText("Last updated");
  await expect(panel.getByRole("link", { name: /history/ })).toHaveAttribute(
    "href",
    "/sensors/2",
  );
});

test("screenshots at laptop and tablet size (synthetic fixture data)", async ({
  page,
}) => {
  mkdirSync(SHOTS, { recursive: true });
  await logIn(page);
  await expect(
    page.getByRole("heading", { name: /daily and seasonal pattern/ }),
  ).toBeVisible();
  await page.screenshot({
    path: join(SHOTS, "dashboard_1366x768.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 768, height: 1024 });
  await page.screenshot({
    path: join(SHOTS, "dashboard_tablet_768x1024.png"),
    fullPage: true,
  });
});
