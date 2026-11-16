// Experimental (app/experimental/separation.py): the song separated again by
// the other model (Demucs <-> BS-RoFormer SW), as a copy beside it. Shown only
// when RoFormer is installed (.run/tools/roformer); the song never changes.

export async function wireSeparation({ $, api, job }) {
  let info = null;
  try {
    info = await api("/api/experimental/separation");
  } catch {
    return;
  }
  if (!info?.available) return;
  const song = await api(`/api/jobs/${job}`).catch(() => null);
  // A solo piano imported as such was never separated: nothing to compare.
  if (song?.separator === "none") return;
  const used = song?.separator === "roformer" ? "roformer" : "demucs";
  const other = used === "roformer" ? "demucs" : "roformer";
  const names = { demucs: "Demucs", roformer: "RoFormer" };
  $("sc-resep-what").textContent =
    used === "demucs"
      ? "(esta canción se separó con Demucs; RoFormer, experimental, distingue mejor teclado y guitarra)."
      : "(esta canción se separó con RoFormer; Demucs es el modelo de siempre).";
  $("sc-resep-go").textContent = `Crear copia con ${names[other]}`;
  $("sc-resep").hidden = false;
  const say = (text, kind = "") => {
    const el = $("sc-resep-status");
    el.textContent = text;
    el.className = `sc-muted ${kind}`;
  };
  $("sc-resep-go").onclick = async () => {
    $("sc-resep-go").disabled = true;
    say("En cola…");
    try {
      const r = await api(`/api/experimental/jobs/${job}/separation?model=${other}`, { method: "POST" });
      const phases = { queued: "En cola (espera a otra separación)…", separating: `Separando con ${names[other]} (~1 min con GPU)…`, finishing: "Preparando la copia…" };
      for (;;) {
        await new Promise((ok) => setTimeout(ok, 2000));
        const st = await api(`/api/experimental/separation/${r.run_id}`);
        if (st.state === "done") {
          const x = st.result;
          const p = x.stem_presence || {};
          say(`Lista: «${x.title}» (piano ${p.piano ?? "?"}, guitarra ${p.guitar ?? "?"}, otros ${p.other ?? "?"}). Está en la biblioteca.`, "ok");
          const a = $("sc-resep-open");
          a.href = `/score/?job=${x.job_id}&stem=piano`;
          a.hidden = false;
          return;
        }
        if (st.state === "error") throw new Error(st.error);
        say(phases[st.phase] || "Separando…");
      }
    } catch (e) {
      say(`No se pudo separar: ${e.message}`, "err");
      $("sc-resep-go").disabled = false;
    }
  };
}
