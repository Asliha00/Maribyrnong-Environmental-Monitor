import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { STATE } from "./state";

/** Insights page (§4.3) on the SYNTHETIC fixture database: every section renders from the API. */
test.use({ storageState: STATE.analyst });

test("insights answer the project aims with computed numbers", async ({
  page,
}) => {
  const cspErrors: string[] = [];
  page.on("console", (msg) => {
    if (
      msg.type() === "error" &&
      /Content Security Policy|Refused to/i.test(msg.text())
    )
      cspErrors.push(msg.text());
  });
  await page.goto("/");
  await page.getByRole("link", { name: "Insights" }).click();
  await expect(
    page.getByRole("heading", { name: "Insights", level: 1 }),
  ).toBeVisible();
  for (const name of [
    "Recommendations",
    "Where is it hottest, and where is the air worst?",
    "Sensitive sites",
    "Do parks keep the area cooler?",
    "Daily and seasonal patterns",
    "Trends",
    "The sensor network",
  ])
    await expect(page.getByRole("heading", { name, level: 2 })).toBeVisible();

  // the numbers come from the data: the comparison names the fixture sites
  const temp = page.getByRole("region", {
    name: /Temperature compared with the other sites/,
  });
  await expect(temp.getByRole("img")).toHaveAttribute(
    "aria-label",
    /FX-TR: .*°C/,
  );
  await temp.getByRole("button", { name: "table" }).click();
  await expect(temp.getByRole("table")).toContainText(
    "Fixture Residential Street (sensitive site)",
  );
  await expect(
    page
      .getByRole("listitem")
      .filter({ hasText: /priority/i })
      .first(),
  ).toBeVisible();

  await page.getByText("Methodology and limitations").click();
  await expect(page.getByText(/Comparing sites\./)).toBeVisible();

  mkdirSync(join(import.meta.dirname, "..", "docs", "screenshots", "fixture"), {
    recursive: true,
  });
  await page.screenshot({
    path: join(
      import.meta.dirname,
      "..",
      "docs",
      "screenshots",
      "fixture",
      "insights_1366.png",
    ),
    fullPage: true,
  });
  expect(cspErrors).toEqual([]);
});
