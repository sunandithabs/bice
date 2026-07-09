#!/usr/bin/env python3
"""
sample_dataset.py

Grabs the first ROWS_PER_FILE rows from every CSV in the source folder
and writes them into a new folder. Run once, then point BICE at the output.

Usage:
    python3 sample_dataset.py \
        --src ~/Downloads/archive \
        --dst ~/Downloads/archive_sampled \
        --rows 500
"""

import argparse
import csv
import os
import sys


def sample(src_dir, dst_dir, rows_per_file, skip_rows=0):
    if not os.path.isdir(src_dir):
        print(f"ERROR: source folder not found: {src_dir}")
        sys.exit(1)

    os.makedirs(dst_dir, exist_ok=True)

    csv_files = sorted(
        f for f in os.listdir(src_dir)
        if f.lower().endswith(".csv") and f.lower() != "device_info.csv"
    )

    if not csv_files:
        print(f"ERROR: no CSV files found in {src_dir}")
        sys.exit(1)

    print(f"Found {len(csv_files)} CSV files. Sampling {rows_per_file} rows each...")
    print()

    total_rows = 0
    for fname in csv_files:
        src_path = os.path.join(src_dir, fname)
        dst_path = os.path.join(dst_dir, fname)

        with open(src_path, newline="", encoding="utf-8") as fin, \
             open(dst_path, "w", newline="", encoding="utf-8") as fout:

            reader = csv.DictReader(fin)
            if reader.fieldnames is None:
                print(f"  SKIP {fname} — no header")
                continue

            writer = csv.DictWriter(fout, fieldnames=reader.fieldnames)
            writer.writeheader()

            skipped = 0
            count = 0
            for row in reader:
                if skipped < skip_rows:
                    skipped += 1
                    continue
                writer.writerow(row)
                count += 1
                if count >= rows_per_file:
                    break

        total_rows += count
        print(f"  {fname}: {count} rows")

    print()
    print(f"Done. {len(csv_files)} files, {total_rows} total rows → {dst_dir}")
    print()
    print("Now run:")
    print(f"  BICE_DATASET_PATH={dst_dir} python3 -m uvicorn main:app --port 8000")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sample N rows from each N-BaIoT CSV.")
    parser.add_argument("--src", required=True, help="Source dataset folder")
    parser.add_argument("--dst", required=True, help="Output folder for sampled CSVs")
    parser.add_argument("--rows", type=int, default=500, help="Rows per file (default 500)")
    parser.add_argument(
        "--skip", type=int, default=60,
        help=(
            "Burn-in rows discarded from the start of each CSV before sampling begins "
            "(default 1000). N-BaIoT's decay-based Kitsune features (esp. L0.1/L0.01) "
            "start at zero and are still converging in the first rows of any capture. "
            "Without this, taking 'the first N rows' of every file -- benign and attack "
            "alike -- samples exactly that cold-start transient rather than steady-state "
            "behavior, which the engine (engine/dataset.py DatasetDevice.BURN_IN_ROWS) "
            "also discards independently as defense-in-depth."
        ),
    )
    args = parser.parse_args()

    sample(
        os.path.expanduser(args.src),
        os.path.expanduser(args.dst),
        args.rows,
        skip_rows=args.skip,
    )
