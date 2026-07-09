import os
import random, math, sys
from collections import deque

DATASET_PATH = os.path.expanduser(os.getenv("BICE_DATASET_PATH", ""))
DATASET_NAME = os.getenv("BICE_DATASET_NAME", "n_baiot").lower()

try:
    if DATASET_PATH:
        from engine.dataset import create_dataset_devices
        devices = create_dataset_devices(DATASET_PATH, DATASET_NAME)
    else:
        devices = None
except Exception as exc:
    print(f"Warning: failed to load dataset from {DATASET_PATH}: {exc}")
    devices = None

DATASET_MODE = bool(DATASET_PATH and devices is not None)

class Device:
    def __init__(self, name, features, attack_deltas, theta=3.0):
        # features:      {label: (mean, sigma)}
        # attack_deltas: {label: offset} added at full intensity
        self.name      = name
        self.features  = features
        self.deltas    = attack_deltas
        self.theta     = theta
        self.history   = deque(maxlen=120)     # 2-min rolling window
        self.attacked  = False
        self.quarantine = False
        self.intensity = 0.0                   # 0..1, ramps with attack state
        self.current   = {k: v[0] for k, v in features.items()}

    def tick(self):
        # If quarantined, we simulate "blocking" by freezing metrics (or just letting them decay)
        # For this demo, let's say quarantine halves intensity ramp-up and speeds up decay.
        step = 0.06
        if self.quarantine:
            self.intensity = max(0.0, self.intensity - 0.15) # Force drop under quarantine
        else:
            self.intensity = (
                min(1.0, self.intensity + step) if self.attacked
                else max(0.0, self.intensity - step)
            )

        f = []
        for k, (mean, sigma) in self.features.items():
            target        = mean + self.deltas.get(k, 0) * self.intensity
            val           = self.current[k]
            val          += 0.12 * (target - val) + random.gauss(0, sigma)
            val           = max(0.0, val)
            self.current[k] = val
            f.append(val)
        self.history.append(f)

    def state(self):
        if len(self.history) < 10:
            return None

        h    = list(self.history)
        ref  = h[:-5]
        test = h[-5:]

        zs = []
        for i in range(len(self.features)):
            rv = [r[i] for r in ref]
            tv = [t[i] for t in test]
            m  = sum(rv) / len(rv)
            sd = math.sqrt(sum((x-m)**2 for x in rv) / len(rv)) or 0.001
            zs.append((sum(tv)/len(tv) - m) / sd) # Keeping SIGN for explainability

        abs_zs = [abs(z) for z in zs]
        drift = round(math.sqrt(sum(z**2 for z in abs_zs)), 2)
        
        # --- Trust Scoring Engine ---
        # Base 100, drops quickly with drift. >3.0 starts eating trust.
        trust = max(0, min(100, 100 - int(pow(drift/self.theta, 2.2) * 20)))
        
        # --- Automated Mitigation ---
        if trust < 30 and not self.quarantine:
            self.quarantine = True
        
        # --- Explainability Engine ---
        explanation = "Normal behavioral pattern."
        if drift > self.theta:
            # Find the feature that contributed most
            top_idx = abs_zs.index(max(abs_zs))
            feat_key = list(self.features.keys())[top_idx]
            impact = "increase" if zs[top_idx] > 0 else "decrease"
            
            mapping = {
                "dns_entropy": f"Abnormal DNS entropy {impact} (Tunneling/C2)",
                "dest_ips":    f"Unusual {impact} in unique destination IPs (Scanning)",
                "tx_kb":       f"Sudden {impact} in outbound traffic (Exfiltration)",
                "api_calls":   f"Anomalous API request {impact} (Unauthorized behavior)",
                "auth_fails":  f"Spike in authentication failures (Brute Force)",
                "new_conns":   f"Elevated new connection rate (Port scan/DDoS)",
                "rx_kb":       f"High inbound traffic {impact} (DDoS/Infiltration)",
                "ble_scans":   f"Unusual BLE scanning activity (Proximity crawl)",
            }
            explanation = mapping.get(feat_key, f"Anomalous {feat_key} behavior.")

        return {
            "name":        self.name,
            "drift":       drift,
            "trust":       trust,
            "explanation": explanation,
            "alert":       drift > self.theta,
            "attacked":    self.attacked,
            "quarantine":  self.quarantine,
            "intensity":   round(self.intensity, 2),
            "features":    {k: round(self.current[k], 2) for k in self.features},
        }

    def adapt_baseline(self):
        """Gated learning: nudge baseline towards observations if trust is high."""
        if len(self.history) < 20 or self.quarantine: return
        recent = list(self.history)[-10:]
        updated = {}
        for i, (k, (mu, sigma)) in enumerate(self.features.items()):
            obs = sum(r[i] for r in recent) / len(recent)
            # Only learn if we are NOT in alert state
            updated[k] = (0.998 * mu + 0.002 * obs, sigma)
        self.features = updated

# Root configuration of devices is loaded from a dataset when configured.
# Otherwise we fall back to built-in synthetic device simulations.
if devices is None:
    devices = [
        Device("CCTV",
            {"dns_entropy": (0.22, 0.018), "dest_ips": (1.5, 0.10), "tx_kb": (512, 3.5)},
            {"dest_ips": 7.5, "tx_kb": 120}),

        Device("Thermostat",
            {"dns_entropy": (0.15, 0.012), "dest_ips": (1.0, 0.06), "api_calls": (3.0, 0.20)},
            {"dns_entropy": 3.5, "dest_ips": 5.0}),

        Device("Smart Lock",
            {"auth_fails": (0.08, 0.05), "ble_scans": (0.5, 0.09), "tx_kb": (0.2, 0.018)},
            {"auth_fails": 14.0, "ble_scans": 9.0, "tx_kb": 2.5}),

        Device("Router",
            {"dns_entropy": (0.45, 0.025), "new_conns": (10.0, 1.2), "rx_kb": (150, 10)},
            {"new_conns": 55.0, "rx_kb": 350}),
    ]

device_map = {d.name: d for d in devices}
