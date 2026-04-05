"""
ALAUTO Smart Fan Controller — Python Flask Backend
====================================================
এই server টি আপনার PC/Laptop এ চলবে।
Mobile App এই server এ request পাঠাবে।
Server ESP8266 কে WiFi দিয়ে command দেবে।

Install করুন:
    pip install flask flask-cors requests schedule

Run করুন:
    python alauto_server.py

তারপর Browser এ যান:
    http://localhost:5000
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import schedule
import threading
import time
import datetime
import logging

# ─────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────

ESP8266_IP = "192.168.1.200"       # আপনার ESP8266 এর IP (পরে set করবেন)
ESP8266_PORT = 80
SERVER_PORT = 5000

# ─────────────────────────────────────────
# App Setup
# ─────────────────────────────────────────

app = Flask(__name__)
CORS(app)  # Mobile App থেকে request allow করতে

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("ALAUTO")

# ─────────────────────────────────────────
# State — ফ্যানের বর্তমান অবস্থা
# ─────────────────────────────────────────

fan_state = {
    "power": False,          # True = চালু, False = বন্ধ
    "speed": 2,              # 1=ধীর, 2=মধ্যম, 3=দ্রুত, 4=টার্বো
    "temperature": 29.0,     # ঘরের তাপমাত্রা (sensor থেকে আসবে)
    "uptime_start": None,    # কখন থেকে চলছে
    "total_cost": 0.0,       # আজকের বিদ্যুৎ খরচ (₹)
    "schedule": {
        "on_time": "22:00",      # রাত ১০টা
        "off_time": "06:00",     # সকাল ৬টা
        "on_enabled": True,
        "off_enabled": True,
        "auto_temp": False,      # অটো তাপমাত্রা মোড
        "temp_threshold": 30.0   # এই তাপমাত্রার বেশি হলে চালু
    }
}

SPEED_WATTS = {1: 28, 2: 45, 3: 65, 4: 85}

# ─────────────────────────────────────────
# ESP8266 এ Command পাঠানো
# ─────────────────────────────────────────

def send_to_esp(endpoint):
    """ESP8266 এ HTTP request পাঠায়"""
    url = f"http://{ESP8266_IP}:{ESP8266_PORT}/{endpoint}"
    try:
        resp = requests.get(url, timeout=3)
        if resp.status_code == 200:
            log.info(f"✅ ESP8266: /{endpoint} সফল")
            return True
        else:
            log.warning(f"⚠️ ESP8266 response: {resp.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        log.warning(f"🔌 ESP8266 connected নেই (Demo mode চলছে)")
        return False
    except Exception as e:
        log.error(f"❌ ESP8266 error: {e}")
        return False

# ─────────────────────────────────────────
# বিদ্যুৎ খরচ হিসাব
# ─────────────────────────────────────────

def calculate_cost():
    if not fan_state["power"] or not fan_state["uptime_start"]:
        return fan_state["total_cost"]
    elapsed_hours = (datetime.datetime.now() - fan_state["uptime_start"]).seconds / 3600
    watts = SPEED_WATTS.get(fan_state["speed"], 45)
    kwh = (watts / 1000) * elapsed_hours
    return round(kwh * 7, 2)  # ₹7 per kWh (India average)

# ─────────────────────────────────────────
# API Routes
# ─────────────────────────────────────────

@app.route("/")
def home():
    return jsonify({
        "app": "ALAUTO Smart Fan Controller",
        "version": "1.0",
        "status": "running",
        "docs": "GET /status | POST /fan/on | POST /fan/off | POST /fan/speed | POST /schedule"
    })


@app.route("/status")
def status():
    """ফ্যানের সব তথ্য একবারে পাঠায়"""
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
        "esp_ip": ESP8266_IP,
        "server_time": datetime.datetime.now().strftime("%H:%M:%S")
    })


@app.route("/fan/on", methods=["GET", "POST"])
def fan_on():
    """ফ্যান চালু"""
    fan_state["power"] = True
    fan_state["uptime_start"] = datetime.datetime.now()
    ok = send_to_esp("fan/on")
    log.info("🌀 ফ্যান চালু হলো")
    return jsonify({
        "success": True,
        "power": True,
        "esp_connected": ok,
        "message": "ফ্যান চালু হলো ✅"
    })


@app.route("/fan/off", methods=["GET", "POST"])
def fan_off():
    """ফ্যান বন্ধ"""
    fan_state["total_cost"] = calculate_cost()
    fan_state["power"] = False
    fan_state["uptime_start"] = None
    ok = send_to_esp("fan/off")
    log.info("⛔ ফ্যান বন্ধ হলো")
    return jsonify({
        "success": True,
        "power": False,
        "esp_connected": ok,
        "total_cost": fan_state["total_cost"],
        "message": "ফ্যান বন্ধ হলো 🔴"
    })


@app.route("/fan/speed/<int:level>", methods=["GET", "POST"])
def fan_speed(level):
    """গতি পরিবর্তন (1-4)"""
    if level not in [1, 2, 3, 4]:
        return jsonify({"success": False, "message": "গতি ১ থেকে ৪ এর মধ্যে হতে হবে"}), 400

    fan_state["speed"] = level
    ok = send_to_esp(f"fan/speed/{level}")
    speed_names = {1: "ধীর", 2: "মধ্যম", 3: "দ্রুত", 4: "টার্বো"}
    log.info(f"🔄 গতি পরিবর্তন: {speed_names[level]}")
    return jsonify({
        "success": True,
        "speed": level,
        "speed_name": speed_names[level],
        "watts": SPEED_WATTS[level],
        "esp_connected": ok,
        "message": f"গতি {speed_names[level]} হলো ✅"
    })


@app.route("/schedule", methods=["POST"])
def update_schedule():
    """শিডিউল আপডেট"""
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "Data পাওয়া যায়নি"}), 400

    sch = fan_state["schedule"]

    if "on_time" in data:
        sch["on_time"] = data["on_time"]
    if "off_time" in data:
        sch["off_time"] = data["off_time"]
    if "on_enabled" in data:
        sch["on_enabled"] = data["on_enabled"]
    if "off_enabled" in data:
        sch["off_enabled"] = data["off_enabled"]
    if "auto_temp" in data:
        sch["auto_temp"] = data["auto_temp"]
    if "temp_threshold" in data:
        sch["temp_threshold"] = float(data["temp_threshold"])

    # নতুন শিডিউল apply করো
    apply_schedule()

    log.info(f"📅 শিডিউল আপডেট: {sch}")
    return jsonify({
        "success": True,
        "schedule": sch,
        "message": "শিডিউল সেভ হলো ✅"
    })


@app.route("/temperature", methods=["POST"])
def update_temperature():
    """ESP8266 sensor থেকে তাপমাত্রা আপডেট"""
    data = request.get_json()
    if data and "temperature" in data:
        fan_state["temperature"] = float(data["temperature"])

        # অটো তাপমাত্রা মোড চেক
        sch = fan_state["schedule"]
        if sch["auto_temp"]:
            if fan_state["temperature"] >= sch["temp_threshold"] and not fan_state["power"]:
                log.info(f"🌡️ তাপমাত্রা {fan_state['temperature']}°C — অটো চালু!")
                fan_state["power"] = True
                fan_state["uptime_start"] = datetime.datetime.now()
                send_to_esp("fan/on")
            elif fan_state["temperature"] < sch["temp_threshold"] - 2 and fan_state["power"]:
                log.info(f"🌡️ তাপমাত্রা {fan_state['temperature']}°C — অটো বন্ধ!")
                fan_state["power"] = False
                send_to_esp("fan/off")

        return jsonify({"success": True, "temperature": fan_state["temperature"]})
    return jsonify({"success": False}), 400

# ─────────────────────────────────────────
# Schedule System
# ─────────────────────────────────────────

def scheduled_fan_on():
    sch = fan_state["schedule"]
    if sch["on_enabled"] and not fan_state["power"]:
        log.info("⏰ শিডিউল অনুযায়ী ফ্যান চালু হচ্ছে...")
        fan_state["power"] = True
        fan_state["uptime_start"] = datetime.datetime.now()
        send_to_esp("fan/on")


def scheduled_fan_off():
    sch = fan_state["schedule"]
    if sch["off_enabled"] and fan_state["power"]:
        log.info("⏰ শিডিউল অনুযায়ী ফ্যান বন্ধ হচ্ছে...")
        fan_state["total_cost"] = calculate_cost()
        fan_state["power"] = False
        fan_state["uptime_start"] = None
        send_to_esp("fan/off")


def apply_schedule():
    """শিডিউল clear করে নতুন করে set করে"""
    schedule.clear()
    sch = fan_state["schedule"]
    if sch["on_enabled"]:
        schedule.every().day.at(sch["on_time"]).do(scheduled_fan_on)
        log.info(f"📅 চালু শিডিউল: {sch['on_time']}")
    if sch["off_enabled"]:
        schedule.every().day.at(sch["off_time"]).do(scheduled_fan_off)
        log.info(f"📅 বন্ধ শিডিউল: {sch['off_time']}")


def run_scheduler():
    """Background এ schedule check করতে থাকে"""
    while True:
        schedule.run_pending()
        time.sleep(30)

# ─────────────────────────────────────────
# Start
# ─────────────────────────────────────────

if __name__ == "__main__":
    print("""
    ╔══════════════════════════════════════╗
    ║   ALAUTO Smart Fan Server v1.0  ⚡   ║
    ╠══════════════════════════════════════╣
    ║  Mobile App URL:                     ║
    ║  http://আপনার-PC-IP:5000            ║
    ║                                      ║
    ║  Local test:                         ║
    ║  http://localhost:5000               ║
    ╚══════════════════════════════════════╝
    """)

    # শিডিউল চালু করো
    apply_schedule()

    # Background thread এ scheduler চালাও
    t = threading.Thread(target=run_scheduler, daemon=True)
    t.start()
    log.info("⏰ Scheduler চালু হলো")

    # Flask server চালাও
    app.run(host="0.0.0.0", port=SERVER_PORT, debug=False)
