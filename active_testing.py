# ==========================================
# 🟢 Raspberry Pi Live Anomaly Detector (Safe & Normalized)
# ==========================================

import time
import statistics
import subprocess
import psutil
import pandas as pd
import serial
import firebase_admin
from firebase_admin import credentials, firestore
import joblib
import numpy as np

# -----------------------------
# 1️⃣ Initialize Firebase
# -----------------------------
cred = credentials.Certificate("/home/admin/firebase-key.json")
firebase_admin.initialize_app(cred)
db = firestore.client()
firebase_collection = "network_anomalies"

# -----------------------------
# 2️⃣ Load model + scaler
# -----------------------------
model = joblib.load("/home/admin/anomaly_detector.pkl")
scaler = joblib.load("/home/admin/scaler.pkl")

# Define feature order (must match training)
feature_order = [
    'ambient_temp', 'ax', 'ay', 'az', 'bytes_recv', 'bytes_sent',
    'cpu_load', 'cpu_temp', 'gx', 'gy', 'gz', 'humidity',
    'motion_level', 'packet_loss', 'ping_avg', 'ping_jitter', 'wifi_strength'
]

# Define reasonable min/max for clipping based on training data
feature_clip_ranges = {
    'ambient_temp': (15, 35),
    'ax': (-20000, 20000),
    'ay': (-20000, 20000),
    'az': (-20000, 20000),
    'gx': (-5000, 5000),
    'gy': (-5000, 5000),
    'gz': (-5000, 5000),
    'bytes_recv': (0, 50_000_000),
    'bytes_sent': (0, 50_000_000),
    'cpu_load': (0, 100),
    'cpu_temp': (20, 90),
    'humidity': (0, 100),
    'motion_level': (0, 100),
    'packet_loss': (0, 100),
    'ping_avg': (0, 2000),
    'ping_jitter': (0, 200),
    'wifi_strength': (-100, 0)
}

# -----------------------------
# 3️⃣ Initialize Arduino Serial
# -----------------------------
ser = serial.Serial('/dev/ttyACM0', 9600, timeout=1)
time.sleep(2)  # allow Arduino to reset

# -----------------------------
# 4️⃣ Functions to collect metrics
# -----------------------------
def ping_test(host="8.8.8.8", count=3):
    try:
        output = subprocess.check_output(["ping", "-c", str(count), host]).decode()
        latencies = [float(line.split('time=')[1].split(' ms')[0])
                     for line in output.split('\n') if "time=" in line]
        avg = statistics.mean(latencies)
        loss = 100 - (len(latencies) / count * 100)
        jitter = statistics.pstdev(latencies)
        return avg, loss, jitter
    except:
        return None, 100, None

def get_wifi_strength():
    try:
        output = subprocess.check_output(["iwconfig"]).decode()
        for line in output.split("\n"):
            if "Signal level" in line:
                return int(line.split("Signal level=")[1].split(" ")[0])
    except:
        return None

def collect_system_metrics():
    temps = psutil.sensors_temperatures()
    temp = None
    if 'cpu_thermal' in temps and len(temps['cpu_thermal']) > 0:
        temp = temps['cpu_thermal'][0].current
    net_io = psutil.net_io_counters()
    return {
        "cpu_temp": temp,
        "bytes_sent": net_io.bytes_sent,
        "bytes_recv": net_io.bytes_recv,
        "cpu_load": psutil.cpu_percent()
    }

def read_arduino_data():
    if ser.in_waiting > 0:
        line = ser.readline().decode('utf-8').strip()
        print("Raw Arduino:", line)
        try:
            parts = line.split(',')
            data = {}
            for p in parts:
                key, value = p.split(':')
                key = key.strip().upper()
                value = value.strip()
                if key == 'T':
                    data['ambient_temp'] = float(value)
                elif key == 'H':
                    data['humidity'] = float(value)
                elif key == 'M':
                    data['motion_level'] = int(value)
                elif key in ['AX','AY','AZ','GX','GY','GZ']:
                    data[key.lower()] = int(value)
            return data
        except Exception as e:
            print("Parse error:", e)
            return None
    return None

def categorize_anomaly(row, eps=1e-6):
    network_bad = (row["ping_avg"] > 100) or (row["packet_loss"] > 0.1) or (row["ping_jitter"] > 30)
    jitter_ratio = row["ping_jitter"] / (row["ping_avg"] + eps)

    if network_bad and (row["cpu_temp"] > 65 or row["cpu_load"] > 6):
        return "Thermal"
    if network_bad and (row["motion_level"] > 0):
        return "Motion-Induced"
    if network_bad and (row["wifi_strength"] < -70 or row["ping_jitter"] > 40 or jitter_ratio > 0.4):
        return "Weak Signal"
    if (row["ping_jitter"] > 40 or jitter_ratio > 0.6) and (row["cpu_temp"] <= 65 and row["wifi_strength"] >= -70):
        return "Unknown Network Issue"
    if network_bad and row["cpu_load"] > 8:
        return "System Load"
    return "Normal"

# -----------------------------
# 5️⃣ Main loop
# -----------------------------
while True:
    # Read all metrics
    ping_avg, loss, jitter = ping_test()
    sys_data = collect_system_metrics()
    arduino_data = read_arduino_data() or {}
    wifi_strength = get_wifi_strength()

    # Combine into one dict
    row = {
        "ambient_temp": None,
        "ax": None, "ay": None, "az": None,
        "bytes_recv": None, "bytes_sent": None,
        "cpu_load": None, "cpu_temp": None,
        "gx": None, "gy": None, "gz": None,
        "humidity": None,
        "motion_level": None,
        "packet_loss": None,
        "ping_avg": None,
        "ping_jitter": None,
        "wifi_strength": None
    }

    row.update(sys_data)
    row.update(arduino_data)
    row.update({
        "packet_loss": loss,
        "ping_avg": ping_avg,
        "ping_jitter": jitter,
        "wifi_strength": wifi_strength
    })

    # Clip features to training ranges
    for f in feature_order:
        if row[f] is None:
            row[f] = 0
        else:
            min_val, max_val = feature_clip_ranges[f]
            row[f] = min(max(row[f], min_val), max_val)

    # Convert to DataFrame in correct order
    df_row = pd.DataFrame([row], columns=feature_order)

    # Scale and predict
    X_scaled = scaler.transform(df_row.values)
    pred = model.predict(X_scaled)
    is_anomaly = int(pred[0] == -1)

    # Determine category
    category = categorize_anomaly(df_row.iloc[0]) if is_anomaly else "Normal"

    # Prepare Firebase document
    firebase_data = {
        "timestamp": firestore.SERVER_TIMESTAMP,
        "is_anomaly": is_anomaly,
        "category": category,
        **df_row.iloc[0].to_dict()
    }

    # Upload
    db.collection(firebase_collection).add(firebase_data)
    print("Uploaded anomaly status:", firebase_data)

    time.sleep(10)
