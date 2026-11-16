"""Train the hand model of app/score/hands.py (a bidirectional GRU).

    git clone --depth 1 https://github.com/cemfi/hannds.git <dir>
    .venv/Scripts/python.exe scripts/score/train_hands.py --hannds <dir>/data-hannds
        [--all] [--seed 0] [--steps 4000] [--out app/score/models/hands_gru.npz]

Needs torch (CUDA if there is one; ~10 min on a laptop GPU). The features are
app.score.hands.features itself, so training and the app cannot drift apart.

* Augmentation, for transcribed audio rather than clean MIDI: transposition
  (+-6), tempo (x0.7-1.4), onset jitter (8 ms), velocity noise, dropped notes
  (up to 12 %) and ghost notes an octave or a twelfth away (up to 6 %, same
  hand as the note they double).
* Hints: half the windows reveal the hand of up to 8 % of their notes (the
  feature a user's correction fills in). After 300 steps, 60 % of the windows
  also reveal 1-3 of the model's own current mistakes, so it learns what a
  correction says about the notes around it. The loss counts only notes
  whose hand was not revealed.

Without --all, 12 fixed pieces are held out and measured every 500 steps,
with the local jobs whose hands are known (never trained on). The shipped
model is trained without --all, so tests/fixtures/hands_kuhlau_op55_3.json
(one of the 12) is a piece it has never seen.
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

import numpy as np
import torch
from torch import nn

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from hands_data import UNRELIABLE, hannds, held_out, known_jobs  # noqa: E402

from app.score import hands  # noqa: E402

HIDDEN = 64
EMB = 12


class Net(nn.Module):
    def __init__(self):
        super().__init__()
        self.emb = nn.Embedding(88, EMB)
        self.rnn = nn.GRU(
            EMB + hands.N_FEAT,
            HIDDEN,
            num_layers=2,
            batch_first=True,
            bidirectional=True,
            dropout=0.15,
        )
        self.out = nn.Linear(2 * HIDDEN, 1)

    def forward(self, keys, x):
        z, _ = self.rnn(torch.cat([self.emb(keys), x], -1))
        return self.out(z).squeeze(-1)


def augment(notes: list[dict]) -> list[dict]:
    r = random.random
    shift = random.randint(-6, 6)
    scale = 0.7 + 0.7 * r()
    drop = 0.12 * r()
    ghost = 0.06 * r()
    out = []
    for n in notes:
        if r() < drop:
            continue
        m = n["midi"] + shift
        if not 21 <= m <= 108:
            continue
        st = n["start"] * scale + random.gauss(0, 0.008)
        en = max(st + 0.03, n["end"] * scale)
        v = int(np.clip(n["velocity"] + random.gauss(0, 12), 5, 127))
        out.append({"midi": m, "start": st, "end": en, "velocity": v, "gt": n["gt"]})
        if r() < ghost:
            g = m + random.choice([12, 19, 24, -12])
            if 21 <= g <= 108:
                out.append(
                    {
                        "midi": g,
                        "start": st + random.gauss(0, 0.01),
                        "end": en,
                        "velocity": max(5, v - 30),
                        "gt": n["gt"],
                    }
                )
    return out


def encode(notes: list[dict], hint_rate: float = 0.0):
    for i, n in enumerate(notes):
        n["id"] = str(i)
        n["hand"] = None
    idx = hands._order(notes)
    y = np.array([1.0 if notes[i]["gt"] == "R" else 0.0 for i in idx], dtype=np.float32)
    if hint_rate > 0:
        for k in np.flatnonzero(np.random.rand(len(idx)) < hint_rate):
            notes[idx[k]]["hand"] = notes[idx[k]]["gt"]
    keys, X, _ = hands.features(notes, idx)
    return keys, X, y


def make_batch(train, device, size=32, length=256):
    K, Xs, Y, M = [], [], [], []
    while len(Y) < size:
        _, notes = random.choice(train)
        t0 = random.uniform(0, max(0.0, notes[-1]["start"] - 40))
        win = [dict(n) for n in notes if t0 <= n["start"] < t0 + 60] or [
            dict(n) for n in notes[:length]
        ]
        win = augment(win)
        if len(win) < 4:
            continue
        rate = 0.0 if random.random() < 0.5 else random.uniform(0, 0.08)
        keys, X, y = encode(win, rate)
        if len(y) > length:
            a = random.randint(0, len(y) - length)
            keys, X, y = keys[a : a + length], X[a : a + length], y[a : a + length]
        pad = length - len(y)
        K.append(np.r_[keys, np.zeros(pad, np.int64)])
        Xs.append(np.r_[X, np.zeros((pad, hands.N_FEAT), np.float32)])
        Y.append(np.r_[y, np.zeros(pad, np.float32)])
        M.append(np.r_[(X[:, 9] == 0).astype(np.float32), np.zeros(pad, np.float32)])

    def t(a, dtype):
        return torch.tensor(np.stack(a), dtype=dtype, device=device)

    return t(K, torch.long), t(Xs, torch.float32), t(Y, torch.float32), t(M, torch.float32)


def export(net: Net, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path,
        **{k: v.detach().cpu().numpy().astype(np.float32) for k, v in net.state_dict().items()},
    )


def accuracy(path: Path, songs) -> tuple[float, list[float]]:
    """Through the app's own numpy code and decoding."""
    hands._weights.cache_clear()
    hands._CACHE.clear()
    old = hands.MODEL_PATH
    hands.MODEL_PATH = path
    try:
        tot = ok = 0
        per = []
        for name, notes in songs:
            out = hands.assign_hands([{k: v for k, v in n.items() if k != "gt"} for n in notes])
            c = sum(out[n["id"]] == n["gt"] for n in notes)
            per.append(c / len(notes))
            if name not in UNRELIABLE:
                tot += len(notes)
                ok += c
        return ok / max(1, tot), per
    finally:
        hands.MODEL_PATH = old
        hands._weights.cache_clear()
        hands._CACHE.clear()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--hannds", required=True, help="the data-hannds folder of github.com/cemfi/hannds"
    )
    ap.add_argument("--all", action="store_true", help="train on every piece (no held-out measure)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--steps", type=int, default=4000)
    ap.add_argument("--out", default=str(Path(hands.MODEL_PATH)))
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    random.seed(args.seed)
    np.random.seed(args.seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    songs = hannds(args.hannds)
    val_names = set() if args.all else held_out(songs)
    train = [s for s in songs if s[0] not in val_names]
    val = [s for s in songs if s[0] in val_names]
    jobs = known_jobs()
    out = Path(args.out)
    tmp = out.with_suffix(".tmp.npz")

    net = Net().to(device)
    opt = torch.optim.AdamW(net.parameters(), lr=3e-3, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=3e-3, total_steps=args.steps)
    lossf = nn.BCEWithLogitsLoss(reduction="none")
    t0 = time.time()
    for step in range(1, args.steps + 1):
        keys, X, y, m = make_batch(train, device)
        if step > 300:  # reveal some of the model's own mistakes
            with torch.no_grad():
                wrong = ((net(keys, X) > 0) != (y > 0.5)) & (m > 0)
            for b in range(len(y)):
                if random.random() < 0.6:
                    pos = torch.nonzero(wrong[b]).flatten().tolist()
                    for q in random.sample(pos, min(len(pos), random.randint(1, 3))):
                        X[b, q, 9] = 1.0 if y[b, q] > 0.5 else -1.0
                        m[b, q] = 0.0
        loss = (lossf(net(keys, X), y) * m).sum() / m.sum()
        opt.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(net.parameters(), 1.0)
        opt.step()
        sched.step()
        if step % 500 == 0 or step == args.steps:
            net.eval()
            export(net, tmp)
            net.train()
            msg = f"{step} loss {loss.item():.3f}"
            if val:
                msg += f" hannds-held-out {100 * accuracy(tmp, val)[0]:.2f}"
            if jobs:
                a, per = accuracy(tmp, jobs)
                msg += f" jobs {100 * a:.2f} [{' '.join(f'{100 * x:.1f}' for x in per)}]"
            print(f"{msg} {time.time() - t0:.0f}s", flush=True)
    net.eval()
    export(net, out)
    tmp.unlink(missing_ok=True)
    print("saved", out)


if __name__ == "__main__":
    main()
