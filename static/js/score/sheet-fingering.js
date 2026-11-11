// Experimental (app/experimental/sheet, app/api/experimental.py): a song from
// a printed score, and a finger for every note in the falling-notes view.
//
// Everything here is opt-in: the landing's import box only shows when the
// server can read scores (Audiveris), and the fingers only for a song that has
// them (GET .../fingering answers {"available": false} for every other song,
// which then offers «Activar dedos» in the piano view, for that song alone).

/** The landing's «Importar partitura (experimental)» box. */
export async function wireSheetImport({ $, api }) {
  let info = null;
  try {
    info = await api("/api/experimental/sheet");
  } catch {
    return;
  }
  if (!info?.available) return;
  $("sc-sheet").hidden = false;
  const say = (text, kind = "") => {
    const el = $("sc-sheet-status");
    el.textContent = text;
    el.className = `sc-sheet-status ${kind}`;
  };
  $("sc-sheet-go").onclick = async () => {
    const file = $("sc-sheet-file").files?.[0];
    if (!file) return say("Elige un PDF o una imagen de la partitura.", "err");
    const fd = new FormData();
    fd.append("file", file);
    const bpm = Number($("sc-sheet-bpm").value);
    if (bpm) fd.append("bpm", String(bpm));
    const title = $("sc-sheet-title").value.trim();
    if (title) fd.append("title", title);
    $("sc-sheet-go").disabled = true;
    say("Subiendo…");
    try {
      const res = await fetch("/api/experimental/sheet", { method: "POST", body: fd });
      const r = await res.json();
      if (!res.ok) throw new Error(r.detail || res.statusText);
      const phases = { queued: "En cola…", omr: "Leyendo la partitura (Audiveris, ~30 s)…", audio: "Generando el audio con Pianoteq…" };
      for (;;) {
        await new Promise((ok) => setTimeout(ok, 1500));
        const st = await api(`/api/experimental/sheet/${r.import_id}`);
        if (st.state === "done") {
          const x = st.result;
          say(
            `Lista: ${x.measures} compases, ${x.notes} notas, ${x.fingers_read} dedos leídos de la partitura` +
              (x.missing_measures.length ? `; no se pudo leer el compás ${x.missing_measures.join(", ")} (queda en silencio)` : "") +
              ". Abriendo…",
            "ok",
          );
          setTimeout(() => (location.href = `/score/?job=${x.job_id}&stem=piano`), 1200);
          return;
        }
        if (st.state === "error") throw new Error(st.error);
        say(phases[st.phase] || "Procesando…");
      }
    } catch (e) {
      say(`No se pudo importar: ${e.message}`, "err");
      $("sc-sheet-go").disabled = false;
    }
  };
}

/** Fingers for the open song: loaded once, again after edits, and set by
 *  hand (1-5 on the selected notes, 0 back to the suggestion). They show on
 *  the falling notes when «En las notas» says so; the note name is the
 *  default, as in every other song. */
export function fingeringFeature({ $, api, API, fall, state, status, onShown }) {
  const f = {
    available: false,
    fingers: null,
    source: null,
    counts: null,
    async load() {
      try {
        f.show(await api(`${API}/fingering`));
      } catch {
        /* no fingering */
      }
    },
    /** Show what the server answered: the fingers, or «Activar dedos». */
    show(data) {
      f.available = !!data.available;
      f.fingers = data.available ? data.fingers : null;
      f.source = data.source || null;
      fall.setFingers(f.available && f.visible() ? f.fingers : null);
      $("sc-fall-fingers-wrap").hidden = !f.available;
      // One selector for what goes on the notes: it takes over «Nombres».
      $("sc-fall-names-wrap").hidden = f.available;
      $("sc-editbar-fingers").hidden = !f.available;
      $("sc-fall-fingers-on").hidden = f.available;
      $("sc-fall-fingers-off").hidden = !f.available || f.source !== "manual";
      if (f.available) {
        $("sc-fall-fingers").value = f.label();
        f.summary(data.counts);
      }
      onShown?.();
    },
    /** «Activar dedos»: this song gets fingers (suggested; corrected by hand). */
    async enable() {
      f.show(await api(`${API}/fingering/enable`, { method: "POST" }));
      status("Dedos activados: sugeridos en gris. Elige notas y pulsa 1–5 para corregirlos.");
    },
    async disable() {
      f.show(await api(`${API}/fingering`, { method: "DELETE" }));
      status("Dedos quitados de esta canción");
    },
    /** What «En las notas» shows: the names (C D E by default), the fingers, both, nothing. */
    label() {
      const l = state.view.fallLabel;
      return l === "finger" || l === "both" ? l : state.view.fallNames || "letters";
    },
    /** Finger numbers on the notes: only when asked for (the note name by default). */
    visible() {
      return state.view.fallLabel === "finger" || state.view.fallLabel === "both";
    },
    summary(c) {
      f.counts = c;
      $("sc-fall-fingers-wrap").title =
        `Dedos: ${c.score} de la partitura, ${c.user} puestos a mano, ${c.auto} sugeridos (en gris). ` +
        "Selecciona notas y pulsa 1–5 para cambiarlos, 0 para volver al sugerido.";
    },
    /** Reload after an edit (the suggestion follows the notes). */
    refresh() {
      if (!f.available) return;
      clearTimeout(f.timer);
      f.timer = setTimeout(() => f.load(), 400);
    },
    async set(ids, finger) {
      if (!f.available || !ids.length) return false;
      const body = { set: Object.fromEntries(ids.map((id) => [id, finger])) };
      const data = await api(`${API}/fingering`, { method: "PUT", body });
      f.fingers = data.fingers;
      fall.setFingers(f.visible() ? f.fingers : null);
      f.summary(data.counts);
      status(finger ? `Dedo ${finger} en ${ids.length} nota(s)` : `${ids.length} nota(s) con el dedo sugerido`);
      return true;
    },
    describe(id) {
      const x = f.fingers?.[id];
      if (!x) return "";
      return ` · dedo ${x.f} (${{ score: "de la partitura", user: "puesto a mano", auto: "sugerido" }[x.src] || x.src})`;
    },
  };
  return f;
}
