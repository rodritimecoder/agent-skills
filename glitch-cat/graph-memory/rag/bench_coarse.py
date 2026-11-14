"""Does the EMA update earn its place? Measure it against Lloyd, and against
the negative control.

Two questions, two tables:

  1. Quality. Same seed, same init, Lloyd for 25 full passes against the EMA rule
     for 5 epochs. Revival is ablated so the test can fail: with it off the dead
     count must go up, otherwise the harness is measuring nothing.
  2. Incremental update. Fit on 80% of the corpus, then show what happens when
     the other 20% arrives: leave the centroids stale, update them by EMA, or
     refit from scratch. If the EMA update does not land near the refit, the
     premise fails and the module should not be wired into the index.

Run: python3 bench_coarse.py [--real] [--n 4000] [--k 32]
"""

import argparse
import math
import os
import random
import sqlite3
import struct
from pathlib import Path

from coarse import Coarse, _dot

HERE = Path(__file__).resolve().parent
DB = Path(os.environ.get("RAG_DB_PATH", str(HERE / "rag.db")))


# -- baseline ---------------------------------------------------------------

def lloyd(data, k, epochs=25, seed=0, init=None):
    """Lloyd's algorithm, full batch, written independently of Coarse.

    The comparison target should not share code with the thing it judges.
    """
    dim = len(data[0])
    rng = random.Random(seed)
    if init is not None:
        centroids = [list(p) for p in init[:k]]
    else:
        idx = list(range(len(data)))
        rng.shuffle(idx)
        centroids = [list(data[i]) for i in idx[:k]]
    for _ in range(epochs):
        sums = [[0.0] * dim for _ in range(k)]
        counts = [0] * k
        for x in data:
            best, best_d = 0, 1e308
            for j, c in enumerate(centroids):
                d = _dot(c, c) - 2.0 * _dot(x, c)
                if d < best_d:
                    best_d, best = d, j
            counts[best] += 1
            sums[best] = [s + v for s, v in zip(sums[best], x)]
        for j in range(k):
            if counts[j]:
                inv = 1.0 / counts[j]
                centroids[j] = [v * inv for v in sums[j]]
    return centroids


# -- scoring ----------------------------------------------------------------

def score(data, centroids):
    """MSE, dead clusters, size imbalance. Independent of Coarse's methods.

    Dead means zero assigned points. A count threshold tied to the points on
    hand would call most clusters dead on a 400-point sample, which is a
    property of the sample and not of the clustering.
    """
    k = len(centroids)
    norms = [_dot(c, c) for c in centroids]
    counts = [0] * k
    total = 0.0
    for x in data:
        best, best_d = 0, 1e308
        for j, c in enumerate(centroids):
            d = norms[j] - 2.0 * _dot(x, c)
            if d < best_d:
                best_d, best = d, j
        counts[best] += 1
        total += max(0.0, 1.0 + norms[best] - 2.0 * _dot(x, centroids[best]))
    dead = sum(1 for c in counts if c == 0)
    live = [c for c in counts if c > 0]
    mean = sum(live) / len(live) if live else 0
    imbalance = (
        math.sqrt(sum((c - mean) ** 2 for c in live) / len(live)) / mean if mean else float("inf")
    )
    return total / len(data), dead, imbalance, counts


# -- data -------------------------------------------------------------------

def toy(n=4000, dim=32, seed=7):
    """The paper's toy shape: two wide blobs, three small ones, light background.

    Sizes and spreads differ by an order of magnitude, which is what makes Lloyd
    strand centroids in the gaps. The result is shuffled: emitted in blob order,
    a 80/20 slice is a distribution shift rather than a random partition, and
    the incremental table would be measuring the wrong thing.
    """
    rng = random.Random(seed)
    blobs = [
        ([3.0, 0.0] + [0.0] * (dim - 2), 3.0, 0.36),
        ([-3.0, 0.0] + [0.0] * (dim - 2), 3.0, 0.24),
        ([0.0, 4.0] + [0.0] * (dim - 2), 0.5, 0.09),
        ([0.0, -4.0] + [0.0] * (dim - 2), 0.5, 0.08),
        ([4.0, 4.0] + [0.0] * (dim - 2), 0.5, 0.08),
    ]
    out = []
    for center, spread, share in blobs:
        for _ in range(int(n * share)):
            p = [c + rng.gauss(0.0, spread) for c in center]
            out.append([max(-8.0, min(8.0, v)) for v in p])
    while len(out) < n:
        out.append([rng.uniform(-8.0, 8.0) for _ in range(dim)])
    for x in out:
        norm = math.sqrt(_dot(x, x)) or 1.0
        x[:] = [v / norm for v in x]
    rng.shuffle(out)
    return out


def real_vectors():
    """Unit vectors already in rag.db, if there are enough to cluster."""
    if not DB.is_file():
        return []
    db = sqlite3.connect(DB)
    try:
        dim = int(dict(db.execute("SELECT key, value FROM meta").fetchall()).get("embedding_dim", 0))
        rows = db.execute("SELECT vec FROM vectors").fetchall()
    except sqlite3.Error:
        return []
    finally:
        db.close()
    if not dim or len(rows) < 32:
        return []
    return [list(struct.unpack(f"{dim}f", r[0])) for r in rows]


# -- experiments ------------------------------------------------------------

def quality_table(data, k):
    print(f"\n{'method':<34}{'MSE':>10}{'dead':>7}{'imbal':>8}{'steps':>8}")
    print("-" * 67)
    base = None
    rows = []

    loyd = lloyd(data, k, epochs=25, seed=0)
    mse, dead, imb, _ = score(data, loyd)
    base = mse
    print(f"{'Lloyd, 25 full passes':<34}{mse:>10.6f}{dead:>7}{imb:>8.3f}{25:>8}")
    rows.append(("lloyd", mse))

    for revival in (True, False):
        em = Coarse(k, len(data[0]), epochs=5, seed=0, revival=revival)
        em.fit(data)
        steps = em.events["steps"]
        mse, dead, imb, _ = score(data, em.centroids)
        label = "EMA+revival+finalize" if revival else "EMA, revival OFF (control)"
        if revival:
            print(f"{'EMA+revival, before finalize':<34}{mse:>10.6f}{dead:>7}{imb:>8.3f}{steps:>8}")
            em.finalize(data)
            mse_fin, dead_fin, imb_fin, _ = score(data, em.centroids)
            print(f"{label:<34}{mse_fin:>10.6f}{dead_fin:>7}{imb_fin:>8.3f}{steps:>8}")
            rows.append(("ema_final", mse_fin))
        else:
            print(f"{label:<34}{mse:>10.6f}{dead:>7}{imb:>8.3f}{steps:>8}")
            rows.append(("ema_control", mse))

    for name, mse in rows:
        if name != "lloyd":
            print(f"  {name:<20} vs Lloyd: {100 * (mse - base) / base:+.2f}% MSE")
    return rows


def stuck_table(data, k):
    """Bad init: centroids seeded in empty space.

    This is the regime where clusters die and the only one where revival has a
    job. Real data points are the wrong seed here: a centroid sitting on a point
    always wins it, so nothing dies and the table proves nothing.
    """
    dim = len(data[0])
    rng = random.Random(11)
    seeds = []
    for _ in range(k):
        v = [rng.gauss(0.0, 1.0) for _ in range(dim)]
        norm = math.sqrt(_dot(v, v)) or 1.0
        seeds.append([x / norm for x in v])

    print(f"\n{'method (bad init: centroids in empty space)':<46}{'MSE':>9}{'dead':>7}{'imbal':>8}")
    print("-" * 70)
    loyd = lloyd(data, k, epochs=25, seed=0, init=seeds)
    mse_l, dead_l, imb_l, _ = score(data, loyd)
    print(f"{'Lloyd, 25 passes, same start':<46}{mse_l:>9.5f}{dead_l:>7}{imb_l:>8.3f}")

    out = {}
    for revival in (True, False):
        em = Coarse(k, dim, epochs=5, seed=0, revival=revival)
        em.init_from(seeds)
        em.fit(data)
        em.finalize(data)
        mse, dead, imb, _ = score(data, em.centroids)
        label = "EMA+finalize, revival ON" if revival else "EMA+finalize, revival OFF (control)"
        print(f"{label:<46}{mse:>9.5f}{dead:>7}{imb:>8.3f}")
        out[revival] = (mse, dead, em.events["revivals"])
    return out


def incremental_table(data, k):
    """The case that actually matters for a vault that grows."""
    cut = int(len(data) * 0.8)
    old, new = data[:cut], data[cut:]
    dim = len(data[0])

    em = Coarse(k, dim, epochs=5, seed=0)
    em.fit(old)
    em.finalize(old)
    stale = em.snapshot()

    mse_stale, dead_stale, _, _ = score(new, stale)
    drift_before = 0.0

    em.alpha0 = 0.1 * em.alpha0
    for _ in range(3):
        em.partial_fit(new)
    em.finalize(data)
    incremental = em.snapshot()
    mse_inc, dead_inc, _, _ = score(new, incremental)
    drift = em.drift(stale)

    fresh = Coarse(k, dim, epochs=5, seed=0)
    fresh.fit(data)
    fresh.finalize(data)
    mse_fresh, dead_fresh, _, _ = score(new, fresh.centroids)

    print(f"\n{'stage':<34}{'MSE on new':>12}{'dead':>7}{'work':>28}")
    print("-" * 81)
    print(f"{'centroids stale (no update)':<34}{mse_stale:>12.6f}{dead_stale:>7}{'0 passes':>28}")
    print(f"{'EMA update on new batch':<34}{mse_inc:>12.6f}{dead_inc:>7}{'3 mini-batches, 20% of data':>28}")
    print(f"{'full refit from scratch':<34}{mse_fresh:>12.6f}{dead_fresh:>7}{f'{len(data)} pts x 5 epochs':>28}")
    print(f"\n  centroid drift (cosine distance, stale -> incremental): {drift:.4f}")
    gap = 100 * (mse_inc - mse_fresh) / mse_fresh if mse_fresh else 0.0
    print(f"  EMA update vs full refit: {gap:+.2f}% MSE")
    return mse_stale, mse_inc, mse_fresh


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=4000)
    ap.add_argument("--k", type=int, default=32)
    ap.add_argument("--dim", type=int, default=32)
    ap.add_argument("--real", action="store_true", help="cluster rag.db vectors instead of the toy")
    args = ap.parse_args()

    if args.real:
        data = real_vectors()
        if not data:
            raise SystemExit("rag.db has no usable vectors; run build_index.py first or drop --real")
        print(f"real corpus: {len(data)} vectors, {len(data[0])}d")
    else:
        data = toy(args.n, args.dim)
        print(f"toy corpus: {len(data)} vectors, {len(data[0])}d, k={args.k}")

    batch, alpha0 = Coarse.scaling_laws(len(data), args.k, 5)
    print(f"scaling laws at this size: batch={batch}, alpha0={alpha0:.4f}")

    quality_table(data, args.k)
    stuck_table(data, args.k)
    incremental_table(data, args.k)


if __name__ == "__main__":
    main()
