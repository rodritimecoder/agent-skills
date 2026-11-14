"""Tests for the coarse quantizer. Fast, no network, no corpus.

The revival test is the one that matters: it starts from a codebook that is
guaranteed to strand centroids, so it fails if revival regresses to doing
nothing. A test that passes with the feature turned off is not a test.
"""

import math
import random
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from coarse import Coarse, _dot

FAILED = []


def check(name, condition, detail=""):
    print(f"{'ok  ' if condition else 'FAIL'} {name}{'  ' + detail if detail else ''}")
    if not condition:
        FAILED.append(name)


def blobs(n_clusters=3, per=200, dim=8, seed=1):
    rng = random.Random(seed)
    out = []
    for c in range(n_clusters):
        centre = [0.0] * dim
        centre[c % dim] = 4.0
        for _ in range(per):
            out.append([v + rng.gauss(0.0, 0.25) for v in centre])
    for x in out:
        norm = math.sqrt(_dot(x, x)) or 1.0
        x[:] = [v / norm for v in x]
    rng.shuffle(out)
    return out


def test_scaling_laws():
    batch, alpha0 = Coarse.scaling_laws(2000, 24, 5)
    check("scaling laws: batch in range", 1 <= batch <= 2000, f"batch={batch}")
    check("scaling laws: alpha0 in (0,1]", 0.0 < alpha0 <= 1.0, f"alpha0={alpha0:.4f}")
    big_batch, big_alpha = Coarse.scaling_laws(1_000_000, 16384, 5)
    check("scaling laws: large problem stays sane",
          1 <= big_batch <= 1_000_000 and 0 < big_alpha <= 1.0,
          f"batch={big_batch} alpha0={big_alpha:.4f}")


def test_lloyd_equivalence():
    """alpha0=1 with a full-batch epoch must reproduce Lloyd's update exactly.

    This is the paper's claim that Lloyd is the special case; if it does not
    hold in code, the EMA rule is not a generalisation of the thing it replaces.
    """
    data = blobs()
    k = 6
    em = Coarse(k, len(data[0]), alpha0=1.0, batch=len(data), epochs=1, seed=3, revival=False)
    em._init(data)
    start = [list(c) for c in em.centroids]
    em.fit(data)

    sums = [[0.0] * len(data[0]) for _ in range(k)]
    counts = [0] * k
    for x in data:
        best, best_d = 0, 1e308
        for j, c in enumerate(start):
            d = _dot(c, c) - 2.0 * _dot(x, c)
            if d < best_d:
                best_d, best = d, j
        counts[best] += 1
        sums[best] = [s + v for s, v in zip(sums[best], x)]
    expected = [
        [v / counts[j] for v in sums[j]] if counts[j] else start[j] for j in range(k)
    ]
    worst = max(
        abs(a - b) for ce, ca in zip(expected, em.centroids) for a, b in zip(ce, ca)
    )
    check("alpha=1 reproduces Lloyd's mean", worst < 1e-9, f"max diff {worst:.2e}")


def test_revival_control():
    """A stranding init must be rescued by revival and stay bad without it.

    Centroids are seeded in empty space, not on data points: a centroid sitting
    on a real point always wins that point, and nothing ever dies.
    """
    data = blobs(n_clusters=3, per=200, dim=8)
    k = 12
    rng = random.Random(11)
    seed_points = []
    for _ in range(k):
        v = [rng.gauss(0.0, 1.0) for _ in range(len(data[0]))]
        norm = math.sqrt(_dot(v, v)) or 1.0
        seed_points.append([x / norm for x in v])

    on = Coarse(k, len(data[0]), epochs=4, seed=0, revival=True).init_from(seed_points)
    on.fit(data)
    counts_on, _ = on._exact_stats(data)

    off = Coarse(k, len(data[0]), epochs=4, seed=0, revival=False).init_from(seed_points)
    off.fit(data)
    counts_off, _ = off._exact_stats(data)

    dead_on = sum(1 for c in counts_on if c < 10)
    dead_off = sum(1 for c in counts_off if c < 10)
    check("control: bad init strands clusters with revival OFF", dead_off > 0, f"dead={dead_off}")
    check("revival: fewer dead clusters than control", dead_on < dead_off,
          f"dead on={dead_on} off={dead_off}")
    check("revival: it actually fired", on.events["revivals"] > 0,
          f"revivals={on.events['revivals']}")


def test_all_clusters_reachable():
    """Every centroid must be able to win a point, or capacity is wasted."""
    data = blobs()
    em = Coarse(6, len(data[0]), epochs=3, seed=0)
    em.fit(data)
    em.finalize(data)
    counts, _ = em._exact_stats(data)
    check("no cluster left empty", min(counts) > 0, f"min count={min(counts)}")


def test_incremental_drift():
    """Appending same-distribution data must not scramble an existing codebook,
    and appending a genuinely new blob must move it."""
    data = blobs(per=300)
    cut = int(len(data) * 0.8)
    em = Coarse(6, len(data[0]), epochs=4, seed=0)
    em.fit(data[:cut])
    em.finalize(data[:cut])
    before = em.snapshot()

    em.alpha0 = 0.1 * em.alpha0
    em.partial_fit(data[cut:])
    steady = em.drift(before)
    check("incremental update: same distribution leaves codebook stable", steady < 0.05,
          f"drift={steady:.4f}")

    # now a location the codebook has never seen
    rng = random.Random(5)
    dim = len(data[0])
    shifted = []
    for _ in range(120):
        centre = [0.0] * dim
        centre[dim - 1] = 5.0
        v = [c + rng.gauss(0.0, 0.2) for c in centre]
        norm = math.sqrt(_dot(v, v)) or 1.0
        shifted.append([x / norm for x in v])
    em.partial_fit(shifted)
    moved = em.drift(before)
    check("incremental update: a new region does move the codebook", moved > steady,
          f"drift {steady:.4f} -> {moved:.4f}")


def test_persistence():
    data = blobs()
    em = Coarse(6, len(data[0]), epochs=3, seed=0).fit(data)
    db = sqlite3.connect(":memory:")
    em.save(db)
    back = Coarse.load(db)
    worst = max(
        abs(a - b) for ca, cb in zip(em.centroids, back.centroids) for a, b in zip(ca, cb)
    )
    check("save/load round-trips centroids", worst < 1e-6, f"max diff {worst:.2e}")
    check("save/load keeps k and dim", back.k == em.k and back.dim == em.dim)


def test_empty_batch_cluster():
    """A cluster missing from a batch must decay, not divide by zero."""
    data = blobs()
    em = Coarse(6, len(data[0]), epochs=2, seed=0)
    em._init(data)
    em.alpha0 = 0.5
    em.partial_fit(data[:5])
    check("partial fit on a tiny batch is finite",
          all(math.isfinite(v) for c in em.centroids for v in c))


if __name__ == "__main__":
    for fn in (
        test_scaling_laws,
        test_lloyd_equivalence,
        test_revival_control,
        test_all_clusters_reachable,
        test_incremental_drift,
        test_persistence,
        test_empty_batch_cluster,
    ):
        print(f"\n{fn.__name__}")
        fn()
    print(f"\n{len(FAILED)} failed" if FAILED else "\nall passed")
    sys.exit(1 if FAILED else 0)
