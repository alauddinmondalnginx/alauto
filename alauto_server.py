"""
ALAUTO Smart Fan Controller — Python Flask Backend v2.0
========================================================
Run: python alauto_server.py
App: https://alauto.onrender.com/app
"""

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import requests
import schedule
import threading
import time
import datetime
import logging
import os

# ─────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────

ESP8266_IP   = os.environ.get("ESP_IP", "192.168.1.200")
ESP8266_PORT = 80
SERVER_PORT  = int(os.environ.get("PORT", 5000))

# ─────────────────────────────────────────
# App Setup
# ─────────────────────────────────────────

app = Flask(__name__, static_folder=".")
CORS(app)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("ALAUTO")

# ─────────────────────────────────────────
# Fan State
# ─────────────────────────────────────────

fan_state = {
    "power": False,
    "speed": 2,
    "temperature": 29.0,
    "uptime_start": None,
    "total_cost": 0.0,
    "schedule": {
        "on_time": "22:00",
        "off_time": "06:00",
        "on_enabled": True,
        "off_enabled": True,
        "auto_temp": False,
        "temp_threshold": 30.0
    }
}

SPEED_WATTS = {1: 28, 2: 45, 3: 65, 4: 85}

# ─────────────────────────────────────────
# ESP8266 Communication
# ─────────────────────────────────────────

def send_to_esp(endpoint):
    url = f"http://{ESP8266_IP}:{ESP8266_PORT}/{endpoint}"
    try:
        resp = requests.get(url, timeout=3)
        return resp.status_code == 200
    except:
        log.warning("ESP8266 not connected (Demo mode)")
        return False

# ─────────────────────────────────────────
# Cost Calculation
# ─────────────────────────────────────────

def calculate_cost():
    if not fan_state["power"] or not fan_state["uptime_start"]:
        return fan_state["total_cost"]
    elapsed_hours = (datetime.datetime.now() - fan_state["uptime_start"]).seconds / 3600
    watts = SPEED_WATTS.get(fan_state["speed"], 45)
    kwh = (watts / 1000) * elapsed_hours
    return round(kwh * 7, 2)

# ─────────────────────────────────────────
# Routes
# ─────────────────────────────────────────

@app.route("/")
def home():
    return jsonify({
        "app": "ALAUTO Smart Fan Controller",
        "version": "2.0",
        "status": "running",
        "app_url": "/app",
        "docs": "GET /status | GET /fan/on | GET /fan/off | GET /fan/speed/<1-4> | POST /schedule"
    })


@app.route("/app")
def serve_app():
    return send_from_directory(".", "smart_fan_app.html")


@app.route("/status")
def status():
    uptime = 0
    if fan_state["power"] and fan_state["uptime_start"]:
        uptime = int((datetime.datetime.now() - fan_state["uptime_start"]).total_seconds())
    return jsonify({
        "power": fan_state["power"],
        "speed": fan_state["speed"],
        "temperature": fan_state["temperature"],
        "watts": SPEED_WATTS.get(fan_state["speed"], 0) if fan_state["power"] else 0,
        "uptime_seconds": uptime,
        "total_cost": calculate_cost(),
        "schedule": fan_state["schedule"],
        "server_time": datetime.datetime.now().strftime("%H:%M:%S")
    })


@app.route("/fan/on", methods=["GET", "POST"])
def fan_on():
    fan_state["power"] = True
    fan_state["uptime_start"] = datetime.datetime.now()
    ok = send_to_esp("fan/on")
    log.info("Fan turned ON")
    return jsonify({"success": True, "power": True, "esp_connected": ok, "message": "Fan ON ✅"})


@app.route("/fan/off", methods=["GET", "POST"])
def fan_off():
    fan_state["total_cost"] = calculate_cost()
    fan_state["power"] = False
    fan_state["uptime_start"] = None
    ok = send_to_esp("fan/off")
    log.info("Fan turned OFF")
    return jsonify({"success": True, "power": False, "esp_connected": ok, "total_cost": fan_state["total_cost"], "message": "Fan OFF 🔴"})


@app.route("/fan/speed/<int:level>", methods=["GET", "POST"])
def fan_speed(level):
    if level not in [1, 2, 3, 4]:
        return jsonify({"success": False, "message": "Speed must be 1-4"}), 400
    fan_state["speed"] = level
    ok = send_to_esp(f"fan/speed/{level}")
    names = {1: "Slow", 2: "Medium", 3: "Fast", 4: "Turbo"}
    log.info(f"Speed changed: {names[level]}")
    return jsonify({"success": True, "speed": level, "speed_name": names[level], "watts": SPEED_WATTS[level], "esp_connected": ok})


@app.route("/schedule", methods=["POST"])
def update_schedule():
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "No data received"}), 400
    sch = fan_state["schedule"]
    for key in ["on_time", "off_time", "on_enabled", "off_enabled", "auto_temp"]:
        if key in data:
            sch[key] = data[key]
    if "temp_threshold" in data:
        sch["temp_threshold"] = float(data["temp_threshold"])
    apply_schedule()
    log.info(f"Schedule updated: {sch}")
    return jsonify({"success": True, "schedule": sch, "message": "Schedule saved ✅"})


@app.route("/temperature", methods=["POST"])
def update_temperature():
    data = request.get_json()
    if data and "temperature" in data:
        fan_state["temperature"] = float(data["temperature"])
        sch = fan_state["schedule"]
        if sch["auto_temp"]:
            if fan_state["temperature"] >= sch["temp_threshold"] and not fan_state["power"]:
                log.info(f"Auto ON: temp {fan_state['temperature']}C")
                fan_state["power"] = True
                fan_state["uptime_start"] = datetime.datetime.now()
                send_to_esp("fan/on")
            elif fan_state["temperature"] < sch["temp_threshold"] - 2 and fan_state["power"]:
                log.info(f"Auto OFF: temp {fan_state['temperature']}C")
                fan_state["power"] = False
                send_to_esp("fan/off")
        return jsonify({"success": True, "temperature": fan_state["temperature"]})
    return jsonify({"success": False}), 400

# ─────────────────────────────────────────
# Scheduler
# ─────────────────────────────────────────

def scheduled_fan_on():
    if fan_state["schedule"]["on_enabled"] and not fan_state["power"]:
        log.info("Schedule: Fan turning ON")
        fan_state["power"] = True
        fan_state["uptime_start"] = datetime.datetime.now()
        send_to_esp("fan/on")


def scheduled_fan_off():
    if fan_state["schedule"]["off_enabled"] and fan_state["power"]:
        log.info("Schedule: Fan turning OFF")
        fan_state["total_cost"] = calculate_cost()
        fan_state["power"] = False
        fan_state["uptime_start"] = None
        send_to_esp("fan/off")


def apply_schedule():
    schedule.clear()
    sch = fan_state["schedule"]
    if sch["on_enabled"]:
        schedule.every().day.at(sch["on_time"]).do(scheduled_fan_on)
        log.info(f"Schedule ON set: {sch['on_time']}")
    if sch["off_enabled"]:
        schedule.every().day.at(sch["off_time"]).do(scheduled_fan_off)
        log.info(f"Schedule OFF set: {sch['off_time']}")


def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(30)

# ─────────────────────────────────────────
# Start
# ─────────────────────────────────────────

if __name__ == "__main__":
    print("""
    ╔══════════════════════════════════════╗
    ║   ALAUTO Smart Fan Server v2.0  ⚡   ║
    ╠══════════════════════════════════════╣
    ║  Local:   http://localhost:5000      ║
    ║  App:     http://localhost:5000/app  ║
    ╚══════════════════════════════════════╝
    """)
    apply_schedule()
    t = threading.Thread(target=run_scheduler, daemon=True)
    t.start()
    log.info("Scheduler started ✅")
    app.run(host="0.0.0.0", port=SERVER_PORT, debug=False)
