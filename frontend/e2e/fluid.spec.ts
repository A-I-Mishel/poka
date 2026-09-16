import { expect, test } from "@playwright/test";

// Fluid across display sizes (plain desktop Chromium, no mobile
// emulation — mixing isMobile with resized viewports misreports
// innerWidth, e.g. a 768 window seeing 904; mobile behavior itself is
// covered in mobile.spec.ts): small phone, tablet, laptop, wide desktop.
// Each width boots clean, shows a usable composer, never overflows
// horizontally, and puts the sidebar in the right mode (drawer below
// 861px, static dock at and above it).
for (const width of [360, 768, 1280, 1600]) {
  test(`fluid layout at ${width}px`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(`pageerror: ${String(e)}`));
    page.on("console", (m) => {
      if (m.type() === "error") errors.push(`console: ${m.text()}`);
    });

    await page.setViewportSize({ width, height: 800 });
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
