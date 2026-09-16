import { expect, test } from "@playwright/test";

// Mobile pass (390x844, touch): drawer sidebar opens/closes, composer is
// usable, no horizontal overflow. Fails on ANY uncaught page error.
test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

test("mobile layout: drawer, composer, no horizontal scroll", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${String(e)}`));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(`console: ${m.text()}`);
  });

  await page.goto("/");

  // Boot: dismiss the login dialog like the desktop smoke does.
  await expect(page.locator("#authDlg")).toBeVisible({ timeout: 30_000 });
  await page.click("#authCancel");
  await expect(page.locator("#authDlg")).toBeHidden();

  // Sidebar starts folded off-canvas on small screens.
  const sidebar = page.locator(".sidebar");
  await expect.poll(async () =>
    page.evaluate(() => document.body.classList.contains("folded")),
  ).toBe(true);
  const foldedBox = await sidebar.boundingBox();
  expect(foldedBox && foldedBox.x).toBeLessThan(0);

  // Drawer opens via the fold button, with backdrop.
  await page.click("#foldBtn");
  await expect.poll(async () =>
    page.evaluate(() => document.body.classList.contains("folded")),
  ).toBe(false);
  await expect(page.locator("#backdrop")).toBeVisible();
  // Drawer slides in over .18s — wait for the transform to settle.
  await expect.poll(async () =>
    page.locator(".sidebar").evaluate((el) => el.getBoundingClientRect().x),
  ).toBeGreaterThanOrEqual(0);
  const openBox = await sidebar.boundingBox();
  expect(openBox && openBox.width).toBeLessThanOrEqual(390);

  // Backdrop tap closes it (clear of the 280px drawer).
  await page.mouse.click(360, 420);
  await expect.poll(async () =>
    page.evaluate(() => document.body.classList.contains("folded")),
  ).toBe(true);

  // Composer is visible and usable at mobile width.
  await expect(page.locator("#composer")).toBeVisible();
  await expect(page.locator("#input")).toBeVisible();
  await expect(page.locator("#sendBtn")).toBeVisible();
  await page.fill("#input", "hello mobile e2e");
  await page.click("#sendBtn");
  // Settles to either a toast (no live tiers) or a completed assistant
  // reply (live tiers answering from the dev .env) — both prove send works.
  await expect.poll(async () => {
    if (await page.locator("#toasts .toast").count()) return "toast";
    if (await page.locator('.msg.ai[aria-busy="true"]').count()) return "pending";
    const bodies = await page.locator("#viewChat .msg.ai .body").allInnerTexts();
    return bodies.some((t) => t.trim().length > 0) ? "reply" : "pending";
  }, { timeout: 60_000 }).not.toBe("pending");

  // No horizontal overflow on the document.
  const overflow = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }));
  expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.innerWidth);

  expect(errors).toEqual([]);
});
