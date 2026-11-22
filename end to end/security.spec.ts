import { expect, test, type Page } from "@playwright/test";
import { STATE } from "./state";

/** Browser-side security checks (BUILD_PROMPT §7: SEC-09, SEC-07, SEC-10). */

const ANALYST = {
  email: "demo.analyst@example.org",
  password: process.env.SEED_ANALYST_PASSWORD ?? "",
};
const ADMIN = {
  email: "demo.admin@example.org",
  password: process.env.SEED_ADMIN_PASSWORD ?? "",
};

test.beforeAll(() => {
  expect(
    ANALYST.password,
    "set SEED_ANALYST_PASSWORD (in .env) and run seed_users.py",
  ).not.toBe("");
});

async function logIn(page: Page, who: { email: string; password: string }) {
  await page.goto("/login");
  await page.getByLabel("Email", { exact: true }).fill(who.email);
  await page.getByLabel("Password", { exact: true }).fill(who.password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

test.describe("with a saved Analyst session", () => {
  test.use({ storageState: STATE.analyst });

  test("no tokens in localStorage", async ({ page, context }) => {
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: "Dashboard" }),
    ).toBeVisible();

    const storage = await page.evaluate(() => ({
      local: Object.keys(window.localStorage),
      session: Object.keys(window.sessionStorage),
      readableCookies: document.cookie,
    }));
    expect(storage.local).toEqual([]);
    expect(storage.session).toEqual([]);
    // Page JavaScript can see only the CSRF token, never the access or refresh token
    expect(storage.readableCookies).toContain("mem_csrf=");
    expect(storage.readableCookies).not.toContain("mem_access");
    expect(storage.readableCookies).not.toContain("mem_refresh");

    const cookies = await context.cookies();
    const access = cookies.find((c) => c.name === "mem_access");
    expect(access?.httpOnly).toBe(true);
    expect(access?.sameSite).toBe("Strict");
  });

  test("an Analyst sees the permission message on the admin page", async ({
    page,
  }) => {
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: "Dashboard" }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: "Administration" }),
    ).toHaveCount(0);
    // the header names the role, never the username or email (D-035)
    const banner = page.getByRole("banner");
    await expect(banner).toContainText("Analyst");
    await expect(banner).not.toContainText("demo");
    await page.goto("/admin");
    await expect(
      page.getByText("You do not have permission to access this page."),
    ).toBeVisible();
  });
});

test("an administrator is sent to MFA before anything else", async ({
  page,
}) => {
  test.skip(ADMIN.password === "", "SEED_ADMIN_PASSWORD not set");
  await logIn(page, ADMIN);
  await expect(
    page.getByRole("heading", { name: "Two-factor authentication" }),
  ).toBeVisible();
  await page.goto("/admin");
  await expect(
    page.getByRole("heading", { name: "Two-factor authentication" }),
  ).toBeVisible();
});

test("logging out ends the session", async ({ page }) => {
  await logIn(page, ANALYST);
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(
    page.getByRole("heading", { name: "Welcome back" }),
  ).toBeVisible();
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Welcome back" }),
  ).toBeVisible();
});

test.describe("with a saved Analyst session (SEC-22)", () => {
  test.use({ storageState: STATE.analyst });

  test("sensor name with <script> renders as text", async ({ page }) => {
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: "Dashboard", level: 1 }),
    ).toBeVisible();
    // The fixture database names one sensor with an XSS payload (backend/scripts/make_fixture_db.py)
    await page.getByRole("button", { name: /FX-XS/ }).click();
    const title = page.getByRole("heading", { name: /Fixture Kiosk/ });
    await expect(title).toBeVisible();
    await expect(title).toContainText("<script>window.__xss=1</script>"); // shown literally
    expect(
      await page.evaluate(
        () => (window as unknown as { __xss?: number }).__xss,
      ),
    ).toBeUndefined();
    await expect(page.locator('img[src="x"]')).toHaveCount(0); // the <img onerror> was not created
  });

  test("no CSP violations in console", async ({ page }) => {
    const violations: string[] = [];
    page.on("console", (msg) => {
      if (
        msg.type() === "error" &&
        /Content Security Policy|Refused to/i.test(msg.text())
      )
        violations.push(msg.text());
    });
    await page.addInitScript(() => {
      document.addEventListener("securitypolicyviolation", (e) => {
        const w = window as unknown as { __csp?: string[] };
        (w.__csp ??= []).push(`${e.violatedDirective} ${e.blockedURI}`);
      });
    });
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: "Dashboard", level: 1 }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /over time/ }),
    ).toBeVisible(); // chart rendered
    await expect(
      page.getByRole("heading", { name: /daily and seasonal pattern/ }),
    ).toBeVisible();
    await page.getByRole("button", { name: /FX-TR/ }).click(); // sensor panel
    await page.goto("/api/docs"); // the self-hosted API docs page too
    await expect(page.getByText("/api/readings").first()).toBeVisible();
    const fromEvents = await page.evaluate(
      () => (window as unknown as { __csp?: string[] }).__csp ?? [],
    );
    expect([...violations, ...fromEvents]).toEqual([]);
  });
});
