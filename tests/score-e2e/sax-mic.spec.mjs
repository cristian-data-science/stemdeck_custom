// «🎤 Practicar» in «🎷 Saxo», with Chromium's fake microphone playing a
// steady A440 (written to a WAV here): the page hears it as A4, judges it
// against the note sounding, and «Esperarme» stops the song on a note that
// is not played.
import { test, expect } from "@playwright/test";
import { writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

function toneWav(hz, seconds = 6, sr = 48000) {
  const n = sr * seconds;
  const buf = Buffer.alloc(44 + n * 2);
  buf.write("RIFF", 0); buf.writeUInt32LE(36 + n * 2, 4); buf.write("WAVEfmt ", 8); buf.writeUInt32LE(16, 16);
  buf.writeUInt16LE(1, 20); buf.writeUInt16LE(1, 22); buf.writeUInt32LE(sr, 24); buf.writeUInt32LE(sr * 2, 28);
  buf.writeUInt16LE(2, 32); buf.writeUInt16LE(16, 34); buf.write("data", 36); buf.writeUInt32LE(n * 2, 40);
  for (let i = 0; i < n; i++) {
    let v = 0;
    for (let k = 1; k <= 6; k++) v += Math.sin((2 * Math.PI * hz * k * i) / sr) / k;
    buf.writeInt16LE(Math.round(v * 0.25 * 32767), 44 + i * 2);
  }
  const file = join(mkdtempSync(join(tmpdir(), "sax-mic-")), "a440.wav");
  writeFileSync(file, buf);
  return file;
}

const WAV = toneWav(440);
test.use({
  launchOptions: {
    args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", `--use-file-for-fake-audio-capture=${WAV}`],
  },
});

test("🎤 Practicar: the microphone heard as A4, judged against the line, «Esperarme» waits", async ({ page, context }) => {
  await context.grantPermissions(["microphone"]);
  await page.goto("/sax/?job=5c0de0000001&stems=piano");
  await page.waitForFunction(() => window.__sax?.notes?.length > 0 && document.querySelector("#sx-audio").readyState >= 1);
  await page.locator("#sx-view").selectOption("concert"); // the names as they sound: A4 is La4
  await page.locator("#sx-mic").click();
  await expect(page.locator("#sx-mic")).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("#sx-you")).toBeVisible();
  await expect.poll(() => page.evaluate(() => window.__sax && document.querySelector("#sx-you-text").textContent), { timeout: 15_000 }).toContain("La4");
  // The note asked for, against it: on an A4 it is right; elsewhere, how far.
  const atA = await page.evaluate(() => { const n = window.__sax.notes.find((x) => x.midi === 69 && x.end - x.start > 0.3); return n ? (n.start + n.end) / 2 : null; });
  if (atA != null) {
    await page.evaluate((t) => { document.querySelector("#sx-audio").currentTime = t; }, atA);
    await expect.poll(() => page.locator("#sx-you-text").textContent(), { timeout: 10_000 }).toContain("✓");
  }
  // «Esperarme»: playing on, the first note that is not an A stops the song.
  await page.locator("#sx-wait").click();
  const notA = await page.evaluate(() => { const n = window.__sax.notes.find((x) => x.midi !== 69 && x.start > 1); return n.start; });
  await page.evaluate((t) => { document.querySelector("#sx-audio").currentTime = t - 0.4; }, notA);
  await page.locator("#sx-play").click();
  await expect.poll(() => page.evaluate(() => !!window.__saxPractice.waiting), { timeout: 10_000 }).toBe(true);
  expect(await page.evaluate(() => document.querySelector("#sx-audio").paused)).toBe(true);
  // Off: the song goes on.
  await page.locator("#sx-wait").click();
  await expect.poll(() => page.evaluate(() => document.querySelector("#sx-audio").paused)).toBe(false);
  await expect(page.locator("#sx-score")).toContainText("Aciertos");
});
