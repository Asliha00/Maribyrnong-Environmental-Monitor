import { expect, test, type Page } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

/** UC1 login page: layout, accessibility and the CSP, against the production build. */
const SHOTS = join(import.meta.dirname, "..", "docs", "screenshots", "fixture");
mkdirSync(SHOTS, { recursive: true });

function watchCsp(page: Page) {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (
      msg.type() === "error" &&
      /Content Security Policy|Refused to/i.test(msg.text())
    )
      errors.push(msg.text());
  });
  return errors;
}

/** WCAG contrast of each element's text against the first opaque background behind it.
 *  Colours go through a canvas, so any CSS colour syntax (Tailwind 4 uses oklch) is read as sRGB. */
async function contrastRatios(page: Page, selectors: string[]) {
  return page.evaluate((sels) => {
    const ctx = document.createElement("canvas").getContext("2d")!;
    const rgba = (css: string) => {
      ctx.clearRect(0, 0, 1, 1);
      ctx.fillStyle = "#000";
      ctx.fillStyle = css;
      ctx.fillRect(0, 0, 1, 1);
      return [...ctx.getImageData(0, 0, 1, 1).data];
    };
    const lum = ([r, g, b]: number[]) => {
      const c = [r, g, b].map((v) => {
        const s = v / 255;
        return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
    };
    const background = (el: Element | null): number[] => {
      for (; el; el = el.parentElement) {
        const bg = getComputedStyle(el).backgroundColor;
        if (bg && rgba(bg)[3] === 255) return rgba(bg);
      }
      return [255, 255, 255, 255];
    };
    const out: Record<string, number> = {};
    for (const sel of sels) {
      const el = document.querySelector(sel)!;
      const fg = lum(rgba(getComputedStyle(el).color));
      const bg = lum(background(el));
      out[sel] =
        Math.round(
          ((Math.max(fg, bg) + 0.05) / (Math.min(fg, bg) + 0.05)) * 100,
        ) / 100;
    }
    return out;
  }, selectors);
}

const TEXT = [
  "main section > p:first-child", // platform label
  "h1",
  "h1 + p", // subtitle
  "label[for=email]",
  "label[for=password]",
  "button[aria-controls=forgot-help]",
];

const SIZES = [
  { name: "1440", width: 1440, height: 900 },
  { name: "768", width: 768, height: 1024 },
  { name: "390", width: 390, height: 844 },
];
const contrastReport: Record<string, Record<string, number>> = {};

for (const scheme of ["light", "dark"] as const) {
  test(`login page, ${scheme}: theme illustration only, AA contrast, no CSP errors`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.emulateMedia({ colorScheme: scheme });
    const cspErrors = watchCsp(page);
    const images: string[] = [];
    page.on("request", (r) => {
      if (/login-illustration/.test(r.url())) images.push(r.url());
    });
    await page.goto("/login");
    await expect(
      page.getByRole("heading", { name: "Welcome back", level: 1 }),
    ).toBeVisible();
    const img = page.locator("main img");
    await expect(img).toBeVisible();
    await expect(img).toHaveAttribute("alt", "");
    await expect
      .poll(() =>
        img.evaluate((i: HTMLImageElement) => i.complete && i.naturalWidth),
      )
      .toBeGreaterThan(0);
    const current = await img.evaluate((i: HTMLImageElement) => i.currentSrc);
    // served from our own domain, and the image for the active theme
    expect(new URL(current).pathname).toMatch(
      new RegExp(`^/assets/login-illustration-${scheme}-.+\\.webp$`),
    );
    // only the active theme's image is downloaded
    expect(images.length).toBeGreaterThan(0);
    expect(images.every((u) => u.includes(`illustration-${scheme}`))).toBe(
      true,
    );

    const ratios = await contrastRatios(page, TEXT);
    // the Sign in button text, measured on the enabled button
    await page.getByLabel("Email", { exact: true }).fill("x@example.org");
    await page.getByLabel("Password", { exact: true }).fill("x");
    Object.assign(ratios, await contrastRatios(page, ["button[type=submit]"]));
    for (const [sel, ratio] of Object.entries(ratios))
      expect(ratio, `${sel} contrast (${scheme})`).toBeGreaterThanOrEqual(4.5);
    contrastReport[scheme] = ratios;
    writeFileSync(
      join(SHOTS, "login_contrast.json"),
      JSON.stringify(contrastReport, null, 2) + "\n",
    );
    expect(cspErrors).toEqual([]);
  });

  for (const size of SIZES) {
    test(`login page screenshot, ${scheme}, ${size.name} px`, async ({
      page,
    }) => {
      await page.setViewportSize({ width: size.width, height: size.height });
      await page.emulateMedia({ colorScheme: scheme });
      await page.goto("/login");
      await expect(
        page.getByRole("heading", { name: "Welcome back" }),
      ).toBeVisible();
      const img = page.locator("main img");
      if (size.width < 768) {
        await expect(img).toBeHidden();
      } else {
        await expect(img).toBeVisible();
        await expect
          .poll(() =>
            img.evaluate((i: HTMLImageElement) => i.complete && i.naturalWidth),
          )
          .toBeGreaterThan(0);
        // illustration and card side by side, not overlapping
        const a = (await page
          .locator("main [data-illustration]")
          .boundingBox())!;
        const b = (await page.locator("main section").boundingBox())!;
        expect(a.x + a.width).toBeLessThanOrEqual(b.x);
      }
      // no sideways scroll
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth,
        ),
      ).toBe(true);
      await page.screenshot({
        path: join(SHOTS, `login_${scheme}_${size.name}.png`),
      });
    });
  }
}

test("keyboard only: visible focus, eye button and forgot-password help", async ({
  page,
}) => {
  await page.goto("/login");
  const email = page.getByLabel("Email", { exact: true });
  const password = page.getByLabel("Password", { exact: true });
  await email.focus();
  await page.keyboard.type("x@example.org");
  await page.keyboard.press("Tab");
  const forgot = page.getByRole("button", { name: "Forgot password?" });
  await expect(forgot).toBeFocused();
  // a visible focus ring (Tailwind's ring is a box-shadow)
  expect(
    await forgot.evaluate((el) => getComputedStyle(el).boxShadow),
  ).not.toBe("none");
  await page.keyboard.press("Enter");
  await expect(
    page.getByText("Please contact your administrator to reset your password."),
  ).toBeVisible();
  await page.keyboard.press("Tab");
  await expect(password).toBeFocused();
  await page.keyboard.type("not-the-password");
  await page.keyboard.press("Tab");
  const eye = page.getByRole("button", { name: "Show password" });
  await expect(eye).toBeFocused();
  expect(await eye.evaluate((el) => getComputedStyle(el).boxShadow)).not.toBe(
    "none",
  );
  await page.keyboard.press("Space");
  await expect(password).toHaveAttribute("type", "text");
  await expect(
    page.getByRole("button", { name: "Hide password" }),
  ).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Sign in" })).toBeFocused();
  await page.screenshot({
    path: join(SHOTS, "login_forgot_password_1366.png"),
  });
});

test("a deactivated account cannot log in (SEC-12)", async ({ page }) => {
  // backend/scripts/make_fixture_db.py adds this deactivated analyst
  await page.goto("/login");
  await page
    .getByLabel("Email", { exact: true })
    .fill("fixture.inactive@example.org");
  await page
    .getByLabel("Password", { exact: true })
    .fill(process.env.SEED_ANALYST_PASSWORD ?? "");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toHaveText(
    "Your account has been deactivated. Please contact your administrator.",
  );
  await expect(
    page.getByRole("heading", { name: "Welcome back" }),
  ).toBeVisible();
});
