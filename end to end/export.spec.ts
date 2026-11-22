import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { STATE } from "./state";

/** UC3 export against the production build and the SYNTHETIC fixture database. */
test.use({ storageState: STATE.analyst });

test("export is locked until Apply Filter, then CSV and PDF download", async ({
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
  await expect(
    page.getByRole("heading", { name: "Dashboard", level: 1 }),
  ).toBeVisible();

  const exportButton = page.getByRole("button", { name: "Export" });
  await expect(exportButton).toHaveAttribute("aria-disabled", "true");
  await exportButton.hover();
  await expect(page.getByRole("tooltip")).toHaveText(
    "Please apply a filter before exporting.",
  );

  await page.getByRole("button", { name: "Apply Filter" }).click();
  await expect(exportButton).toHaveAttribute("aria-disabled", "false");

  // CSV
  await exportButton.click();
  const dialog = page.getByRole("dialog", { name: "Export data" });
  await expect(dialog).toBeVisible();
  let download = page.waitForEvent("download");
  await dialog.getByRole("button", { name: "Download" }).click();
  const csv = await download;
  expect(csv.suggestedFilename()).toMatch(
    /^maribyrnong_temperature_c_day_\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}\.csv$/,
  );
  const text = readFileSync(await csv.path(), "utf-8");
  expect(text.charCodeAt(0)).toBe(0xfeff); // BOM for Excel
  expect(text).toContain("Variable,Temperature (°C)");
  expect(text).toContain("mean (°C)");
  expect(text).toContain("FX-TR");
  await expect(page.getByText("Your export is ready.")).toBeVisible();

  // PDF
  await exportButton.click();
  await dialog.getByRole("radio", { name: /PDF report/ }).check();
  download = page.waitForEvent("download");
  await dialog.getByRole("button", { name: "Download" }).click();
  const pdf = await download;
  expect(pdf.suggestedFilename()).toMatch(/\.pdf$/);
  expect(
    readFileSync(await pdf.path())
      .subarray(0, 5)
      .toString(),
  ).toBe("%PDF-");
  await expect(page.getByText("Your export is ready.")).toBeVisible();

  expect(cspErrors).toEqual([]);
});
