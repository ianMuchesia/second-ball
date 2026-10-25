"""The 10 Hz movement file of a recorded match: `tracks.json` + `tracks.bin`.

tracks.json: {"hz", "n", "slots": [player_id, ...], "events": {event_id: sample}}
tracks.bin (gzip): little-endian blocks, each n long,
  float32 t        match seconds (the engine's clock: period 2 starts at 2700)
  uint8   period
  uint8   dead     1 while the ball is out of play
  int16   values   per sample: ball x, y, h (cm), then per slot x, y (cm) and
                   facing (0.1 degree); off the pitch = -32768
Positions are absolute: home attacks +x (the broadcast frame).
"""

import gzip
import json
import struct
from pathlib import Path

MISSING = -32768


def write(tracks, folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    n, slots = len(tracks.samples), len(tracks.slots)
    header = {
        "hz": tracks.hz,
        "n": n,
        "slots": tracks.slots,
        "events": tracks.events,
        "values_per_sample": 3 + 3 * slots,
    }
    (folder / "tracks.json").write_text(json.dumps(header))
    t = struct.pack(f"<{n}f", *(s.t for s in tracks.samples))
    period = bytes(s.period for s in tracks.samples)
    dead = bytes(int(s.dead) for s in tracks.samples)
    values = []
    for s in tracks.samples:
        values += [
            round(s.ball[0] * 100),
            round(s.ball[1] * 100),
            round(s.ball[2] * 100),
        ]
        for p in s.players:
            if p is None:
                values += [MISSING, MISSING, MISSING]
            else:
                values += [
                    round(p[0] * 100),
                    round(p[1] * 100),
                    round(p[2] * 10) % 3600,
                ]
    pad = b"\0" * ((-(len(t) + 2 * n)) % 2)
    body = t + period + dead + pad + struct.pack(f"<{len(values)}h", *values)
    (folder / "tracks.bin").write_bytes(gzip.compress(body, compresslevel=6))
