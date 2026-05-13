import asyncio, random, math, sqlite3, json
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import FileResponse
from engine import devices, device_map, DATASET_MODE

try:
    from dataset import cleanup_dataset_dirs
except ImportError:
    def cleanup_dataset_dirs():
        pass

DB_PATH = "bice.db"

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS telemetry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                device TEXT,
                drift REAL,
                trust INTEGER,
                metrics TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                device TEXT,
                drift REAL,
                explanation TEXT
            )
        """)
        conn.commit()

def log_telemetry(device_name, state):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO telemetry (timestamp, device, drift, trust, metrics) VALUES (?, ?, ?, ?, ?)",
            (datetime.now().isoformat(), device_name, state["drift"], state["trust"], json.dumps(state["features"]))
        )
        if state["alert"]:
            conn.execute(
                "INSERT INTO alerts (timestamp, device, drift, explanation) VALUES (?, ?, ?, ?)",
                (datetime.now().isoformat(), device_name, state["drift"], state["explanation"])
            )
        conn.commit()

alerts_cache = [] # Keep recent in memory for quick UI access
calibrated = set()  # Track which devices have been calibrated
calibration_log = []  # Log calibration events

async def telemetry_loop():
    prev_alert = {d.name: False for d in devices}
    while True:
        for d in devices:
            d.tick()
            d.adapt_baseline() # Gated learning
            s = d.state()
            if s:
                log_telemetry(d.name, s)
                
                # Calibrate theta for benign devices (one-time, when they have enough data)
                if d.name not in calibrated and not d.attacked and len(d.drift_history) > 100:
                    old_theta = d.calibrated_theta
                    d.calibrate_theta()
                    calibrated.add(d.name)
                    log_entry = f"[{datetime.now().strftime('%H:%M:%S')}] Calibrated {d.name}: theta={d.calibrated_theta} (was {old_theta})"
                    calibration_log.append(log_entry)
                    if len(calibration_log) > 50:
                        calibration_log.pop(0)
                
                if s["alert"] and not prev_alert[d.name]:
                    alerts_cache.insert(0, {
                        "device":  d.name, 
                        "drift":   s["drift"], 
                        "time":    datetime.now().strftime("%H:%M:%S"),
                        "msg":     s["explanation"]
                    })
                    if len(alerts_cache) > 20: alerts_cache.pop()
                prev_alert[d.name] = s["alert"]
            else:
                prev_alert[d.name] = False
        await asyncio.sleep(1)

async def attack_simulator():
    while True:
        # Randomly inject attacks if no one is currently being attacked
        if not any(d.attacked for d in devices):
            await asyncio.sleep(random.randint(15, 30))
            target = random.choice(devices)
            target.attacked = True
            await asyncio.sleep(random.randint(20, 40))
            target.attacked = False
        await asyncio.sleep(5)

@asynccontextmanager
async def lifespan(_):
    init_db()
    asyncio.create_task(telemetry_loop())
    if not DATASET_MODE:
        asyncio.create_task(attack_simulator())
    yield
    cleanup_dataset_dirs()

app = FastAPI(lifespan=lifespan)

@app.get("/")
def index(): return FileResponse("index.html")

@app.get("/api/calibration")
def get_calibration():
    return {"calibrated_count": len(calibrated), "logs": calibration_log}

@app.get("/api/state")
def get_state():
    states = [d.state() for d in devices]
    if not all(states): return {"ready": False}
    return {
        "ready":  True, 
        "assets": states, 
        "alerts": alerts_cache
    }

@app.post("/api/attack/{name}")
def toggle_attack(name: str):
    d = device_map.get(name)
    if not d: return {"error": "not found"}
    d.attacked = not d.attacked
    return {"device": name, "attacked": d.attacked}

@app.post("/api/quarantine/{name}")
def toggle_quarantine(name: str):
    d = device_map.get(name)
    if not d: return {"error": "not found"}
    d.quarantine = not d.quarantine
    return {"device": name, "quarantine": d.quarantine}

@app.post("/api/reset")
def reset_run():
    """Resets all devices for a clean second (or Nth) run.
    Rewinds CSVs to row 0, clears all statistical state and calibration."""
    global calibrated, calibration_log
    for d in devices:
        if hasattr(d, 'reset'):
            d.reset()
    calibrated = set()
    calibration_log = []
    alerts_cache.clear()
    return {"status": "reset", "devices": len(devices)}
