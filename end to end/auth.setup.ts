import { expect, test as setup } from "@playwright/test";
import { STATE } from "./state";

/**
 * Log in once per role through the real login form and save the session (HttpOnly cookies)
 * for the other tests. Logging in for every test would hit the 5-logins-per-minute limit
 * (SEC-23), which is the limit working, not a bug.
 */
const ACCOUNTS = [
  [
    "analyst",
    "demo.analyst@example.org",
    process.env.SEED_ANALYST_PASSWORD ?? "",
  ],
] as const;

for (const [role, email, password] of ACCOUNTS) {
  setup(`log in as ${role}`, async ({ page }) => {
    expect(password, `set the SEED_ password for ${role}`).not.toBe("");
    await page.goto("/login");
    await page.getByLabel("Email", { exact: true }).fill(email);
    await page.getByLabel("Password", { exact: true }).fill(password);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(
      page.getByRole("heading", { name: "Dashboard", level: 1 }),
    ).toBeVisible();
    await page.context().storageState({ path: STATE[role] });
  });
}
