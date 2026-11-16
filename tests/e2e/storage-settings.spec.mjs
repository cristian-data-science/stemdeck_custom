// Settings › Storage: where the songs are, what they take on disk by kind,
// what Pianoteq makes in the background, and cleaning what is made again.
//
// The real /api/storage answers for the seeded song (its stems); the cleaning
// is checked against a stubbed answer with Pianoteq renders, since the e2e
// backend has no Pianoteq (tests/test_score_api.py covers the server side).

import { test, expect } from "@playwright/test";
import { JOB_ID, seedLibrary } from "./helpers.mjs";

async function openStorage(page) {
  await seedLibrary(page);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.locator("#settingsBtn").click();
  await page.locator('.settings-tab[data-tab="storage"]').click();
}

test("shows the folder, the disk and each song's size from the server", async ({ page }) => {
  await openStorage(page);
  const body = page.locator(".settings-storage-body");
  await expect(body.locator(".settings-logs-path").first()).not.toBeEmpty();
  await expect(body).toContainText(/StemDeck/);
  const row = body.locator(`.settings-storage-song[data-job="${JOB_ID}"]`);
  await expect(row).toBeVisible();
  await row.locator("summary").click();
  await expect(row.locator(".kind-stems")).toBeVisible();
  // Nothing of Pianoteq to clean: the buttons say 0 B and are off.
  await expect(body.locator('.settings-storage-actions [data-clean="slow"]').first()).toBeDisabled();
});

test("cleaning asks a second click, says what it freed, and the background choice is kept", async ({ page }) => {
  const GB = 1e9;
  const answer = {
    path: "C:/stems",
    total: 3 * GB,
    disk: { total: 500 * GB, free: 100 * GB, used: 400 * GB },
    background: "all",
    totals: { stems: GB, pt_main: 0.2 * GB, pt_slow: 1.5 * GB, pt_hands: 0.3 * GB },
    jobs: [{ id: JOB_ID, title: "Song", path: "C:/stems/x", total: 3 * GB, parts: { stems: GB, pt_main: 0.2 * GB, pt_slow: 1.5 * GB, pt_hands: 0.3 * GB } }],
  };
  const cleans = [];
  const puts = [];
  await page.route("**/api/storage", (r) => r.fulfill({ json: answer }));
  await page.route("**/api/storage/clean", (r) => {
    cleans.push(r.request().postDataJSON());
    return r.fulfill({ json: { files: 9, bytes: 1.5 * GB } });
  });
  await page.route("**/api/storage/background", (r) => {
    puts.push(r.request().postDataJSON());
    return r.fulfill({ json: { background: r.request().postDataJSON().value } });
  });
  await openStorage(page);
  const body = page.locator(".settings-storage-body");
  await expect(body).toContainText("100 GB");
  const slow = body.locator('.settings-storage-actions [data-clean="slow"]').first();
  await expect(slow).toContainText("1.5 GB");
  await slow.click();
  expect(cleans).toEqual([]); // the first click only asks
  await expect(slow).toHaveClass(/armed/);
  await slow.click();
  await expect.poll(() => cleans).toEqual([{ what: "slow", jobs: null }]);
  await expect(page.locator(".settings-storage-msg")).toContainText("1.5 GB");
  // Slow renders still made in the background: said, so they do not come back unexpectedly.
  await expect(page.locator(".settings-storage-msg")).toContainText(/background|segundo plano/);
  // One song alone.
  await body.locator(`.settings-storage-song[data-job="${JOB_ID}"] summary`).click();
  const one = body.locator(`.settings-storage-song[data-job="${JOB_ID}"] [data-clean="pianoteq"]`);
  await one.click();
  await one.click();
  await expect.poll(() => cleans.at(-1)).toEqual({ what: "pianoteq", jobs: [JOB_ID] });
  await body.locator(".set-pianoteq-background").selectOption("hands");
  await expect.poll(() => puts).toEqual([{ value: "hands" }]);
});
