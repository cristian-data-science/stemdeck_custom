// The score view in a real browser: engraving, labels, chords, following the
// audio, and edits that persist. The fixture (seed.py) is the calibration
// piece transcribed exactly, so every expected value is known.
import { expect, test } from "@playwright/test";

const JOB = "5c0de0000001";
const API = `/api/jobs/${JOB}/score/piano`;
const PAGE = `/score/?job=${JOB}&stem=piano`;
const EXPECTED_CHORDS = ["Fa", "Do", "Fa", "Si♭", "Do", "Rem", "La/Mi", "Do7", "Fa"];
const N_NOTES = 59;

async function resetServer(request) {
  await request.delete(`${API}/notes`);
  await request.put(`${API}/settings`, {
    // Fixed split: these tests check where a note lands relative to it. The
    // automatic hand following is covered in tests/test_score_engrave.py.
    data: { grid: "16t", split: 60, tempo: "normal", chord_rate: "half", chords: true, names: "solfege", hands: "split", key: "auto", meter: "auto", pulse: "auto", bar_shift: 0 },
  });
}

// Note names are off by default; most tests read or click the pills, so they
// open the page with names on (once: a reload keeps what the test chose).
async function open(page, { names = true } = {}) {
  await page.addInitScript((on) => {
    if (sessionStorage.getItem("e2e.seeded")) return;
    sessionStorage.setItem("e2e.seeded", "1");
    localStorage.removeItem("stemdeck.score.view");
    if (on) localStorage.setItem("stemdeck.score.view", JSON.stringify({ noteNames: true }));
  }, names);
  await page.goto(PAGE);
  await expect(page.locator("#sc-score g.note").first()).toBeVisible();
  await page.waitForFunction(() => window.__score?.ctx?.timeline?.length > 0);
}

const notes = (page) => page.evaluate(() => window.__score.notes.map((n) => ({ ...n, heads: undefined })));
const savedOk = (page) => expect(page.locator("#sc-save")).toContainText("Guardado");

async function clickNote(page, predicate) {
  const id = await page.evaluate((src) => {
    const fn = new Function("n", `return (${src})(n)`);
    return window.__score.notes.find((n) => fn(n)).id;
  }, predicate.toString());
  await page.locator(`#sc-score g.note[id="${id}"] .sd-pill`).click();
  return id;
}

test.beforeEach(async ({ request }) => {
  await resetServer(request);
});

test("grand staff with G and F clefs, one labelled pill per note, chords above", async ({ page }) => {
  await open(page);
  await expect(page.locator("#sc-bpm")).toHaveText("90");
  await expect(page.locator("#sc-meter")).toHaveText("4/4");
  await expect(page.locator("#sc-key")).toHaveText("Fa mayor");
  await expect(page.locator("#sc-count")).toHaveText(String(N_NOTES));
  const shapes = await page.locator("#sc-score g.clef use").evaluateAll((els) =>
    els.map((e) => e.getAttribute("href") || e.getAttribute("xlink:href")),
  );
  // SMuFL gClef E050, fClef E062.
  expect(shapes.some((h) => h.includes("E050"))).toBeTruthy();
  expect(shapes.some((h) => h.includes("E062"))).toBeTruthy();
  const drawn = await page.locator("#sc-score g.note").count();
  await expect(page.locator("#sc-score .sd-pill")).toHaveCount(drawn);
  const ids = await page.locator("#sc-score g.note").evaluateAll((els) => [...new Set(els.map((e) => e.id.split("-")[0]))]);
  expect(ids.length).toBe(N_NOTES);
  // Every pill says its own note's name.
  // With its accidental: a key-signature flat is not drawn next to the note.
  const mismatches = await page.evaluate(() => {
    const SOL = { C: "do", D: "re", E: "mi", F: "fa", G: "sol", A: "la", B: "si" };
    const ACC = { "-1": "♭", 1: "♯" };
    const byId = new Map(window.__score.notes.map((n) => [n.id, n]));
    return [...document.querySelectorAll("#sc-score g.note")]
      .map((el) => {
        const n = byId.get(el.id.split("-")[0]);
        return [el.id, el.querySelector(".sd-pill text")?.textContent, SOL[n?.letter] + (ACC[n?.alter] || "")];
      })
      .filter(([, got, want]) => got !== want);
  });
  expect(mismatches).toEqual([]);
  // Bar 1 of the treble reads fa sol la si, as the calibration sheet says.
  const bar1 = await page.evaluate(() =>
    window.__score.notes
      .filter((n) => n.measure === 1 && n.staff === 1)
      .sort((a, b) => a.start - b.start)
      .map((n) => window.__score.ctx.notes.get(n.id)[0].querySelector(".sd-pill text").textContent),
  );
  // B-flat is in F major's key signature: no flat by the note, so the pill says it.
  expect(bar1).toEqual(["fa", "sol", "la", "si♭"]);
  const chords = await page.evaluate(() => window.__score.data.chords.map((c) => c.text));
  expect(chords).toEqual(EXPECTED_CHORDS);
  await expect(page.locator("#sc-score g.harm")).toHaveCount(EXPECTED_CHORDS.length);
  // The calibration panel does not show on an ordinary track.
  await expect(page.locator("#sc-calib-check")).toBeHidden();
});

test("following: the notes sounding at t light up and the cursor advances", async ({ page }) => {
  await open(page);
  for (const t of [1.2, 6.1, 12.4, 15.5]) {
    const { lit, want } = await page.evaluate((time) => {
      window.__scoreFollow(time);
      const lit = [...document.querySelectorAll("#sc-score g.note.sd-playing")].map((e) => e.id.split("-")[0]);
      const want = window.__score.notes.filter((n) => n.start <= time && (n.draw_end ?? n.end) > time).map((n) => n.id);
      return { lit: [...new Set(lit)].sort(), want: want.sort() };
    }, t);
    expect(lit, `at ${t}s`).toEqual(want);
    expect(want.length).toBeGreaterThan(0);
  }
  const xs = await page.evaluate(() =>
    [1.1, 1.5, 2.0, 2.4].map((t) => {
      window.__scoreFollow(t);
      return Number(document.querySelector(".sd-cursor").getAttribute("x"));
    }),
  );
  for (let i = 1; i < xs.length; i++) expect(xs[i]).toBeGreaterThan(xs[i - 1]);
});

test("real playback drives the follow loop", async ({ page }) => {
  await open(page);
  await page.evaluate(async () => {
    const a = document.getElementById("sc-audio");
    a.muted = true;
    a.currentTime = 4.5;
    await a.play();
  });
  await expect(page.locator("#sc-score g.note.sd-playing").first()).toBeVisible();
  await expect(page.locator("#sc-play")).toHaveText("❚❚");
  const t = await page.evaluate(() => document.getElementById("sc-audio").currentTime);
  expect(t).toBeGreaterThan(4.5);
});

test("delete persists across a reload, and Restaurar brings it back", async ({ page }) => {
  await open(page);
  const id = await clickNote(page, (n) => n.midi === 67 && n.staff === 1);
  await expect(page.locator("#sc-status")).toContainText("Sol4");
  await page.keyboard.press("Delete");
  await savedOk(page);
  await page.reload();
  await page.waitForFunction(() => window.__score?.notes?.length > 0);
  const after = await notes(page);
  expect(after.length).toBe(N_NOTES - 1);
  expect(after.some((n) => n.id === id)).toBeFalsy();
  await expect(page.locator(`#sc-score g.note[id="${id}"]`)).toHaveCount(0);
  await expect(page.locator("#sc-sub")).toContainText("editada");

  await page.locator("#sc-reset").click();
  await page.locator('#sc-confirm button[value="ok"]').click();
  await expect(page.locator("#sc-save")).toContainText("restaurado");
  expect((await notes(page)).length).toBe(N_NOTES);
});

test("pitch, octave, move, duration and hand edits, each saved", async ({ page }) => {
  await open(page);
  const id = await clickNote(page, (n) => n.midi === 67 && n.staff === 1);
  const get = async () => (await notes(page)).find((n) => n.id === id);
  const start0 = (await get()).q_start;

  await page.keyboard.press("ArrowUp");
  await savedOk(page);
  expect((await get()).midi).toBe(68);
  await page.keyboard.press("Control+ArrowDown");
  await savedOk(page);
  expect((await get()).midi).toBe(56);
  await expect.poll(async () => (await get()).staff).toBe(2); // below the split now

  await page.keyboard.press("h");
  await savedOk(page);
  expect((await get()).hand).toBe("R");
  expect((await get()).staff).toBe(1); // the override wins over the split

  await page.keyboard.press("ArrowRight");
  await savedOk(page);
  const moved = await get();
  expect(moved.q_start).toBeCloseTo(start0 + moved.step_sec, 3);

  const len0 = moved.q_end - moved.q_start;
  await page.keyboard.press("Shift+ArrowLeft");
  await savedOk(page);
  const shorter = await get();
  expect(shorter.q_end - shorter.q_start).toBeLessThan(len0);

  // All of it is on the server.
  const server = await (await page.request.get(API)).json();
  const s = server.notes.find((n) => n.id === id);
  expect([s.midi, s.hand]).toEqual([56, "R"]);
});

test("undo and redo, saved too", async ({ page }) => {
  await open(page);
  const id = await clickNote(page, (n) => n.midi === 72 && n.staff === 1);
  await page.keyboard.press("ArrowUp");
  await savedOk(page);
  await page.keyboard.press("Control+z");
  await savedOk(page);
  let server = await (await page.request.get(API)).json();
  expect(server.notes.find((n) => n.id === id).midi).toBe(72);
  await page.keyboard.press("Control+y");
  await savedOk(page);
  server = await (await page.request.get(API)).json();
  expect(server.notes.find((n) => n.id === id).midi).toBe(73);
});

test("area selection and bulk delete", async ({ page }) => {
  await open(page);
  // Select every note of bar 5 (the eighths) with a drag over its pills.
  const box = await page.evaluate(() => {
    const ids = window.__score.notes.filter((n) => n.measure === 5 && n.staff === 1).map((n) => n.id);
    const rects = ids.map((id) => window.__score.ctx.notes.get(id)[0].querySelector(".sd-pill").getBoundingClientRect());
    return {
      n: ids.length,
      l: Math.min(...rects.map((r) => r.left)) - 4,
      t: Math.min(...rects.map((r) => r.top)) - 4,
      r: Math.max(...rects.map((r) => r.right)) + 4,
      b: Math.max(...rects.map((r) => r.bottom)) + 4,
    };
  });
  // Start the drag on empty paper above the staff.
  await page.mouse.move(box.l, box.t - 30);
  await page.mouse.down();
  await page.mouse.move(box.r, box.b, { steps: 5 });
  await page.mouse.up();
  const selected = await page.evaluate(() => [...window.__score.selection]);
  expect(selected.length).toBe(box.n);
  await page.keyboard.press("Delete");
  await savedOk(page);
  expect((await notes(page)).length).toBe(N_NOTES - box.n);
});

test("chord: rename, persist, back to detected", async ({ page }) => {
  await open(page);
  await page.locator("#sc-score g.harm").first().click();
  await expect(page.locator("#sc-chord-dialog")).toBeVisible();
  await page.locator("#sc-chord-input").fill("Fa6");
  await page.keyboard.press("Enter");
  await expect(page.locator("#sc-save")).toContainText("Acorde guardado");
  await page.reload();
  await page.waitForFunction(() => window.__score?.data?.chords?.length > 0);
  expect(await page.evaluate(() => window.__score.data.chords[0].text)).toBe("Fa6");
  await expect(page.locator("#sc-score g.harm").first()).toContainText("Fa6");
  await page.locator("#sc-score g.harm").first().click();
  await page.locator('#sc-chord-dialog button[value="auto"]').click();
  await expect(page.locator("#sc-save")).toContainText("Acorde guardado");
  expect(await page.evaluate(() => window.__score.data.chords[0].text)).toBe("Fa");
});

test("note names: hidden by default, shown from the Nombres setting", async ({ page }) => {
  await open(page, { names: false });
  await expect(page.locator("#sc-names")).toHaveValue("none");
  await expect(page.locator("#sc-score .sd-pill")).toHaveCount(0);
  // Notes are still selectable without their names.
  const id = await page.evaluate(() => window.__score.notes[0].id);
  await page.locator(`#sc-score g.note[id="${id}"] .sd-hit`).first().click();
  await expect(page.locator(`#sc-score g.note[id="${id}"]`).first()).toHaveClass(/sd-selected/);
  await page.locator("#sc-names").selectOption("solfege");
  await expect(page.locator("#sc-score .sd-pill").first()).toBeVisible();
  await page.reload();
  await page.waitForFunction(() => window.__score?.data);
  await expect(page.locator("#sc-names")).toHaveValue("solfege");
  await expect(page.locator("#sc-score .sd-pill").first()).toBeVisible();
});

test("settings: letter names, hidden labels, hand split, persisted", async ({ page }) => {
  await open(page);
  await page.locator("#sc-names").selectOption("letters");
  await expect(page.locator("#sc-key")).toHaveText("F major");
  await expect(page.locator("#sc-score .sd-pill text").first()).toHaveText(/^[A-G][♭♯]?$/);
  expect(await page.evaluate(() => window.__score.data.chords.map((c) => c.text))).toEqual(
    ["F", "C", "F", "Bb", "C", "Dm", "A/E", "C7", "F"],
  );
  await page.locator("#sc-split").selectOption("48");
  await expect.poll(async () => (await notes(page)).filter((n) => n.midi === 48).every((n) => n.staff === 1)).toBeTruthy();
  await page.reload();
  await page.waitForFunction(() => window.__score?.data);
  await expect(page.locator("#sc-split")).toHaveValue("48");
  await page.locator("#sc-names").selectOption("none");
  await expect(page.locator("#sc-score .sd-pill")).toHaveCount(0);
  await page.locator("#sc-hands-select").selectOption("auto");
  await expect(page.locator("#sc-save")).toContainText("Guardado");
  await page.reload();
  await page.waitForFunction(() => window.__score?.data);
  await expect(page.locator("#sc-hands-select")).toHaveValue("auto");
});

test("clean-up previews in red, then deletes", async ({ page }) => {
  await open(page);
  await page.locator("#sc-clean-toggle").click();
  await page.locator("#sc-clean-dur").fill("300");
  await page.locator("#sc-clean-dur").dispatchEvent("input");
  const want = await page.evaluate(() => window.__score.notes.filter((n) => (n.end - n.start) * 1000 < 300).length);
  await expect(page.locator("#sc-clean-count")).toHaveText(String(want));
  expect(want).toBeGreaterThan(0);
  await expect(page.locator("#sc-score g.note.sd-doomed").first()).toBeVisible();
  await page.locator("#sc-clean-apply").click();
  await savedOk(page);
  expect((await notes(page)).length).toBe(N_NOTES - want);
});

test("exports download", async ({ request }) => {
  for (const [path, needle] of [
    [`${API}/export.mid`, "MThd"],
    [`${API}/export.musicxml`, "<score-partwise"],
  ]) {
    const r = await request.get(path);
    expect(r.ok()).toBeTruthy();
    expect((await r.body()).toString("latin1")).toContain(needle);
  }
});

test("landing lists the track and the page works without a job", async ({ page }) => {
  await page.goto("/score/");
  await expect(page.locator("#sc-joblist a")).toContainText("Score E2E");
  await expect(page.locator("#sc-make-calib")).toBeVisible();
});

test("no console errors on the score page", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  await open(page);
  await page.evaluate(() => window.__scoreFollow(3));
  expect(errors).toEqual([]);
});

test("the cursor flows: real playback never steps back or leaps", async ({ page }) => {
  await open(page);
  // Across the whole piece, at 50 ms steps: never back within a system.
  const sweep = await page.evaluate(() => {
    const ctx = window.__score.ctx;
    const end = Math.max(...window.__score.notes.map((n) => n.end));
    let prev = null;
    let back = 0;
    for (let t = 0; t < end; t += 0.05) {
      window.__scoreFollow(t);
      const x = Number(ctx.cursor.getAttribute("x"));
      if (prev && prev.sys === ctx.cursorSys && x < prev.x - 1) back++;
      prev = { x, sys: ctx.cursorSys };
    }
    return back;
  });
  expect(sweep).toBe(0);
  // Real audio for 3 s: the cursor moves every sample or so, smoothly.
  const steps = await page.evaluate(async () => {
    const a = document.getElementById("sc-audio");
    a.muted = true;
    a.currentTime = 1.0;
    await a.play();
    const ctx = window.__score.ctx;
    const xs = [];
    await new Promise((done) => {
      const id = setInterval(() => {
        xs.push([Number(ctx.cursor.getAttribute("x")), ctx.cursorSys]);
        if (xs.length >= 60) {
          clearInterval(id);
          done();
        }
      }, 50);
    });
    a.pause();
    const d = [];
    for (let i = 1; i < xs.length; i++) if (xs[i][1] === xs[i - 1][1]) d.push(xs[i][0] - xs[i - 1][0]);
    return d;
  });
  expect(steps.filter((d) => d < -1)).toEqual([]);
  const moving = steps.filter((d) => d > 0.5).length;
  expect(moving).toBeGreaterThan(steps.length * 0.6); // it flows, not stop-and-go
});

test("Pianoteq: plays the score rendered by Pianoteq, re-rendered after an edit", async ({ page, request }) => {
  const info = await (await request.get("/api/score/pianoteq")).json();
  test.skip(!info.available, "Pianoteq is not installed on this machine");
  test.setTimeout(120_000);
  await open(page);
  await expect(page.locator('#sc-source option[value="pianoteq"]')).not.toHaveAttribute("hidden", "");
  await page.locator("#sc-source").selectOption("pianoteq");
  await expect(page.locator("#sc-pt-wrap")).toBeVisible();
  await expect(page.locator("#sc-pt-preset")).toHaveValue(info.default);
  await expect(page.locator("#sc-pt-status")).toContainText("✓", { timeout: 60_000 });
  const first = await page.evaluate(() => document.querySelector("#sc-audio").src);
  expect(first).toContain("/pianoteq/audio/");
  // An edit makes it stale; a new render replaces it.
  await clickNote(page, (n) => n.midi === 65);
  await page.keyboard.press("ArrowUp");
  await savedOk(page);
  await expect.poll(() => page.evaluate(() => document.querySelector("#sc-audio").src), { timeout: 60_000 }).not.toBe(first);
  await expect(page.locator("#sc-pt-status")).toContainText("✓");
  // Back to the stem: the Pianoteq controls go away.
  await page.locator("#sc-source").selectOption("stem");
  await expect(page.locator("#sc-pt-wrap")).toBeHidden();
  expect(await page.evaluate(() => document.querySelector("#sc-audio").src)).toContain("/score/audio/");
});

test("pedal slider: 0 % by default, held notes, saved", async ({ page }) => {
  await open(page);
  await expect(page.locator("#sc-pedal")).toHaveValue("0");
  await expect(page.locator("#sc-pedal-val")).toHaveText("0 %");
  // The server says where the pedal would stop each note.
  expect(await page.evaluate(() => window.__score.data.notes.some((n) => n.pedal_end != null))).toBe(true);
  await page.locator("#sc-pedal").fill("60");
  await expect(page.locator("#sc-pedal-val")).toHaveText("60 %");
  await expect(page.locator("#sc-save")).toContainText("Guardado");
  expect(await page.evaluate(() => window.__score.data.settings.pedal)).toBe(60);
  await page.reload();
  await page.waitForFunction(() => window.__score?.data);
  await expect(page.locator("#sc-pedal")).toHaveValue("60");
  await expect(page.locator("#sc-pedal-wrap")).toHaveAttribute("title", /100 %/);
});

test("speed slider: slower playback, pitch kept, remembered", async ({ page }) => {
  await open(page);
  await expect(page.locator("#sc-speed")).toHaveValue("100");
  await page.locator("#sc-speed").fill("40");
  await expect(page.locator("#sc-speed-val")).toHaveText("40 %");
  const audio = () => page.evaluate(() => ({ rate: document.querySelector("#sc-audio").playbackRate, keep: document.querySelector("#sc-audio").preservesPitch }));
  expect(await audio()).toEqual({ rate: 0.4, keep: true });
  // It really plays slower: ~0.4 s of song per second.
  await page.evaluate(() => { const a = document.querySelector("#sc-audio"); a.muted = true; return a.play(); });
  const t0 = await page.evaluate(() => document.querySelector("#sc-audio").currentTime);
  await page.waitForTimeout(1500);
  const t1 = await page.evaluate(() => document.querySelector("#sc-audio").currentTime);
  await page.evaluate(() => document.querySelector("#sc-audio").pause());
  expect(t1 - t0).toBeGreaterThan(0.4);
  expect(t1 - t0).toBeLessThan(0.9);
  await page.reload();
  await page.waitForFunction(() => window.__score?.data);
  await expect(page.locator("#sc-speed")).toHaveValue("40");
  expect((await audio()).rate).toBe(0.4);
});

test("piano view: falling notes at the same point, options remembered, back to the score", async ({ page }) => {
  await open(page);
  await page.waitForFunction(() => document.querySelector("#sc-audio").readyState >= 1);
  await page.evaluate(() => { document.querySelector("#sc-audio").currentTime = 3.2; });
  await page.locator("#sc-view-toggle").click();
  await expect(page.locator("#sc-fall")).toBeVisible();
  await expect(page.locator(".sc-tools")).toBeHidden();
  await expect(page.locator("#sc-scroll")).toBeHidden();
  await expect(page.locator("#sc-view-toggle")).toHaveText("𝄞 Partitura");
  // Same point of the song, and notes drawn on the canvas (amber bars by default).
  expect(await page.evaluate(() => document.querySelector("#sc-audio").currentTime)).toBeCloseTo(3.2, 1);
  const amber = () => page.evaluate(() => {
    const c = document.querySelector(".sc-fall-canvas");
    const d = c.getContext("2d").getImageData(0, 0, c.width, c.height).data;
    let n = 0;
    for (let i = 0; i < d.length; i += 4) if (d[i] > 230 && d[i + 1] > 160 && d[i + 1] < 200 && d[i + 2] < 60) n++;
    return n;
  });
  await expect.poll(amber).toBeGreaterThan(500);
  // By hand: two colours and a legend; the 88 keys; names off. Remembered.
  await page.locator("#sc-fall-colors").selectOption("hands");
  await expect(page.locator("#sc-fall-legend")).toBeVisible();
  await expect.poll(amber).toBe(0);
  await page.locator("#sc-fall-keys").selectOption("full");
  await page.reload();
  await page.waitForFunction(() => window.__score?.data);
  await expect(page.locator("#sc-fall")).toBeVisible();
  await expect(page.locator("#sc-fall-keys")).toHaveValue("full");
  await expect(page.locator("#sc-fall-colors")).toHaveValue("hands");
  // Back to the score.
  await page.locator("#sc-view-toggle").click();
  await expect(page.locator("#sc-scroll")).toBeVisible();
  await expect(page.locator("#sc-fall")).toBeHidden();
  await expect(page.locator("#sc-view-toggle")).toHaveText("🎹 Piano");
});

test("jump buttons: back and forward 5, 10 and 30 s, within the song", async ({ page }) => {
  await open(page);
  await page.waitForFunction(() => document.querySelector("#sc-audio").readyState >= 1);
  const now = () => page.evaluate(() => document.querySelector("#sc-audio").currentTime);
  await page.evaluate(() => { document.querySelector("#sc-audio").currentTime = 12; });
  await page.locator('[data-jump="-10"]').click();
  expect(await now()).toBeCloseTo(2, 1);
  await page.locator('[data-jump="5"]').click();
  expect(await now()).toBeCloseTo(7, 1);
  await page.locator('[data-jump="10"]').click();
  expect(await now()).toBeCloseTo(17, 1);
  await page.locator('[data-jump="-5"]').click();
  expect(await now()).toBeCloseTo(12, 1);
  await page.locator('[data-jump="-30"]').click();
  expect(await now()).toBe(0);
  await page.locator('[data-jump="30"]').click();
  const dur = await page.evaluate(() => document.querySelector("#sc-audio").duration);
  // Clamped to the end (Chrome lands an mp3 seek this close to the end up to
  // ~0.1 s early).
  expect(Math.abs((await now()) - Math.min(30, dur - 0.05))).toBeLessThan(0.15);
});

test("sincronía holds the picture behind the audio by the set ms, per device", async ({ page }) => {
  await open(page);
  await page.waitForFunction(() => document.querySelector("#sc-audio").readyState >= 1);
  await page.locator("#sc-view-toggle").click();
  await page.evaluate(() => { document.querySelector("#sc-audio").currentTime = 5; });
  await expect.poll(() => page.evaluate(() => window.__fall.lastT)).toBeCloseTo(5, 2);
  await page.locator("#sc-sync").fill("200");
  await expect(page.locator("#sc-sync-val")).toHaveText("200 ms");
  await expect.poll(() => page.evaluate(() => window.__fall.lastT)).toBeCloseTo(4.8, 2);
  // The time shown and the sound are not delayed: only the picture.
  await expect(page.locator("#sc-now")).toHaveText("0:05");
  await page.reload();
  await page.waitForFunction(() => window.__score?.data);
  await expect(page.locator("#sc-sync")).toHaveValue("200");
});

test("score: drag a note later in time and up the scale; saved", async ({ page }) => {
  await open(page);
  const pick = await page.evaluate(() => {
    const n = window.__score.notes.find((x) => x.measure === 2 && x.staff === 1);
    const el = window.__score.ctx.notes.get(n.id)[0];
    el.scrollIntoView({ block: "center" });
    const head = el.querySelector(".notehead").getBoundingClientRect();
    const sys = el.closest("g.system");
    const pts = window.__score.ctx.timeline.filter((p) => p.sys === sys);
    const a = pts[0], b = pts[pts.length - 1];
    const scale = el.parentNode.getScreenCTM().a;
    return { id: n.id, midi: n.midi, q: n.q_start, step: n.step_sec, key: window.__score.data.key.id,
      x: head.x + head.width / 2, y: head.y + head.height / 2, stepPx: ((b.x - a.x) / (b.t - a.t)) * n.step_sec * scale, half: head.height / 2 };
  });
  await page.mouse.move(pick.x, pick.y);
  await page.mouse.down();
  for (let i = 1; i <= 6; i++) await page.mouse.move(pick.x + (2 * pick.stepPx * i) / 6, pick.y - (2 * pick.half * i) / 6);
  await page.mouse.up();
  await savedOk(page);
  const moved = await page.evaluate((id) => window.__score.notes.find((n) => n.id === id), pick.id);
  expect(moved.q_start).toBeCloseTo(pick.q + 2 * pick.step, 2);
  const { scaleShift } = await import("../../static/js/score/model.js");
  expect(moved.midi).toBe(scaleShift(pick.midi, 2, pick.key));
});

test("piano view: tap a falling note, delete it with 🗑, drag another one key up", async ({ page }) => {
  await open(page);
  await page.waitForFunction(() => document.querySelector("#sc-audio").readyState >= 1);
  await page.locator("#sc-view-toggle").click();
  await page.evaluate(() => { document.querySelector("#sc-audio").currentTime = 2.0; });
  await expect.poll(() => page.evaluate(() => window.__fall.hits.length)).toBeGreaterThan(2);
  await page.waitForTimeout(400); // the piano settles its height first
  const bar = (i) => page.evaluate((i) => {
    const r = document.querySelector(".sc-fall-canvas").getBoundingClientRect();
    const h = [...window.__fall.hits].sort((a, b) => b.h - a.h)[i];
    // Inside the visible part: a long bar may start above the top edge.
    return { id: h.id, x: r.left + h.x + h.w / 2, y: r.top + Math.max(h.y, 0) + 10 };
  }, i);
  const count = () => page.evaluate(() => window.__score.notes.length);
  const before = await count();
  const a = await bar(0);
  await page.mouse.click(a.x, a.y);
  await expect(page.locator("#sc-editbar")).toBeVisible();
  await expect(page.locator("#sc-editbar-n")).toHaveText("1 nota");
  await page.locator("#sc-edit-del").click();
  await savedOk(page);
  expect(await count()).toBe(before - 1);
  expect(await page.evaluate((id) => window.__score.notes.some((n) => n.id === id), a.id)).toBe(false);
  await expect(page.locator("#sc-editbar")).toBeHidden();
  // Drag one bar a key to the right: one semitone up, same time.
  const b = await bar(0);
  const was = await page.evaluate((id) => window.__score.notes.find((n) => n.id === id), b.id);
  const per = await page.evaluate(() => window.__fall.scale().perSemitone);
  await page.mouse.move(b.x, b.y);
  await page.mouse.down();
  for (let i = 1; i <= 5; i++) await page.mouse.move(b.x + (per * i) / 5, b.y);
  await page.mouse.up();
  await savedOk(page);
  const now = await page.evaluate((id) => window.__score.notes.find((n) => n.id === id), b.id);
  expect(now.midi).toBe(was.midi + 1);
  expect(now.start).toBeCloseTo(was.start, 2);
});

test("piano view: drag a note's bottom edge down onto the note before on its key: one note", async ({ page }) => {
  await open(page);
  await page.waitForFunction(() => document.querySelector("#sc-audio").readyState >= 1);
  // Two notes in a row on one key, the second starting soon after the first ends.
  const pair = await page.evaluate(() => {
    const ns = [...window.__score.notes].sort((a, b) => a.start - b.start);
    for (const b of ns) {
      const a = ns.filter((n) => n.midi === b.midi && n.start < b.start).pop();
      if (a && b.start - a.end < 0.4 && b.start - a.start < 2) return { a: a.id, b: b.id, at: a.start, end: Math.max(a.end, b.end) };
    }
    return null;
  });
  expect(pair).not.toBeNull();
  await page.locator("#sc-view-toggle").click();
  await page.evaluate((t) => { document.querySelector("#sc-audio").currentTime = t; }, Math.max(0, pair.at - 0.3));
  await expect.poll(() => page.evaluate((id) => window.__fall.hits.some((h) => h.id === id), pair.b)).toBe(true);
  await page.waitForTimeout(400); // the piano settles its height first
  const edge = await page.evaluate((id) => {
    const r = document.querySelector(".sc-fall-canvas").getBoundingClientRect();
    const h = window.__fall.hits.find((x) => x.id === id);
    return { x: r.left + h.x + h.w / 2, y: r.top + h.y + h.h - 1 };
  }, pair.b);
  const count = () => page.evaluate(() => window.__score.notes.length);
  const before = await count();
  await page.mouse.move(edge.x, edge.y);
  expect(await page.evaluate(() => document.querySelector("#sc-fall").style.cursor)).toBe("ns-resize");
  // A click on the edge alone never joins.
  await page.mouse.down();
  await page.mouse.up();
  expect(await count()).toBe(before);
  await page.mouse.move(edge.x, edge.y);
  await page.mouse.down();
  for (let i = 1; i <= 6; i++) await page.mouse.move(edge.x, edge.y + i * 15);
  await expect(page.locator("#sc-status")).toContainText("unir");
  await page.mouse.up();
  await savedOk(page);
  expect(await count()).toBe(before - 1);
  const one = await page.evaluate((p) => ({
    a: window.__score.notes.find((n) => n.id === p.a),
    b: window.__score.notes.some((n) => n.id === p.b),
  }), pair);
  expect(one.b).toBe(false);
  expect(one.a.end).toBeCloseTo(pair.end, 3);
  // Still whole after the server's answer (the score cuts a note where its
  // hand plays next; a joined one is held), and not among the deleted notes.
  expect(one.a.held).toBe(true);
  const { soundEnd } = await import("../../static/js/score/model.js");
  expect(soundEnd(one.a)).toBeCloseTo(pair.end, 3);
  expect(await page.evaluate((id) => window.__score.data.trash.some((t) => t.id === id), pair.b)).toBe(false);
  // And the score has one note there too; undo brings both back.
  await page.locator("#sc-view-toggle").click();
  await expect(page.locator(`#sc-score g.note[id*="${pair.b}"]`)).toHaveCount(0);
  await page.locator("#sc-undo").click();
  await savedOk(page);
  expect(await count()).toBe(before);
});

test("＋ Nota in the piano view: a tap on a key's lane adds a note there, dragged up it lasts longer", async ({ page }) => {
  await open(page);
  await page.waitForFunction(() => document.querySelector("#sc-audio").readyState >= 1);
  await page.locator("#sc-view-toggle").click();
  await page.evaluate(() => { document.querySelector("#sc-audio").currentTime = 2.0; });
  await expect.poll(() => page.evaluate(() => window.__fall.hits.length)).toBeGreaterThan(0);
  await page.waitForTimeout(400);
  const before = await page.evaluate(() => window.__score.notes.length);
  await page.locator("#sc-fall-add").click();
  await expect(page.locator("#sc-fall-add")).toHaveAttribute("aria-pressed", "true");
  // A point a third of the way up the lane, over some key.
  const at = await page.evaluate(() => {
    const r = document.querySelector(".sc-fall-canvas").getBoundingClientRect();
    const f = window.__fall;
    const fallH = f.size.h - f.keyHeight();
    const x = r.left + f.size.w * 0.55;
    const y = r.top + fallH * 0.75;
    return { x, y, p: f.pointAt(x, y), up: f.pointAt(x, r.top + fallH * 0.45) };
  });
  expect(at.p).not.toBeNull();
  await page.mouse.move(at.x, at.y);
  await page.mouse.down();
  for (let i = 1; i <= 5; i++) await page.mouse.move(at.x, at.y - i * 30);
  await page.mouse.up();
  await savedOk(page);
  expect(await page.evaluate(() => window.__score.notes.length)).toBe(before + 1);
  const added = await page.evaluate(() => window.__score.notes.find((n) => n.id.startsWith("nu")));
  expect(added.midi).toBe(at.p.midi);
  expect(added.held).toBe(true);
  expect(added.end - added.start).toBeGreaterThan(0.3);
  await expect(page.locator("#sc-editbar")).toBeVisible(); // selected: 🗑 takes it away again
  // Still adding until N, Esc or the button.
  await page.keyboard.press("Escape");
  await expect(page.locator("#sc-fall-add")).toHaveAttribute("aria-pressed", "false");
  // Undo takes it away.
  await page.keyboard.press("Control+z");
  await savedOk(page);
  expect(await page.evaluate(() => window.__score.notes.length)).toBe(before);
});

test("＋ Nota on the score: a tap on a line of a staff adds that note, in the key, on its staff", async ({ page }) => {
  await open(page);
  const before = await page.evaluate(() => window.__score.notes.length);
  await page.locator("#sc-add").click();
  // The middle line of the treble staff of the second measure.
  const at = await page.evaluate(() => {
    const m = document.querySelectorAll("#sc-score g.measure")[1];
    const st = m.querySelector(":scope > g.staff");
    const lines = [...st.querySelectorAll(":scope > path")].slice(0, 5);
    const mid = lines.map((l) => l.getBoundingClientRect()).sort((a, b) => a.top - b.top)[2];
    const r = m.getBoundingClientRect();
    return { x: r.left + r.width * 0.5, y: mid.top + mid.height / 2 };
  });
  await page.mouse.click(at.x, at.y);
  await savedOk(page);
  expect(await page.evaluate(() => window.__score.notes.length)).toBe(before + 1);
  const added = await page.evaluate(() => window.__score.notes.find((n) => n.id.startsWith("nu")));
  const key = await page.evaluate(() => window.__score.data.key.id);
  const { pitchOnStaff } = await import("../../static/js/score/model.js");
  expect(added.midi).toBe(pitchOnStaff(1, 4, key)); // B4, or B♭4 in a flat key
  expect(added.hand).toBe("R");
  await expect.poll(() => page.evaluate((id) => window.__score.notes.find((n) => n.id === id)?.staff, added.id)).toBe(1);
  await expect(page.locator(`#sc-score g.note[id*="${added.id}"]`).first()).toBeVisible();
  await page.keyboard.press("n"); // done adding
  await expect(page.locator("#sc-add")).toHaveAttribute("aria-pressed", "false");
  await page.locator("#sc-undo").click();
  await savedOk(page);
});

test("switching the sound keeps the moment of the song (stem, MIDI, both, Pianoteq)", async ({ page, request }) => {
  await open(page);
  await page.waitForFunction(() => document.querySelector("#sc-audio").readyState >= 1);
  const now = () => page.evaluate(() => window.__player.time);
  await page.evaluate(() => { document.querySelector("#sc-audio").currentTime = 9; });
  for (const src of ["midi", "both", "stem"]) {
    await page.locator("#sc-source").selectOption(src);
    await page.waitForTimeout(300);
    expect(await now()).toBeCloseTo(9, 1);
  }
  const info = await (await request.get("/api/score/pianoteq")).json();
  if (!info.available) return;
  await page.locator("#sc-play").click();
  await page.locator("#sc-source").selectOption("pianoteq");
  await page.waitForFunction(() => document.querySelector("#sc-audio").src.includes("/pianoteq/audio/"), null, { timeout: 60000 });
  await page.waitForFunction(() => !window.__player.pending && document.querySelector("#sc-audio").readyState >= 1);
  // Arrived at the moment the stem had reached, not at 0:00, and playing on
  // from there. (The switch is immediate now -- the render already there, or
  // the MIDI until it is -- so it can land at 9.0 exactly: wait for it to move.)
  expect(await now()).toBeGreaterThanOrEqual(9);
  await page.waitForFunction(() => window.__player.time > 9.05, null, { timeout: 3000 });
  await page.evaluate(() => document.querySelector("#sc-audio").pause());
});

test("a deleted note is not played by the MIDI synth, even before the save returns", async ({ page }) => {
  await open(page);
  await page.waitForFunction(() => document.querySelector("#sc-audio").readyState >= 1);
  await page.evaluate(async () => {
    const { Player } = await import("/js/score/player.js");
    window.__voiced = new Set();
    const v = Player.prototype._voice;
    Player.prototype._voice = function (n, when, dur) { window.__voiced.add(n.id); return v.call(this, n, when, dur); };
  });
  await page.locator("#sc-source").selectOption("midi");
  const target = await page.evaluate(() => window.__score.notes.filter((n) => n.start > 3.5 && n.start < 6).sort((a, b) => a.start - b.start)[0]);
  await page.evaluate(() => { document.querySelector("#sc-audio").currentTime = 2.5; });
  await page.locator("#sc-play").click();
  await page.waitForFunction((t) => window.__player.time > t - 0.6, target.start);
  await clickNote(page, `(n) => n.id === "${target.id}"`);
  await page.keyboard.press("Delete");
  await page.waitForFunction((t) => window.__player.time > t + 0.3, target.start);
  await page.evaluate(() => document.querySelector("#sc-audio").pause());
  expect(await page.evaluate((id) => window.__voiced.has(id), target.id)).toBe(false);
});

test("Borradas: deleted notes listed, restore one, then all", async ({ page }) => {
  await open(page);
  await expect(page.locator("#sc-trash-toggle")).toBeHidden();
  const ids = await page.evaluate(() => window.__score.notes.slice(4, 6).map((n) => n.id));
  for (const id of ids) {
    await clickNote(page, `(n) => n.id === "${id}"`);
    await page.keyboard.press("Delete");
    await savedOk(page);
  }
  await expect(page.locator("#sc-trash-count")).toHaveText("2");
  await page.locator("#sc-trash-toggle").click();
  await expect(page.locator("#sc-trash-list li")).toHaveCount(2);
  // Newest first: the second deletion is on top; restore it alone.
  await page.locator("#sc-trash-list li").first().getByRole("button", { name: "Restaurar" }).click();
  await savedOk(page);
  await expect(page.locator("#sc-trash-count")).toHaveText("1");
  expect(await page.evaluate((id) => window.__score.notes.some((n) => n.id === id), ids[1])).toBe(true);
  await page.reload();
  await page.waitForFunction(() => window.__score?.data);
  await expect(page.locator("#sc-trash-count")).toHaveText("1");
  await page.locator("#sc-trash-toggle").click();
  await page.locator("#sc-trash-all").click();
  await savedOk(page);
  await expect(page.locator("#sc-trash-toggle")).toBeHidden();
  expect(await page.evaluate((ids) => ids.every((id) => window.__score.notes.some((n) => n.id === id)), ids)).toBe(true);
});

test("Pianoteq after an edit: the MIDI plays the edit until the new render is back", async ({ page, request }) => {
  const info = await (await request.get("/api/score/pianoteq")).json();
  test.skip(!info.available, "Pianoteq is not installed on this machine");
  test.setTimeout(120_000);
  await open(page);
  await page.locator("#sc-source").selectOption("pianoteq");
  await expect(page.locator("#sc-pt-status")).toContainText("✓", { timeout: 60_000 });
  const first = await page.evaluate(() => document.querySelector("#sc-audio").src);
  await clickNote(page, (n) => n.midi === 65);
  await page.keyboard.press("Delete");
  // At once: the old render is muted and the synth (with the edit) takes over.
  expect(await page.evaluate(() => window.__player.ptStale && document.querySelector("#sc-audio").muted)).toBe(true);
  await expect.poll(() => page.evaluate(() => document.querySelector("#sc-audio").src), { timeout: 60_000 }).not.toBe(first);
  await expect.poll(() => page.evaluate(() => window.__player.ptStale)).toBe(false);
  expect(await page.evaluate(() => document.querySelector("#sc-audio").muted)).toBe(false);
});

test("piano view style: 3D by default, Plano on request, remembered", async ({ page }) => {
  await open(page);
  await page.locator("#sc-view-toggle").click();
  await expect(page.locator("#sc-fall-style")).toHaveValue("3d");
  expect(await page.evaluate(() => window.__fall.opts.style)).toBe("3d");
  await page.locator("#sc-fall-style").selectOption("flat");
  await page.reload();
  await page.waitForFunction(() => window.__score?.data);
  await expect(page.locator("#sc-fall-style")).toHaveValue("flat");
  expect(await page.evaluate(() => window.__fall.opts.style)).toBe("flat");
});

test("the score's settings bar stays at the top while scrolling down the score", async ({ page }) => {
  await page.setViewportSize({ width: 1100, height: 500 });
  await open(page);
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await page.waitForTimeout(300);
  const box = (s) => page.evaluate((s) => { const b = document.querySelector(s).getBoundingClientRect(); return { top: Math.round(b.top), bottom: Math.round(b.bottom) }; }, s);
  const [top, transport, tools] = [await box(".sc-top"), await box(".sc-transport"), await box(".sc-tools")];
  expect(await page.evaluate(() => scrollY)).toBeGreaterThan(0);
  expect(top.top).toBe(0);
  expect(transport.top).toBe(top.bottom);
  expect(tools.top).toBe(transport.bottom);
});

test("Controles ▴/▾ hides every control but the playback line, remembered", async ({ page }) => {
  await open(page);
  await expect(page.locator(".sc-tools")).toBeVisible();
  await page.locator("#sc-controls-toggle").click();
  await expect(page.locator("#sc-controls-toggle")).toHaveText("Controles ▾");
  for (const s of [".sc-tools", "#sc-speed", "#sc-sync", "#sc-zoom"]) await expect(page.locator(s)).toBeHidden();
  for (const s of ["#sc-play", '[data-jump="-5"]', "#sc-view-toggle", "#sc-seek", "#sc-source"]) await expect(page.locator(s)).toBeVisible();
  await page.reload();
  await page.waitForFunction(() => window.__score?.data);
  await expect(page.locator(".sc-tools")).toBeHidden();
  await page.locator("#sc-controls-toggle").click();
  await expect(page.locator(".sc-tools")).toBeVisible();
  await expect(page.locator("#sc-controls-toggle")).toHaveText("Controles ▴");
});

// ── practice ────────────────────────────────────────────────────────────

test("?t= opens the song at that moment (from the mixer's 𝄞), else where it was left", async ({ page }) => {
  await page.goto(`${PAGE}&t=12.5`);
  await page.waitForFunction(() => window.__score?.data && document.querySelector("#sc-audio").readyState >= 1);
  await page.waitForFunction(() => !window.__player.pending);
  expect(await page.evaluate(() => window.__player.time)).toBeCloseTo(12.5, 1);
  await expect(page.locator("#sc-now")).toHaveText("0:12");
  // Opened again without ?t=: where it was left.
  await page.evaluate(() => window.__player.seek(10)); // left at 10 s (the piece lasts ~21 s; near its end it starts over)
  await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
  await page.goto(PAGE);
  await page.waitForFunction(() => window.__score?.data && document.querySelector("#sc-audio").readyState >= 1 && !window.__player.pending);
  expect(await page.evaluate(() => window.__player.time)).toBeCloseTo(8, 0); // a moment before, to get into it
});

test("loop: A and B on the bars sounding, past B back to A, faster each time, remembered", async ({ page }) => {
  await open(page);
  await page.waitForFunction(() => document.querySelector("#sc-audio").readyState >= 1);
  const m = await page.evaluate(() => window.__score.data.measures.slice(0, 4));
  await page.evaluate((t) => window.__player.seek(t), m[1].start + 0.1);
  await page.locator("#sc-loop-a").click();
  await page.evaluate((t) => window.__player.seek(t), m[2].start + 0.1);
  await page.locator("#sc-loop-b").click();
  await expect(page.locator("#sc-loop-label")).toHaveText(`compases ${m[1].number}–${m[2].number}`);
  await expect(page.locator("#sc-loop-toggle")).toHaveAttribute("aria-pressed", "true");
  expect(await page.evaluate(() => window.__practice.loop)).toMatchObject({ a: m[1].start, b: m[2].end, on: true });
  // Played up to B: back to A, and the ramp takes the speed up a step.
  await page.locator("#sc-speed").fill("60");
  await page.locator("#sc-loop-ramp").selectOption("10");
  await page.evaluate((t) => { window.__player.seek(t); const a = document.querySelector("#sc-audio"); a.muted = true; return a.play(); }, m[2].end - 0.3);
  await page.waitForFunction((a) => window.__practice.practice.loops >= 1 && window.__player.time < a + 1, m[1].start, { timeout: 5000 });
  await page.evaluate(() => document.querySelector("#sc-audio").pause());
  await expect(page.locator("#sc-speed-val")).toHaveText("70 %");
  // The falling notes mark it too; the song remembers it.
  expect(await page.evaluate(() => window.__fall.loop?.on)).toBe(true);
  await page.reload();
  await page.waitForFunction(() => window.__score?.data);
  await expect(page.locator("#sc-loop-label")).toHaveText(`compases ${m[1].number}–${m[2].number}`);
  await page.keyboard.press("l");
  await expect(page.locator("#sc-loop-toggle")).toHaveAttribute("aria-pressed", "false");
  await page.locator("#sc-loop-clear").click();
  await expect(page.locator("#sc-loop-label")).toHaveText("sin bucle");
});

test("hands: the player's hand is left out of the MIDI and faint on the piano; per song", async ({ page }) => {
  await open(page);
  await page.locator("#sc-hand").selectOption("R");
  expect(await page.evaluate(() => window.__player.silentStaff)).toBe(1);
  expect(await page.evaluate(() => window.__fall.opts.dimStaff)).toBe(2);
  await expect(page.locator("#sc-hand-hint")).toBeVisible(); // the stem cannot leave a hand out
  await page.locator("#sc-source").selectOption("midi");
  await expect(page.locator("#sc-hand-hint")).toBeHidden();
  await page.reload();
  await page.waitForFunction(() => window.__score?.data);
  await expect(page.locator("#sc-hand")).toHaveValue("R");
  await expect(page.locator("#sc-source")).toHaveValue("midi"); // what was heard, remembered too
  expect(await page.evaluate(() => window.__player.silentStaff)).toBe(1);
});

test("metronome and count-in: clicks on the bars' beats, remembered", async ({ page }) => {
  await open(page);
  await page.locator("#sc-metronome").check();
  await page.locator("#sc-countin").selectOption("bar");
  const beats = await page.evaluate(() => window.__player.beats.length);
  const bars = await page.evaluate(() => window.__score.data.measures.reduce((s, m) => s + m.meter, 0));
  expect(beats).toBe(bars);
  // ▶ counts a bar in first: playing, the audio not started yet.
  await page.evaluate(() => { document.querySelector("#sc-audio").muted = true; });
  await page.locator("#sc-play").click();
  expect(await page.evaluate(() => !!window.__player.countIn && document.querySelector("#sc-audio").paused)).toBe(true);
  await page.waitForFunction(() => !document.querySelector("#sc-audio").paused, null, { timeout: 5000 });
  await page.locator("#sc-play").click();
  await page.reload();
  await page.waitForFunction(() => window.__score?.data);
  await expect(page.locator("#sc-metronome")).toBeChecked();
  await expect(page.locator("#sc-countin")).toHaveValue("bar");
});

test("MIDI keyboard «Esperarme»: the song stops at a chord until its keys are played", async ({ page }) => {
  await open(page);
  await page.waitForFunction(() => document.querySelector("#sc-audio").readyState >= 1);
  await page.locator("#sc-midi-mode").evaluate((el) => { el.hidden = false; el.value = "wait"; el.dispatchEvent(new Event("change")); });
  await page.evaluate(() => { window.__practice.mk.on = true; });
  const first = await page.evaluate(() => {
    const s = window.__score.index.sorted;
    const t0 = s[0].start;
    return { start: t0, keys: [...new Set(s.filter((n) => n.start - t0 <= 0.06).map((n) => n.midi))] };
  });
  await page.evaluate((t) => { window.__player.seek(Math.max(0, t - 0.4)); const a = document.querySelector("#sc-audio"); a.muted = true; return a.play(); }, first.start);
  await page.waitForFunction(() => window.__practice.mk.waiting, null, { timeout: 5000 });
  expect(await page.evaluate(() => document.querySelector("#sc-audio").paused)).toBe(true);
  await expect(page.locator("#sc-midi-status")).toContainText("esperando");
  for (const k of first.keys) await page.evaluate((m) => window.__practice.keyDown(m, 80), k);
  await page.waitForFunction(() => !window.__practice.mk.waiting && !document.querySelector("#sc-audio").paused, null, { timeout: 3000 });
  expect(await page.evaluate(() => window.__practice.mk.hits)).toBe(1);
  for (const k of first.keys) await page.evaluate((m) => window.__practice.keyUp(m), k);
  await page.evaluate(() => document.querySelector("#sc-audio").pause());
});

test("falling notes: bar lines with their numbers, «Anticipación» remembered", async ({ page }) => {
  await open(page);
  await page.locator("#sc-view-toggle").click();
  expect(await page.evaluate(() => window.__fall.measures.length)).toBeGreaterThan(5);
  const lines = await page.evaluate(() => window.__fall.gridLines(0).filter((l) => l.number != null).length);
  expect(lines).toBeGreaterThan(0);
  await page.locator("#sc-fall-ahead").selectOption("8");
  expect(await page.evaluate(() => window.__fall.lookahead)).toBe(8);
  await page.reload();
  await page.waitForFunction(() => window.__score?.data);
  await expect(page.locator("#sc-fall-ahead")).toHaveValue("8");
});

test("practice is kept on the server and the /score/ list shows it", async ({ page, request }) => {
  const r = await request.put(`${API}/practice`, { data: { seconds: 125, loops: 3, speed: 80 } });
  expect(r.ok()).toBe(true);
  await page.goto("/score/");
  await expect(page.locator("#sc-joblist")).toContainText("partitura");
  await expect(page.locator("#sc-joblist")).toContainText("mejor 80 %");
});

test("Pianoteq: each song opens with its own piano, not the last one chosen anywhere", async ({ page, request }) => {
  const info = await (await request.get("/api/score/pianoteq")).json();
  test.skip(!info.available || info.presets.length < 2, "Pianoteq is not installed here");
  const own = info.presets.find((p) => p !== info.default);
  const other = info.default;
  // This song was last heard with `own`; another song since with `other`.
  await request.post(`${API}/pianoteq`, { data: { preset: own } });
  await page.addInitScript((p) => localStorage.setItem("stemdeck.score.view", JSON.stringify({ ptPreset: p })), other);
  await page.goto(PAGE);
  await page.waitForFunction(() => document.querySelector("#sc-pt-preset").options.length > 1);
  await expect(page.locator("#sc-pt-preset")).toHaveValue(own);
  expect((await (await request.get(API)).json()).pianoteq.preset).toBe(own);
  // Only one of each in the list.
  const names = await page.locator("#sc-pt-preset option").evaluateAll((os) => os.map((o) => o.value));
  expect(new Set(names).size).toBe(names.length);
});

test("Pianoteq at the practice speed: rendered slower, played at its own rate, on the song's clock", async ({ page, request }) => {
  test.setTimeout(120_000);
  const info = await (await request.get("/api/score/pianoteq")).json();
  test.skip(!info.available, "Pianoteq is not installed here");
  await open(page);
  await page.waitForFunction(() => document.querySelector("#sc-audio").readyState >= 1);
  await page.locator("#sc-speed").fill("50");
  await page.locator("#sc-source").selectOption("pianoteq");
  // The render made at 50 % arrives: the file plays at 1x, the song at 0.5x.
  await page.waitForFunction(() => window.__player.scale === 0.5 && !window.__player.pending, null, { timeout: 100_000 });
  expect(await page.evaluate(() => document.querySelector("#sc-audio").playbackRate)).toBe(1);
  await expect(page.locator("#sc-pt-status")).toContainText("a 50 %");
  // The song's clock: a moment of the song is that moment, whichever file plays.
  await page.evaluate(() => window.__player.seek(6));
  expect(await page.evaluate(() => window.__player.time)).toBeCloseTo(6, 1);
  expect(await page.evaluate(() => document.querySelector("#sc-audio").currentTime)).toBeCloseTo(12, 1);
  // Back to the stem: the same moment, at 0.5x stretched as before.
  await page.locator("#sc-source").selectOption("stem");
  await page.waitForFunction(() => !window.__player.pending && window.__player.scale === 1);
  expect(await page.evaluate(() => window.__player.time)).toBeCloseTo(6, 1);
  expect(await page.evaluate(() => document.querySelector("#sc-audio").playbackRate)).toBe(0.5);
});

// ── moving the song with a finger, panels hidden, full screen ──────────────

test("piano view: dragging the lane moves the song, back or forward, paused or playing", async ({ page }) => {
  await open(page);
  await page.waitForFunction(() => document.querySelector("#sc-audio").readyState >= 1);
  await page.locator("#sc-view-toggle").click();
  await page.locator("#sc-fall-style").selectOption("flat");
  await page.evaluate(() => window.__player.seek(8));
  const box = await page.locator("#sc-fall").boundingBox();
  // An empty column (no key with a note in this song: the lane's left edge).
  const x = box.x + 4;
  const y = box.y + box.height * 0.3;
  const lane = await page.evaluate(() => window.__fall.laneHeight() / window.__fall.lookahead); // px per second
  // Paused: pull the notes down 1 s worth -> 1 s later.
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x, y + lane * 0.5, { steps: 4 });
  await page.mouse.move(x, y + lane, { steps: 4 });
  await page.mouse.up();
  expect(await page.evaluate(() => window.__player.time)).toBeCloseTo(9, 0);
  expect(await page.evaluate(() => !window.__player.playing)).toBe(true);
  // Playing, pushed up 2 s worth -> 2 s back, and it plays on after; the
  // notes under the finger are not moved.
  const before = await page.evaluate(() => JSON.stringify(window.__score.notes.map((n) => [n.id, n.start, n.midi])));
  await page.evaluate(() => { const a = document.querySelector("#sc-audio"); a.muted = true; return a.play(); });
  const t0 = await page.evaluate(() => window.__player.time);
  await page.mouse.move(box.x + box.width / 2, y + lane * 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2, y + lane, { steps: 4 });
  await page.mouse.move(box.x + box.width / 2, y, { steps: 4 });
  const during = await page.evaluate(() => window.__player.time);
  await page.mouse.up();
  expect(during).toBeLessThan(t0 - 1.5);
  await page.waitForFunction(() => !document.querySelector("#sc-audio").paused);
  expect(await page.evaluate(() => JSON.stringify(window.__score.notes.map((n) => [n.id, n.start, n.midi])))).toBe(before);
  await page.evaluate(() => document.querySelector("#sc-audio").pause());
});

test("«Ocultar paneles»: one line with the song and where it is; remembered; P", async ({ page }) => {
  await open(page);
  await page.locator("#sc-bare").click();
  for (const sel of [".sc-top", ".sc-transport", "#sc-practice-bar", ".sc-tools"]) await expect(page.locator(sel).first()).toBeHidden();
  await expect(page.locator("#sc-mini")).toBeVisible();
  await expect(page.locator("#sc-mini-text")).toContainText("Score E2E");
  await expect(page.locator("#sc-mini-text")).toContainText("compás");
  await page.evaluate(() => window.__player.seek(12));
  await expect(page.locator("#sc-mini-text")).toContainText("0:12");
  // ▶ there plays and pauses.
  await page.evaluate(() => { document.querySelector("#sc-audio").muted = true; });
  await page.locator("#sc-mini-play").click();
  await expect(page.locator("#sc-mini-play")).toHaveText("❚❚");
  await page.locator("#sc-mini-play").click();
  await page.reload();
  await page.waitForFunction(() => window.__score?.data);
  await expect(page.locator("#sc-mini")).toBeVisible();
  await page.keyboard.press("p");
  await expect(page.locator("#sc-mini")).toBeHidden();
  await expect(page.locator(".sc-transport")).toBeVisible();
});

test("full screen: the piano edge to edge in a falling-notes video's proportions", async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await open(page);
  await page.locator("#sc-view-toggle").click();
  await page.locator("#sc-fs").click();
  await page.waitForFunction(() => document.body.classList.contains("sc-fs"));
  expect(await page.evaluate(() => window.__fall.opts.style)).toBe("video");
  await page.locator("#sc-mini-fs").evaluate(() => {}); // present
  await page.keyboard.press("p"); // panels away too
  await page.waitForTimeout(300);
  const fall = await page.locator("#sc-fall").boundingBox();
  expect(fall.height).toBeGreaterThan(1000);
  const keys = await page.evaluate(() => ({ keyH: window.__fall.keyHeight(), unit: window.__fall.size.w / window.__fall.layout.whites, h: window.__fall.size.h }));
  expect(keys.keyH / keys.h).toBeGreaterThanOrEqual(0.12);
  expect(keys.keyH / keys.h).toBeLessThanOrEqual(0.221); // 22 %, rounded to the pixel
  // Out again: the style chosen before.
  await page.keyboard.press("f");
  await page.waitForFunction(() => !document.body.classList.contains("sc-fs"));
  expect(await page.evaluate(() => window.__fall.opts.style)).toBe("3d");
});
