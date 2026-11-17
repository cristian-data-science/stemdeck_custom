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

// The score opens without note names; most tests read or click the pills,
// so they turn them on as a player does («Nombres»; a reload keeps them).
async function open(page, { names = true } = {}) {
  await page.addInitScript(() => {
    if (sessionStorage.getItem("e2e.seeded")) return;
    sessionStorage.setItem("e2e.seeded", "1");
    localStorage.removeItem("stemdeck.score.view");
    // «🎼 Ajustes» open: most tests change the transcription's settings.
    localStorage.setItem("stemdeck.score.view", JSON.stringify({ panelSettings: true }));
  });
  await page.goto(PAGE);
  await expect(page.locator("#sc-score g.note").first()).toBeVisible();
  await page.waitForFunction(() => window.__score?.ctx?.timeline?.length > 0);
  if (names) {
    const spelling = await page.evaluate(() => window.__score.data.names);
    await page.locator("#sc-names").selectOption(spelling);
    await expect(page.locator("#sc-score .sd-pill").first()).toBeVisible();
  }
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

test("undo on a tablet: ↶ on the playback bar in the piano view, a two-finger tap; three fingers redo", async ({ page }) => {
  await open(page);
  const id = await clickNote(page, (n) => n.midi === 72 && n.staff === 1);
  await page.keyboard.press("ArrowUp");
  await savedOk(page);
  // On the score, ↶ ↷ once (the editing row's), not twice.
  await expect(page.locator("#sc-undo")).toBeVisible();
  await expect(page.locator("#sc-undo2")).toBeHidden();
  await page.locator("#sc-view-toggle").click(); // the score's editing row (↶ Deshacer) is hidden here
  await expect(page.locator("#sc-undo")).toBeHidden();
  await expect(page.locator("#sc-undo2")).toBeVisible();
  await expect(page.locator("#sc-undo2")).toHaveAttribute("title", /Deshacer: Semitono|Deshacer: /);
  const midi = async () => (await (await page.request.get(API)).json()).notes.find((n) => n.id === id).midi;
  await page.locator("#sc-undo2").click();
  await expect(page.locator("#sc-toast")).toContainText("Deshecho");
  await expect.poll(midi).toBe(72);
  await page.locator("#sc-redo2").click();
  await expect.poll(midi).toBe(73);
  // Fingers on the lane: two tap = undo, three tap = redo (nothing else moves).
  const r = await page.locator(".sc-fall-canvas").boundingBox();
  const taps = (n) => page.evaluate(({ x, y, n }) => {
    const el = document.querySelector("#sc-fall");
    const ev = (type, i) => el.dispatchEvent(new PointerEvent(type, { bubbles: true, clientX: x + i * 60, clientY: y, button: 0, pointerId: 30 + i, pointerType: "touch", isPrimary: i === 0 }));
    for (let i = 0; i < n; i++) ev("pointerdown", i);
    for (let i = 0; i < n; i++) ev("pointerup", i);
  }, { x: r.x + r.width / 3, y: r.y + r.height / 3, n });
  const ahead = await page.evaluate(() => window.__fall.lookahead);
  await taps(2);
  await expect.poll(midi).toBe(72);
  await taps(3);
  await expect.poll(midi).toBe(73);
  expect(await page.evaluate(() => window.__fall.lookahead)).toBe(ahead); // not a pinch
});

test("🕘 Historial: every saved edit, named, kept after a reload; back to before one; back to the original", async ({ page }) => {
  await open(page);
  const total = await page.evaluate(() => window.__score.notes.length);
  const id = await clickNote(page, (n) => n.midi === 72 && n.staff === 1);
  await page.keyboard.press("ArrowUp");
  await savedOk(page);
  await clickNote(page, (n) => n.midi === 65);
  await page.keyboard.press("Delete");
  await savedOk(page);
  await page.reload(); // the page's own undo is gone; the history is not
  await page.waitForFunction(() => window.__score?.data);
  await page.locator("#sc-view-toggle").click();
  await page.locator("#sc-history-toggle").click();
  const rows = page.locator("#sc-history-list li");
  // The newest two are these (the shared test server keeps other tests' edits below).
  await expect(rows.nth(1)).toBeVisible();
  const count = await rows.count();
  await expect(rows.nth(0)).toContainText("borrada");
  await expect(rows.nth(0)).toContainText("−");
  await expect(rows.nth(1)).toContainText("→"); // the pitch change, named before → after
  // Back to before the first edit (both undone), asked first.
  await rows.nth(1).getByRole("button").click();
  await page.locator('#sc-confirm button[value="ok"]').click();
  await expect(page.locator("#sc-toast")).toContainText("Volver a antes de");
  await expect.poll(() => page.evaluate(() => window.__score.notes.length)).toBe(total);
  expect(await page.evaluate((id) => window.__score.notes.find((n) => n.id === id).midi, id)).toBe(72);
  await expect(rows).toHaveCount(count + 1);
  // ↶ undoes that too (the piano view: the playback bar's).
  await page.locator("#sc-undo2").click();
  await expect.poll(() => page.evaluate(() => window.__score.notes.length)).toBe(total - 1);
  // «Volver al original»: the transcription, no edit at all.
  await page.locator("#sc-history-reset").click();
  await page.locator('#sc-confirm button[value="ok"]').click();
  await expect(page.locator("#sc-toast")).toContainText("sin ediciones");
  await expect.poll(() => page.evaluate(() => window.__score.notes.length)).toBe(total);
  expect(await page.evaluate((id) => window.__score.notes.find((n) => n.id === id).midi, id)).toBe(72);
  await expect(rows.first()).toContainText("Restaurar original");
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

test("speed: four fixed speeds (25, 50, 70, 100 %), slower playback, pitch kept, remembered", async ({ page }) => {
  await open(page);
  const pressed = () => page.locator('[data-speed][aria-pressed="true"]');
  await expect(pressed()).toHaveText(/^100 %/);
  expect(await page.locator("[data-speed]").evaluateAll((bs) => bs.map((b) => b.dataset.speed))).toEqual(["25", "50", "70", "100"]);
  await page.locator('[data-speed="50"]').click();
  await expect(pressed()).toHaveText(/^50 %/);
  const audio = () => page.evaluate(() => ({ rate: document.querySelector("#sc-audio").playbackRate, keep: document.querySelector("#sc-audio").preservesPitch }));
  expect(await audio()).toEqual({ rate: 0.5, keep: true });
  // It really plays slower: ~0.5 s of song per second.
  await page.evaluate(() => { const a = document.querySelector("#sc-audio"); a.muted = true; return a.play(); });
  const t0 = await page.evaluate(() => document.querySelector("#sc-audio").currentTime);
  await page.waitForTimeout(1500);
  const t1 = await page.evaluate(() => document.querySelector("#sc-audio").currentTime);
  await page.evaluate(() => document.querySelector("#sc-audio").pause());
  expect(t1 - t0).toBeGreaterThan(0.5);
  expect(t1 - t0).toBeLessThan(1.05);
  await page.reload();
  await page.waitForFunction(() => window.__score?.data);
  await expect(pressed()).toHaveText(/^50 %/);
  expect((await audio()).rate).toBe(0.5);
});

test("the hands in two colours by default: once for a browser that kept the old default, a choice made after kept", async ({ page }) => {
  // Saved before: the old default, «Un color».
  await page.addInitScript(() => {
    if (sessionStorage.getItem("e2e.colors")) return;
    sessionStorage.setItem("e2e.colors", "1");
    localStorage.setItem("stemdeck.score.view", JSON.stringify({ fallColors: "one", panelSettings: true }));
  });
  await page.goto(PAGE);
  await page.waitForFunction(() => window.__score?.data);
  expect(await page.evaluate(() => window.__score.view.fallColors)).toBe("hands");
  // Chosen after: kept on the next visit.
  await page.locator("#sc-view-toggle").click();
  await page.locator("#sc-fall-colors").selectOption("one");
  await page.reload();
  await page.waitForFunction(() => window.__score?.data);
  expect(await page.evaluate(() => window.__score.view.fallColors)).toBe("one");
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
  // Same point of the song, and notes drawn on the canvas (each hand its colour by default).
  expect(await page.evaluate(() => document.querySelector("#sc-audio").currentTime)).toBeCloseTo(3.2, 1);
  const amber = () => page.evaluate(() => {
    const c = document.querySelector(".sc-fall-canvas");
    const d = c.getContext("2d").getImageData(0, 0, c.width, c.height).data;
    let n = 0;
    for (let i = 0; i < d.length; i += 4) if (d[i] > 230 && d[i + 1] > 160 && d[i + 1] < 200 && d[i + 2] < 60) n++;
    return n;
  });
  // By hand by default: two colours (the right hand's blue drawn) and a legend.
  const blue = () => page.evaluate(() => {
    const c = document.querySelector(".sc-fall-canvas");
    const d = c.getContext("2d").getImageData(0, 0, c.width, c.height).data;
    let n = 0;
    for (let i = 0; i < d.length; i += 4) if (d[i + 2] > 200 && d[i] < 140 && d[i + 1] > 120 && d[i + 1] < 190) n++;
    return n;
  });
  await expect.poll(blue).toBeGreaterThan(300);
  await expect(page.locator("#sc-fall-colors")).toHaveValue("hands");
  await expect(page.locator("#sc-fall-legend")).toBeVisible();
  await expect.poll(amber).toBe(0);
  // «Un color»: amber.
  await page.locator("#sc-fall-colors").selectOption("one");
  await expect(page.locator("#sc-fall-legend")).toBeHidden();
  await expect.poll(amber).toBeGreaterThan(500);
  // Back by hand; the 88 keys; names off. Remembered (a choice is kept).
  await page.locator("#sc-fall-colors").selectOption("hands");
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

test("piano view: a tap on a falling note while it plays pauses the song there and selects it", async ({ page }) => {
  await open(page);
  await page.waitForFunction(() => document.querySelector("#sc-audio").readyState >= 1);
  await page.locator("#sc-view-toggle").click();
  await page.evaluate(() => { document.querySelector("#sc-audio").currentTime = 2.0; });
  await expect.poll(() => page.evaluate(() => window.__fall.hits.length)).toBeGreaterThan(2);
  await page.waitForTimeout(400);
  await page.locator("#sc-play").click();
  await expect.poll(() => page.evaluate(() => window.__player.playing)).toBe(true);
  const a = await page.evaluate(() => {
    const r = document.querySelector(".sc-fall-canvas").getBoundingClientRect();
    const h = [...window.__fall.hits].sort((a, b) => b.h - a.h)[0];
    return { id: h.id, x: r.left + h.x + h.w / 2, y: r.top + Math.max(h.y, 0) + h.h / 2 };
  });
  await page.mouse.click(a.x, a.y);
  await expect.poll(() => page.evaluate(() => window.__player.playing)).toBe(false);
  await expect(page.locator("#sc-editbar")).toBeVisible();
  await expect(page.locator("#sc-editbar-n")).toHaveText("1 nota");
  // A drag while it plays still moves the song (and it plays on after).
  await page.locator("#sc-edit-clear").click();
  await page.locator("#sc-play").click();
  await expect.poll(() => page.evaluate(() => window.__player.playing)).toBe(true);
  const r = await page.locator(".sc-fall-canvas").boundingBox();
  await page.mouse.move(r.x + 20, r.y + 60);
  await page.mouse.down();
  for (let i = 1; i <= 5; i++) await page.mouse.move(r.x + 20, r.y + 60 + i * 12);
  await page.mouse.up();
  await expect.poll(() => page.evaluate(() => window.__player.playing)).toBe(true);
});

test("piano view: a double click or double tap on the empty background pauses, again plays", async ({ page }) => {
  await open(page);
  await page.waitForFunction(() => document.querySelector("#sc-audio").readyState >= 1);
  await page.locator("#sc-view-toggle").click();
  await page.waitForTimeout(400);
  const r = await page.locator(".sc-fall-canvas").boundingBox();
  const at = { x: r.x + 8, y: r.y + 40 }; // the edge of the lane: no note there
  const playing = () => page.evaluate(() => window.__player.playing);
  await page.mouse.dblclick(at.x, at.y);
  await expect.poll(playing).toBe(true);
  await page.mouse.dblclick(at.x, at.y);
  await expect.poll(playing).toBe(false);
  // Two taps far apart in time are two taps, not a double tap.
  await page.mouse.click(at.x, at.y);
  await page.waitForTimeout(700);
  await page.mouse.click(at.x, at.y);
  await page.waitForTimeout(300);
  expect(await playing()).toBe(false);
  // A finger: the same pointer events, touch type.
  const tap = () => page.evaluate(({ x, y }) => {
    const el = document.querySelector("#sc-fall");
    for (const type of ["pointerdown", "pointerup"]) {
      el.dispatchEvent(new PointerEvent(type, { bubbles: true, clientX: x, clientY: y, button: 0, pointerId: 7, pointerType: "touch", isPrimary: true }));
    }
  }, at);
  await page.waitForTimeout(500);
  await tap();
  await tap();
  await expect.poll(playing).toBe(true);
  await tap();
  await tap();
  await expect.poll(playing).toBe(false);
});

test("messages that come and go float: the page never grows a scrollbar for them", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  await open(page);
  await page.locator("#sc-view-toggle").click();
  await page.waitForTimeout(400);
  const size = () => page.evaluate(() => [document.documentElement.scrollHeight, innerHeight, document.querySelector(".sc-fall-canvas").getBoundingClientRect().width]);
  const before = await size();
  expect(before[0]).toBe(before[1]);
  await page.evaluate(() => {
    const long = "Pianoteq: generando con Bösendorfer VC Player (solo mano derecha) a 75 %… 38 s (mientras, suena el MIDI)";
    const pt = document.querySelector("#sc-pt-status");
    pt.hidden = false;
    pt.textContent = long;
    document.querySelector("#sc-hands-msg").textContent = "Mano derecha: 1 nota · guardando… · el programa ajustó además 4 notas";
  });
  await page.waitForTimeout(300);
  expect(await size()).toEqual(before);
});

test("hands: the edit bar sets a note's hand, and Auto gives it back to the program", async ({ page }) => {
  await open(page);
  const id = await clickNote(page, (n) => n.midi === 67 && n.staff === 1);
  const get = async () => (await notes(page)).find((n) => n.id === id);
  await expect(page.locator("#sc-editbar")).toBeVisible();
  await page.locator('#sc-editbar [data-sethand="L"]').click();
  await savedOk(page);
  expect((await get()).hand).toBe("L");
  expect((await get()).staff).toBe(2);
  await page.locator('#sc-editbar [data-sethand=""]').click();
  await savedOk(page);
  expect((await get()).hand).toBe(null);
  expect((await get()).staff).toBe(1); // G4: back above the split
});

test("piano view: 🖌 Corregir manos paints the notes a stroke crosses, colours by hand, own colours", async ({ page }) => {
  await open(page);
  await page.waitForFunction(() => document.querySelector("#sc-audio").readyState >= 1);
  await page.locator("#sc-view-toggle").click();
  await page.evaluate(() => { document.querySelector("#sc-audio").currentTime = 2.0; });
  await expect.poll(() => page.evaluate(() => window.__fall.hits.length)).toBeGreaterThan(2);
  await page.waitForTimeout(400); // the piano settles its height first
  await page.locator("#sc-paint").click();
  await expect(page.locator("#sc-paint-pick")).toBeVisible();
  await expect(page.locator("#sc-fall-colors")).toHaveValue("hands"); // painting shows the hands
  await page.locator('#sc-paint-pick [data-paint="L"]').click();
  // Two right-hand bars, one stroke from the first to the second.
  const two = await page.evaluate(() => {
    const r = document.querySelector(".sc-fall-canvas").getBoundingClientRect();
    const right = new Set(window.__score.notes.filter((n) => n.staff === 1).map((n) => n.id));
    const hs = window.__fall.hits.filter((h) => right.has(h.id) && h.y + h.h > 20).sort((a, b) => b.h - a.h).slice(0, 2);
    return hs.map((h) => ({ id: h.id, x: r.left + h.x + h.w / 2, y: r.top + Math.max(h.y, 0) + 10 }));
  });
  expect(two.length).toBe(2);
  await page.mouse.move(two[0].x, two[0].y);
  await page.mouse.down();
  for (let i = 1; i <= 8; i++) await page.mouse.move(two[0].x + ((two[1].x - two[0].x) * i) / 8, two[0].y + ((two[1].y - two[0].y) * i) / 8);
  await page.mouse.up();
  await expect(page.locator("#sc-hands-msg")).toContainText("Mano corregida");
  const after = await notes(page);
  for (const { id } of two) {
    const n = after.find((x) => x.id === id);
    expect([n.hand, n.staff]).toEqual(["L", 2]);
  }
  // A stroke does not move the song.
  await expect(page.locator("#sc-status")).not.toContainText("⇅");
  // Own colours: the swatches follow, ↺ goes back.
  await page.locator("#sc-color-l").evaluate((el) => { el.value = "#ff0000"; el.dispatchEvent(new Event("input", { bubbles: true })); });
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--hand-l").trim())).toBe("#ff0000");
  await expect(page.locator("#sc-color-reset")).toBeVisible();
  await page.locator("#sc-color-reset").click();
  await expect(page.locator("#sc-color-l")).toHaveValue("#3ecf8e");
  await page.keyboard.press("Escape");
  await expect(page.locator("#sc-paint-pick")).toBeHidden();
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

test("Pianoteq after deleting a note: the current file keeps playing, said, until the new one takes over", async ({ page, request }) => {
  const info = await (await request.get("/api/score/pianoteq")).json();
  test.skip(!info.available, "Pianoteq is not installed on this machine");
  test.setTimeout(120_000);
  await open(page);
  await page.locator("#sc-source").selectOption("pianoteq");
  await expect(page.locator("#sc-pt-status")).toContainText("✓", { timeout: 60_000 });
  const first = await page.evaluate(() => document.querySelector("#sc-audio").src);
  await clickNote(page, (n) => n.midi === 65);
  await page.keyboard.press("Delete");
  // At once: Pianoteq's file still plays (no jump to the synth, the rhythm
  // kept), and the floating status says the note is being taken out.
  expect(await page.evaluate(() => !window.__player.ptStale && !document.querySelector("#sc-audio").muted)).toBe(true);
  await expect(page.locator("#sc-pt-status")).toContainText("quitando 1 nota");
  await expect(page.locator("#sc-pt-status")).toContainText("sigue sonando la pista actual");
  await expect.poll(() => page.evaluate(() => document.querySelector("#sc-audio").src), { timeout: 60_000 }).not.toBe(first);
  await expect(page.locator("#sc-pt-status")).toContainText("nota quitada ✓");
  expect(await page.evaluate(() => window.__player.ptStale || document.querySelector("#sc-audio").muted)).toBe(false);
  // Another kind of edit: the synth plays it at once, as before.
  await clickNote(page, (n) => n.midi > 65);
  await page.keyboard.press("ArrowUp");
  expect(await page.evaluate(() => window.__player.ptStale && document.querySelector("#sc-audio").muted)).toBe(true);
});

test("deleted on Pianoteq, then «MIDI» chosen while it renders: the MIDI never plays the deleted note", async ({ page, request }) => {
  const info = await (await request.get("/api/score/pianoteq")).json();
  test.skip(!info.available, "Pianoteq is not installed on this machine");
  test.setTimeout(120_000);
  await open(page);
  await page.evaluate(async () => {
    const { Player } = await import("/js/score/player.js");
    window.__voiced = new Set();
    const v = Player.prototype._voice;
    Player.prototype._voice = function (n, when, dur) { window.__voiced.add(n.id); return v.call(this, n, when, dur); };
  });
  await page.locator("#sc-source").selectOption("pianoteq");
  await expect(page.locator("#sc-pt-status")).toContainText("✓", { timeout: 60_000 });
  const first = await page.evaluate(() => document.querySelector("#sc-audio").src);
  const target = await page.evaluate(() => window.__score.notes.filter((n) => n.start > 3.5 && n.start < 6).sort((a, b) => a.start - b.start)[0]);
  await clickNote(page, `(n) => n.id === "${target.id}"`);
  await page.keyboard.press("Delete");
  await expect(page.locator("#sc-pt-status")).toContainText("quitando 1 nota");
  // Switched to the MIDI while Pianoteq is still rendering without it.
  await page.locator("#sc-source").selectOption("midi");
  expect(await page.evaluate(() => window.__player.synthOnly)).toBe(true);
  await page.evaluate((t) => window.__player.seek(t - 1), target.start);
  await page.locator("#sc-play").click();
  await page.waitForFunction((t) => window.__player.time > t + 0.5, target.start, { timeout: 15_000 });
  await page.locator("#sc-play").click();
  expect(await page.evaluate((id) => window.__voiced.has(id), target.id)).toBe(false);
  expect(await page.evaluate(() => window.__voiced.size)).toBeGreaterThan(0); // the others did sound
  // The render went on behind: back on «Pianoteq», the file without the note.
  await page.locator("#sc-source").selectOption("pianoteq");
  await expect.poll(() => page.evaluate(() => document.querySelector("#sc-audio").src), { timeout: 60_000 }).not.toBe(first);
  expect(await page.evaluate(() => window.__player.ptStale)).toBe(false);
});

test("«🔇 Silenciar» on Pianoteq: the hand's render is made beforehand, so no MIDI stands in", async ({ page, request }) => {
  const info = await (await request.get("/api/score/pianoteq")).json();
  test.skip(!info.available, "Pianoteq is not installed on this machine");
  test.setTimeout(180_000);
  const asked = new Set();
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().endsWith("/pianoteq")) asked.add(JSON.parse(r.postData() || "{}").hand ?? "both");
  });
  await open(page);
  await page.locator("#sc-source").selectOption("pianoteq");
  await expect(page.locator("#sc-pt-status")).toContainText("✓", { timeout: 60_000 });
  const first = await page.evaluate(() => document.querySelector("#sc-audio").src);
  const preset = await page.locator("#sc-pt-preset").inputValue();
  // The server renders each hand alone (and each speed) after the full
  // render, by itself (app/api/score.py _pt_background): the page never asks.
  expect(asked.has("L") || asked.has("R")).toBe(false);
  for (const hand of ["L", "R"]) {
    await expect
      .poll(async () => (await (await request.post(`${API}/pianoteq`, { data: { preset, hand } })).json()).state, { timeout: 90_000, intervals: [2000] })
      .toBe("ready");
  }
  await page.evaluate(() => {
    window.__staleCalls = [];
    const p = window.__player;
    const orig = p.setPianoteqStale.bind(p);
    p.setPianoteqStale = (v) => (window.__staleCalls.push(v), orig(v));
  });
  await page.locator('[data-mute="L"]').click();
  await expect.poll(() => page.evaluate(() => document.querySelector("#sc-audio").src), { timeout: 10_000 }).not.toBe(first);
  expect(await page.evaluate(() => window.__staleCalls.includes(true))).toBe(false); // the synth never took over
  expect(await page.evaluate(() => window.__player.silentStaff)).toBe(2);
  // The left hand silenced: Pianoteq plays the right one alone.
  await expect(page.locator("#sc-pt-status")).toContainText("solo mano derecha", { timeout: 10_000 });
});

test("«🔇 Silenciar»: Izquierda on the left, and the silenced one lit and pulsing", async ({ page }) => {
  await open(page);
  const buttons = page.locator("[data-mute]");
  expect(await buttons.evaluateAll((bs) => bs.map((b) => b.dataset.mute))).toEqual(["L", "R"]);
  const left = page.locator('[data-mute="L"]');
  const look = () => left.evaluate((b) => [getComputedStyle(b).animationName, getComputedStyle(b).backgroundColor, b.textContent.trim()]);
  const off = await look();
  await left.click();
  const on = await look();
  expect(on[0]).toBe("sc-mute-pulse");
  expect(on[1]).not.toBe(off[1]);
  expect(on[2]).toContain("🔇");
  expect(off[2]).toContain("🔈");
  await left.click();
  expect((await look())[0]).toBe("none");
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

test("the editing row stays at the top while scrolling down the score", async ({ page }) => {
  await page.setViewportSize({ width: 1100, height: 500 });
  await open(page);
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await page.waitForTimeout(300);
  const box = (s) => page.evaluate((s) => { const b = document.querySelector(s).getBoundingClientRect(); return { top: Math.round(b.top), bottom: Math.round(b.bottom) }; }, s);
  const [top, transport, tools] = [await box(".sc-top"), await box(".sc-transport"), await box(".sc-editrow")];
  expect(await page.evaluate(() => scrollY)).toBeGreaterThan(0);
  expect(top.top).toBe(0);
  expect(transport.top).toBe(top.bottom);
  expect(tools.top).toBe(transport.bottom);
});

test("the menu in order: the transcription's settings folded under «🎼 Ajustes» (remembered), the exports in one menu, editing beside the status", async ({ page }) => {
  await page.addInitScript(() => {
    if (sessionStorage.getItem("e2e.fresh")) return;
    sessionStorage.setItem("e2e.fresh", "1");
    localStorage.removeItem("stemdeck.score.view");
  });
  await page.goto(PAGE);
  await page.waitForFunction(() => window.__score?.ctx?.timeline?.length > 0);
  // Folded at first: the score is nearer the top.
  await expect(page.locator("#sc-grid")).toBeHidden();
  await expect(page.locator("#sc-settings-toggle")).toHaveText("🎼 Ajustes ▾");
  const folded = (await page.locator("#sc-scroll").boundingBox()).y;
  await page.locator("#sc-settings-toggle").click();
  await expect(page.locator("#sc-grid")).toBeVisible();
  expect((await page.locator("#sc-scroll").boundingBox()).y).toBeGreaterThan(folded + 30);
  await page.reload();
  await page.waitForFunction(() => window.__score?.data);
  await expect(page.locator("#sc-grid")).toBeVisible(); // remembered
  await page.locator("#sc-settings-toggle").click();
  await expect(page.locator("#sc-grid")).toBeHidden();
  // The names are a matter of the view: beside Zoom, not in the settings.
  await expect(page.locator("#sc-names")).toBeVisible();
  // Editing and the status on one row, always at hand.
  for (const id of ["#sc-undo", "#sc-add", "#sc-status"]) await expect(page.locator(id)).toBeVisible();
  // «⬇ Exportar»: the four downloads in one menu, closed again with Esc.
  await expect(page.locator("#sc-dl-mid")).toBeHidden();
  await page.locator("#sc-export-toggle").click();
  for (const id of ["#sc-dl-mid", "#sc-dl-raw", "#sc-dl-xml", "#sc-print"]) await expect(page.locator(id)).toBeVisible();
  expect(await page.locator("#sc-dl-xml").getAttribute("href")).toContain("export.musicxml");
  await page.keyboard.press("Escape");
  await expect(page.locator("#sc-dl-mid")).toBeHidden();
});

test("the song's length is shown at once, before its audio has loaded", async ({ page }) => {
  // The audio held back: the length still shows, from the song.
  let release;
  const held = new Promise((r) => (release = r));
  await page.route("**/score/audio/**", async (route) => {
    await held;
    await route.continue();
  });
  await open(page, { names: false });
  const job = await (await page.request.get("/api/jobs/5c0de0000001")).json();
  const want = `${Math.floor(job.duration / 60)}:${String(Math.floor(job.duration % 60)).padStart(2, "0")}`;
  expect(await page.evaluate(() => document.getElementById("sc-audio").readyState)).toBe(0);
  await expect(page.locator("#sc-total")).toHaveText(want);
  release();
});

test("each view shows its own controls: the score's (zoom, names, settings, editing) not on the piano, the piano's not on the score", async ({ page }) => {
  await open(page);
  const scoreOnly = ["#sc-zoom", "#sc-follow", "#sc-names", "#sc-settings-toggle", "#sc-undo", "#sc-add", "#sc-status"];
  const pianoOnly = ["#sc-fall-style", "#sc-fall-ahead", "#sc-fall-keys", "#sc-fall-colors", "#sc-fall-add", "#sc-paint", "#sc-undo2"];
  for (const s of scoreOnly) await expect(page.locator(s), s).toBeVisible();
  for (const s of pianoOnly) await expect(page.locator(s), s).toBeHidden();
  await page.locator("#sc-view-toggle").click();
  for (const s of scoreOnly) await expect(page.locator(s), s).toBeHidden();
  for (const s of pianoOnly) await expect(page.locator(s), s).toBeVisible();
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

test("Zoom: dragged, the drawing is scaled at once; let go, engraved again at that size, back where the song is", async ({ page }) => {
  await open(page);
  const width = async () => (await page.locator("#sc-score svg").first().boundingBox()).width;
  const w0 = await width();
  const rendered = await page.evaluate(() => document.body.dataset.rendered);
  // Dragging (input events only): scaled, not engraved again.
  await page.evaluate(() => {
    const z = document.getElementById("sc-zoom");
    z.value = String(Number(z.value) + 14);
    z.dispatchEvent(new Event("input"));
  });
  expect(await page.evaluate(() => document.body.dataset.rendered)).toBe(rendered);
  expect(await width()).toBeGreaterThan(w0 * 1.2);
  // Let go: engraved again (the scale gone), the cursor back on the song's system.
  await page.evaluate(() => document.getElementById("sc-zoom").dispatchEvent(new Event("change")));
  await expect.poll(() => page.evaluate(() => document.body.dataset.rendered)).not.toBe(rendered);
  await expect.poll(() => page.evaluate(() => document.querySelector("#sc-score > svg").style.transform)).toBe("");
  await expect(page.locator("#sc-score")).not.toHaveClass(/sd-zooming/);
  expect(await page.evaluate(() => window.__score.view.zoom)).toBe(56);
});

test("opened again, the score comes back as the score without names (a reload keeps the view)", async ({ page }) => {
  await open(page);
  await page.locator("#sc-view-toggle").click();
  await expect(page.locator("#sc-fall")).toBeVisible();
  await page.reload(); // F5: the view it was in
  await expect(page.locator("#sc-fall")).toBeVisible();
  await expect(page.locator("#sc-view-toggle")).toHaveText("𝄞 Partitura");
  // Opened again (from the mixer's 𝄞): the score, no names; the piano a tap away.
  await page.goto(PAGE);
  await expect(page.locator("#sc-score g.note").first()).toBeVisible();
  await expect(page.locator("#sc-fall")).toBeHidden();
  await expect(page.locator("#sc-view-toggle")).toHaveText("🎹 Piano");
  await expect(page.locator("#sc-names")).toHaveValue("none");
  await expect(page.locator("#sc-score .sd-pill")).toHaveCount(0);
  await page.locator("#sc-view-toggle").click();
  await expect(page.locator("#sc-fall")).toBeVisible();
});

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
  await page.locator('[data-speed="50"]').click();
  await page.locator("#sc-loop-ramp").selectOption("1");
  await page.evaluate((t) => { window.__player.seek(t); const a = document.querySelector("#sc-audio"); a.muted = true; return a.play(); }, m[2].end - 0.3);
  await page.waitForFunction((a) => window.__practice.practice.loops >= 1 && window.__player.time < a + 1, m[1].start, { timeout: 5000 });
  await page.evaluate(() => document.querySelector("#sc-audio").pause());
  await expect(page.locator('[data-speed][aria-pressed="true"]')).toHaveText(/^70 %/);
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

test("«🔇 Silenciar» a hand: left out of the MIDI, faint and dashed on the piano; per song; off again", async ({ page }) => {
  await open(page);
  const right = page.locator('[data-mute="R"]');
  await right.click();
  await expect(right).toHaveAttribute("aria-pressed", "true");
  expect(await page.evaluate(() => window.__player.silentStaff)).toBe(1);
  expect(await page.evaluate(() => window.__fall.opts.dimStaff)).toBe(1); // the silenced hand is the faint one
  // The stem has both hands in it: silencing one moves to the MIDI.
  await expect(page.locator("#sc-source")).toHaveValue("midi");
  await expect(page.locator("#sc-hand-hint")).toBeHidden();
  expect(await page.evaluate(() => window.__fall.muted({ staff: 1 }) && !window.__fall.muted({ staff: 2 }))).toBe(true);
  await page.locator("#sc-source").selectOption("stem");
  await expect(page.locator("#sc-hand-hint")).toBeVisible(); // the stem cannot leave a hand out
  await page.locator("#sc-source").selectOption("midi");
  await page.reload();
  await page.waitForFunction(() => window.__score?.data);
  await expect(page.locator('[data-mute="R"]')).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("#sc-source")).toHaveValue("midi"); // what was heard, remembered too
  expect(await page.evaluate(() => window.__player.silentStaff)).toBe(1);
  // Pressed again: both hands sound.
  await page.locator('[data-mute="R"]').click();
  await expect(page.locator('[data-mute="R"]')).toHaveAttribute("aria-pressed", "false");
  expect(await page.evaluate(() => [window.__player.silentStaff, window.__fall.opts.dimStaff])).toEqual([0, 0]);
  // The left one, straight from the right one.
  await page.locator('[data-mute="R"]').click();
  await page.locator('[data-mute="L"]').click();
  await expect(page.locator('[data-mute="R"]')).toHaveAttribute("aria-pressed", "false");
  expect(await page.evaluate(() => [window.__player.silentStaff, window.__fall.opts.dimStaff])).toEqual([2, 2]);
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

test("falling notes: bar lines with their numbers, «Notas a la vista» remembered", async ({ page }) => {
  await open(page);
  await page.locator("#sc-view-toggle").click();
  expect(await page.evaluate(() => window.__fall.measures.length)).toBeGreaterThan(5);
  const lines = await page.evaluate(() => window.__fall.gridLines(0).filter((l) => l.number != null).length);
  expect(lines).toBeGreaterThan(0);
  await page.locator("#sc-fall-ahead").fill("100");
  expect(await page.evaluate(() => window.__fall.lookahead)).toBe(20);
  await expect(page.locator("#sc-fall-ahead-val")).toHaveText("20 s");
  await page.reload();
  await page.waitForFunction(() => window.__score?.data);
  await expect(page.locator("#sc-fall-ahead")).toHaveValue("100");
  await expect.poll(() => page.evaluate(() => window.__fall.lookahead)).toBe(20);
});

test("«Notas a la vista»: Ctrl + wheel, + and −, and a two-finger pinch on the lane, said over it", async ({ page }) => {
  await open(page);
  await page.locator("#sc-view-toggle").click();
  await page.waitForTimeout(300);
  const ahead = () => page.evaluate(() => window.__fall.lookahead);
  expect(await ahead()).toBe(4);
  const r = await page.locator(".sc-fall-canvas").boundingBox();
  const mid = { x: r.x + r.width / 2, y: r.y + r.height / 2 };
  // Ctrl + wheel down: more seconds (the notes closer together); the page is not zoomed.
  await page.mouse.move(mid.x, mid.y);
  await page.keyboard.down("Control");
  await page.mouse.wheel(0, 200);
  await page.keyboard.up("Control");
  await expect.poll(ahead).toBeGreaterThan(6);
  await expect(page.locator("#sc-fall-hint")).toBeVisible();
  await expect(page.locator("#sc-fall-hint")).toContainText("Notas a la vista");
  expect(await page.evaluate(() => window.visualViewport?.scale ?? 1)).toBe(1);
  // + fewer, − more.
  const before = await ahead();
  await page.keyboard.press("+");
  expect(await ahead()).toBeLessThan(before);
  await page.keyboard.press("-");
  await page.keyboard.press("-");
  expect(await ahead()).toBeGreaterThan(before);
  // A pinch: two fingers apart -> fewer seconds; nothing else happens (no
  // seek, no note selected).
  const t0 = await page.evaluate(() => window.__player.time);
  const was = await ahead();
  await page.evaluate(({ x, y }) => {
    const el = document.querySelector("#sc-fall");
    const ev = (type, id, dx) => el.dispatchEvent(new PointerEvent(type, { bubbles: true, clientX: x + dx, clientY: y, button: 0, pointerId: id, pointerType: "touch", isPrimary: id === 11 }));
    ev("pointerdown", 11, -40);
    ev("pointerdown", 12, 40);
    for (let i = 1; i <= 5; i++) {
      ev("pointermove", 11, -40 - i * 16);
      ev("pointermove", 12, 40 + i * 16);
    }
    ev("pointerup", 11, -120);
    ev("pointerup", 12, 120);
  }, mid);
  const now = await ahead();
  expect(now).toBeLessThan(was * 0.6); // 80 px apart -> 240 px: a third of the seconds
  expect(await page.evaluate(() => window.__player.time)).toBeCloseTo(t0, 2);
  expect(await page.evaluate(() => window.__score.selection.size)).toBe(0);
  // Kept on this device.
  await page.reload();
  await page.waitForFunction(() => window.__score?.data);
  await expect.poll(() => page.evaluate(() => window.__fall.lookahead)).toBeCloseTo(now, 1);
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
  await page.locator('[data-speed="50"]').click();
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
  await page.waitForTimeout(150); // held still before letting go: no glide
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
  await page.waitForTimeout(150);
  await page.mouse.up();
  expect(during).toBeLessThan(t0 - 1.5);
  await page.waitForFunction(() => !document.querySelector("#sc-audio").paused);
  expect(await page.evaluate(() => JSON.stringify(window.__score.notes.map((n) => [n.id, n.start, n.midi])))).toBe(before);
  await page.evaluate(() => document.querySelector("#sc-audio").pause());
});

test("piano view: a flick keeps the song going and slowing down; a press catches it", async ({ page }) => {
  await open(page);
  await page.waitForFunction(() => document.querySelector("#sc-audio").readyState >= 1);
  await page.locator("#sc-view-toggle").click();
  await page.locator("#sc-fall-style").selectOption("flat");
  await page.evaluate(() => window.__player.seek(2));
  const box = await page.locator("#sc-fall").boundingBox();
  const x = box.x + 4;
  const y = box.y + box.height * 0.2;
  const lane = await page.evaluate(() => window.__fall.laneHeight() / window.__fall.lookahead); // px per second
  // Pull the notes down 1 s worth in ~100 ms and let go while moving.
  await page.mouse.move(x, y);
  await page.mouse.down();
  for (let i = 1; i <= 6; i++) {
    await page.mouse.move(x, y + (lane * i) / 6);
    await page.waitForTimeout(16);
  }
  await page.mouse.up();
  const released = await page.evaluate(() => window.__player.time);
  expect(released).toBeCloseTo(3, 0);
  // It glides on (forward), then stops by itself.
  await page.waitForFunction((r) => window.__player.time > r + 1, released, { timeout: 3000 });
  await page.waitForFunction(() => {
    const t = window.__player.time;
    return new Promise((ok) => setTimeout(() => ok(window.__player.time === t), 250));
  }, null, { timeout: 5000 });
  const stopped = await page.evaluate(() => window.__player.time);
  expect(stopped).toBeLessThan(released + 15);
  expect(await page.evaluate(() => !window.__player.playing)).toBe(true);
  // Another flick, caught by a tap: it stops where it is and nothing is selected.
  await page.mouse.move(x, y);
  await page.mouse.down();
  for (let i = 1; i <= 6; i++) {
    await page.mouse.move(x, y + (lane * i) / 6);
    await page.waitForTimeout(16);
  }
  await page.mouse.up();
  await page.waitForTimeout(60);
  await page.mouse.click(x, y);
  const caught = await page.evaluate(() => window.__player.time);
  await page.waitForTimeout(300);
  expect(await page.evaluate(() => window.__player.time)).toBeCloseTo(caught, 2);
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

test("«⚙» quick menu with the panels hidden: half see-through, lit when touched, edits, speed, mute, closes by itself", async ({ page }) => {
  await open(page);
  await page.locator("#sc-view-toggle").click();
  const gear = page.locator("#sc-qm-gear");
  await expect(gear).toBeHidden(); // panels shown: no need for it
  await page.keyboard.press("p");
  await expect(gear).toBeVisible();
  const opacity = () => gear.evaluate((g) => Number(getComputedStyle(g).opacity));
  await page.waitForTimeout(3000); // nothing touched
  await expect.poll(opacity).toBeLessThan(0.5);
  await page.mouse.move(200, 300);
  await expect.poll(opacity).toBeGreaterThan(0.9);
  // Opens downwards, one item under the other, at the top right.
  await gear.click();
  const menu = page.locator("#sc-qm-menu");
  await expect(menu).toBeVisible();
  const [g, m] = [await gear.boundingBox(), await menu.boundingBox()];
  expect(m.y).toBeGreaterThan(g.y + g.height - 1);
  expect(m.x + m.width).toBeGreaterThan((page.viewportSize().width) - 40);
  // Speed.
  await menu.locator('[data-qm-speed="50"]').click();
  expect(await page.evaluate(() => window.__player.rate)).toBe(0.5);
  await expect(menu.locator('[data-qm-speed="50"]')).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator('#sc-speed [data-speed="50"]')).toHaveAttribute("aria-pressed", "true");
  // Mute the left hand, then not.
  await menu.locator('[data-qm-mute="L"]').click();
  expect(await page.evaluate(() => window.__player.silentStaff)).toBe(2);
  await menu.locator('[data-qm-mute="L"]').click();
  expect(await page.evaluate(() => window.__player.silentStaff || 0)).toBe(0);
  // Notes on screen.
  await menu.locator('[data-qm="ahead+"]').click();
  expect(await page.evaluate(() => window.__fall.lookahead)).toBe(5);
  // ✏️ Editar notas: a tapped note shows the edit bar, even with the panels hidden.
  await menu.locator('[data-qm="edit"]').click();
  await expect(menu).toBeHidden();
  await page.evaluate(() => { document.querySelector("#sc-audio").currentTime = 2.0; });
  await expect.poll(() => page.evaluate(() => window.__fall.hits.length)).toBeGreaterThan(2);
  const a = await page.evaluate(() => {
    const r = document.querySelector(".sc-fall-canvas").getBoundingClientRect();
    const h = [...window.__fall.hits].sort((a, b) => b.h - a.h)[0];
    return { x: r.left + h.x + h.w / 2, y: r.top + Math.max(h.y, 0) + 10 };
  });
  await page.mouse.click(a.x, a.y);
  await expect(page.locator("#sc-editbar")).toBeVisible();
  await page.locator("#sc-edit-clear").click();
  // ＋ Agregar nota.
  await gear.click();
  await menu.locator('[data-qm="add"]').click();
  expect(await page.evaluate(() => window.__score.adding)).toBe(true);
  await page.keyboard.press("Escape");
  // Left alone, the menu closes by itself.
  await gear.click();
  await expect(menu).toBeVisible();
  await page.waitForTimeout(6500);
  await expect(menu).toBeHidden();
  // ▤ Mostrar paneles.
  await gear.click();
  await menu.locator('[data-qm="panels"]').click();
  await expect(page.locator(".sc-transport")).toBeVisible();
  await expect(gear).toBeHidden();
});

test("🎷 Saxo: the piano as a saxophone line, notes flying to the horn, its keys lit, written for the saxophone", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/sax/?job=5c0de0000001&stems=piano");
  await page.waitForFunction(() => window.__sax?.notes?.length > 0);
  const st = await page.evaluate(() => ({ n: window.__sax.notes.length, mono: window.__sax.notes.every((x, i, a) => i === 0 || x.start >= a[i - 1].end) }));
  expect(st.n).toBeGreaterThan(10);
  expect(st.mono).toBe(true); // one note at a time
  await expect(page.locator('#sx-stems [data-stem="piano"]')).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("#sx-sub")).toContainText("Alto");
  // A moment with a note sounding: its keys lit on the horn, its name below, first in the strip.
  const at = await page.evaluate(() => { const n = window.__sax.notes[3]; return (n.start + n.end) / 2; });
  await page.evaluate((t) => { document.querySelector("#sx-audio").currentTime = t; }, at);
  await expect.poll(() => page.locator(".sx-key.on").count()).toBeGreaterThan(0);
  await expect(page.locator(".sx-chip.now")).toHaveCount(1);
  const alto = await page.locator("#sx-now-name").textContent();
  await expect(page.locator("#sx-now-sub")).toContainText("suena");
  // Another saxophone: the same sound, written otherwise.
  await page.locator("#sx-type").selectOption("tenor");
  await expect.poll(() => page.locator("#sx-now-name").textContent()).not.toBe(alto);
  await expect(page.locator("#sx-sub")).toContainText("Tenor");
  // Only the piano in this song: nothing else to play under it; it still plays (silent clock).
  await page.locator("#sx-play").click();
  await expect.poll(() => page.evaluate(() => window.__sax.playing)).toBe(true);
  await page.waitForTimeout(800);
  expect(await page.evaluate(() => document.querySelector("#sx-audio").currentTime)).toBeGreaterThan(at);
  await page.locator("#sx-play").click();
  // Remembered: the saxophone chosen.
  await page.reload();
  await page.waitForFunction(() => window.__sax?.notes?.length > 0);
  await expect(page.locator("#sx-type")).toHaveValue("tenor");
  // The fingering chart by default (the photograph is one choice away), and the recorded notes loaded.
  await expect(page.locator(".sx-chart")).toHaveCount(1);
  await expect(page.locator("#sx-sound-state")).toContainText("Saxo real", { timeout: 30_000 });
  // «Como suenan»: the names of the song's own notes, not the saxophone's.
  await page.locator("#sx-type").selectOption("alto");
  await page.evaluate((t) => { document.querySelector("#sx-audio").currentTime = t; }, at);
  await expect.poll(() => page.locator("#sx-now-sub").textContent()).toContain("suena");
  await page.locator("#sx-view").selectOption("concert");
  await expect(page.locator("#sx-now-sub")).toContainText("en tu saxo");
  await page.locator("#sx-view").selectOption("written");
  expect(errors).toEqual([]);
});

test("🎷 Saxo: changing what plays under it while it plays goes on playing (it stuck, until a reload)", async ({ page }) => {
  // Two different files for «Saxo + resto» and «Canción original» (the seed
  // has only a piano): changing the source mid-play is what stuck.
  const piano = await (await page.request.get("/api/jobs/5c0de0000001/score/audio/piano.flac")).body();
  for (const url of ["**/sax/backing.flac*", "**/score/audio/mix.flac"]) {
    await page.route(url, (r) => r.fulfill({ status: 200, contentType: "audio/flac", body: piano }));
  }
  await page.goto("/sax/?job=5c0de0000001&stems=piano");
  await page.waitForFunction(() => window.__sax?.notes?.length > 0 && document.querySelector("#sx-audio").readyState >= 1);
  await page.locator("#sx-play").click();
  await expect.poll(() => page.evaluate(() => window.__sax.playing)).toBe(true);
  await page.waitForTimeout(1200);
  const t1 = await page.evaluate(() => document.querySelector("#sx-audio").currentTime);
  await page.locator("#sx-sound").selectOption("original");
  await page.waitForTimeout(1500);
  const after = await page.evaluate(() => ({ t: document.querySelector("#sx-audio").currentTime, paused: document.querySelector("#sx-audio").paused, playing: window.__sax.playing }));
  expect(after.paused).toBe(false);
  expect(after.playing).toBe(true);
  expect(after.t).toBeGreaterThan(t1); // where it was, and on
  await page.locator("#sx-sound").selectOption("sax-rest");
  await page.waitForTimeout(1200);
  expect(await page.evaluate(() => document.querySelector("#sx-audio").paused)).toBe(false);
  // ▶ still answers.
  await page.locator("#sx-play").click();
  await expect.poll(() => page.evaluate(() => document.querySelector("#sx-audio").paused)).toBe(true);
  await page.locator("#sx-play").click();
  await expect.poll(() => page.evaluate(() => document.querySelector("#sx-audio").paused)).toBe(false);
});

test("🎷 Saxo Bucle: A and B at the bars sounding, past B back to A, kept for the next visit, cleared", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const JOB = "5c0de0000001";
  await page.goto(`/sax/?job=${JOB}&stems=piano`);
  await page.evaluate(() => localStorage.removeItem("stemdeck.sax.loop.5c0de0000001"));
  await page.reload();
  await page.waitForFunction(() => window.__sax?.notes?.length > 5 && window.__sax.bars && document.querySelector("#sx-audio").readyState >= 1);
  const at = (t) => page.evaluate((x) => { document.querySelector("#sx-audio").currentTime = x; return new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))); }, t);
  await expect(page.locator("#sx-loop-on")).toBeDisabled();
  // The fixture: 90 BPM in 4 from 1 s: bar 2 is 3.667-6.333, bar 3 is 6.333-9.
  await at(4.0);
  await page.locator("#sx-loop-a").click();
  await expect(page.locator("#sx-loop-info")).toContainText("desde 0:03");
  await at(7.0);
  await page.locator("#sx-loop-b").click();
  const loop = await page.evaluate(() => ({ ...window.__saxLoop }));
  expect(loop.a).toBeCloseTo(3.6667, 2);
  expect(loop.b).toBeCloseTo(9.0, 2);
  expect(loop.on).toBe(true);
  await expect(page.locator("#sx-loop-info")).toHaveText("compases 2–3");
  await expect(page.locator("#sx-loop-on")).toHaveAttribute("aria-pressed", "true");
  expect(await page.evaluate(() => window.__saxLane.loop)).toEqual({ a: loop.a, b: loop.b });
  // Playing past B: back to A.
  await at(8.7);
  await page.locator("#sx-play").click();
  await expect.poll(() => page.evaluate(() => document.querySelector("#sx-audio").currentTime), { timeout: 8000 }).toBeLessThan(6);
  expect(await page.evaluate(() => document.querySelector("#sx-audio").currentTime)).toBeGreaterThanOrEqual(3.6);
  await page.locator("#sx-play").click();
  // Kept for the next visit; 🔁 turns it off without losing it; ✕ takes it away.
  await page.reload();
  await page.waitForFunction(() => window.__sax?.notes?.length > 5 && window.__sax.bars);
  await expect(page.locator("#sx-loop-info")).toHaveText("compases 2–3");
  await page.locator("#sx-loop-on").click();
  expect(await page.evaluate(() => window.__saxLane.loop)).toBe(null);
  await expect(page.locator("#sx-loop-info")).toHaveText("compases 2–3");
  await page.locator("#sx-loop-clear").click();
  await expect(page.locator("#sx-loop-info")).toHaveText("");
  await expect(page.locator("#sx-loop-on")).toBeDisabled();
  expect(await page.evaluate(() => localStorage.getItem("stemdeck.sax.loop.5c0de0000001"))).toBe(null);
  expect(errors).toEqual([]);
});

test("🎷 Saxo Metrónomo y Cuenta: a click on each beat of the song, the bar's first accented; a bar counted before ▶", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(`/sax/?job=5c0de0000001&stems=piano`);
  await page.waitForFunction(() => window.__sax?.notes?.length > 5 && window.__sax.bars && document.querySelector("#sx-audio").readyState >= 1);
  await expect(page.locator("#sx-metronome")).toBeVisible();
  // «🎚 Sonido»: what is set once is in a menu of its own, out of the bar.
  await expect(page.locator("#sx-expression")).toBeHidden();
  await page.locator("#sx-sound-toggle").click();
  await expect(page.locator("#sx-expression")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator("#sx-expression")).toBeHidden();
  await expect(page.locator("#sx-sound")).toBeVisible(); // «Escuchar» stays at hand
  await page.evaluate(() => { document.querySelector("#sx-audio").currentTime = 0.8; });
  await page.locator("#sx-metronome").check();
  await page.locator("#sx-play").click();
  // The fixture: 90 BPM in 4 from 1 s (a beat every 0.667 s).
  await expect.poll(() => page.evaluate(() => window.__saxMetro.clicks.length), { timeout: 8000 }).toBeGreaterThanOrEqual(5);
  await page.locator("#sx-play").click();
  const clicks = await page.evaluate(() => window.__saxMetro.clicks.slice(0, 5));
  expect(clicks.map((c) => Number(c.t.toFixed(2)))).toEqual([1, 1.67, 2.33, 3, 3.67]);
  expect(clicks.map((c) => c.accent)).toEqual([true, false, false, false, true]);
  // «Cuenta: 1 compás»: four clicks at the tempo, the song starting after them.
  await page.locator("#sx-metronome").uncheck();
  await page.locator("#sx-countin").selectOption("bar");
  await page.evaluate(() => { document.querySelector("#sx-audio").currentTime = 4; });
  await page.locator("#sx-play").click();
  await expect(page.locator("#sx-play")).toHaveText("…");
  await page.waitForTimeout(1500);
  expect(await page.evaluate(() => document.querySelector("#sx-audio").paused)).toBe(true); // still counting (2.67 s)
  expect(await page.evaluate(() => window.__saxMetro.counted)).toBe(4);
  await expect.poll(() => page.evaluate(() => !document.querySelector("#sx-audio").paused), { timeout: 5000 }).toBe(true);
  await page.locator("#sx-play").click();
  // ▶ again during the count calls it off.
  await page.locator("#sx-play").click();
  await expect(page.locator("#sx-play")).toHaveText("…");
  await page.locator("#sx-play").click();
  await expect(page.locator("#sx-play")).toHaveText("▶");
  await page.waitForTimeout(3000);
  expect(await page.evaluate(() => document.querySelector("#sx-audio").paused)).toBe(true);
  await page.locator("#sx-countin").selectOption("0");
  expect(errors).toEqual([]);
});

test("🎷 Saxo on a tablet: the notation folds into «⚙ Notas» (one header row), the fingering panel can be put away", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(`/sax/?job=5c0de0000001&stems=piano`);
  await page.evaluate(() => { const p = JSON.parse(localStorage.getItem("stemdeck.sax") || "{}"); delete p.hornHidden; localStorage.setItem("stemdeck.sax", JSON.stringify(p)); });
  await page.waitForFunction(() => window.__sax?.notes?.length > 5 && window.__saxLane.hits.length > 3);
  // Wide: the three settings in the header, no menu button.
  await expect(page.locator("#sx-view")).toBeVisible();
  await expect(page.locator("#sx-notation-toggle")).toBeHidden();
  const tall = (await page.locator(".sx-chart svg").boundingBox()).height;
  // A tablet: folded; the header is one row and the chart keeps its height in a shorter window.
  await page.setViewportSize({ width: 1024, height: 768 });
  await expect(page.locator("#sx-view")).toBeHidden();
  expect((await page.locator(".sx-top").boundingBox()).height).toBeLessThan(70);
  await page.locator("#sx-notation-toggle").click();
  await expect(page.locator("#sx-view")).toBeVisible();
  await page.locator("#sx-view").selectOption("concert");
  expect(await page.evaluate(() => window.__saxLane.concert)).toBe(true);
  await page.locator("#sx-view").selectOption("written");
  await page.keyboard.press("Escape");
  await expect(page.locator("#sx-view")).toBeHidden();
  // Narrower, the button wraps to the left of the header: the menu opens toward the room there is.
  await page.setViewportSize({ width: 700, height: 768 });
  await page.locator("#sx-notation-toggle").click();
  const menu = await page.locator("#sx-notation-menu").boundingBox();
  expect(menu.x).toBeGreaterThanOrEqual(0);
  expect(menu.x + menu.width).toBeLessThanOrEqual(700);
  await page.keyboard.press("Escape");
  await page.setViewportSize({ width: 1024, height: 768 });
  expect((await page.locator(".sx-chart svg").boundingBox()).height).toBeGreaterThan(380);
  expect(tall).toBeGreaterThan(380);
  // The fingering panel put away: the staff takes the whole width; back with the tab.
  const before = (await page.locator("#sx-lane").boundingBox()).width;
  await page.locator("#sx-horn-hide").click();
  await expect(page.locator("#sx-horn-panel")).toBeHidden();
  await expect.poll(async () => (await page.locator("#sx-lane").boundingBox()).width).toBeGreaterThan(before + 150);
  await page.reload(); // kept
  await page.waitForFunction(() => window.__sax?.notes?.length > 5);
  await expect(page.locator("#sx-horn-panel")).toBeHidden();
  await page.locator("#sx-horn-show").click();
  await expect(page.locator("#sx-horn-panel")).toBeVisible();
  expect(errors).toEqual([]);
});

test("🎷 Saxo ✏️ Editar, varias notas: picked with Mayús or «Varias» or a box, moved and deleted together (one ↶), joined into one", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const JOB = "5c0de0000001";
  await page.request.put(`/api/jobs/${JOB}/sax/edits`, { data: { set: "piano|clean", edits: {} } });
  await page.goto(`/sax/?job=${JOB}&stems=piano`);
  await page.waitForFunction(() => window.__sax?.notes?.length > 5 && window.__saxLane.hits.length > 3);
  await page.locator("#sx-edit").click();
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
  const box = await page.locator("#sx-lane").boundingBox();
  const hit = (i) => page.evaluate((k) => window.__saxLane.hits[k], i);
  const tap = async (i, { shift = false } = {}) => {
    const h = await hit(i);
    if (shift) await page.keyboard.down("Shift");
    await page.mouse.click(box.x + h.x + Math.min(h.w / 2, 12), box.y + h.y + h.h / 2);
    if (shift) await page.keyboard.up("Shift");
    return h;
  };
  const picked = () => page.evaluate(() => [window.__saxEdit.selected, ...window.__saxEdit.more].filter(Boolean).sort());
  const note = (key) => page.evaluate((k) => { const n = window.__sax.notes.find((x) => x.key === k); return n ? { midi: n.midi, start: n.start, end: n.end } : null; }, key);
  // Mayús + clic: two notes picked; ↑ moves both; one ↶ takes both back.
  const a = await tap(1);
  const b = await tap(2, { shift: true });
  expect(await picked()).toEqual([a.key, b.key].sort());
  await expect(page.locator("#sx-edit-info")).toHaveText("2 notas elegidas");
  await expect(page.locator("#sx-join")).toBeEnabled();
  await page.keyboard.press("ArrowUp");
  expect((await note(a.key)).midi).toBe(a.midi + 1);
  expect((await note(b.key)).midi).toBe(b.midi + 1);
  await page.keyboard.press("Control+z");
  expect((await note(a.key)).midi).toBe(a.midi);
  expect((await note(b.key)).midi).toBe(b.midi);
  // Mayús + clic again on one: out of the group.
  await tap(2, { shift: true });
  expect(await picked()).toEqual([a.key]);
  // «Unir»: the two become one, from the first's start to the second's end.
  await tap(2, { shift: true });
  const [na, nb] = [await note(a.key), await note(b.key)];
  const count = await page.evaluate(() => window.__sax.notes.length);
  await page.locator("#sx-join").click();
  expect(await page.evaluate(() => window.__sax.notes.length)).toBe(count - 1);
  expect((await note(a.key)).start).toBeCloseTo(na.start, 2);
  expect((await note(a.key)).end).toBeCloseTo(nb.end, 2);
  expect(await note(b.key)).toBe(null);
  await page.keyboard.press("Control+z");
  expect(await page.evaluate(() => window.__sax.notes.length)).toBe(count);
  // «Varias»: taps add up; a box dragged over the staff picks what is in it.
  await page.keyboard.press("Escape");
  await page.locator("#sx-multi").click();
  await expect(page.locator("#sx-edit-info")).toHaveText("Toca las notas");
  await tap(3);
  await tap(4);
  expect((await picked()).length).toBe(2);
  await page.keyboard.press("Escape");
  const hits = await page.evaluate(() => window.__saxLane.hits.slice(0, 5));
  const x0 = Math.min(...hits.map((h) => h.x)) - 6;
  const x1 = Math.max(...hits.map((h) => h.x + h.w)) + 6;
  await page.mouse.move(box.x + x0, box.y + box.height - 12);
  await page.mouse.down();
  await page.mouse.move(box.x + (x0 + x1) / 2, box.y + box.height / 2, { steps: 4 });
  await page.mouse.move(box.x + x1, box.y + 30, { steps: 4 });
  // The notes the box covers (it spans the staff's height: any note in those seconds).
  const inBox = await page.evaluate(([a, b]) => window.__saxLane.hits.filter((h) => h.x + h.w >= a && h.x <= b).length, [x0, x1]);
  await page.mouse.up();
  expect(inBox).toBeGreaterThanOrEqual(5);
  expect((await picked()).length).toBe(inBox);
  // 🗑: all of them, one change undone at once.
  await page.locator("#sx-del").click();
  expect(await page.evaluate(() => window.__sax.notes.length)).toBe(count - inBox);
  await page.locator("#sx-undo").click();
  expect(await page.evaluate(() => window.__sax.notes.length)).toBe(count);
  // Ctrl+A: every note.
  await page.locator("#sx-multi").click();
  await page.keyboard.press("Control+a");
  expect((await picked()).length).toBe(count);
  expect(errors).toEqual([]);
});

test("🎷 Saxo: the part written out, MusicXML downloaded and printed as A4 pages (with the edits)", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const JOB = "5c0de0000001";
  await page.request.put(`/api/jobs/${JOB}/sax/edits`, { data: { set: "piano|clean", edits: {} } });
  await page.goto(`/sax/?job=${JOB}&stems=piano`);
  await page.waitForFunction(() => window.__sax?.notes?.length > 5);
  // MusicXML: a file named for the song and the saxophone, one treble staff.
  const [download] = await Promise.all([page.waitForEvent("download"), page.locator("#sx-part-xml").click()]);
  expect(download.suggestedFilename()).toMatch(/saxo alto\.musicxml$/);
  const xml = (await import("node:fs")).readFileSync(await download.path(), "utf8");
  expect(xml).toContain("<part-name>Saxofón alto en Mi♭</part-name>");
  expect(xml).not.toContain("<staves>");
  // PDF: the print dialog with the part laid out in pages (print itself stubbed).
  await page.evaluate(() => { window.__printed = 0; window.print = () => { window.__printed += 1; }; });
  await page.locator("#sx-part-pdf").click();
  await expect.poll(() => page.evaluate(() => window.__printed), { timeout: 20000 }).toBe(1);
  const pages = await page.locator("#sx-print .sx-print-page svg").count();
  expect(pages).toBeGreaterThanOrEqual(1);
  expect(await page.locator("#sx-print .note").count()).toBeGreaterThan(5);
  await expect(page.locator("#sx-part-pdf")).toHaveText("🖨 PDF");
  // Printed: only the part, on A4.
  await page.emulateMedia({ media: "print" });
  await expect(page.locator(".sx-stage")).toBeHidden();
  await expect(page.locator("#sx-print")).toBeVisible();
  await page.emulateMedia({ media: "screen" });
  await expect(page.locator("#sx-print")).toBeHidden();
  expect(errors).toEqual([]);
});

test("🎷 Saxo ✏️ Editar ＋ Nota: a note put in (button, double tap), moved, stretched, kept, taken out", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const JOB = "5c0de0000001";
  await page.request.put(`/api/jobs/${JOB}/sax/edits`, { data: { set: "piano|clean", edits: {} } });
  await page.goto(`/sax/?job=${JOB}&stems=piano`);
  await page.waitForFunction(() => window.__sax?.notes?.length > 5 && window.__saxLane.hits.length > 3);
  const n0 = await page.evaluate(() => window.__sax.notes.length);
  await page.locator("#sx-edit").click();
  // The edit bar is a row above the staff, not over it (it covered the high notes).
  const bar = await page.locator("#sx-editbar").boundingBox();
  const staff = await page.locator("#sx-lane").boundingBox();
  expect(bar.y + bar.height).toBeLessThanOrEqual(staff.y + 1);
  expect(await page.evaluate(() => Math.abs(window.__saxLane.size.h - document.getElementById("sx-lane").clientHeight))).toBeLessThanOrEqual(1);
  // «＋ Nota»: one more note, where the song is, picked.
  await page.locator("#sx-add").click();
  const added = () => page.evaluate(() => window.__sax.notes.filter((n) => n.added).map((n) => ({ key: n.key, midi: n.midi, start: n.start, len: +(n.end - n.start).toFixed(2) })));
  let a = await added();
  expect(a.length).toBe(1);
  expect(await page.evaluate(() => window.__saxEdit.selected)).toBe(a[0].key);
  expect(a[0].len).toBe(0.4);
  // Moved and stretched like any other.
  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("Alt+ArrowRight");
  const b = (await added())[0];
  expect(b.midi).toBe(a[0].midi + 1);
  expect(b.len).toBe(0.5);
  // A double tap on the empty lane: another, at that moment.
  const box = await page.locator("#sx-lane").boundingBox();
  const free = await page.evaluate(() => {
    const hits = window.__saxLane.hits;
    const y = window.__saxLane.size.h - 24; // clear of the edit bar, which floats over the top
    for (let x = 400; x < 900; x += 20) if (!hits.some((h) => x >= h.x - 8 && x <= h.x + h.w + 8 && y >= h.y - 10 && y <= h.y + h.h + 10)) return { x, y };
    return null;
  });
  await page.mouse.dblclick(box.x + free.x, box.y + free.y);
  expect((await added()).length).toBe(2);
  // Kept for the next visit.
  await page.waitForTimeout(800);
  await page.reload();
  await page.waitForFunction(() => window.__sax?.notes?.length > 5);
  expect((await added()).length).toBe(2);
  const saved = await (await page.request.get(`/api/jobs/${JOB}/sax/edits`)).json();
  expect(Object.values(saved.sets["piano|clean"]).filter((e) => e.add).length).toBe(2);
  // 🗑 takes one out for good; «Volver al original» the rest.
  await page.locator("#sx-edit").click();
  await page.evaluate((k) => window.__saxEdit.selected = k, b.key);
  await page.locator("#sx-add").click(); // the same place: picks the one there
  await page.locator("#sx-reset").click();
  expect((await added()).length).toBe(0);
  expect(await page.evaluate(() => window.__sax.notes.length)).toBe(n0);
  await page.waitForTimeout(800);
  expect(errors).toEqual([]);
});

test("🎷 Saxo ✏️ Editar: a note taken out, moved, undone, kept for the next visit, back to the original", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const JOB = "5c0de0000001";
  await page.request.put(`/api/jobs/${JOB}/sax/edits`, { data: { set: "piano|clean", edits: {} } });
  await page.goto(`/sax/?job=${JOB}&stems=piano`);
  await page.waitForFunction(() => window.__sax?.notes?.length > 5 && window.__saxLane.hits.length > 3);
  const original = await page.evaluate(() => window.__sax.notes.map((n) => `${n.key}:${n.midi}`).join());
  await page.locator("#sx-edit").click();
  await expect(page.locator("#sx-editbar")).toBeVisible();
  await expect(page.locator("#sx-del")).toBeDisabled();
  // A tap on a note picks it.
  const box = await page.locator("#sx-lane").boundingBox();
  const tap = async (i) => {
    const h = await page.evaluate((k) => window.__saxLane.hits[k], i);
    await page.mouse.click(box.x + h.x + Math.min(h.w / 2, 12), box.y + h.y + h.h / 2);
    return h;
  };
  const h = await tap(2);
  await expect.poll(() => page.evaluate(() => window.__saxEdit.selected)).toBe(h.key);
  await expect(page.locator("#sx-del")).toBeEnabled();
  const midiOf = (key) => page.evaluate((k) => window.__sax.notes.find((n) => n.key === k)?.midi ?? null, key);
  // ↑ a semitone, then 🗑: one change (the note is out).
  await page.keyboard.press("ArrowUp");
  expect(await midiOf(h.key)).toBe(h.midi + 1);
  await expect(page.locator("#sx-edit-count")).toHaveText("1 cambio");
  const n = await page.evaluate(() => window.__sax.notes.length);
  await page.locator("#sx-del").click();
  expect(await page.evaluate(() => window.__sax.notes.length)).toBe(n - 1);
  expect(await midiOf(h.key)).toBe(null);
  // The next note is picked: a run of wrong notes goes one tap each.
  expect(await page.evaluate(() => window.__saxEdit.selected)).not.toBe(h.key);
  // Ctrl+Z twice: back where it was; Ctrl+Y: moved again.
  await page.keyboard.press("Control+z");
  expect(await midiOf(h.key)).toBe(h.midi + 1);
  await page.locator("#sx-undo").click();
  expect(await midiOf(h.key)).toBe(h.midi);
  await expect(page.locator("#sx-edit-count")).toHaveText("");
  await page.keyboard.press("Control+y");
  expect(await midiOf(h.key)).toBe(h.midi + 1);
  // Dragged down: by semitones (an octave is 7 staff steps).
  const h2 = await tap(4);
  const semitone = await page.evaluate(() => (window.__saxLane.geometry().hs * 7) / 12);
  const x = box.x + h2.x + Math.min(h2.w / 2, 12);
  const y = box.y + h2.y + h2.h / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x, y + semitone * 1.1, { steps: 3 });
  await page.mouse.move(x, y + semitone * 2.1, { steps: 3 });
  await page.mouse.up();
  expect(await midiOf(h2.key)).toBe(h2.midi - 2);
  await expect(page.locator("#sx-edit-count")).toHaveText("2 cambios");
  // Kept: on the next visit the line has them.
  await page.waitForTimeout(800);
  await page.reload();
  await page.waitForFunction(() => window.__sax?.notes?.length > 5);
  expect(await midiOf(h.key)).toBe(h.midi + 1);
  expect(await midiOf(h2.key)).toBe(h2.midi - 2);
  // «Volver al original»: as the line was made (and kept so).
  await page.locator("#sx-edit").click();
  await page.locator("#sx-reset").click();
  expect(await page.evaluate(() => window.__sax.notes.map((n) => `${n.key}:${n.midi}`).join())).toBe(original);
  await page.waitForTimeout(800);
  const saved = await (await page.request.get(`/api/jobs/${JOB}/sax/edits`)).json();
  expect(saved.sets["piano|clean"]).toBeUndefined();
  expect(errors).toEqual([]);
});

test("🎷 Saxo: the lane dragged moves the song; a note made longer and shorter; the strip by phrases; the chart or the photo", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const JOB = "5c0de0000001";
  await page.request.put(`/api/jobs/${JOB}/sax/edits`, { data: { set: "piano|clean", edits: {} } });
  await page.goto(`/sax/?job=${JOB}&stems=piano`);
  await page.waitForFunction(() => window.__sax?.notes?.length > 5 && window.__saxLane.hits.length > 3 && document.querySelector("#sx-audio").readyState >= 1);
  // Dragged left on the lane: the song goes on by what moved under the pointer.
  let box = await page.locator("#sx-lane").boundingBox();
  const t0 = await page.evaluate(() => document.querySelector("#sx-audio").currentTime);
  const pps = await page.evaluate(() => (window.__saxLane.size.w - 64) / window.__saxLane.lookahead);
  const y = box.y + 12; // above the notes
  await page.mouse.move(box.x + 700, y);
  await page.mouse.down();
  await page.mouse.move(box.x + 600, y, { steps: 4 });
  await page.mouse.move(box.x + 500, y, { steps: 4 });
  await page.mouse.up();
  const t1 = await page.evaluate(() => document.querySelector("#sx-audio").currentTime);
  expect(t1 - t0).toBeGreaterThan((200 / pps) * 0.8);
  expect(t1 - t0).toBeLessThan((200 / pps) * 1.2);
  // The song's rhythm on the staff: a line where each bar starts, numbered
  // (the fixture: 90 BPM in 4, the first bar at 1 s, so a bar every 2.667 s).
  const marks = await page.evaluate(() => window.__saxLane.barMarks);
  expect(marks.length).toBeGreaterThan(0);
  expect(marks.map((m) => m.bar)).toEqual([...marks.keys()].map((k) => marks[0].bar + k));
  if (marks.length > 1) expect(marks[1].x - marks[0].x).toBeCloseTo((4 * 60 / 90) * pps, 0);
  // The strip: the group being played, one colour; it does not change at every note.
  await expect(page.locator("#sx-next .sx-chip[data-i]").first()).toBeVisible();
  const group = await page.evaluate(() => { const n = window.__sax.notes.find((x) => x.start > document.querySelector("#sx-audio").currentTime + 0.5); return window.__sax.groups[n.g].length; });
  expect(group).toBeGreaterThan(0);
  expect(group).toBeLessThanOrEqual(10);
  // «Editar»: longer with Alt+→, shorter with ⇤, and by its right end dragged.
  await page.locator("#sx-edit").click();
  // The edit bar is a row above the staff: the staff is lower, and drawn again.
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
  box = await page.locator("#sx-lane").boundingBox();
  const h = await page.evaluate(() => window.__saxLane.hits[2]);
  await page.mouse.click(box.x + h.x + Math.min(h.w / 3, 8), box.y + h.y + h.h / 2);
  await expect.poll(() => page.evaluate(() => window.__saxEdit.selected)).toBe(h.key);
  // Picking a note does not move the staff (the bar keeps its height).
  expect((await page.locator("#sx-lane").boundingBox()).y).toBe(box.y);
  const len = () => page.evaluate((k) => { const n = window.__sax.notes.find((x) => x.key === k); return n.end - n.start; }, h.key);
  const l0 = await len();
  await page.keyboard.press("Alt+ArrowRight");
  expect(await len()).toBeCloseTo(l0 + 0.1, 2);
  await page.locator("#sx-shorter").click();
  await page.locator("#sx-shorter").click();
  expect(await len()).toBeCloseTo(Math.max(0.05, l0 - 0.1), 2);
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))); // the lane redrawn
  const h2 = await page.evaluate((k) => window.__saxLane.hits.find((x) => x.key === k), h.key);
  const ex = box.x + h2.x + h2.w - 2;
  const ey = box.y + h2.y + h2.h / 2;
  await page.mouse.move(ex, ey);
  await page.mouse.down();
  await page.mouse.move(ex + pps * 0.25, ey, { steps: 4 });
  await page.mouse.move(ex + pps * 0.5, ey, { steps: 4 });
  await page.mouse.up();
  expect(await len()).toBeGreaterThan(Math.max(0.05, l0 - 0.1) + 0.3);
  // Back to the original, and the photograph back with one choice.
  await page.locator("#sx-reset").click();
  expect(await len()).toBeCloseTo(l0, 2);
  await expect(page.locator(".sx-chart")).toHaveCount(1);
  await expect(page.locator("#sx-horn-switch")).toHaveText("🖼 Ver foto");
  await page.locator("#sx-horn-switch").click();
  await expect(page.locator(".sx-horn-photo")).toHaveCount(1);
  await expect.poll(() => page.locator(".sx-horn-img").evaluate((img) => img.complete && img.naturalWidth > 0)).toBe(true);
  await expect(page.locator(".sx-chart")).toHaveCount(0);
  await page.reload();
  await expect(page.locator(".sx-horn-photo")).toHaveCount(1);
  await expect(page.locator("#sx-horn-switch")).toHaveText("▦ Ver diagrama");
  await page.locator("#sx-horn-switch").click();
  await expect(page.locator(".sx-chart")).toHaveCount(1);
  expect(errors).toEqual([]);
});
