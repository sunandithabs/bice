# BICE — Behavioral Identity Continuity Engine

BICE is a per-device behavioral anomaly detection framework for IoT networks.
It maintains a running statistical baseline per device (Welford online mean/variance)
and raises an alert when observed behavior drifts beyond a per-device Z-score
threshold, without requiring any labeled attack traffic.

Evaluated on the [N-BaIoT dataset](docs/DATASET.md) across 89 behavioral profiles
from 9 physical IoT devices. See [`docs/IEEE_EVALUATION_REPORT.md`](docs/IEEE_EVALUATION_REPORT.md)
for full methodology and results.

## Requirements

- Python 3.10+
- See `requirements.txt`

## Setup

```bash
git clone <repo-url>
cd bice
pip install -r requirements.txt
```

## Running

From the project root (this directory, the one containing `run.py`):

```bash
python run.py --dataset /path/to/n-baiot-folder
```

Leave `--dataset` empty to run a synthetic simulation instead of the real dataset.
Once running, the dashboard is served at `http://localhost:8000`.

Alternatively, set the dataset path via environment variable and launch uvicorn directly:

```bash
BICE_DATASET_PATH=/path/to/n-baiot-folder python -m uvicorn engine.main:app --port 8000
```

## Evaluation

`test_metrics.py` polls a running server and reports drift/trust statistics
once all device baselines are ready. `scripts/run_eval.sh` automates a full
start-server → wait-for-baseline → collect-metrics run:

```bash
BICE_DATASET_PATH=/path/to/n-baiot-folder ./scripts/run_eval.sh
```

For offline evaluation (no server needed) against real N-BaIoT data:

```bash
python3 scripts/full_evaluation.py            # classification metrics, runtime, ablation study
python3 scripts/baseline_comparison.py --dataset /path/to/n-baiot-folder
```

If `results/synthetic_nbaiot/` doesn't exist yet, `full_evaluation.py`
generates a deterministic (seed=42) synthetic stand-in dataset first — the
real N-BaIoT dataset is hosted at archive.ics.uci.edu; point
`scripts/full_evaluation.py`'s `DATASET_DIR` (or `baseline_comparison.py
--dataset`) at a real download to evaluate on it instead. See
[`docs/IEEE_EVALUATION_REPORT.md`](docs/IEEE_EVALUATION_REPORT.md) §2.3 and
§3 for full methodology, parameters, and results, and
`results/full_evaluation.json` for raw output.

## Project structure

```
bice/
├── run.py                  # CLI entry point, launches uvicorn
├── requirements.txt
├── engine/
│   ├── main.py              # FastAPI app, telemetry loop, API routes
│   ├── engine.py             # Device model, drift/trust scoring
│   ├── dataset.py            # N-BaIoT CSV loading, DatasetDevice
│   ├── evaluate.py           # Scenario-based evaluation harness
│   └── evaluate_optimizations.py
├── dashboard/
│   └── index.html            # Live monitoring dashboard (served at "/")
├── scripts/
│   ├── run_eval.sh           # End-to-end evaluation runner (live server)
│   ├── full_evaluation.py    # Offline: classification metrics, runtime, ablation study
│   ├── generate_synthetic_dataset.py  # Deterministic N-BaIoT-format stand-in dataset
│   └── baseline_comparison.py # BICE vs IsolationForest/OC-SVM, theta sweep
├── sample_dataset.py         # Utility: sample a subset of the raw N-BaIoT CSVs
├── test_metrics.py           # Polls a running server, prints summary stats
└── docs/
    ├── DATASET.md             # N-BaIoT dataset description
    └── IEEE_EVALUATION_REPORT.md
```

## API

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Dashboard UI |
| `/api/state` | GET | Current per-device drift/trust/alert state |
| `/api/calibration` | GET | Theta calibration log |
| `/api/export` | GET | Export telemetry as CSV/JSON |
| `/api/attack/{name}` | POST | Toggle simulated attack (synthetic mode only) |
| `/api/quarantine/{name}` | POST | Toggle manual quarantine |
| `/api/reset` | POST | Reset all device state for a clean re-run |

## License

MIT — see [LICENSE](LICENSE).
