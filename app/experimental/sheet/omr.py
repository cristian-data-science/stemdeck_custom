"""Optical music recognition with Audiveris (AGPL, run as a separate program).

Audiveris is not bundled: it is found at STEMDECK_AUDIVERIS, in
.run/tools/audiveris (where the dev setup unpacks the official .msi without
installing it), or in Program Files. Fingering recognition is a processing
switch that Audiveris leaves off; it is turned on here. On the Chopin
nocturne page it then read 10 of the ~50 printed fingers, all on the right
note; the rest are suggested (fingering.py) and can be corrected by hand.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TIMEOUT = 15 * 60
FINGERINGS = "org.audiveris.omr.sheet.ProcessingSwitches.fingerings=true"


def executable() -> Path | None:
    env = os.environ.get("STEMDECK_AUDIVERIS")
    cands = [Path(env)] if env else []
    cands.append(ROOT / ".run" / "tools" / "audiveris" / "Audiveris" / "Audiveris.exe")
    for base in (os.environ.get("PROGRAMFILES", r"C:\Program Files"), r"C:\Program Files"):
        cands.append(Path(base) / "Audiveris" / "Audiveris.exe")
    cands.append(Path("/opt/audiveris/bin/Audiveris"))
    cands.append(Path("/Applications/Audiveris.app/Contents/MacOS/Audiveris"))
    return next((p for p in cands if p.is_file()), None)


class OmrError(RuntimeError):
    pass


def recognize(image: Path, out_dir: Path) -> Path:
    """Run Audiveris on a PDF or image; the exported MusicXML (.mxl)."""
    exe = executable()
    if exe is None:
        raise OmrError(
            "No encuentro Audiveris. Descárgalo de github.com/Audiveris/audiveris/releases "
            "o define STEMDECK_AUDIVERIS con la ruta del ejecutable."
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    res = subprocess.run(
        [
            str(exe),
            "-batch",
            "-force",
            "-export",
            "-constant",
            FINGERINGS,
            "-output",
            str(out_dir),
            "--",
            str(image),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=TIMEOUT,
        creationflags=flags,
        check=False,
    )
    (out_dir / "audiveris.log").write_text(
        (res.stdout or "") + (res.stderr or ""), encoding="utf-8"
    )
    found = sorted(out_dir.glob("*.mxl")) or sorted(out_dir.glob("*.xml"))
    if not found:
        tail = ((res.stdout or "") + (res.stderr or "")).strip().splitlines()[-3:]
        raise OmrError("Audiveris no pudo leer la partitura. " + " | ".join(tail)[:300])
    return found[0]
