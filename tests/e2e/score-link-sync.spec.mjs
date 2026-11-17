// The 𝄞 beside a stem in the studio opens its score at the moment the song
// is at (?t=), not at 0:00, and the studio stops so the two do not play at
// once.

import { test, expect } from "@playwright/test";
import { openStudio } from "./helpers.mjs";

test("𝄞 opens the score where the song is, and the studio stops", async ({ page, context }) => {
  await openStudio(page);
  const link = page.locator("a.mx-score-link").first();
  await expect(link).toBeVisible();
  await page.locator("#t-play").click();
  await page.waitForTimeout(1500);
  const [popup] = await Promise.all([context.waitForEvent("page"), link.click()]);
  const url = new URL(popup.url());
  expect(url.pathname).toBe("/score/");
  expect(Number(url.searchParams.get("t"))).toBeGreaterThan(0.5);
  await expect(page.locator("#t-play")).not.toHaveClass(/playing/);
  await popup.close();
});

test("🎷 in the mixer's header opens the saxophone for the song, where it is, and the studio stops", async ({ page, context }) => {
  await openStudio(page);
  const sax = page.locator("#mixer-sax");
  await expect(sax).toBeVisible();
  await page.locator("#t-play").click();
  await page.waitForTimeout(1500);
  const [popup] = await Promise.all([context.waitForEvent("page"), sax.click()]);
  const url = new URL(popup.url());
  expect(url.pathname).toBe("/sax/");
  expect(url.searchParams.get("job")).toMatch(/^[a-f0-9]{12}$/);
  expect(Number(url.searchParams.get("t"))).toBeGreaterThan(0.5);
  await expect(page.locator("#t-play")).not.toHaveClass(/playing/);
  await popup.close();
  // The stems keep a single icon (𝄞): their names have no room for more.
  expect(await page.locator(".mx-sax-link").count()).toBe(0);
});
