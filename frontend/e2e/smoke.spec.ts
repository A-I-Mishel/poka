import { expect, test } from "@playwright/test";

// Split-UI smoke: boot, login dialog, panel walk, toggles, graceful
// no-tier send. Fails on ANY uncaught page error (the signature of a
// bad module split: ReferenceError: X is not defined).
test("split UI boots and degrades gracefully with zero page errors", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${String(e)}`));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(`console: ${m.text()}`);
  });

  await page.goto("/");

  // Boot: logged-out visitor gets the login dialog once.
  await expect(page.locator("#authDlg")).toBeVisible({ timeout: 30_000 });
  await page.click("#authCancel");
  await expect(page.locator("#authDlg")).toBeHidden();

  // Chat shell is up.
  await expect(page.locator("#chatTitle")).toContainText("New chat");
  await expect(page.locator("#composer")).toBeVisible();
  await expect(page.locator("#sendBtn")).toBeVisible();

  // Always-visible workspace sections.
  for (const name of ["research", "workflows"]) {
    await page.locator(`button.nav[data-section="${name}"]`).click();
    await expect(page.locator("#viewPanel")).toBeVisible();
    await expect(page.locator("#panelBody")).not.toBeEmpty();
  }

  // "More" sections may start collapsed — expand if needed.
  for (const name of ["memory", "files", "artifacts", "sources", "stats"]) {
    const btn = page.locator(`#moreItems button.nav[data-section="${name}"]`);
    if (!(await btn.isVisible())) await page.click("#moreToggle");
    await btn.click();
    await expect(page.locator("#viewPanel")).toBeVisible();
  }
  await page.click("#backBtn");
  await expect(page.locator("#viewChat")).toBeVisible();

  // Theme + Fast/Deep toggles.
  await page.click("#themeBtn");
  await page.click("#themeBtn");
  await page.locator('#modeToggle button[data-mode="deep"]').click();
  await page.locator('#modeToggle button[data-mode="fast"]').click();

  // Send: with no tiers configured this must degrade to a toast, never
  // crash; with live tiers (dev .env) it answers instead — either settled
  // outcome proves the send path works end to end.
  await page.fill("#input", "hello e2e");
  await page.click("#sendBtn");
  await expect.poll(async () => {
    if (await page.locator("#toasts .toast").count()) return "toast";
    if (await page.locator('.msg.ai[aria-busy="true"]').count()) return "pending";
    const bodies = await page.locator("#viewChat .msg.ai .body").allInnerTexts();
    return bodies.some((t) => t.trim().length > 0) ? "reply" : "pending";
  }, { timeout: 60_000 }).not.toBe("pending");

  expect(errors).toEqual([]);
});
