"""Experimental: a song from a printed score (PDF or image), with fingering.

omr.py         runs Audiveris (optical music recognition) -> MusicXML
musicxml.py    MusicXML -> notes in seconds, beats/bars, printed fingers
fingering.py   a finger for every note, keeping the printed ones
song.py        the library track: audio rendered from the notes, beats,
               notes.json with each note's hand, the fingers in meta.json
"""
