"""Incremental coarse quantizer: EMA centroids with dead-cluster revival.

Two pieces of e-means (Bessa et al., arXiv:2611.09501) survive contact with a
living notes corpus. The centroid rule:

    S_j <- (1 - a) S_j + a s_j        N_j <- (1 - a) N_j + a n_j
    c_j  = S_j / N_j

where s_j, n_j are the sum and count of the current batch's points assigned to
cluster j. Lloyd's algorithm is the special case a = 1 with the full dataset as
the batch, so this is a rewrite of the update, not a new algorithm.

The second piece is revival: a cluster with too few points is split from a donor
chosen with probability proportional to its size, rather than resampled from the
batch. On their 16k-codebook ablation that is 47 dead clusters against 2,343 for
batch resampling.

What is deliberately not here: their scaling laws are exposed but not used as
defaults, and the GPU kernels are irrelevant to a stdlib-only CPU index. The
point of the module is that the centroids can be updated from a batch of new
chunks without re-reading the corpus, which is what a vault that grows needs.
Lloyd has to see everything, every time.

Cost note: pure Python, no numpy. Assignment is k dot products per point, and
the dot products run at C speed through map/sum. That is comfortable to about
10^4 points and the wrong tool past 10^5; past that, install numpy and the same
rules run 50x faster.
"""

import json
import math
import random
import sqlite3
import struct
from operator import mul

TINY = 1e-12


def _dot(a, b):
    """Float dot product, iterated in C rather than in the interpreter."""
    return sum(map(mul, a, b))


class Coarse:
    """k centroids updated by exponential moving average.

    `batch` and `alpha0` default to the published scaling laws for the problem
    size, so callers get the paper's no-tuning property for free. Pass either
    explicitly to override; pass alpha0=1.0 and batch=len(data) to recover
    plain Lloyd on a single call to fit().
    """

    def __init__(self, k, dim, alpha0=None, batch=None, epochs=5, seed=0,
                 revive_ratio=0.1, revival=True):
        if k < 1 or dim < 1:
            raise ValueError("k and dim must be positive")
        self.k = k
        self.dim = dim
        self.epochs = epochs
        self.seed = seed
        self.revive_ratio = revive_ratio
        self.revival = revival
        self.rng = random.Random(seed)
        self.centroids = []
        self._cn = []          # squared norm of each centroid, cached for assignment
        self.S = []            # EMA sums
        self.N = []            # EMA counts
        self.counts = []       # exact counts from the last epoch
        self.alpha0 = alpha0
        self.batch = batch
        self.events = {"revivals": 0, "dead_at_build": 0, "steps": 0}

    @staticmethod
    def scaling_laws(n, k, epochs, quality=False):
        """Batch size and initial step for (n, k, T), from the paper's fit.

        They validated on 10^6-10^8 points; the laws are reproduced as published
        and are used here far below that range, so treat the output as a sane
        starting point rather than a guarantee.
        """
        c_b = 0.0044 if quality else 0.035
        batch = c_b * (k ** 0.13) * (n ** 0.88) * (epochs ** 0.81)
        batch = int(max(1, min(n, round(batch))))
        alpha0 = 0.824 * (k ** -0.46) * (batch ** 0.90) * (n ** -0.45) * (epochs ** -0.11)
        return batch, min(1.0, alpha0)

    # -- centroids ---------------------------------------------------------

    def _reindex(self):
        self._cn = [_dot(c, c) for c in self.centroids]

    def _recompute_centroids(self):
        out = []
        for j in range(self.k):
            n = self.N[j]
            if n <= TINY:
                out.append(self.centroids[j])
                continue
            inv = 1.0 / n
            out.append([v * inv for v in self.S[j]])
        self.centroids = out
        self._reindex()

    def _init(self, data):
        """Seed from k distinct data points, which is what the paper does."""
        idx = list(range(len(data)))
        self.rng.shuffle(idx)
        pick = idx[: self.k]
        if len(pick) < self.k:
            raise ValueError(f"need at least k={self.k} points to initialise, got {len(pick)}")
        self.centroids = [list(data[i]) for i in pick]
        self.S = [[v * TINY for v in c] for c in self.centroids]
        self.N = [TINY] * self.k
        self._reindex()

    def init_from(self, points):
        """Seed the codebook from explicit points, for a bad-init control."""
        if len(points) < self.k:
            raise ValueError(f"need {self.k} seed points, got {len(points)}")
        self.centroids = [list(p) for p in points[: self.k]]
        self.S = [[v * TINY for v in c] for c in self.centroids]
        self.N = [TINY] * self.k
        self._reindex()
        return self

    def _assign_one(self, x):
        """Nearest centroid by squared euclidean, with ||x|| folded out.

        For unit-norm x, ||x - c||^2 = 1 - 2 x.c + ||c||^2, so only the last two
        terms are needed.
        """
        best, best_d = 0, 1e308
        for j, c in enumerate(self.centroids):
            d = self._cn[j] - 2.0 * _dot(x, c)
            if d < best_d:
                best_d, best = d, j
        return best

    def assign(self, data):
        return [self._assign_one(x) for x in data]

    # -- update ------------------------------------------------------------

    def _alpha(self, step, total):
        """Cosine anneal from alpha0 down to 0.1 * alpha0, as published."""
        a0 = self.alpha0
        frac = step / total if total > 1 else 0.0
        return a0 * (0.1 + 0.9 * 0.5 * (1.0 + math.cos(math.pi * frac)))

    def partial_fit(self, batch_data):
        """One EMA step over a batch, then rebuild the centroids from S/N."""
        if not self.centroids:
            self._init(batch_data)
        if self.alpha0 is None:
            _, self.alpha0 = self.scaling_laws(len(batch_data), self.k, 5)
        alpha = self.alpha0
        sums = [[0.0] * self.dim for _ in range(self.k)]
        counts = [0] * self.k
        for x in batch_data:
            j = self._assign_one(x)
            counts[j] += 1
            sums[j] = [s + v for s, v in zip(sums[j], x)]
        keep = 1.0 - alpha
        for j in range(self.k):
            if counts[j] == 0:
                # a cluster that missed this batch just decays toward nothing
                self.S[j] = [v * keep for v in self.S[j]]
                self.N[j] *= keep
                continue
            self.S[j] = [keep * s + alpha * bs for s, bs in zip(self.S[j], sums[j])]
            self.N[j] = keep * self.N[j] + alpha * counts[j]
        self._recompute_centroids()
        self.events["steps"] += 1

    def fit(self, data):
        """Run `epochs` shuffled passes, with revival between them."""
        n = len(data)
        if self.epochs < 1:
            raise ValueError("epochs must be at least 1")
        if self.batch is None or self.alpha0 is None:
            batch, alpha0 = self.scaling_laws(n, self.k, self.epochs)
            self.batch = self.batch or batch
            self.alpha0 = self.alpha0 or alpha0
        if not self.centroids:
            self._init(data)
        total = self.epochs * max(1, math.ceil(n / self.batch))
        step = 0
        order = list(range(n))
        for _ in range(self.epochs):
            self.rng.shuffle(order)
            for start in range(0, n, self.batch):
                idx = order[start:start + self.batch]
                self._ema_step(data, idx, step, total)
                step += 1
            counts, spread = self._exact_stats(data)
            self.counts = counts
            self.set_spread(spread)
            if self.revival:
                self._revive()
        self.events["dead_at_build"] = self.dead_count()
        return self

    def _ema_step(self, data, idx, step, total):
        alpha = self._alpha(step, total)
        sums = [[0.0] * self.dim for _ in range(self.k)]
        counts = [0] * self.k
        for i in idx:
            x = data[i]
            j = self._assign_one(x)
            counts[j] += 1
            sums[j] = [s + v for s, v in zip(sums[j], x)]
        keep = 1.0 - alpha
        for j in range(self.k):
            if counts[j] == 0:
                self.S[j] = [v * keep for v in self.S[j]]
                self.N[j] *= keep
            else:
                self.S[j] = [keep * s + alpha * bs for s, bs in zip(self.S[j], sums[j])]
                self.N[j] = keep * self.N[j] + alpha * counts[j]
        self._recompute_centroids()
        self.events["steps"] += 1

    def _exact_stats(self, data):
        """Per-cluster counts and mean radius from one pass.

        The radius sets how far a split pushes its two halves apart. Without it
        a revival produces two coincident centroids and the slot dies again on
        the next epoch.
        """
        counts = [0] * self.k
        squared = [0.0] * self.k
        for x in data:
            j = self._assign_one(x)
            counts[j] += 1
            # the norm identity can cancel to a tiny negative on near-duplicates
            squared[j] += max(0.0, 1.0 + self._cn[j] - 2.0 * _dot(x, self.centroids[j]))
        spread = [
            math.sqrt(squared[j] / counts[j]) if counts[j] else 0.0 for j in range(self.k)
        ]
        return counts, spread

    # -- revival -----------------------------------------------------------

    def dead_count(self, min_size=None):
        """Clusters holding fewer than `min_size` points.

        Default threshold is a tenth of an average cluster, floored at one
        point, so the count is meaningful whether the sample is 10^3 or 10^7.
        """
        if not self.counts:
            return 0
        if min_size is None:
            min_size = max(1, int(self.revive_ratio * sum(self.counts) / self.k))
        return sum(1 for c in self.counts if c < min_size)

    def _revive(self):
        """Split a donor into a dead cluster's slot.

        Donor is sampled proportionally to size, and the split is two points on
        either side of the donor centroid along a random direction, scaled by the
        donor's own spread. Reviving toward the middle of a big cluster is what
        keeps capacity from drifting to a random corner of the space.
        """
        if not self.counts:
            return
        min_size = max(1, int(self.revive_ratio * sum(self.counts) / self.k))
        dead = [j for j, c in enumerate(self.counts) if c < min_size]
        if not dead:
            return
        alive = [j for j, c in enumerate(self.counts) if c >= min_size]
        if len(alive) < 2:
            return
        weights = [self.counts[j] for j in alive]
        for slot in dead:
            donor = self.rng.choices(alive, weights=weights, k=1)[0]
            spread = self._spread[donor] if hasattr(self, "_spread") else 0.0
            scale = 0.5 * spread if spread > TINY else 1e-3
            direction = [self.rng.gauss(0.0, 1.0) for _ in range(self.dim)]
            norm = math.sqrt(_dot(direction, direction)) or 1.0
            direction = [v / norm for v in direction]
            donor_c = self.centroids[donor]
            self.centroids[slot] = [c + scale * u for c, u in zip(donor_c, direction)]
            self.centroids[donor] = [c - scale * u for c, u in zip(donor_c, direction)]
            # both halves inherit half the donor's mass so neither looks empty
            half = self.N[donor] * 0.5
            self.S[slot] = [v * 0.5 for v in self.S[donor]]
            self.N[slot] = half
            self.S[donor] = [v * 0.5 for v in self.S[donor]]
            self.N[donor] = half
            self.counts[slot] = self.counts[donor] // 2
            self.counts[donor] -= self.counts[slot]
            weights = [self.counts[j] for j in alive]
            self.events["revivals"] += 1
        self._reindex()

    def set_spread(self, spread):
        """Per-cluster mean distance to centroid, used to size a split."""
        self._spread = list(spread)

    # -- finishing ---------------------------------------------------------

    def finalize(self, data):
        """One full pass, then each cluster's exact mean over its final members.

        The EMA centroids lag a batch behind and carry the decay of old
        assignments. This drops that bias for one sequential-latency pass, which
        the paper reports as free quality at the end of training.
        """
        counts = [0] * self.k
        sums = [[0.0] * self.dim for _ in range(self.k)]
        for x in data:
            j = self._assign_one(x)
            counts[j] += 1
            sums[j] = [s + v for s, v in zip(sums[j], x)]
        out = []
        for j in range(self.k):
            if counts[j] == 0:
                out.append(self.centroids[j])
            else:
                inv = 1.0 / counts[j]
                out.append([v * inv for v in sums[j]])
        self.centroids = out
        self.counts = counts
        self.S = sums
        self.N = [float(c) for c in counts]
        self._reindex()
        return self

    def mse(self, data, labels=None):
        """Mean squared distance from each point to its assigned centroid."""
        if labels is None:
            labels = self.assign(data)
        total = 0.0
        for x, j in zip(data, labels):
            c = self.centroids[j]
            d = _dot(x, c)
            total += max(0.0, 1.0 + self._cn[j] - 2.0 * d)
        return total / len(data) if data else 0.0

    def imbalance(self):
        """Evenness of cluster sizes; 1.0 means every cluster has the same count."""
        live = [c for c in self.counts if c > 0]
        if not live:
            return float("inf")
        mean = sum(live) / len(live)
        var = sum((c - mean) ** 2 for c in live) / len(live)
        return math.sqrt(var) / mean if mean else float("inf")

    def drift(self, previous):
        """Mean cosine distance between these centroids and an earlier snapshot.

        Lower means the codebook stayed put. This is the number to watch on a
        growing vault: if it stays near zero after an incremental update, the
        old assignments are still valid and the index did not need a rebuild.
        """
        if not previous:
            return 1.0
        total, n = 0.0, 0
        for a, b in zip(self.centroids, previous):
            na = math.sqrt(_dot(a, a)) or 1.0
            nb = math.sqrt(_dot(b, b)) or 1.0
            total += 1.0 - (_dot(a, b) / (na * nb))
            n += 1
        return total / n if n else 1.0

    def snapshot(self):
        return [list(c) for c in self.centroids]

    # -- persistence -------------------------------------------------------

    def save(self, db, table="coarse", meta=None):
        """Write centroids and the build parameters into the index database.

        Same blob convention as the vectors table: little-endian floats, so
        anything that already reads this database can read these too.
        """
        db.execute(f"DROP TABLE IF EXISTS {table}")
        db.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, vec BLOB NOT NULL)")
        for j, c in enumerate(self.centroids):
            db.execute(
                f"INSERT INTO {table} (id, vec) VALUES (?,?)",
                (j, struct.pack(f"{self.dim}f", *c)),
            )
        db.execute("DROP TABLE IF EXISTS coarse_meta")
        db.execute("CREATE TABLE coarse_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        rows = {
            "k": str(self.k),
            "dim": str(self.dim),
            "alpha0": repr(self.alpha0),
            "batch": str(self.batch),
            "epochs": str(self.epochs),
            "seed": str(self.seed),
            "revival": str(self.revival),
            "events": json.dumps(self.events),
        }
        rows.update(meta or {})
        for key, value in rows.items():
            db.execute("INSERT INTO coarse_meta VALUES (?,?)", (key, str(value)))

    @classmethod
    def load(cls, db, table="coarse"):
        meta = dict(db.execute("SELECT key, value FROM coarse_meta").fetchall())
        centroids = [
            list(struct.unpack(f"{meta['dim']}f", blob))
            for blob in (r[0] for r in db.execute(f"SELECT vec FROM {table} ORDER BY id"))
        ]
        obj = cls(
            int(meta["k"]),
            int(meta["dim"]),
            alpha0=float(meta["alpha0"]),
            batch=int(meta["batch"]),
            epochs=int(meta["epochs"]),
            seed=int(meta["seed"]),
            revival=meta["revival"] == "True",
        )
        obj.centroids = centroids
        obj._reindex()
        return obj
