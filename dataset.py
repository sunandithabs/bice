import atexit
import csv
import os
import math
import re
import shutil
import sys
import tempfile
from collections import defaultdict, deque

_TEMP_DATASET_DIRS = []


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _sanitize_filename(name):
    safe = re.sub(r'[^A-Za-z0-9_-]', '_', str(name).strip())
    return safe[:64] if safe else 'unknown'


def _infer_feature_names(sample_row, reserved=None):
    reserved = set(reserved or [])
    features = []
    for key, value in sample_row.items():
        if key in reserved:
            continue
        if value is None or value == "":
            continue
        if _to_float(value) is not None:
            features.append(key)
    return features


def _prepare_device_files(dataset_path, reserved=None):
    reserved = set(reserved or [])
    temp_dir = tempfile.mkdtemp(prefix="bice_nbaio_")
    _TEMP_DATASET_DIRS.append(temp_dir)
    device_paths = {}
    writers = {}
    feature_names = None

    with open(dataset_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError("Dataset file must contain a header row.")

        for row in reader:
            if feature_names is None:
                feature_names = _infer_feature_names(row, reserved=reserved)
                if not feature_names:
                    raise ValueError("Could not infer numeric feature columns from dataset")

            device_name = str(row.get("device") or row.get("Device") or "unknown").strip() or "unknown"
            if device_name not in writers:
                safe_name = _sanitize_filename(device_name)
                path = os.path.join(temp_dir, f"{len(writers)}_{safe_name}.csv")
                out_fh = open(path, "w", newline="", encoding="utf-8")
                writer = csv.DictWriter(out_fh, fieldnames=reader.fieldnames)
                writer.writeheader()
                writers[device_name] = (out_fh, writer)
                device_paths[device_name] = path

            writers[device_name][1].writerow(row)

    for out_fh, _ in writers.values():
        out_fh.close()

    return feature_names, device_paths


def cleanup_dataset_dirs():
    for temp_dir in list(_TEMP_DATASET_DIRS):
        try:
            shutil.rmtree(temp_dir)
        except Exception:
            pass
    _TEMP_DATASET_DIRS.clear()


def _collect_csv_paths(dataset_path):
    if os.path.isfile(dataset_path):
        return [dataset_path]
    if not os.path.isdir(dataset_path):
        raise ValueError(f"Dataset path is not a file or directory: {dataset_path}")

    csv_paths = []
    for entry in sorted(os.listdir(dataset_path)):
        if entry.lower().endswith('.csv') and entry.lower() != 'device_info.csv':
            csv_paths.append(os.path.join(dataset_path, entry))

    if not csv_paths:
        raise ValueError(f"No CSV files found in dataset directory: {dataset_path}")

    # Load all devices for comprehensive evaluation
    return sorted(csv_paths)


def _infer_feature_names_from_csv(csv_path, reserved=None):
    reserved = set(reserved or [])
    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError(f"Dataset file does not contain a header row: {csv_path}")
        first_row = next(reader, None)
        if first_row is None:
            raise ValueError(f"Dataset file is empty: {csv_path}")
        return _infer_feature_names(first_row, reserved=reserved)


atexit.register(cleanup_dataset_dirs)


class DatasetDevice:
    # Mapping for human-readable feature names
    FEATURE_NAMES = {
        "MI_dir_L5_weight": "MI Dir L5 Weight",
        "MI_dir_L5_mean": "MI Dir L5 Mean",
        "MI_dir_L5_variance": "MI Dir L5 Variance",
        "MI_dir_L3_weight": "MI Dir L3 Weight",
        "MI_dir_L3_mean": "MI Dir L3 Mean",
        "MI_dir_L3_variance": "MI Dir L3 Variance",
        "MI_dir_L1_weight": "MI Dir L1 Weight",
        "MI_dir_L1_mean": "MI Dir L1 Mean",
        "MI_dir_L1_variance": "MI Dir L1 Variance",
        "MI_dir_L0.1_weight": "MI Dir L0.1 Weight",
        "MI_dir_L0.1_mean": "MI Dir L0.1 Mean",
        "MI_dir_L0.1_variance": "MI Dir L0.1 Variance",
        "MI_dir_L0.01_weight": "MI Dir L0.01 Weight",
        "MI_dir_L0.01_mean": "MI Dir L0.01 Mean",
        "MI_dir_L0.01_variance": "MI Dir L0.01 Variance",
        "H_L5_weight": "Hurst L5 Weight",
        "H_L5_mean": "Hurst L5 Mean",
        "H_L5_variance": "Hurst L5 Variance",
        "H_L3_weight": "Hurst L3 Weight",
        "H_L3_mean": "Hurst L3 Mean",
        "H_L3_variance": "Hurst L3 Variance",
        "H_L1_weight": "Hurst L1 Weight",
        "H_L1_mean": "Hurst L1 Mean",
        "H_L1_variance": "Hurst L1 Variance",
        "H_L0.1_weight": "Hurst L0.1 Weight",
        "H_L0.1_mean": "Hurst L0.1 Mean",
        "H_L0.1_variance": "Hurst L0.1 Variance",
        "H_L0.01_weight": "Hurst L0.01 Weight",
        "H_L0.01_mean": "Hurst L0.01 Mean",
        "H_L0.01_variance": "Hurst L0.01 Variance",
        "HH_L5_weight": "HH Hurst L5 Weight",
        "HH_L5_mean": "HH Hurst L5 Mean",
        "HH_L5_std": "HH Hurst L5 Std",
        "HH_L5_magnitude": "HH Hurst L5 Magnitude",
        "HH_L5_radius": "HH Hurst L5 Radius",
        "HH_L5_covariance": "HH Hurst L5 Covariance",
        "HH_L5_pcc": "HH Hurst L5 PCC",
        "HH_L3_weight": "HH Hurst L3 Weight",
        "HH_L3_mean": "HH Hurst L3 Mean",
        "HH_L3_std": "HH Hurst L3 Std",
        "HH_L3_magnitude": "HH Hurst L3 Magnitude",
        "HH_L3_radius": "HH Hurst L3 Radius",
        "HH_L3_covariance": "HH Hurst L3 Covariance",
        "HH_L3_pcc": "HH Hurst L3 PCC",
        "HH_L1_weight": "HH Hurst L1 Weight",
        "HH_L1_mean": "HH Hurst L1 Mean",
        "HH_L1_std": "HH Hurst L1 Std",
        "HH_L1_magnitude": "HH Hurst L1 Magnitude",
        "HH_L1_radius": "HH Hurst L1 Radius",
        "HH_L1_covariance": "HH Hurst L1 Covariance",
        "HH_L1_pcc": "HH Hurst L1 PCC",
        "HH_L0.1_weight": "HH Hurst L0.1 Weight",
        "HH_L0.1_mean": "HH Hurst L0.1 Mean",
        "HH_L0.1_std": "HH Hurst L0.1 Std",
        "HH_L0.1_magnitude": "HH Hurst L0.1 Magnitude",
        "HH_L0.1_radius": "HH Hurst L0.1 Radius",
        "HH_L0.1_covariance": "HH Hurst L0.1 Covariance",
        "HH_L0.1_pcc": "HH Hurst L0.1 PCC",
        "HH_L0.01_weight": "HH Hurst L0.01 Weight",
        "HH_L0.01_mean": "HH Hurst L0.01 Mean",
        "HH_L0.01_std": "HH Hurst L0.01 Std",
        "HH_L0.01_magnitude": "HH Hurst L0.01 Magnitude",
        "HH_L0.01_radius": "HH Hurst L0.01 Radius",
        "HH_L0.01_covariance": "HH Hurst L0.01 Covariance",
        "HH_L0.01_pcc": "HH Hurst L0.01 PCC",
        "HpHp_L5_weight": "HpHp L5 Weight",
        "HpHp_L5_mean": "HpHp L5 Mean",
        "HpHp_L5_std": "HpHp L5 Std",
        "HpHp_L5_magnitude": "HpHp L5 Magnitude",
        "HpHp_L5_radius": "HpHp L5 Radius",
        "HpHp_L5_covariance": "HpHp L5 Covariance",
        "HpHp_L5_pcc": "HpHp L5 PCC",
        "HpHp_L3_weight": "HpHp L3 Weight",
        "HpHp_L3_mean": "HpHp L3 Mean",
        "HpHp_L3_std": "HpHp L3 Std",
        "HpHp_L3_magnitude": "HpHp L3 Magnitude",
        "HpHp_L3_radius": "HpHp L3 Radius",
        "HpHp_L3_covariance": "HpHp L3 Covariance",
        "HpHp_L3_pcc": "HpHp L3 PCC",
        "HpHp_L1_weight": "HpHp L1 Weight",
        "HpHp_L1_mean": "HpHp L1 Mean",
        "HpHp_L1_std": "HpHp L1 Std",
        "HpHp_L1_magnitude": "HpHp L1 Magnitude",
        "HpHp_L1_radius": "HpHp L1 Radius",
        "HpHp_L1_covariance": "HpHp L1 Covariance",
        "HpHp_L1_pcc": "HpHp L1 PCC",
        "HpHp_L0.1_weight": "HpHp L0.1 Weight",
        "HpHp_L0.1_mean": "HpHp L0.1 Mean",
        "HpHp_L0.1_std": "HpHp L0.1 Std",
        "HpHp_L0.1_magnitude": "HpHp L0.1 Magnitude",
        "HpHp_L0.1_radius": "HpHp L0.1 Radius",
        "HpHp_L0.1_covariance": "HpHp L0.1 Covariance",
        "HpHp_L0.1_pcc": "HpHp L0.1 PCC",
        "HpHp_L0.01_weight": "HpHp L0.01 Weight",
        "HpHp_L0.01_mean": "HpHp L0.01 Mean",
        "HpHp_L0.01_std": "HpHp L0.01 Std",
        "HpHp_L0.01_magnitude": "HpHp L0.01 Magnitude",
        "HpHp_L0.01_radius": "HpHp L0.01 Radius",
        "HpHp_L0.01_covariance": "HpHp L0.01 Covariance",
        "HpHp_L0.01_pcc": "HpHp L0.01 PCC",
    }

    def __init__(self, name, feature_names, row_source=None, row_file_path=None, label_key="label", benign_labels=None, default_attacked=None, theta=3.0):
        self.name = name
        self.feature_names = feature_names
        self.row_source = row_source
        self.row_file_path = row_file_path
        self.label_key = label_key
        self.benign_labels = set(x.upper() for x in (benign_labels or ["BENIGN", "NORMAL"]))
        self.default_attacked = default_attacked
        self.theta = 3.0  # Default threshold (will be calibrated per-device)
        self.calibrated_theta = None  # Per-device theta from benign baseline
        self.history = deque(maxlen=300)  # Extended to 5 min for slow drift detection
        self.attacked = False
        self.quarantine = False
        self.intensity = 0.0
        self.current = {k: 0.0 for k in self.feature_names}
        self.baseline = None
        self.drift_history = deque(maxlen=200)  # Track drift for calibration

        self._csv_file = None
        self._reader = None
        self._finished = False
        self.index = 0

    def _ensure_reader(self):
        if self._reader is not None:
            return self._reader

        if self.row_source is not None:
            return None

        if not self.row_file_path:
            raise RuntimeError("No row source available for DatasetDevice")

        self._csv_file = open(self.row_file_path, newline="", encoding="utf-8")
        self._reader = csv.DictReader(self._csv_file)
        return self._reader

    def tick(self):
        if self._finished:
            return

        if self.row_source is not None:
            if self.index >= len(self.row_source):
                self._finished = True
                return
            row = self.row_source[self.index]
        else:

            reader = self._ensure_reader()
            row = next(reader, None)
            if row is None:
                self._finished = True
                return

        self.index += 1
        values = []
        for key in self.feature_names:
            value = _to_float(row.get(key, 0.0))
            values.append(0.0 if value is None else value)

        self.current = {k: v for k, v in zip(self.feature_names, values)}
        label = None
        if self.label_key and self.label_key in row:
            label = str(row.get(self.label_key, "")).strip().upper()

        if label:
            self.attacked = label not in self.benign_labels
        elif self.default_attacked is not None:
            self.attacked = bool(self.default_attacked)


        import math
        self.history.append(values)

        if self.baseline is None and len(self.history) >= 120:
            self.baseline = self._compute_baseline(list(self.history)[:100])
        
        if self.baseline is not None and not self.default_attacked:
            self.calibrate_theta()

    def _compute_baseline(self, rows):
        if not rows or len(rows) < 50:
            return None
        transposed = list(zip(*rows))
        baseline = []
        for values in transposed:
            n = len(values)
            mean = sum(values) / n
            variance = sum((x - mean) ** 2 for x in values) / n
            sigma = math.sqrt(variance)
            floor = max(abs(mean) * 0.01, 0.1)
            baseline.append((mean, sigma if sigma > floor else floor))
        return baseline

    def state(self):
        if len(self.history) < 120:
            return None

        if self.baseline is None:
            return None

        full_history = list(self.history)
        test = full_history[-20:]

        zs = []
        for i, (mean, sigma) in enumerate(self.baseline):
            tv = [t[i] for t in test]
            obs_mean = sum(tv) / len(tv)
            baseline_sd = max(abs(mean) * 0.001, 1.0)
            z = (obs_mean - mean) / baseline_sd
            zs.append(min(max(z, -100), 100))

        abs_zs = [abs(z) for z in zs]
        
        # Mean absolute Z-score — matches paper formula



        drift = round(sum(abs_zs) / len(abs_zs), 2)



        
        # Store drift for calibration
        self.drift_history.append(drift)
        
        # Use per-device calibrated theta if available
        effective_theta = self.calibrated_theta if self.calibrated_theta else self.theta
        trust = max(0, int(100 - ((drift / effective_theta) ** 2.2) * 20))

        # Quarantine management: use paper thresholds for robustness
        if trust < 30 and not self.quarantine:
            self.quarantine = True
        elif self.quarantine and trust > 75:
            self.quarantine = False

        explanation = "Dataset-derived behavioral profile is nominal."
        if drift > effective_theta:
            top_idx = abs_zs.index(max(abs_zs))
            feat_key = self.feature_names[top_idx]
            impact = "increase" if zs[top_idx] > 0 else "decrease"
            explanation = f"Anomalous {feat_key} {impact} in N-BaIoT observations."

        # Select top 5 features for display to keep it readable
        selected_features = dict(list(self.current.items())[:5])
        readable_features = {self.FEATURE_NAMES.get(k, k): round(v, 2) for k, v in selected_features.items()}

        return {
            "name": self.name,
            "drift": drift,
            "trust": trust,
            "explanation": explanation,
            "alert": drift > effective_theta,
            "attacked": self.attacked,
            "quarantine": self.quarantine,
            "intensity": round(self.intensity, 2),
            "features": readable_features,
        }

    def calibrate_theta(self):
        """
        For benign devices, compute 99th percentile of drift as the device's theta.
        Call this after baseline is established and device has stabilized.
        """
        if len(self.drift_history) < 50:
            return  # Need enough data
        
        sorted_drifts = sorted(list(self.drift_history))
        percentile_idx = int(len(sorted_drifts) * 0.99)
        self.calibrated_theta = max(1.0, sorted_drifts[percentile_idx] * 1.5)

    def adapt_baseline(self):
        return  # Frozen for dataset evaluation

    def __del__(self):
        if self._csv_file is not None:
            try:
                self._csv_file.close()
            except Exception:
                pass

    def reset(self):
        """Close and reopen the CSV, wipe all statistical state.
        Lets the same device instance run a second pass without
        reinstantiation — temp-dir paths stay valid."""
        if self._csv_file is not None:
            try:
                self._csv_file.close()
            except Exception:
                pass
        self._csv_file = None
        self._reader = None
        self._finished = False
        self.index = 0

        self.history = deque(maxlen=300)
        self.baseline = None
        self.drift_history = deque(maxlen=200)
        self.calibrated_theta = None
        self.attacked = False
        self.quarantine = False
        self.intensity = 0.0
        self.current = {k: 0.0 for k in self.feature_names}


def create_dataset_devices(dataset_path, dataset_name="n_baiot"):
    if dataset_name.lower() != "n_baiot":
        raise ValueError(f"Unsupported dataset: {dataset_name}")

    reserved = {"device", "label", "attack", "class", "type"}

    csv_paths = _collect_csv_paths(dataset_path)
    if len(csv_paths) == 1 and os.path.isfile(dataset_path):
        feature_names, device_paths = _prepare_device_files(dataset_path, reserved=reserved)
        if not feature_names:
            raise ValueError("Could not infer numeric feature columns from dataset")
        return [DatasetDevice(name, feature_names, row_file_path=path, label_key="label") for name, path in device_paths.items()]

    feature_names = _infer_feature_names_from_csv(csv_paths[0], reserved=reserved)
    if not feature_names:
        raise ValueError("Could not infer numeric feature columns from dataset")

    devices = []
    name_counts = {}
    for csv_path in csv_paths:
        base_name = os.path.splitext(os.path.basename(csv_path))[0]
        parts = base_name.split('.')
        device_id = parts[0] if parts else base_name
        label_part = '.'.join(parts[1:]) if len(parts) > 1 else ''
        if 'benign' in label_part.lower():
            readable_name = f"Device {device_id} (Normal)"
        elif label_part:
            attack_type = label_part.replace('_', ' ').title()
            readable_name = f"Device {device_id} ({attack_type})"
        else:
            readable_name = f"Device {device_id}"

        # Deduplicate names to prevent device_map collisions
        if readable_name in name_counts:
            name_counts[readable_name] += 1
            readable_name = f"{readable_name} [{name_counts[readable_name]}]"
        else:
            name_counts[readable_name] = 1

        default_attacked = "benign" not in base_name.lower()
        devices.append(
            DatasetDevice(
                readable_name,
                feature_names,
                row_file_path=csv_path,
                label_key="label",
                default_attacked=default_attacked
            )
        )
    return devices
