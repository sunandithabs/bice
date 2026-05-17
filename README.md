# BICE — Behavioral Identity Continuity Engine

IoT anomaly detection without deep learning, without labeled attack data, and without needing to know what the attack looks like in advance.

BICE builds a behavioral baseline per device and watches for drift from it using sliding-window Z-scores. When a device starts acting differently enough from its own history, it gets flagged. That's it. No training phase, no signatures, no tuning per attack family.

Validated on the [N-BaIoT dataset](https://www.kaggle.com/datasets/mkashifn/nbaiot-dataset) — 89 behavioral profiles across 9 physical devices, Gafgyt and Mirai botnet traffic:

- **TPR: 100%** (80/80 attack profiles detected)
- **FPR: 0%** (9/9 benign profiles clean)

---

## How it works

Each device gets its own baseline — mean and variance per feature, updated online using Welford's algorithm. Every tick, BICE computes a Z-score for each feature against that device's own history, takes the mean absolute Z-score across all features, and compares it to a threshold θ.

```
drift Δ = mean(|z_i|) for all features i
alert if Δ > θ
```

Trust score decays as drift increases:

```
T = max(0, 100 - (Δ/θ)^2.2 × 20)
```

When trust drops below 30, the device gets quarantined automatically. Getting un-quarantined requires a human.

Baseline updates are gated — if a device is in alert state, its baseline freezes. This prevents an attacker from slowly poisoning the baseline over time.

---

## Running it

**Requirements:** Python 3.10+, uvicorn, fastapi

```bash
git clone https://github.com/yourname/bice
cd bice
pip install -r requirements.txt
```

**With the N-BaIoT dataset:**

```bash
BICE_DATASET_PATH=/path/to/nbaiot/archive python3 -m uvicorn main:app --port 8000
```

The dataset should be a flat directory of CSVs named like `1.benign.csv`, `1.gafgyt.combo.csv`, etc. Metadata files (non-device CSVs) should be moved out before running — BICE will try to load everything it finds.

**Check status:**

```bash
curl http://localhost:8000/api/state
curl http://localhost:8000/api/calibration
```

**Run metrics** (once the server is ready):

```bash
python3 test_metrics.py
```

---

## Dataset layout expected

```
archive/
  1.benign.csv
  1.gafgyt.combo.csv
  1.gafgyt.junk.csv
  ...
  9.mirai.udpplain.csv
```

9 physical devices × ~10 traffic variants each = 89 behavioral profiles after excluding metadata files.

---

## Numerical stability notes

N-BaIoT features span wildly different scales — some means sit around 10^14. The default sigma floor of `0.001` will cause Z-scores to explode on features like that. BICE uses a magnitude-scaled floor instead:

```python
sigma_floor = max(abs(mean) * 0.001, 1.0)
```

Z-scores are also clipped to [-100, +100] to prevent individual features from dominating the aggregate drift. If you're running BICE on a different dataset, watch for this — it'll look like everything is alerting immediately.

---

## API

| Endpoint | Method | Description |
|---|---|---|
| `/api/state` | GET | Device states, drift scores, alert status |
| `/api/calibration` | GET | Which devices have been calibrated, calibration log |
| `/api/attack/{name}` | POST | Toggle attack flag on a device (for testing) |
| `/api/quarantine/{name}` | POST | Toggle quarantine on a device |
| `/api/reset` | POST | Reset all devices, rewind CSVs to row 0 |

---

## Paper

Full writeup: *BICE: Behavioral Identity Continuity Engine for Time-Aware Anomaly Detection in IoT Networks* — submitted for a double-blind review.

Covers the full ablation study (50% → 88.9% → 100%), two implementation bugs that caused the initial low TPR, and a head-to-head comparison against Isolation Forest and One-Class SVM on the same feature set.

---

## What it doesn't do

- Volumetric attacks (DDoS, floods, brute force) — those are handled fine by threshold-based tools, BICE isn't trying to replace them
- Attack classification — it'll tell you *that* a device drifted, not *which* attack it is
- Real-time packet capture — the current prototype runs on pre-extracted CSVs; eBPF/XDP deployment is the next step
