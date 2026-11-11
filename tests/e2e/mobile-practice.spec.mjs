// The phone UI while practising: the song's lyrics beside the mixer, the 🔒
// that leaves only ▶/❚❚ and «next» answering a stray finger, and the 𝄞 that
// opens the score at the moment the song is at.

import { test, expect } from "@playwright/test";
import { JOB_ID } from "./helpers.mjs";

const LYRICS = {
  v: 1,
  source: "lrclib",
  track: "Fixture Song",
  artist: "Fixture Band",
  album: "Studio",
  duration: 6,
  synced: "[00:00.50] Line one\n[00:02.00] Line two\n[00:04.00] Line three",
  plain: "Line one\nLine two\nLine three",
  instrumental: false,
  lrclib_id: 301,
  others: [],
};

async function openOnPhone(page, { lyrics = LYRICS } = {}) {
  // The fixture track as having lyrics, and these as its lyrics.
  await page.route(`**/api/jobs/${JOB_ID}`, async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    return route.fulfill({ response: res, json: { ...body, has_lyrics: !!lyrics } });
  });
  await page.route(`**/api/jobs/${JOB_ID}/lyrics`, (route) =>
    lyrics ? route.fulfill({ json: lyrics }) : route.fulfill({ status: 404, json: { detail: "no lyrics" } }),
  );
  await page.goto("/?ui=mobile", { waitUntil: "domcontentloaded" });
  await page.locator('[data-action="tab"][data-tab="library"]').first().click();
  await page.locator(`.track[data-id="${JOB_ID}"]`).first().waitFor({ timeout: 20000 });
  await page.locator(`.track[data-id="${JOB_ID}"]`).first().click();
  await expect(page.locator(".t-play")).toBeEnabled({ timeout: 20000 });
}

test("the lyrics: a strip under the transport and a «Letra» view, the line sung lit", async ({ page }) => {
  await openOnPhone(page);
  await expect(page.locator(".lyr-strip .lyr-now")).toHaveText("♪");
  await expect(page.locator(".lyr-strip .lyr-next")).toHaveText("Line one");
  await page.locator('.segmented [data-view="lyrics"]').click();
  await expect(page.locator(".lyr-line")).toHaveCount(3);
  // A tap on a line goes there; the strip and the view follow.
  await page.locator('.lyr-line[data-i="1"]').click();
  await expect(page.locator(".lyr-line.on")).toHaveText("Line two");
  await expect(page.locator(".lyr-strip .lyr-now")).toHaveText("Line two");
  await expect(page.locator(".lyr-strip .lyr-next")).toHaveText("Line three");
});

test("no lyrics: said so, with a button to look them up", async ({ page }) => {
  await openOnPhone(page, { lyrics: null });
  await expect(page.locator(".lyr-strip")).toHaveCount(0);
  await page.locator('.segmented [data-view="lyrics"]').click();
  await expect(page.locator('[data-action="lyrics-lookup"]')).toBeVisible();
});

test("🔒 locks everything but ▶/❚❚ and «next»; held down it unlocks", async ({ page }) => {
  await openOnPhone(page);
  const lock = page.locator("[data-lock]");
  await expect(lock).toBeVisible();
  await lock.click();
  await expect(lock).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".speed-slider")).toBeDisabled();
  // A mute, a tab, the score link: nothing happens.
  const mute = page.locator('[data-action="mute"]').first();
  await mute.click();
  await expect(mute).not.toHaveAttribute("style", /background/);
  await page.locator('[data-action="tab"][data-tab="library"]').first().click();
  await expect(page.locator(".t-play")).toBeVisible(); // still on the mixer
  // ▶/❚❚ still works.
  await page.locator(".t-play").click();
  await expect(page.locator(".t-play")).toHaveAttribute("data-playing", "true");
  await page.locator(".t-play").click();
  await expect(page.locator(".t-play")).toHaveAttribute("data-playing", "false");
  // A tap does not unlock (a stray finger); held down it does.
  await lock.click();
  await expect(lock).toHaveAttribute("aria-pressed", "true");
  const box = await lock.boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.waitForTimeout(900);
  await page.mouse.up();
  await expect(page.locator("[data-lock]")).toHaveAttribute("aria-pressed", "false");
  await expect(page.locator(".speed-slider")).toBeEnabled();
});

test("𝄞 opens the score at the moment the song is at, and the mixer stops", async ({ page, context }) => {
  await openOnPhone(page);
  const link = page.locator("a.ms-score").first();
  test.skip((await link.count()) === 0, "the fixture track has no stem with a score");
  await page.locator('.lyr-line[data-i="2"]').count(); // (lyrics view not needed)
  await page.locator(".t-play").click();
  await page.waitForTimeout(1200);
  const [popup] = await Promise.all([context.waitForEvent("page"), link.click()]);
  const t = Number(new URL(popup.url()).searchParams.get("t"));
  expect(t).toBeGreaterThan(0.5);
  await expect(page.locator(".t-play")).toHaveAttribute("data-playing", "false");
  await popup.close();
});
