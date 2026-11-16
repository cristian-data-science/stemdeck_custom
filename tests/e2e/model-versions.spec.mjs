// The same song separated with the other model is a second version beside
// the first, not a replacement, and every view says which model made it.
//
// Before, importing a link again with RoFormer replaced the Demucs track in
// the library (addTrackToLibrary dedups by source), so the two could never be
// compared. Now the dedup is by source AND model: the same model still
// replaces (a re-import), the other model adds a version.
//
// The extra jobs are added to the server's answer with page.route rather than
// to tests/e2e/seed.py, which every spec shares: one more row there would
// change what the others see.

import { test, expect } from "@playwright/test";

import {
  JOB_ID,
  SIBLING_JOB_ID,
  TRACK_TITLE,
  fixtureTrack,
  readCatalogState,
  seedCatalogState,
  stubUpdateCheck,
} from "./helpers.mjs";

const ROFORMER_ID = "e2e0r0f0a0e1";

/** The fixture and its sibling known to the library (no dedup on load), and
 *  the server reporting one more job of the same source, separated with
 *  `separator`. */
async function seedWithVersion(page, separator) {
  await seedCatalogState(page, {
    folders: [
      { id: "f-unsorted", name: "Unsorted", items: [JOB_ID, SIBLING_JOB_ID], color: null },
      { id: "trash", name: "Trash", items: [], color: null },
    ],
    tracks: {
      [JOB_ID]: fixtureTrack(JOB_ID, TRACK_TITLE),
      [SIBLING_JOB_ID]: { ...fixtureTrack(SIBLING_JOB_ID, TRACK_TITLE), status: "done" },
    },
  });
  await stubUpdateCheck(page);
  await page.route(/\/api\/jobs(\?.*)?$/, async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const res = await route.fetch();
    const jobs = await res.json();
    const base = jobs.find((j) => j.job_id === JOB_ID);
    jobs.push({ ...base, job_id: ROFORMER_ID, id: ROFORMER_ID, separator, title: TRACK_TITLE });
    await route.fulfill({ response: res, json: jobs });
  });
}

test("a version separated with the other model is added beside the first", async ({ page }) => {
  await seedWithVersion(page, "roformer");
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const added = page.locator(`.cat-item[data-id="${ROFORMER_ID}"]`).first();
  await expect(added).toBeVisible();
  await expect(page.locator(`.cat-item[data-id="${JOB_ID}"]`).first()).toBeVisible();
  // Each row says which model made it (the sync backfills the old ones).
  await expect(added.locator(".cat-sub")).toContainText("RoFormer");
  await expect(page.locator(`.cat-item[data-id="${JOB_ID}"] .cat-sub`).first()).toContainText("Demucs");
  const state = await readCatalogState(page);
  expect(Object.keys(state.tracks)).toEqual(expect.arrayContaining([JOB_ID, ROFORMER_ID]));
  expect(state.tracks[ROFORMER_ID].separator).toBe("roformer");
});

test("the same model still replaces: a re-import of the same version", async ({ page }) => {
  await seedWithVersion(page, "demucs");
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.locator(`.cat-item[data-id="${ROFORMER_ID}"]`).first()).toBeVisible();
  await page.waitForTimeout(300);
  const state = await readCatalogState(page);
  const ids = Object.keys(state.tracks);
  expect(ids).toContain(ROFORMER_ID);
  // One of the two Demucs tracks of this source was taken over by it.
  expect(ids.filter((id) => id === JOB_ID || id === SIBLING_JOB_ID).length).toBe(1);
});

test("the open track says which model separated it", async ({ page }) => {
  await seedWithVersion(page, "roformer");
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const row = page.locator(`.cat-item[data-id="${JOB_ID}"]`).first();
  await expect(row).toBeVisible();
  await row.click();
  // On its row (highlighted, always on screen) and in the now-playing line.
  await expect(row.locator(".cat-sub")).toContainText("Demucs");
  await expect(page.locator("#track-separator")).toHaveText(/Demucs/);
});

test("a song with one version shows no model on its row", async ({ page }) => {
  await seedCatalogState(page, {
    folders: [
      { id: "f-unsorted", name: "Unsorted", items: [JOB_ID], color: null },
      { id: "trash", name: "Trash", items: [], color: null },
    ],
    tracks: { [JOB_ID]: { ...fixtureTrack(JOB_ID, TRACK_TITLE), sourceUrl: "local:only-one" } },
  });
  await stubUpdateCheck(page);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  const row = page.locator(`.cat-item[data-id="${JOB_ID}"]`).first();
  await expect(row).toBeVisible();
  const sub = row.locator(".cat-sub");
  expect(await sub.textContent()).not.toContain("Demucs");
  // Opened, its row says it.
  await row.click();
  await expect(sub).toContainText("Demucs");
});
