"""The MEI the server writes, engraved by the very Verovio the page loads
(static/vendor/verovio), in node.

The load-bearing claim of the whole score view: every note id reaches the
SVG, so the page can label, light and select each notehead. Plus the visible
facts a person would check: two staves with G and F clefs, the key signature,
the chord texts, ties and triplets.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.score import calibration as cal
from app.score.chords import chord_name, detect
from app.score.engrave import Settings, engrave
from app.score.keys import parse_key
from app.score.mei import to_mei

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "static" / "vendor" / "verovio"

_SCRIPT = r"""
import { pathToFileURL } from "node:url";
import fs from "node:fs";
const vendor = process.argv[2];
const { default: createVerovioModule } = await import(pathToFileURL(vendor + "/verovio-module.mjs"));
const { VerovioToolkit } = await import(pathToFileURL(vendor + "/verovio.mjs"));
const tk = new VerovioToolkit(await createVerovioModule());
tk.setOptions({ pageWidth: 2100, pageHeight: 60000, adjustPageHeight: true, scale: 40, breaks: "auto", header: "none", footer: "none" });
const ok = tk.loadData(fs.readFileSync(process.argv[3], "utf8"));
let svg = "";
for (let p = 1; p <= tk.getPageCount(); p++) svg += tk.renderToSVG(p);
const ids = [...svg.matchAll(/<g id="([^"]+)" class="note"/g)].map((m) => m[1]);
const harms = [...svg.matchAll(/<g id="h\d+" class="harm">([\s\S]*?)<\/text>/g)].map((m) => m[1].replace(/<[^>]+>/g, "").trim());
const count = (cls) => (svg.match(new RegExp(`class="${cls}"`, "g")) || []).length;
console.log(JSON.stringify({ ok, pages: tk.getPageCount(), ids, harms,
  clefs: count("clef"), keySig: count("keySig"), ties: count("tie"), tuplets: count("tuplet"),
  measures: count("measure"), log: tk.getLog() }));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_verovio_keeps_every_note_id(tmp_path):
    notes = cal.notes()
    key = parse_key(*cal.KEY)
    eng = engrave(notes, cal.beats(), cal.bars(), key, Settings())
    chords = [
        {"beat": c.beat, "text": chord_name(c.root, c.quality, c.bass, key), "id": f"h{i}"}
        for i, c in enumerate(detect(notes, eng.grid, "half"))
    ]
    mei = tmp_path / "cal.mei"
    mei.write_text(to_mei(eng, chords, bpm=90), encoding="utf-8")
    script = tmp_path / "render.mjs"
    script.write_text(_SCRIPT, encoding="utf-8")
    out = subprocess.run(
        ["node", str(script), str(VENDOR), str(mei)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=True,
    )
    r = json.loads(out.stdout.strip().splitlines()[-1])
    assert r["ok"], r["log"]
    drawn = set(r["ids"])
    assert {n["id"] for n in notes} <= drawn, sorted({n["id"] for n in notes} - drawn)
    assert r["measures"] == cal.EXPECTED["measures"]
    assert r["clefs"] >= 2  # G and F at the start of the first system
    assert r["keySig"] >= 2  # one flat on each staff
    assert r["tuplets"] >= 2  # bar 6's two triplets
    # Verovio draws a chord symbol's flat/sharp with its own SMuFL glyphs
    # (csymAccidentalFlat U+EA64, csymAccidentalSharp U+EA66) in a tspan.
    smufl = str.maketrans(
        {chr(0xEA64): chr(0x266D), chr(0xEA66): chr(0x266F), chr(0xEA65): chr(0x266E)}
    )
    harms = ["".join(h.translate(smufl).split()) for h in r["harms"]]
    assert harms == cal.EXPECTED["chords"]
