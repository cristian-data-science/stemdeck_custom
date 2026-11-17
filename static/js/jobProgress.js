// The loading screen of a song being imported: what StemDeck is doing to it,
// step by step (jobSteps.js), each step opening as it starts, its progress,
// what it found (length, tempo, key) as it is found, and the time each took.
// Shown over the studio while the song is downloaded and separated (the
// import just started, or its row opened from the library), and only then:
// it goes when the song is ready, fails or is cancelled, or another track is
// opened. Nothing in it is a control.

import { t } from "./i18n.js";
import { formatKey } from "./keyLabel.js";
import { jobSteps, stageNote, fmtSeconds, PROCESSING } from "./jobSteps.js";

const POLL_MS = 800;
const STEM_VAR = { vocals: "--vocals", lead_vocals: "--vocals", backing_vocals: "--vocals", drums: "--drums", bass: "--bass", guitar: "--guitar", piano: "--piano", other: "--other" };

const view = {
  jobId: null,
  el: null,
  timer: 0,
  ticket: 0,
  onReady: null,
  last: null, // the job's latest state
  current: null, // the step running, and since when (page clock)
  since: 0,
  built: "", // the plan the list was built for
};

function host() {
  if (view.el) return view.el;
  const lanes = document.getElementById("lanes");
  if (!lanes) return null;
  const el = document.createElement("section");
  el.id = "job-progress";
  el.className = "jp hidden";
  el.setAttribute("role", "status");
  el.setAttribute("aria-live", "polite");
  el.innerHTML = `
    <div class="jp-card">
      <header class="jp-head">
        <div class="jp-art" aria-hidden="true"><img alt="" hidden><span class="jp-eq"><i></i><i></i><i></i><i></i><i></i></span></div>
        <div class="jp-titles">
          <div class="jp-kicker"></div>
          <h2 class="jp-title"></h2>
          <div class="jp-facts"></div>
        </div>
        <div class="jp-pct"><b></b><small></small></div>
      </header>
      <div class="jp-bar" aria-hidden="true"><i></i></div>
      <ol class="jp-steps"></ol>
      <p class="jp-foot"></p>
    </div>`;
  lanes.append(el);
  view.el = el;
  return el;
}

/** Show what `jobId` is going through, until it is ready. `onReady` runs
 *  when it is done and this screen still shows it (to open the song). */
export function showJobProgress(jobId, { title = "", thumb = "", onReady = null } = {}) {
  const el = host();
  if (!el || !jobId) return;
  if (view.jobId !== jobId) {
    view.jobId = jobId;
    view.last = { status: "queued", title, thumbnail: thumb };
    view.current = null;
    view.built = "";
    el.querySelector(".jp-steps").innerHTML = "";
    el.querySelector(".jp-facts").innerHTML = "";
    el.classList.remove("jp-failed");
  }
  view.onReady = onReady;
  document.getElementById("lanes")?.classList.add("jp-on");
  el.classList.remove("hidden");
  render();
  poll();
}

/** Gone (for `jobId` only, when given). */
export function hideJobProgress(jobId) {
  if (jobId && jobId !== view.jobId) return;
  clearTimeout(view.timer);
  view.ticket++;
  view.jobId = null;
  view.onReady = null;
  document.getElementById("lanes")?.classList.remove("jp-on");
  view.el?.classList.add("hidden");
}

export const jobProgressFor = () => view.jobId;

async function poll() {
  clearTimeout(view.timer);
  const ticket = ++view.ticket;
  const id = view.jobId;
  try {
    const r = await fetch(`/api/jobs/${id}`, { cache: "no-store" });
    if (ticket !== view.ticket) return;
    if (r.status === 404) return hideJobProgress(id);
    if (r.ok) view.last = await r.json();
  } catch {
    /* the next one */
  }
  if (ticket !== view.ticket) return;
  const s = view.last;
  if (s.status === "done") {
    render();
    const ready = view.onReady;
    // A moment on the finished list, then the song.
    view.timer = setTimeout(() => {
      if (view.jobId !== id) return;
      hideJobProgress(id);
      ready?.(id);
    }, 700);
    return;
  }
  if (s.status === "cancelled" || s.status === "stopped") return hideJobProgress(id);
  render();
  if (s.status === "error") return; // said on screen until another track is opened
  view.timer = setTimeout(poll, POLL_MS);
}

function stemLabel(name) {
  const key = name === "other" ? "stem.others" : `stem.${name}`;
  const s = t(key);
  return s === key ? name : s;
}

const stepText = (id, part) => t(`jobProgress.step.${id}.${part}`);

function separateDetail(s) {
  const model = s.separator === "roformer" ? "RoFormer" : "Demucs";
  const dev = String(s.compute_device || "");
  const where = dev.startsWith("cuda") ? t("jobProgress.onGpu") : dev.startsWith("cpu") ? t("jobProgress.onCpu") : "";
  return t("jobProgress.step.separate.detail", { model }) + (where ? ` · ${where}` : "");
}

function facts(s) {
  const out = [];
  if (s.duration) out.push(fmtClock(s.duration));
  if (s.bpm) out.push(`${s.bpm} BPM`);
  if (s.key) out.push(formatKey(s.key, s.scale, t));
  return out;
}

function fmtClock(sec) {
  const v = Math.round(sec);
  return `${Math.floor(v / 60)}:${String(v % 60).padStart(2, "0")}`;
}

function render() {
  const el = view.el;
  const s = view.last;
  if (!el || !s) return;
  const now = performance.now();
  const probe = jobSteps(s, 0);
  if (probe.current !== view.current) {
    view.current = probe.current;
    view.since = now;
  }
  const elapsed = (now - view.since) / 1000;
  const info = jobSteps(s, elapsed);
  const failed = s.status === "error";
  el.classList.toggle("jp-failed", failed);

  // Head: the song, what it is, the whole.
  el.querySelector(".jp-kicker").textContent = failed
    ? t("jobProgress.failed")
    : info.finished
      ? t("jobProgress.ready")
      : info.queued
        ? t("jobProgress.queued")
        : t("jobProgress.kicker");
  el.querySelector(".jp-title").textContent = s.title || t("job.processingTrackTitle");
  const img = el.querySelector(".jp-art img");
  if (s.thumbnail && img.getAttribute("src") !== s.thumbnail) img.src = s.thumbnail;
  img.hidden = !s.thumbnail;
  el.querySelector(".jp-eq").hidden = !!s.thumbnail;
  const factsEl = el.querySelector(".jp-facts");
  const f = facts(s);
  if (factsEl.dataset.sig !== f.join("|")) {
    // Each fact once, appearing as it is found.
    const had = new Set([...factsEl.children].map((c) => c.textContent));
    factsEl.innerHTML = "";
    for (const x of f) {
      const chip = document.createElement("span");
      chip.className = had.has(x) ? "jp-fact" : "jp-fact jp-new";
      chip.textContent = x;
      factsEl.append(chip);
    }
    factsEl.dataset.sig = f.join("|");
  }
  const pct = Math.floor(info.overall * 100);
  el.querySelector(".jp-pct b").textContent = failed ? "" : `${pct} %`;
  const started = Number(s.created_at) ? Date.now() / 1000 - Number(s.created_at) : 0;
  el.querySelector(".jp-pct small").textContent = started > 0 ? fmtSeconds(started) : "";
  el.querySelector(".jp-bar i").style.width = `${Math.max(1.5, info.overall * 100)}%`;

  // The steps: built once per plan, then only their classes and words move.
  const list = el.querySelector(".jp-steps");
  const plan = info.steps.map((x) => x.id).join(",");
  if (view.built !== plan) {
    list.innerHTML = "";
    info.steps.forEach((x, i) => {
      const li = document.createElement("li");
      li.className = "jp-step next";
      li.dataset.step = x.id;
      li.style.setProperty("--i", i);
      li.innerHTML = `
        <span class="jp-dot" aria-hidden="true"><svg viewBox="0 0 16 16"><path d="M3.5 8.5l3 3 6-7"/></svg></span>
        <div class="jp-body">
          <div class="jp-row"><span class="jp-label"></span><span class="jp-meta"></span></div>
          <div class="jp-detail"><div class="jp-detail-in">
            <p class="jp-what"></p>
            <div class="jp-mini" aria-hidden="true"><i></i></div>
            <div class="jp-stems"></div>
          </div></div>
        </div>`;
      li.querySelector(".jp-label").textContent = stepText(x.id, "label");
      list.append(li);
    });
    view.built = plan;
  }
  for (const x of info.steps) {
    const li = list.querySelector(`[data-step="${x.id}"]`);
    if (!li) continue;
    const st = failed && x.state === "now" ? "fail" : x.state;
    if (!li.classList.contains(st)) li.className = `jp-step ${st}`;
    const meta = li.querySelector(".jp-meta");
    if (x.state === "done") meta.textContent = fmtSeconds(x.seconds);
    else if (x.state === "now" && !failed) meta.textContent = x.fraction != null ? `${Math.floor(x.fraction * 100)} %` : fmtSeconds(elapsed);
    else meta.textContent = "";
    if (x.state !== "now") continue;
    const what = li.querySelector(".jp-what");
    const note = stageNote(s.stage);
    what.textContent = failed
      ? s.error || t("job.unknownError")
      : (x.id === "separate" ? separateDetail(s) : stepText(x.id, "detail")) + (note ? ` — ${t(note.key, note.vars)}` : "");
    const mini = li.querySelector(".jp-mini");
    mini.classList.toggle("jp-indet", x.fraction == null);
    mini.querySelector("i").style.width = x.fraction != null ? `${Math.max(2, x.fraction * 100)}%` : "";
    if (x.id === "separate") paintStems(li.querySelector(".jp-stems"), s, x.fraction);
  }
  // Separation done: its stems stay, lit.
  const sepLi = list.querySelector('[data-step="separate"].done .jp-stems');
  if (sepLi && !sepLi.dataset.done) {
    paintStems(sepLi, s, 1);
    sepLi.dataset.done = "1";
  }
  el.querySelector(".jp-foot").textContent = failed ? "" : info.queued ? t("jobProgress.footQueued") : t("jobProgress.foot");
}

/** The stems coming out: the separator makes them all at once, so they
 *  fill together, each in its colour. */
function paintStems(box, s, fraction) {
  const names = (s.selected_stems?.length ? s.selected_stems : ["vocals", "drums", "bass", "guitar", "piano", "other"]).filter((n) => n !== "original");
  if (box.dataset.sig !== names.join(",")) {
    box.innerHTML = "";
    names.forEach((n, i) => {
      const chip = document.createElement("span");
      chip.className = "jp-stem";
      chip.style.setProperty("--c", `var(${STEM_VAR[n] || "--other"})`);
      chip.style.setProperty("--i", i);
      chip.innerHTML = `<i></i><span></span>`;
      chip.querySelector("span").textContent = stemLabel(n);
      box.append(chip);
    });
    box.dataset.sig = names.join(",");
  }
  const f = fraction == null ? 0.5 : fraction;
  box.style.setProperty("--f", String(f));
  box.classList.toggle("jp-stems-done", f >= 1);
}

// Keep the clocks moving between two answers.
setInterval(() => {
  if (view.jobId && view.last && PROCESSING.has(view.last.status)) render();
}, 500);
