"""Score module: a stem's notes transcribed to MIDI and engraved as an
editable grand-staff score (docs/score-module-plan.md).

Layout:
  keys.py       key signature and note spelling from the job's detected key
  timegrid.py   seconds <-> ticks against the job's real beat grid
  engrave.py    notes -> quantized measures/events (pure, deterministic)
  chords.py     chord symbols from the notes
  mei.py        engraved score -> MEI, what the page renders with Verovio
  musicxml.py   engraved score -> MusicXML, for MuseScore & co.
  midi.py       notes -> Standard MIDI File
  store.py      files under jobs/<id>/score/<stem>/
  transcribe.py the transcription worker launcher; worker.py runs the model
"""
