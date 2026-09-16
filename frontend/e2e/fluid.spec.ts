import { expect, test } from "@playwright/test";

// Fluid across display sizes (plain desktop Chromium, no mobile
// emulation — mixing isMobile with resized viewports misreports
// innerWidth, e.g. a 768 window seeing 904; mobile behavior itself is
// covered in mobile.spec.ts): small phone, tablet, laptop, wide desktop.
// Each width boots clean, shows a usable composer, never overflows
// horizontally, and puts the sidebar in the right mode (drawer below
// 861px, static dock at and above it).
for (const [width, height] of [
  [360, 800],
  [768, 800],
  [1280, 800],
  [1600, 800],
  // Fringes: tablet landscape, landscape phone (short-height rules),
  // very small phone (below the 380px breakpoint).
  [1024, 768],
  [844, 390],
  [320, 568],
] as const) {
  test(`fluid layout at ${width}x${height}`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(`pageerror: ${String(e)}`));
    page.on("console", (m) => {
      if (m.type() === "error") errors.push(`console: ${m.text()}`);
    });

    await page.setViewportSize({ width, height });
    await page.goto("/");
    await expect(page.locator("#authDlg")).toBeVisible({ timeout: 30_000 });
    await page.click("#authCancel");

    await expect(page.locator("#composer")).toBeVisible();
    await expect(page.locator("#input")).toBeVisible();

    // innerWidth must track the window (guards emulation artifacts).
    expect(await page.evaluate(() => window.innerWidth)).toBe(width);

    const sidebarBox = await page.locator(".sidebar").boundingBox();
    if (width < 861) {
      // Drawer mode: starts folded off-canvas.
      await expect.poll(async () =>
        page.evaluate(() => document.body.classList.contains("folded")),
      ).toBe(true);
      expect(sidebarBox && sidebarBox.x).toBeLessThan(0);
    } else {
      // Docked mode: static, on-screen, content column capped.
      expect(sidebarBox && sidebarBox.x).toBeGreaterThanOrEqual(0);
      const col = await page.locator(".chat-col").boundingBox();
      expect(col && col.width).toBeLessThanOrEqual(width);
    }

    const overflow = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth,
    }));
    expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.innerWidth);

    expect(errors).toEqual([]);
  });
}
