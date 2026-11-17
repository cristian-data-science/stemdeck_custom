// The saxophone on the left of «🎷 Saxo»: a real alto (a Yamaha YAS-62,
// photograph from Wikimedia Commons, CC BY-SA 4.0: static/img/sax/NOTICE.txt)
// with the keys of the note sounding lit on it, in that note's colour, and
// the next note's ringed. A saxophonist reads the fingering off the
// instrument itself, where the fingers are.

// [key, cx, cy, rx, ry, label] in the photograph's coordinates (483 × 1100),
// measured on the photograph (the pearls, the spatulas, the table).
const KEYS = [
  ["oct", 214, 392, 10, 10, "Llave de octava (pulgar izquierdo, por detrás)"],
  ["pD", 300, 368, 8, 7, "Llave de palma Re (palma izquierda)"],
  ["pEb", 311, 393, 8, 7, "Llave de palma Mi♭ (palma izquierda)"],
  ["pF", 309, 421, 8, 7, "Llave de palma Fa (palma izquierda)"],
  ["L1", 258, 405, 12.5, 12.5, "Índice izquierdo: Si"],
  ["bis", 263, 429, 8.5, 8.5, "Llave bis: Si♭"],
  ["L2", 263, 457, 12.5, 12.5, "Medio izquierdo: La"],
  ["L3", 281, 481, 12, 12, "Anular izquierdo: Sol"],
  ["Gs", 307, 511, 8, 11, "Meñique izquierdo: Sol♯"],
  ["B", 302, 528, 6, 6, "Meñique izquierdo: Si grave"],
  ["Cs", 313, 534, 6, 6, "Meñique izquierdo: Do♯ grave"],
  ["Bb", 307, 545, 6, 6, "Meñique izquierdo: Si♭ grave"],
  ["sE", 162, 700, 7, 14, "Llave lateral: Mi agudo (canto de la mano derecha)"],
  ["R1", 227, 778, 12.5, 12.5, "Índice derecho: Fa"],
  ["R2", 233, 833, 12.5, 12.5, "Medio derecho: Mi"],
  ["R3", 222, 882, 12.5, 12.5, "Anular derecho: Re"],
  ["Eb", 172, 903, 10, 7, "Meñique derecho: Mi♭"],
  ["C", 176, 922, 10, 7, "Meñique derecho: Do grave"],
];
const W = 483;
const H = 1100;
const NS = "http://www.w3.org/2000/svg";

/** The saxophone, built once into `host`. Returns {set(keysNow, colour,
 *  keysNext)}. */
export function buildHorn(host) {
  host.innerHTML = `
<div class="sx-horn-photo">
  <img class="sx-horn-img" src="/img/sax/yas62.webp" srcset="/img/sax/yas62.webp 1x, /img/sax/yas62@2x.webp 2x"
       alt="Saxofón alto Yamaha YAS-62" draggable="false" />
  <svg class="sx-horn-keys" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" aria-hidden="true">
    <defs>
      <filter id="sx-key-glow" x="-150%" y="-150%" width="400%" height="400%">
        <feGaussianBlur stdDeviation="5" result="b"/>
        <feMerge><feMergeNode in="b"/><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
      </filter>
      <radialGradient id="sx-bell-glow" cx="0.5" cy="0.5" r="0.5">
        <stop offset="0" stop-color="currentColor" stop-opacity="0.9"/>
        <stop offset="1" stop-color="currentColor" stop-opacity="0"/>
      </radialGradient>
    </defs>
    <ellipse class="sx-bell" cx="398" cy="622" rx="80" ry="58" fill="url(#sx-bell-glow)" opacity="0"/>
    <g class="sx-keys"></g>
    <text class="sx-oct-label" x="214" y="374" text-anchor="middle">8va</text>
  </svg>
  <a class="sx-credit" href="https://commons.wikimedia.org/wiki/File:Yamaha_Saxophone_YAS-62.png" target="_blank" rel="noopener"
     title="Foto: Yamaha Corporation; fondo quitado: Habitator terrae. CC BY-SA 4.0">foto CC BY-SA</a>
</div>`;
  const svg = host.querySelector("svg");
  const g = svg.querySelector(".sx-keys");
  const els = new Map();
  for (const [key, cx, cy, rx, ry, label] of KEYS) {
    const k = document.createElementNS(NS, "ellipse");
    k.setAttribute("cx", cx);
    k.setAttribute("cy", cy);
    k.setAttribute("rx", rx);
    k.setAttribute("ry", ry);
    k.setAttribute("class", `sx-key${key === "oct" ? " sx-key-oct" : ""}`);
    k.dataset.key = key;
    const t = document.createElementNS(NS, "title");
    t.textContent = label;
    k.append(t);
    g.append(k);
    els.set(key, k);
  }
  const bell = svg.querySelector(".sx-bell");
  const photo = host.querySelector(".sx-horn-photo");
  return {
    keys: [...els.keys()],
    /** `now`: keys pressed (lit in `colour`); `next`: the next note's keys
     *  (ringed). null now: nothing sounding. */
    set(now, colour, next) {
      const on = new Set(now || []);
      const soon = new Set(next || []);
      for (const [key, el] of els) {
        const pressed = on.has(key);
        el.classList.toggle("on", pressed);
        el.classList.toggle("next", !pressed && soon.has(key));
        el.style.fill = pressed ? colour : "";
        el.style.filter = pressed ? "url(#sx-key-glow)" : "";
      }
      svg.querySelector(".sx-oct-label").classList.toggle("on", on.has("oct"));
      bell.style.color = colour || "transparent";
      bell.setAttribute("opacity", now ? "0.55" : "0");
      photo.style.setProperty("--glow", now ? colour : "transparent");
    },
  };
}
