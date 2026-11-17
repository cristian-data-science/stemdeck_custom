// What an import is doing, step by step, read from the job's state: the
// steps the pipeline runs (app/pipeline/runner.py), which are done (each
// writes its time into `stage_timings` when it ends), which one runs now and
// how far along it is. No DOM here: jobProgress.js draws it, and
// tests/js/job-steps.test.mjs checks it.

export const PROCESSING = new Set(["queued", "downloading", "analyzing", "separating", "processing"]);

// `keys`: the stage_timings entries the step writes; it is done when the last
// one is there. `weight`: its share of the whole bar, roughly its share of
// the time on a GPU (separation is most of it).
function plan(state) {
  const upload = String(state.source_url || "").startsWith("local:");
  const solo = state.separator === "none";
  const steps = [
    upload ? { id: "prepare", keys: ["prepare"], weight: 4 } : { id: "download", keys: ["download"], weight: 12 },
    { id: "analyze", keys: ["analyze"], weight: 6 },
    solo ? { id: "solo", keys: ["separate"], weight: 4 } : { id: "separate", keys: ["separate"], weight: 55 },
    { id: "mix", keys: ["post"], weight: 8 },
    { id: "beats", keys: ["beatgrid"], weight: 5 },
  ];
  if (state.auto_sections) steps.push({ id: "sections", keys: ["sections"], weight: 6 });
  // Identify, lyrics, their transcription and timing: one step for the
  // reader. A solo piano import has no words.
  if (!solo) steps.push({ id: "lyrics", keys: ["identify_wait", "lyrics_wait", "transcribe", "retime"], weight: 8 });
  return steps;
}

/** The fraction a running step reports itself, or null (it says nothing). */
function ownFraction(step, state) {
  const p = Number(state.progress);
  if (!Number.isFinite(p)) return null;
  if (step.id === "download" && state.status === "downloading") return Math.max(0, Math.min(1, p));
  if (step.id === "separate" && state.status === "separating") return Math.max(0, Math.min(1, p));
  return null;
}

/**
 * The steps of this job: [{id, state: "done"|"now"|"next", seconds?, fraction?}]
 * and the whole: {steps, current, overall (0..1), queued, finished}.
 * `elapsed`: seconds the current step has been running (as seen by the page),
 * for an estimate of the steps that report no progress of their own.
 */
export function jobSteps(state, elapsed = 0) {
  const timings = state.stage_timings || {};
  const steps = plan(state);
  const queued = state.status === "queued";
  const finished = state.status === "done";
  let current = null;
  let doneWeight = 0;
  let total = 0;
  const out = steps.map((s) => {
    total += s.weight;
    const done = finished || s.keys[s.keys.length - 1] in timings;
    if (done) {
      doneWeight += s.weight;
      const seconds = s.keys.reduce((sum, k) => sum + (Number(timings[k]) || 0), 0);
      return { id: s.id, state: "done", seconds, weight: s.weight };
    }
    if (!current && !queued) {
      current = { id: s.id, state: "now", fraction: ownFraction(s, state), weight: s.weight };
      return current;
    }
    return { id: s.id, state: "next", weight: s.weight };
  });
  let overall = finished ? 1 : doneWeight / total;
  if (current) {
    // A step that says nothing of itself: creeping on with the time it takes
    // (never to its end), so the bar moves and never lies about being done.
    const f = current.fraction ?? 0.9 * (1 - Math.exp(-Math.max(0, elapsed) / 20));
    overall += (current.weight * f) / total;
  }
  return { steps: out, current: current?.id || null, overall: Math.min(1, overall), queued, finished };
}

/** The server's own words for what goes on, when they add something (a
 *  retry, the GPU giving up) as an i18n key and its values; else null. */
export function stageNote(stage) {
  const s = String(stage || "");
  let m = s.match(/^Network error .*\((\d+)\/(\d+)\)/);
  if (m) return { key: "jobProgress.note.network", vars: { n: m[1], of: m[2] } };
  if (/^Retrying with cookies/.test(s)) return { key: "jobProgress.note.cookies" };
  if (/^GPU failed/.test(s)) return { key: "jobProgress.note.gpuFailed" };
  m = s.match(/^Fetching video (\d+)%/);
  if (m) return { key: "jobProgress.note.video", vars: { pct: m[1] } };
  if (/^Fetching video/.test(s)) return { key: "jobProgress.note.video", vars: { pct: "…" } };
  return null;
}

/** "12 s", "1:05", "1:02:03". */
export function fmtSeconds(sec) {
  const s = Math.max(0, Math.round(Number(sec) || 0));
  if (s < 60) return `${s} s`;
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${r}` : `${m}:${r}`;
}
