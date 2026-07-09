#!/usr/bin/env python3
"""
generate_synthetic_dataset.py

The real N-BaIoT dataset is hosted at archive.ics.uci.edu, which is not on
this environment's network allowlist, so it cannot be downloaded here. To
still produce real, runnable, numeric evaluation results (rather than made
up numbers), this script generates a synthetic dataset that follows the
*exact* N-BaIoT on-disk layout that engine/dataset.py already parses:

  <device_id>.<label>.csv          e.g. "1.benign.csv", "1.gafgyt.combo.csv"

with the same 100 Kitsune-derived numeric columns BICE's FEATURE_NAMES map
already documents (MI_dir / H / HH / HpHp at lambda = 5,3,1,0.1,0.01).

Generation is fully deterministic (fixed seed) and physically plausible:
  - Each physical device gets its own benign feature-mean/scale vector.
  - Benign rows are Gaussian noise around that vector.
  - Attack files apply a per-feature-group offset to a subset of columns.
    Two regimes are generated: "sudden" (offset present from row 0, mimics
    e.g. mirai.syn/ack floods) and "slow" (offset ramps linearly over the
    file, mimics low-and-slow gafgyt scans) -- both patterns BICE's design
    (README/IEEE report) explicitly targets.
  - A short cold-start segment (first BURN_IN_ROWS-equivalent rows) is left
    at the benign vector even in attack files, matching real captures where
    a capture starts before the attack traffic dominates the link -- this
    is what engine/dataset.py's BURN_IN_ROWS is designed to discard.

This is clearly a synthetic stand-in, not the real N-BaIoT data, and all
generated reports must say so.
"""
import argparse
import csv
import os
import random

FEATURE_GROUPS = ["MI_dir", "H", "HH", "HpHp"]
SCALES = ["L5", "L3", "L1", "L0.1", "L0.01"]
STATS_BY_GROUP = {
    "MI_dir": ["weight", "mean", "variance"],
    "H": ["weight", "mean", "variance"],
    "HH": ["weight", "mean", "std", "magnitude", "radius", "covariance", "pcc"],
    "HpHp": ["weight", "mean", "std", "magnitude", "radius", "covariance", "pcc"],
}


def feature_columns():
    cols = []
    for g in FEATURE_GROUPS:
        for s in SCALES:
            for stat in STATS_BY_GROUP[g]:
                cols.append(f"{g}_{s}_{stat}")
    return cols  # 100 columns, matches engine/dataset.py FEATURE_NAMES


def device_profile(rng, columns):
    """Per-physical-device baseline mean/scale for each column."""
    profile = {}
    for c in columns:
        mean = rng.uniform(1.0, 50.0)
        scale = mean * rng.uniform(0.03, 0.08) + 0.05
        profile[c] = (mean, scale)
    return profile


def write_csv(path, columns, rows):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=columns)
        w.writeheader()
        for r in rows:
            w.writerow(r)


COLD_START_ROWS = 80  # matches the rationale in engine/dataset.py BURN_IN_ROWS:
# Kitsune's decay-based features start at zero and overshoot while converging.
# Every capture (benign and attack alike) gets this same decaying transient,
# so a run that skips burn-in discarding sees genuinely contaminated data,
# not a difference we invented to flatter the ablation.


def _cold_start_bump(row_idx, rng):
    if row_idx >= COLD_START_ROWS:
        return 0.0
    decay = pow(2.71828, -row_idx / 25.0)
    return decay * rng.uniform(1.5, 3.0)


def gen_benign_rows(rng, columns, profile, n):
    rows = []
    for i in range(n):
        bump = _cold_start_bump(i, rng)
        rows.append({c: max(0.0, rng.gauss(profile[c][0] * (1 + bump), profile[c][1])) for c in columns})
    return rows


def gen_attack_rows(rng, columns, profile, n, affected_cols, offset_mult, mode, cold_start):
    rows = []
    for i in range(n):
        bump = _cold_start_bump(i, rng)
        if i < cold_start:
            intensity = 0.0
        elif mode == "sudden":
            intensity = 1.0
        else:  # "slow": linear ramp over the remainder of the file
            intensity = min(1.0, (i - cold_start) / max(1, (n - cold_start) * 0.7))
        row = {}
        for c in columns:
            mean, scale = profile[c]
            target_mean = mean * (1 + bump) + (offset_mult * mean * intensity if c in affected_cols else 0.0)
            row[c] = max(0.0, rng.gauss(target_mean, scale))
        rows.append(row)
    return rows


ATTACK_SPECS = [
    # (label, mode, offset_mult, group_fraction) -- deliberately modest
    # offsets/fractions so detection is a genuine statistical call rather
    # than a trivially-separated toy signal.
    ("gafgyt.combo", "slow", 1.4, 0.18),
    ("gafgyt.scan", "slow", 1.8, 0.12),
    ("mirai.syn", "sudden", 2.2, 0.22),
    ("mirai.udp", "sudden", 2.6, 0.28),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results", "synthetic_nbaiot"))
    ap.add_argument("--devices", type=int, default=3)
    ap.add_argument("--rows", type=int, default=900, help="rows per CSV")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    columns = feature_columns()
    os.makedirs(args.out, exist_ok=True)

    for dev_id in range(1, args.devices + 1):
        profile = device_profile(rng, columns)
        benign_rows = gen_benign_rows(rng, columns, profile, args.rows)
        write_csv(os.path.join(args.out, f"{dev_id}.benign.csv"), columns, benign_rows)

        for label, mode, offset_mult, frac in ATTACK_SPECS:
            n_affected = max(1, int(len(columns) * frac))
            affected = set(rng.sample(columns, n_affected))
            rows = gen_attack_rows(rng, columns, profile, args.rows, affected, offset_mult, mode, cold_start=60)
            write_csv(os.path.join(args.out, f"{dev_id}.{label}.csv"), columns, rows)

    print(f"Synthetic N-BaIoT-format dataset written to {args.out}")
    print(f"{args.devices} physical devices x (1 benign + {len(ATTACK_SPECS)} attack) files, {args.rows} rows each, seed={args.seed}")


if __name__ == "__main__":
    main()
