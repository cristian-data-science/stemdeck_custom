// The saxophone on the left of «🎷 Saxo», as a fingering chart: the keys
// big and in the order the hands meet them (the left hand on top, the right
// below), each one named, pressed ones filled in one colour, the next note's
// ringed. Read at a glance while playing, where the photograph's keys were
// small and in the note's own colour (a different one for every note).
//
// The keys are where they are on the instrument seen from the front (as in
// the photograph, horn.js): the octave key and the right hand's side key on
// the left, the palm keys and the left little finger's table on the right.
// Same interface as buildHorn: {keys, set(keysNow, colour, keysNext)}; the
// photograph stays one choice away («Digitación: Foto del saxo»).

const W = 300;
const H = 640;
const NS = "http://www.w3.org/2000/svg";
const X = 150; // the column of the six main keys
const R = 31;

// [key, shape, cx, cy, rx, ry, text inside, title]
const KEYS = [
  ["oct", "e", 54, 92, 24, 15, "8va", "Llave de octava (pulgar izquierdo, por detrás)"],
  ["L1", "c", X, 92, R, R, "1", "Índice izquierdo: Si"],
  ["bis", "c", X, 140, 11, 11, "", "Llave bis: Si♭ (entre el índice y el medio)"],
  ["L2", "c", X, 188, R, R, "2", "Medio izquierdo: La"],
  ["L3", "c", X, 262, R, R, "3", "Anular izquierdo: Sol"],
  ["pD", "e", 246, 64, 19, 12, "Re", "Llave de palma Re (palma izquierda)"],
  ["pEb", "e", 258, 98, 19, 12, "Mi♭", "Llave de palma Mi♭ (palma izquierda)"],
  ["pF", "e", 252, 132, 19, 12, "Fa", "Llave de palma Fa (palma izquierda)"],
  ["Gs", "e", 240, 248, 25, 15, "Sol♯", "Meñique izquierdo: Sol♯"],
  ["Cs", "e", 268, 286, 17, 11, "Do♯", "Meñique izquierdo: Do♯ grave"],
  ["B", "e", 222, 286, 17, 11, "Si", "Meñique izquierdo: Si grave"],
  ["Bb", "e", 245, 318, 17, 11, "Si♭", "Meñique izquierdo: Si♭ grave"],
  ["sE", "e", 62, 432, 13, 28, "Mi", "Llave lateral: Mi agudo (canto de la mano derecha)"],
  ["R1", "c", X, 432, R, R, "1", "Índice derecho: Fa"],
  ["R2", "c", X, 506, R, R, "2", "Medio derecho: Mi"],
  ["R3", "c", X, 580, R, R, "3", "Anular derecho: Re"],
  ["Eb", "e", 250, 560, 22, 13, "Mi♭", "Meñique derecho: Mi♭"],
  ["C", "e", 250, 598, 22, 13, "Do", "Meñique derecho: Do grave"],
];

const CAPTIONS = [
  [X, 24, "MANO IZQUIERDA", "sx-ch-hand"],
  [54, 124, "pulgar", "sx-ch-cap"],
  [252, 162, "palma", "sx-ch-cap"],
  [245, 346, "meñique", "sx-ch-cap"],
  [X, 386, "MANO DERECHA", "sx-ch-hand"],
  [62, 478, "lateral", "sx-ch-cap"],
  [250, 628, "meñique", "sx-ch-cap"],
];

export function buildChart(host) {
  host.innerHTML = "";
  const box = document.createElement("div");
  box.className = "sx-chart";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Digitación: las llaves que se aprietan");
  svg.innerHTML = `
    <defs>
      <filter id="sx-ch-glow" x="-80%" y="-80%" width="260%" height="260%">
        <feGaussianBlur stdDeviation="6" result="b"/>
        <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
      </filter>
    </defs>
    <rect class="sx-ch-body" x="${X - 48}" y="52" width="96" height="248" rx="48"/>
    <rect class="sx-ch-body" x="${X - 48}" y="392" width="96" height="226" rx="48"/>
    <line class="sx-ch-split" x1="16" y1="364" x2="${W - 16}" y2="364"/>`;
  for (const [x, y, text, cls] of CAPTIONS) {
    const t = document.createElementNS(NS, "text");
    t.setAttribute("x", x);
    t.setAttribute("y", y);
    t.setAttribute("text-anchor", "middle");
    t.setAttribute("class", cls);
    t.textContent = text;
    svg.append(t);
  }
  const els = new Map();
  for (const [key, shape, cx, cy, rx, ry, inside, title] of KEYS) {
    const g = document.createElementNS(NS, "g");
    g.setAttribute("class", `sx-key${rx >= R ? " sx-key-main" : ""}`);
    g.dataset.key = key;
    const k = document.createElementNS(NS, shape === "c" ? "circle" : "ellipse");
    k.setAttribute("cx", cx);
    k.setAttribute("cy", cy);
    if (shape === "c") k.setAttribute("r", rx);
    else {
      k.setAttribute("rx", rx);
      k.setAttribute("ry", ry);
    }
    k.setAttribute("class", "sx-ch-key");
    g.append(k);
    if (inside) {
      const t = document.createElementNS(NS, "text");
      t.setAttribute("x", cx);
      t.setAttribute("y", cy + (rx >= R ? 8 : 4));
      t.setAttribute("text-anchor", "middle");
      t.setAttribute("class", rx >= R ? "sx-ch-finger" : "sx-ch-name");
      t.textContent = inside;
      g.append(t);
    }
    const tt = document.createElementNS(NS, "title");
    tt.textContent = title;
    g.append(tt);
    svg.append(g);
    els.set(key, g);
  }
  box.append(svg);
  host.append(box);
  return {
    keys: [...els.keys()],
    /** `now`: keys pressed (filled); `next`: the next note's keys (ringed).
     *  `colour` is not used: one colour for every note reads faster. */
    set(now, _colour, next) {
      const on = new Set(now || []);
      const soon = new Set(next || []);
      for (const [key, el] of els) {
        const pressed = on.has(key);
        el.classList.toggle("on", pressed);
        el.classList.toggle("next", !pressed && soon.has(key));
        el.classList.toggle("lift", pressed && next != null && !soon.has(key));
      }
      box.classList.toggle("sounding", now != null);
    },
  };
}
