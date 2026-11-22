import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { totp } from "./totp";

/**
 * UC5 administration end to end, as an administrator who passes real TOTP MFA (the fixture
 * admin `e2e_admin`, secret written by make_fixture_db.py next to the database).
 *
 * Runs in its own project AFTER the other specs (playwright.config.ts): it registers a sensor
 * and changes a threshold, which would change what the dashboard specs expect.
 * One login for the whole file (the 5-logins-per-minute limit, SEC-23).
 */
test.describe.configure({ mode: "serial" });

let page: Page;
const cspErrors: string[] = [];

test.beforeAll(async ({ browser }) => {
  page = await browser.newPage({ viewport: { width: 1366, height: 900 } });
  page.on("console", (msg) => {
    if (
      msg.type() === "error" &&
      /Content Security Policy|Refused to/i.test(msg.text())
    )
      cspErrors.push(msg.text());
  });
  const secret = readFileSync(
    join(import.meta.dirname, ".fixture.db.totp"),
    "utf-8",
  ).trim();
  await page.goto("/login");
  await page.getByLabel("Email", { exact: true }).fill("e2e.admin@example.org");
  await page
    .getByLabel("Password", { exact: true })
    .fill(process.env.SEED_ADMIN_PASSWORD ?? "");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(
    page.getByRole("heading", { name: "Two-factor authentication" }),
  ).toBeVisible();
  await page.getByLabel("6-digit code").fill(totp(secret));
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(
    page.getByRole("heading", { name: "Dashboard", level: 1 }),
  ).toBeVisible();
  // the header names the role, never the account (D-035)
  const banner = page.getByRole("banner");
  await expect(banner).toContainText("Administrator");
  await expect(banner).not.toContainText("e2e");
});

test.afterAll(async () => {
  expect(cspErrors).toEqual([]);
  await page.close();
});

/** Reach an admin section by CLICKING the menu and tab, as a person does. (A relative tab
 * link once resolved against the current URL and redirect-looped; typing the URL hid it.) */
async function openTab(label: string, path: string) {
  await page.getByRole("link", { name: "Administration" }).click();
  await page
    .getByRole("navigation", { name: "Administration sections" })
    .getByRole("link", { name: label })
    .click();
  await expect(page).toHaveURL(new RegExp(`${path}$`));
}

test("register a sensor: coordinate check, success message, key once, on the map", async () => {
  await page.getByRole("link", { name: "Administration" }).click();
  await expect(
    page.getByRole("heading", { name: "Sensors", level: 2 }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Register a sensor" }).click();
  const form = page.getByRole("form", { name: "Register a sensor" });
  await form.getByLabel("Sensor code").fill("FX-NEW");
  await form.getByLabel("Name").fill("Fixture New Gardens");
  await form.getByLabel(/Latitude/).fill("-38.5");
  await form.getByLabel(/Longitude/).fill("144.88");
  await form.getByRole("button", { name: "Register sensor" }).click();
  await expect(form.getByRole("alert")).toHaveText(
    "Please enter valid GPS coordinates within the municipality boundary.",
  );
  await expect(form.getByLabel(/Latitude/)).toHaveAttribute(
    "aria-invalid",
    "true",
  );

  await form.getByLabel(/Latitude/).fill("-37.80");
  await form.getByRole("button", { name: "Register sensor" }).click();
  await expect(page.getByText("Sensor registered successfully")).toBeVisible();
  const key = page.getByRole("region", { name: "Device key for FX-NEW" });
  await expect(key.locator("code")).toHaveText(/^[A-Za-z0-9_-]{43,}$/);
  await key.getByRole("button", { name: "I have saved it" }).click();
  await expect(key).toHaveCount(0);

  await page.getByRole("link", { name: "Dashboard" }).click();
  await expect(
    page
      .getByRole("list", { name: "Sensors on the map" })
      .getByRole("button", { name: /FX-NEW/ }),
  ).toBeVisible();
});

test("change a threshold with a reason; the change log shows it", async () => {
  await openTab("Thresholds", "/admin/thresholds");
  await expect(
    page.getByRole("heading", { name: "Thresholds", level: 2 }),
  ).toBeVisible();
  const row = page
    .getByRole("row")
    .filter({ hasText: "PM2.5 24-hour standard" });
  await row.getByRole("button", { name: /^Change/ }).click();
  const form = page.getByRole("form", { name: /^Change/ });
  await form.getByLabel(/New value/).fill("20");
  await form.getByLabel(/Reason/).fill("End-to-end test of the change log.");
  await form.getByRole("button", { name: "Save and recalculate" }).click();
  await expect(page.getByText(/Exceedances recalculated/)).toBeVisible();
  const log = page.getByRole("table", { name: /change log/ });
  await expect(log).toContainText("25 → 20");
  await expect(log).toContainText("End-to-end test of the change log.");
  await expect(log).toContainText("e2e_admin");
});

test("create a user: temporary password shown once", async () => {
  await openTab("Users", "/admin/users");
  await page.getByRole("button", { name: "Create a user" }).click();
  const form = page.getByRole("form", { name: "Create a user" });
  await form.getByLabel("Username").fill("fixture.analyst2");
  await form.getByLabel("Email").fill("fixture.analyst2@example.org");
  await form
    .getByLabel("Role")
    .selectOption({ label: "Environmental Analyst" });
  await form.getByRole("button", { name: "Create user" }).click();
  const secret = page.getByRole("region", {
    name: "Temporary password for fixture.analyst2",
  });
  await expect(secret.locator("code")).toHaveText(/.{20,}/);
  await expect(
    page.getByRole("row").filter({ hasText: "fixture.analyst2" }),
  ).toContainText("must change password");
  // your own account has no access-changing actions
  await expect(
    page.getByRole("row").filter({ hasText: "e2e_admin" }),
  ).toContainText("Another administrator manages your account");
});

test("upload page and data-quality page load", async () => {
  await openTab("Sensors", "/admin/sensors");
  await openTab("Upload data", "/admin/upload");
  await openTab("Thresholds", "/admin/thresholds");
  await openTab("Upload data", "/admin/upload");
  await expect(
    page.getByRole("heading", { name: "Upload sensor data (CSV)" }),
  ).toBeVisible();
  await expect(page.getByLabel("Sensor").locator("option")).toContainText([
    "FX-TR · Fixture Transport Hub",
  ]);
  await page.getByRole("button", { name: "Upload and load" }).click();
  await expect(page.getByRole("alert")).toHaveText("Choose a CSV file.");

  await page.getByRole("link", { name: "Data quality" }).click();
  await expect(
    page.getByRole("heading", { name: "Completeness by day" }),
  ).toBeVisible();
  await expect(
    page.getByRole("img", { name: /FX-TR: \d+ of \d+ days/ }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Suspicious login activity" }),
  ).toBeVisible();
});

test("2FA recovery codes (Change password → Account security): shown once; a code replaces the authenticator (D-037)", async ({
  browser,
}) => {
  await page.getByRole("link", { name: "Change password" }).click();
  await expect(
    page.getByRole("heading", { name: "Account security", level: 2 }),
  ).toBeVisible();
  await expect(page.getByText(/unused recovery code/)).toBeVisible();
  await page
    .getByRole("button", { name: "Generate new recovery codes" })
    .click();
  await page.getByRole("button", { name: "Yes, replace my codes" }).click();
  const items = page
    .getByRole("list", { name: "Recovery codes" })
    .getByRole("listitem");
  await expect(items).toHaveCount(10);
  const code = ((await items.first().textContent()) ?? "").trim();
  expect(code).toMatch(/^[0-9A-HJKMNP-TV-Z]{4}(-[0-9A-HJKMNP-TV-Z]{4}){3}$/);
  const done = page.getByRole("button", { name: "Done" });
  await expect(done).toBeDisabled();
  await page.getByLabel("I have saved these codes").check();
  await done.click();
  await expect(page.getByText(/unused recovery code/)).toContainText("10");

  // A second browser: password, then the recovery code instead of the 6-digit code.
  // Logins are limited to 5 a minute per IP in fixed windows (SEC-23) and the earlier specs
  // used this minute's, so start the sign-in in a fresh window.
  test.setTimeout(150_000);
  await page.waitForTimeout((61 - (Math.floor(Date.now() / 1000) % 60)) * 1000);
  const other = await browser.newPage();
  await other.goto("/login");
  await other
    .getByLabel("Email", { exact: true })
    .fill("e2e.admin@example.org");
  await other
    .getByLabel("Password", { exact: true })
    .fill(process.env.SEED_ADMIN_PASSWORD ?? "");
  await other.getByRole("button", { name: "Sign in" }).click();
  await other
    .getByRole("button", { name: "Use a recovery code instead" })
    .click();
  await other.getByLabel("Recovery code").fill(code.toLowerCase());
  await other.getByRole("button", { name: "Verify" }).click();
  await expect(
    other.getByRole("heading", { name: "Dashboard", level: 1 }),
  ).toBeVisible();
  await other.getByRole("link", { name: "Administration" }).click();
  await expect(
    other.getByRole("heading", { name: "Sensors", level: 2 }),
  ).toBeVisible(); // admin access: the session passed 2FA
  await other.close();

  await page.reload();
  await expect(page.getByText(/unused recovery code/)).toContainText("9");
});
