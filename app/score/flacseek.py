"""A SEEKTABLE for a FLAC that has none.

ffmpeg's FLAC muxer (8.0) and libsndfile write no seek table, and Pianoteq's
renders come without one too. A browser asked to jump to a moment of such a
file has nowhere to look it up: it bisects the file with range requests
(measured on the score page: six requests around the same 300 KB to jump to
0:30 of a 6-minute song). With a table it goes to the right frame at once.

The table is read off the file's own frame headers (each says which sample
it starts at; its CRC-8 tells a real header from audio that looks like one),
one point a second, and written as a metadata block before the audio, which
is left byte for byte as it was (the points count bytes from the first frame,
so the metadata before it may change size).
"""

from __future__ import annotations

import logging
import os
import struct
import threading
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

SEEKTABLE = 3
PADDING = 1
EVERY = 1.0  # s between seek points
MAX_POINTS = 2000  # a longer file gets them further apart
KEEP_PADDING = 1024  # bytes left for tags written later

_LOCK = threading.Lock()


def _crc8_table() -> list[int]:
    table = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = ((c << 1) ^ 0x07) & 0xFF if c & 0x80 else (c << 1) & 0xFF
        table.append(c)
    return table


_CRC8 = _crc8_table()


def _crc8(data: bytes) -> int:
    c = 0
    for b in data:
        c = _CRC8[c ^ b]
    return c


def _metadata(data: bytes) -> tuple[list[tuple[int, bytes]], int]:
    """[(block type, body)] and where the first audio frame starts."""
    if data[:4] != b"fLaC":
        raise ValueError("not a FLAC file")
    pos = 4
    blocks = []
    while True:
        if pos + 4 > len(data):
            raise ValueError("truncated metadata")
        head = data[pos]
        size = int.from_bytes(data[pos + 1 : pos + 4], "big")
        blocks.append((head & 0x7F, data[pos + 4 : pos + 4 + size]))
        pos += 4 + size
        if head & 0x80:
            return blocks, pos


def has_seektable(path: Path) -> bool:
    """Read only the metadata headers."""
    with open(path, "rb") as f:
        if f.read(4) != b"fLaC":
            return False
        while True:
            h = f.read(4)
            if len(h) < 4:
                return False
            if h[0] & 0x7F == SEEKTABLE:
                return True
            if h[0] & 0x80:
                return False
            f.seek(int.from_bytes(h[1:], "big"), 1)


def _utf8_number(data: bytes, i: int) -> tuple[int, int] | None:
    """FLAC's UTF-8-like coded number at data[i]: (value, bytes used)."""
    b0 = data[i]
    if b0 < 0x80:
        return b0, 1
    n = 0
    mask = 0x80
    while b0 & mask:
        n += 1
        mask >>= 1
    if n < 2 or n > 7:
        return None
    value = b0 & (mask - 1)
    for k in range(1, n):
        if i + k >= len(data) or data[i + k] & 0xC0 != 0x80:
            return None
        value = (value << 6) | (data[i + k] & 0x3F)
    return value, n


def frames(data: bytes, first: int, fixed_block: int) -> list[tuple[int, int, int]]:
    """(first sample, byte offset from the first frame, samples) of every
    frame, from the frame headers (the CRC-8 rules out look-alikes)."""
    out: list[tuple[int, int, int]] = []
    i = first
    end = len(data) - 16
    while i < end:
        j = data.find(b"\xff", i, end)
        if j < 0:
            break
        i = j + 1
        b1 = data[j + 1]
        if b1 not in (0xF8, 0xF9):
            continue
        b2, b3 = data[j + 2], data[j + 3]
        bs_code, sr_code = b2 >> 4, b2 & 0x0F
        if bs_code == 0 or sr_code == 15 or (b3 >> 4) > 10 or b3 & 1 or ((b3 >> 1) & 7) == 3:
            continue
        num = _utf8_number(data, j + 4)
        if num is None:
            continue
        value, used = num
        k = j + 4 + used
        if bs_code == 1:
            block = 192
        elif 2 <= bs_code <= 5:
            block = 576 << (bs_code - 2)
        elif bs_code == 6:
            block = data[k] + 1
            k += 1
        elif bs_code == 7:
            block = int.from_bytes(data[k : k + 2], "big") + 1
            k += 2
        else:
            block = 256 << (bs_code - 8)
        if sr_code == 12:
            k += 1
        elif sr_code in (13, 14):
            k += 2
        if _crc8(data[j:k]) != data[k]:
            continue
        sample = value if b1 == 0xF9 else value * fixed_block
        if out and sample <= out[-1][0]:
            continue  # a look-alike that passed the CRC by chance
        out.append((sample, j - first, block))
        i = k + 1
    return out


def seektable(data: bytes) -> tuple[bytes, list[tuple[int, bytes]], int] | None:
    """(the SEEKTABLE's body, the other metadata blocks, where audio starts),
    or None when the file has no frames to point at."""
    blocks, first = _metadata(data)
    info = blocks[0][1]
    if blocks[0][0] != 0 or len(info) < 18:
        raise ValueError("no STREAMINFO")
    fixed_block = struct.unpack(">H", info[2:4])[0]
    rate = int.from_bytes(info[10:13], "big") >> 4
    found = frames(data, first, fixed_block)
    if not found or not rate:
        return None
    total = found[-1][0] + found[-1][2]
    every = max(EVERY, total / rate / MAX_POINTS)
    points = []
    target = 0.0
    k = 0
    while target * rate < total:
        want = int(target * rate)
        while k + 1 < len(found) and found[k + 1][0] <= want:
            k += 1
        if not points or points[-1][0] != found[k][0]:
            points.append(found[k])
        target += every
    body = b"".join(struct.pack(">QQH", s, off, n) for s, off, n in points)
    others = [(t, b) for t, b in blocks if t not in (SEEKTABLE, PADDING)]
    return body, others, first


def add_seektable(path: Path) -> bool:
    """Give `path` a seek table (rewritten atomically); False when it had one,
    is not FLAC, or is in use (it is tried again the next time)."""
    path = Path(path)
    with _LOCK:
        try:
            if not path.is_file() or has_seektable(path):
                return False
            data = path.read_bytes()
            made = seektable(data)
        except (OSError, ValueError, IndexError, struct.error) as exc:
            logger.warning("no seek table for %s: %s", path.name, exc)
            return False
        if made is None:
            return False
        body, others, first = made
        blocks = [*others, (SEEKTABLE, body), (PADDING, bytes(KEEP_PADDING))]
        head = [b"fLaC"]
        for i, (kind, b) in enumerate(blocks):
            last = 0x80 if i == len(blocks) - 1 else 0
            head.append(bytes([last | kind]) + len(b).to_bytes(3, "big") + b)
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.seek")
        try:
            with open(tmp, "wb") as f:
                f.write(b"".join(head))
                f.write(memoryview(data)[first:])
            os.replace(tmp, path)
        except OSError as exc:  # being read (Windows): next time
            logger.info("seek table for %s later: %s", path.name, exc)
            tmp.unlink(missing_ok=True)
            return False
        return True
