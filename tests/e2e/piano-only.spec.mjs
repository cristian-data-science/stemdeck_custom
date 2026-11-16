// A new link asks what it is: «Solo piano» skips the separation (the server
// makes its one stem "piano" the audio itself and goes straight to the score
// and the Pianoteq piano), «Canción completa» separates it as always.
//
// The POST is stubbed: what is checked is what the page asks the server for,
// and the row it puts in the library. tests/test_piano_only.py covers the
// server side.
import { test, expect } from "@playwright/test";

import {
  SIBLING_JOB_ID,
  SIBLING_TITLE,
  fixtureTrack,
  readCatalogState,
  seedCatalogState,
  stubUpdateCheck,
} from "./helpers.mjs";

const URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ";
const NEW_ID = "e2e0b1a2c3d4";

async function openWithLink(page) {
  await seedCatalogState(page, {
    folders: [
      { id: "f-unsorted", name: "Unsorted", items: [SIBLING_JOB_ID], color: null },
      { id: "trash", name: "Trash", items: [], color: null },
    ],
    tracks: { [SIBLING_JOB_ID]: fixtureTrack(SIBLING_JOB_ID, SIBLING_TITLE) },
  });
  await stubUpdateCheck(page);
  const sent = [];
  await page.route("**/api/jobs", (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    sent.push(route.request().postDataJSON());
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ job_id: NEW_ID }) });
  });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.locator(".cat-item").first().waitFor({ timeout: 20000 });
  await page.locator("#url").fill(URL);
  await page.locator("#submit").click();
  await expect(page.locator(".audio-kind-confirm")).toBeVisible();
  return sent;
}

test("a solo piano link is imported without separation", async ({ page }) => {
  const sent = await openWithLink(page);
  await page.locator(".audio-kind-piano").click();
  await expect.poll(() => sent.length, { timeout: 10000 }).toBe(1);
  expect(sent[0]).toMatchObject({ url: URL, piano_only: true, stems: ["piano"], separator: "none" });
  await expect(page.locator(".audio-kind-confirm")).toHaveCount(0);
  // Its row says what it is (a version of its own beside a separated one).
  await expect.poll(async () => (await readCatalogState(page))?.tracks?.[NEW_ID]?.separator, { timeout: 10000 }).toBe("none");
  expect((await readCatalogState(page)).tracks[NEW_ID].stems).toEqual(["piano"]);
  // And the answer is the one offered first next time.
  expect(await page.evaluate(() => localStorage.getItem("stemdeck.importKind"))).toBe("piano");
});

test("a full song is separated as always", async ({ page }) => {
  const sent = await openWithLink(page);
  await page.locator(".audio-kind-song").click();
  await expect.poll(() => sent.length, { timeout: 10000 }).toBe(1);
  expect(sent[0].piano_only).toBe(false);
  expect(sent[0].stems.length).toBeGreaterThan(1);
  expect(sent[0].separator).not.toBe("none");
});

test("closing the question imports nothing", async ({ page }) => {
  const sent = await openWithLink(page);
  await page.keyboard.press("Escape");
  await expect(page.locator(".audio-kind-confirm")).toHaveCount(0);
  await page.waitForTimeout(500);
  expect(sent).toEqual([]);
  // The link stays, and the button is usable again.
  await expect(page.locator("#url")).toHaveValue(URL);
  await expect(page.locator("#submit")).toBeEnabled();
});
