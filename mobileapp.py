"""
TollGate Pro - Mobile Web App (Dark Retro Peachy Edition)
Strong duplicate detection - no more loops
"""

from flask import Flask, render_template_string, jsonify, request
import paho.mqtt.client as mqtt
import json
import threading
from datetime import datetime
from collections import deque

# ======== CONFIGURATION ========
MQTT_BROKER = "broker.emqx.io"
MQTT_PORT = 1883
TOPIC_SCAN = "tollbooth/scan"
TOPIC_CMD = "tollbooth/command"
# ===============================

app = Flask(__name__)

# Vehicle database
VEHICLES = {
    "8BCFF105": {"name": "Ahmed Hassan", "plate": "ABC-123", "balance": 45.00},
    "3A12FF44": {"name": "Sara Mohamed", "plate": "XYZ-789", "balance": 12.50},
    "7C88B210": {"name": "Omar Youssef", "plate": "DEF-456", "balance": 0.00},
}
TOLL_FEE = 5.00

# System state
state = {
    "gate": "CLOSED",
    "last_scan": None,
    "last_driver": "—",
    "last_plate": "—",
    "last_status": "—",
    "total_scans": 0,
    "revenue": 0,
    "denied": 0,
    "transactions": []
}

# Strong duplicate prevention - store last 10 UIDs with timestamps
recent_scans = deque(maxlen=10)  # Stores (uid, timestamp)
last_gate_event = None
last_gate_event_time = None
DUPLICATE_WINDOW_SECONDS = 3  # Ignore same UID for 3 seconds

mqtt_client = None
auto_close_timer = None


def is_duplicate_scan(uid):
    """Check if this UID was scanned recently"""
    global recent_scans
    current_time = datetime.now()
    
    for scanned_uid, scan_time in recent_scans:
        if scanned_uid == uid:
            time_diff = (current_time - scan_time).total_seconds()
            if time_diff < DUPLICATE_WINDOW_SECONDS:
                print(f"⏭️ Duplicate blocked: {uid} (last seen {time_diff:.1f}s ago)")
                return True
    
    # Add to recent scans
    recent_scans.append((uid, current_time))
    return False


def on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code == 0:
        print("✅ Connected to MQTT Broker!")
        client.subscribe(TOPIC_SCAN)
        client.subscribe(TOPIC_CMD)
    else:
        print(f"❌ MQTT Connection failed with code {reason_code}")


def on_message(client, userdata, msg):
    global state, last_gate_event, last_gate_event_time
    
    try:
        payload = json.loads(msg.payload.decode())
    except:
        payload = {"uid": msg.payload.decode()}

    print(f"📨 MQTT: {msg.topic} -> {payload}")

    if msg.topic == TOPIC_SCAN:
        uid = payload.get("uid", "").strip().upper()
        
        # STRONG duplicate prevention
        if is_duplicate_scan(uid):
            return  # Skip this scan completely
        
        vehicle = VEHICLES.get(uid)

        state["total_scans"] += 1
        state["last_scan"] = uid

        if vehicle and vehicle["balance"] >= TOLL_FEE:
            VEHICLES[uid]["balance"] -= TOLL_FEE
            state["last_driver"] = vehicle["name"]
            state["last_plate"] = vehicle["plate"]
            state["last_status"] = "GRANTED ✓"
            state["revenue"] += TOLL_FEE

            state["transactions"].insert(0, {
                "time": datetime.now().strftime("%H:%M:%S"),
                "uid": uid,
                "name": vehicle["name"],
                "status": "GRANTED",
                "balance": f"EGP {VEHICLES[uid]['balance']:.2f}"
            })

            # Send OPEN command
            send_gate_command_with_auto_close("OPEN")
        else:
            driver_name = vehicle["name"] if vehicle else "Unknown"
            state["last_driver"] = driver_name
            state["last_plate"] = vehicle["plate"] if vehicle else "—"
            state["last_status"] = "DENIED ✕"
            state["denied"] += 1

            state["transactions"].insert(0, {
                "time": datetime.now().strftime("%H:%M:%S"),
                "uid": uid,
                "name": driver_name,
                "status": "DENIED",
                "balance": f"EGP {vehicle['balance']:.2f}" if vehicle else "N/A"
            })

        state["transactions"] = state["transactions"][:20]

    elif msg.topic == TOPIC_CMD:
        cmd = str(payload)
        
        # Log gate events (prevent duplicates within 1 second)
        current_time = datetime.now()
        event_key = "OPEN" if "OPEN" in cmd else "CLOSE" if "CLOSE" in cmd else None
        
        if event_key:
            if last_gate_event == event_key and last_gate_event_time:
                time_diff = (current_time - last_gate_event_time).total_seconds()
                if time_diff < 1:
                    print(f"⏭️ Skipping duplicate gate event: {event_key}")
                else:
                    print(f"🚪 Gate {event_key}ED")
                    last_gate_event = event_key
                    last_gate_event_time = current_time
            else:
                print(f"🚪 Gate {event_key}ED")
                last_gate_event = event_key
                last_gate_event_time = current_time
        
        if "OPEN" in cmd:
            state["gate"] = "OPEN"
        elif "CLOSE" in cmd:
            state["gate"] = "CLOSED"
            global auto_close_timer
            if auto_close_timer:
                auto_close_timer.cancel()
                auto_close_timer = None


def send_gate_command_with_auto_close(command):
    """Send OPEN command and schedule auto-close after 4 seconds"""
    global auto_close_timer, mqtt_client, state
    
    if not mqtt_client:
        return
    
    mqtt_client.publish(TOPIC_CMD, json.dumps({"command": command}))
    print(f"📤 Sent: {command}")
    state["gate"] = command
    
    if command == "OPEN":
        if auto_close_timer:
            auto_close_timer.cancel()
        
        def close_gate():
            global auto_close_timer, mqtt_client, state
            print("🔒 Auto-closing gate...")
            if mqtt_client:
                mqtt_client.publish(TOPIC_CMD, json.dumps({"command": "CLOSE"}))
            state["gate"] = "CLOSED"
            auto_close_timer = None
        
        auto_close_timer = threading.Timer(4.0, close_gate)
        auto_close_timer.daemon = True
        auto_close_timer.start()


def start_mqtt():
    global mqtt_client
    mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message

    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqtt_client.loop_forever()
    except Exception as e:
        print(f"❌ MQTT Connection error: {e}")


# HTML Template - With client-side duplicate prevention too
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
    <meta name="theme-color" content="#070B12">
    <title>TollGate Pro - Control System</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Courier New', 'SF Mono', monospace;
            background: #070B12;
            color: #ECF0F7;
            padding: 16px;
            padding-bottom: 80px;
        }
        
        .header {
            text-align: center;
            margin-bottom: 24px;
            padding-bottom: 16px;
            border-bottom: 1px solid #1C2A3A;
        }
        
        .logo {
            font-size: 24px;
            font-weight: bold;
            color: #AAFF00;
            letter-spacing: 4px;
        }
        
        .subtitle {
            font-size: 10px;
            color: #5A7A9A;
            letter-spacing: 2px;
            margin-top: 4px;
        }
        
        .status-bar {
            display: flex;
            justify-content: space-between;
            margin-bottom: 20px;
            padding: 8px 0;
            font-size: 10px;
            color: #5A7A9A;
            border-bottom: 1px solid #1C2A3A;
        }
        
        .mqtt-status {
            display: flex;
            align-items: center;
            gap: 6px;
        }
        
        .dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #AAFF00;
            animation: pulse 2s infinite;
        }
        
        .dot.offline {
            background: #FF3B5C;
            animation: none;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        
        .kpi-row {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
        }
        
        .kpi-card {
            flex: 1;
            background: #0D1421;
            border-radius: 12px;
            padding: 12px;
            text-align: center;
            border: 1px solid #1C2A3A;
        }
        
        .kpi-icon {
            font-size: 20px;
            margin-bottom: 4px;
        }
        
        .kpi-value {
            font-size: 22px;
            font-weight: bold;
            color: #AAFF00;
        }
        
        .kpi-label {
            font-size: 9px;
            color: #5A7A9A;
            margin-top: 4px;
        }
        
        .gate-card {
            background: #0D1421;
            border-radius: 20px;
            padding: 24px;
            text-align: center;
            margin-bottom: 20px;
            border: 1px solid #1C2A3A;
        }
        
        .gate-status {
            font-size: 28px;
            font-weight: bold;
            margin-bottom: 16px;
        }
        
        .gate-status.open {
            color: #AAFF00;
        }
        
        .gate-status.closed {
            color: #FF3B5C;
        }
        
        .gate-icon {
            font-size: 64px;
            margin-bottom: 16px;
        }
        
        .button-row {
            display: flex;
            gap: 12px;
            margin-bottom: 20px;
        }
        
        .btn {
            flex: 1;
            padding: 14px;
            border: none;
            border-radius: 12px;
            font-family: 'Courier New', monospace;
            font-weight: bold;
            font-size: 16px;
            cursor: pointer;
            transition: transform 0.2s, opacity 0.2s;
        }
        
        .btn:active {
            transform: scale(0.98);
        }
        
        .btn-open {
            background: #AAFF00;
            color: #000;
        }
        
        .btn-close {
            background: #FF3B5C;
            color: #fff;
        }
        
        .scan-card {
            background: #0D1421;
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 20px;
            border: 1px solid #1C2A3A;
        }
        
        .card-title {
            color: #AAFF00;
            font-size: 11px;
            letter-spacing: 2px;
            margin-bottom: 16px;
        }
        
        .scan-uid {
            font-size: 20px;
            font-weight: bold;
            font-family: monospace;
            margin-bottom: 8px;
        }
        
        .scan-detail {
            color: #5A7A9A;
            font-size: 13px;
            margin-bottom: 4px;
        }
        
        .scan-status {
            margin-top: 12px;
            font-weight: bold;
            font-size: 16px;
        }
        
        .scan-status.granted {
            color: #AAFF00;
        }
        
        .scan-status.denied {
            color: #FF3B5C;
        }
        
        .feed-card {
            background: #0D1421;
            border-radius: 16px;
            padding: 16px;
            border: 1px solid #1C2A3A;
            height: 280px;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
        }
        
        .feed-title {
            color: #AAFF00;
            font-size: 11px;
            letter-spacing: 2px;
            margin-bottom: 12px;
            flex-shrink: 0;
        }
        
        .feed-container {
            flex: 1;
            overflow-y: auto;
        }
        
        .feed-item {
            font-family: monospace;
            font-size: 10px;
            padding: 6px 0;
            border-bottom: 1px solid #1C2A3A;
            color: #5A7A9A;
        }
        
        .feed-item.ok {
            color: #AAFF00;
        }
        
        .feed-item.err {
            color: #FF3B5C;
        }
        
        .feed-item.info {
            color: #00E5FF;
        }
        
        .feed-item.gate-open {
            color: #AAFF00;
        }
        
        .feed-item.gate-close {
            color: #FFB8C6;
        }
        
        .feed-time {
            color: #3A5570;
            margin-right: 8px;
        }
        
        .transactions-card {
            background: #0D1421;
            border-radius: 16px;
            padding: 16px;
            margin-top: 20px;
            border: 1px solid #1C2A3A;
            max-height: 350px;
            overflow-y: auto;
        }
        
        .transaction-item {
            padding: 10px 0;
            border-bottom: 1px solid #1C2A3A;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .transaction-item:last-child {
            border-bottom: none;
        }
        
        .transaction-time {
            font-size: 10px;
            color: #3A5570;
            font-family: monospace;
        }
        
        .transaction-uid {
            font-family: monospace;
            font-size: 11px;
            font-weight: bold;
        }
        
        .transaction-name {
            font-size: 10px;
            color: #5A7A9A;
            margin-top: 2px;
        }
        
        .transaction-status {
            font-weight: bold;
            font-size: 11px;
            padding: 2px 8px;
            border-radius: 4px;
        }
        
        .transaction-status.granted {
            color: #AAFF00;
            background: #AAFF0010;
        }
        
        .transaction-status.denied {
            color: #FF3B5C;
            background: #FF3B5C10;
        }
        
        .footer {
            text-align: center;
            margin-top: 20px;
            font-size: 9px;
            color: #3A5570;
        }
        
        .refresh-info {
            text-align: center;
            margin-top: 12px;
            font-size: 9px;
            color: #3A5570;
        }
        
        .auto-close-badge {
            background: #1C2A3A;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 9px;
            color: #5A7A9A;
            display: inline-block;
            margin-top: 8px;
        }
        
        ::-webkit-scrollbar {
            width: 6px;
        }
        
        ::-webkit-scrollbar-track {
            background: #0D1421;
        }
        
        ::-webkit-scrollbar-thumb {
            background: #1C2A3A;
            border-radius: 3px;
        }
    </style>
</head>
<body>
    <div class="header">
        <div class="logo">TOLLGATE</div>
        <div class="subtitle">PRO · CONTROL SYSTEM</div>
    </div>
    
    <div class="status-bar">
        <span>🔒 SYSTEM ONLINE</span>
        <div class="mqtt-status">
            <div class="dot" id="mqttDot"></div>
            <span id="mqttStatus">CONNECTED</span>
        </div>
    </div>
    
    <div class="kpi-row">
        <div class="kpi-card">
            <div class="kpi-icon">📊</div>
            <div class="kpi-value" id="totalScans">0</div>
            <div class="kpi-label">SCANS</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-icon">💰</div>
            <div class="kpi-value" id="revenue">EGP 0</div>
            <div class="kpi-label">REVENUE</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-icon">🚫</div>
            <div class="kpi-value" id="denied">0</div>
            <div class="kpi-label">DENIED</div>
        </div>
    </div>
    
    <div class="gate-card">
        <div class="gate-icon" id="gateIcon">🔒</div>
        <div class="gate-status closed" id="gateStatus">GATE CLOSED</div>
        <div class="auto-close-badge" id="autoCloseBadge">🔁 Auto-closes in 4 seconds</div>
    </div>
    
    <div class="button-row">
        <button class="btn btn-open" onclick="sendCommand('OPEN')">▲ OPEN</button>
        <button class="btn btn-close" onclick="sendCommand('CLOSE')">▬ CLOSE</button>
    </div>
    
    <div class="scan-card">
        <div class="card-title">◈ LAST RFID SCAN</div>
        <div class="scan-uid" id="lastUID">— — — — — — —</div>
        <div class="scan-detail" id="lastDriver">Awaiting scan...</div>
        <div class="scan-detail" id="lastPlate"></div>
        <div class="scan-status" id="lastStatus"></div>
    </div>
    
    <div class="feed-card">
        <div class="feed-title">📡 LIVE EVENT FEED</div>
        <div class="feed-container" id="liveFeed">
            <div class="feed-item info">
                <span class="feed-time">[--:--:--]</span> System ready
            </div>
        </div>
    </div>
    
    <div class="transactions-card">
        <div class="card-title">▤ RECENT TRANSACTIONS</div>
        <div id="transactionsList">
            <div style="text-align: center; color: #5A7A9A; padding: 20px;">No transactions yet</div>
        </div>
    </div>
    
    <div class="refresh-info">↻ Auto-refreshes every 2 seconds</div>
    <div class="footer" id="clock"></div>
    
    <script>
        let currentState = {
            gate: "CLOSED",
            last_scan: null,
            last_driver: "—",
            last_plate: "—",
            last_status: "—",
            total_scans: 0,
            revenue: 0,
            denied: 0,
            transactions: []
        };
        
        let autoCloseTimer = null;
        
        // Client-side duplicate prevention
        let lastProcessedUid = null;
        let lastProcessedTime = 0;
        let lastGateEvent = null;
        let lastGateEventTime = 0;
        
        function getFormattedTime() {
            const now = new Date();
            const hours = now.getHours().toString().padStart(2, '0');
            const minutes = now.getMinutes().toString().padStart(2, '0');
            const seconds = now.getSeconds().toString().padStart(2, '0');
            return `${hours}:${minutes}:${seconds}`;
        }
        
        function addToFeed(message, type = "info") {
            const time = getFormattedTime();
            const feedContainer = document.getElementById('liveFeed');
            const newItem = document.createElement('div');
            newItem.className = `feed-item ${type}`;
            newItem.innerHTML = `<span class="feed-time">[${time}]</span> ${message}`;
            feedContainer.insertBefore(newItem, feedContainer.firstChild);
            
            // Keep only last 20 items
            while (feedContainer.children.length > 20) {
                feedContainer.removeChild(feedContainer.lastChild);
            }
        }
        
        async function fetchStats() {
            try {
                const response = await fetch('/api/stats');
                const data = await response.json();
                
                // Check for gate state change (with duplicate prevention)
                if (currentState.gate !== data.gate) {
                    const now = Date.now();
                    const eventKey = data.gate;
                    
                    if (lastGateEvent !== eventKey || (now - lastGateEventTime) > 1500) {
                        lastGateEvent = eventKey;
                        lastGateEventTime = now;
                        
                        if (data.gate === "OPEN") {
                            addToFeed("🚪 Gate OPENED", "gate-open");
                        } else if (data.gate === "CLOSED") {
                            addToFeed("🚪 Gate CLOSED", "gate-close");
                        }
                    }
                }
                
                // Check for new scan (with duplicate prevention)
                if (currentState.last_scan !== data.last_scan && data.last_scan) {
                    const now = Date.now();
                    
                    if (data.last_scan !== lastProcessedUid || (now - lastProcessedTime) > 3000) {
                        lastProcessedUid = data.last_scan;
                        lastProcessedTime = now;
                        
                        if (data.last_status && data.last_status.includes("GRANTED")) {
                            addToFeed(`✓ SCAN ${data.last_scan} → ${data.last_driver} → GRANTED`, "ok");
                        } else if (data.last_status && data.last_status.includes("DENIED")) {
                            addToFeed(`✗ SCAN ${data.last_scan} → ${data.last_driver} → DENIED`, "err");
                        }
                    }
                }
                
                currentState = data;
                updateUI();
                
                document.getElementById('mqttDot').classList.remove('offline');
                document.getElementById('mqttStatus').innerText = 'CONNECTED';
            } catch (error) {
                console.error('Fetch error:', error);
                document.getElementById('mqttDot').classList.add('offline');
                document.getElementById('mqttStatus').innerText = 'OFFLINE';
            }
        }
        
        async function sendCommand(command) {
            try {
                const response = await fetch('/api/gate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ command: command })
                });
                const result = await response.json();
                if (result.ok) {
                    addToFeed(`Command: ${command}`, "info");
                    
                    if (command === 'OPEN') {
                        let seconds = 4;
                        const badge = document.getElementById('autoCloseBadge');
                        
                        if (autoCloseTimer) clearInterval(autoCloseTimer);
                        autoCloseTimer = setInterval(() => {
                            seconds--;
                            if (seconds > 0) {
                                badge.innerHTML = `⏱️ Closing in ${seconds}s`;
                            } else {
                                badge.innerHTML = `🔁 Auto-closes in 4 seconds`;
                                clearInterval(autoCloseTimer);
                                autoCloseTimer = null;
                            }
                        }, 1000);
                    } else if (command === 'CLOSE') {
                        if (autoCloseTimer) {
                            clearInterval(autoCloseTimer);
                            autoCloseTimer = null;
                            document.getElementById('autoCloseBadge').innerHTML = `🔁 Auto-closes in 4 seconds`;
                        }
                    }
                }
            } catch (error) {
                console.error('Command error:', error);
            }
        }
        
        function updateUI() {
            const isOpen = currentState.gate === "OPEN";
            const gateStatusEl = document.getElementById('gateStatus');
            const gateIconEl = document.getElementById('gateIcon');
            
            gateStatusEl.innerText = isOpen ? "GATE OPEN" : "GATE CLOSED";
            gateStatusEl.className = isOpen ? "gate-status open" : "gate-status closed";
            gateIconEl.innerHTML = isOpen ? "▲" : "🔒";
            
            document.getElementById('lastUID').innerText = currentState.last_scan || "— — — — — — —";
            document.getElementById('lastDriver').innerHTML = `👤 ${currentState.last_driver}`;
            document.getElementById('lastPlate').innerHTML = `🚗 ${currentState.last_plate || ''}`;
            
            const statusEl = document.getElementById('lastStatus');
            if (currentState.last_status && currentState.last_status !== "—") {
                statusEl.innerText = currentState.last_status;
                statusEl.className = currentState.last_status.includes("GRANTED") ? "scan-status granted" : "scan-status denied";
            } else {
                statusEl.innerText = "";
            }
            
            document.getElementById('totalScans').innerText = currentState.total_scans || 0;
            document.getElementById('revenue').innerText = `EGP ${(currentState.revenue || 0).toFixed(2)}`;
            document.getElementById('denied').innerText = currentState.denied || 0;
            
            const txContainer = document.getElementById('transactionsList');
            if (currentState.transactions && currentState.transactions.length > 0) {
                txContainer.innerHTML = currentState.transactions.map(tx => `
                    <div class="transaction-item">
                        <div>
                            <div class="transaction-time">${tx.time || '--:--'}</div>
                            <div class="transaction-uid">${tx.uid || '---'}</div>
                            <div class="transaction-name">${tx.name || ''}</div>
                        </div>
                        <div class="transaction-status ${tx.status === 'GRANTED' ? 'granted' : 'denied'}">
                            ${tx.status === 'GRANTED' ? '✓' : '✕'} ${tx.status}
                        </div>
                    </div>
                `).join('');
            } else {
                txContainer.innerHTML = '<div style="text-align: center; color: #5A7A9A; padding: 20px;">No transactions yet</div>';
            }
        }
        
        function updateClock() {
            const now = new Date();
            const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
            const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
            const dayName = days[now.getDay()];
            const month = months[now.getMonth()];
            const date = now.getDate().toString().padStart(2, '0');
            const year = now.getFullYear();
            const hours = now.getHours().toString().padStart(2, '0');
            const minutes = now.getMinutes().toString().padStart(2, '0');
            const seconds = now.getSeconds().toString().padStart(2, '0');
            
            document.getElementById('clock').innerHTML = `${dayName} ${date} ${month} ${year}  •  ${hours}:${minutes}:${seconds}`;
        }
        
        addToFeed("MQTT connected to broker.emqx.io", "info");
        
        setInterval(fetchStats, 2000);
        setInterval(updateClock, 1000);
        fetchStats();
        updateClock();
    </script>
</body>
</html>
"""


@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route('/api/stats')
def stats():
    response_state = state.copy()
    return jsonify(response_state)


@app.route('/api/gate', methods=['POST'])
def gate():
    global auto_close_timer
    command = request.json.get('command', '')
    
    if command in ['OPEN', 'CLOSE']:
        if mqtt_client:
            mqtt_client.publish(TOPIC_CMD, json.dumps({"command": command}))
            print(f"📤 Sent: {command}")
        
        state["gate"] = command
        
        if command == "OPEN":
            if auto_close_timer:
                auto_close_timer.cancel()
            
            def close_gate():
                global auto_close_timer, mqtt_client, state
                print("🔒 Auto-closing gate...")
                if mqtt_client:
                    mqtt_client.publish(TOPIC_CMD, json.dumps({"command": "CLOSE"}))
                state["gate"] = "CLOSED"
                auto_close_timer = None
            
            auto_close_timer = threading.Timer(4.0, close_gate)
            auto_close_timer.daemon = True
            auto_close_timer.start()
        elif command == "CLOSE":
            if auto_close_timer:
                auto_close_timer.cancel()
                auto_close_timer = None
        
        return jsonify({"ok": True, "gate": command})
    
    return jsonify({"ok": False, "error": "Invalid command"}), 400


@app.route('/api/vehicles')
def get_vehicles():
    return jsonify(VEHICLES)


@app.route('/api/add_vehicle', methods=['POST'])
def add_vehicle():
    data = request.json
    uid = data.get('uid', '').upper()
    VEHICLES[uid] = {
        "name": data.get('name', ''),
        "plate": data.get('plate', ''),
        "balance": float(data.get('balance', 0))
    }
    return jsonify({"ok": True})


if __name__ == '__main__':
    mqtt_thread = threading.Thread(target=start_mqtt, daemon=True)
    mqtt_thread.start()

    print("\n" + "=" * 50)
    print("🚀 TollGate Pro - Mobile Control System")
    print("=" * 50)
    print("\n📱 On your phone, open:")
    print("   http://192.168.100.169:5000")
    print("\n💡 Make sure your phone is on the SAME WiFi")
    print("\n🔁 Gate auto-closes 4 seconds after opening")
    print("\n🛡️ Duplicate scans blocked for 3 seconds")
    print("=" * 50 + "\n")

    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)