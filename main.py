from machine import Pin, time_pulse_us, SoftI2C, PWM
from time import sleep, sleep_us, time, localtime
from machine_i2c_lcd import I2cLcd
import network
import urequests
import socket
import json

# ====== CONFIGURATION ======
TRIG = Pin(27, Pin.OUT)
ECHO = Pin(26, Pin.IN)
ir_sensor1 = Pin(4, Pin.IN)
ir_sensor2 = Pin(16, Pin.IN)
ir_sensor3 = Pin(17, Pin.IN)
servo = PWM(Pin(33), freq=50)
I2C_ADDR = 0x27
i2c = SoftI2C(sda=Pin(21), scl=Pin(22), freq=400000)
lcd = I2cLcd(i2c, I2C_ADDR, 2, 16)

# WiFi setup
SSID = "Robotic WIFI"
PASSWORD = "rbtWIFI@2025"
# Telegram setup
BOT_TOKEN = "8232520387:AAGP1TioaRq5YQGzi9vlOVzfzQQAXCzpTnQ"
CHAT_ID = "-4961594574"
# Pricing
RATE = 0.5  # $ per minute
DEBUG = True

API = "https://api.telegram.org/bot" + BOT_TOKEN

# ====== GLOBAL DATA ======
slots = {
    1: {"ir": ir_sensor1, "occupied": False, "id": None, "time_in": None},
    2: {"ir": ir_sensor2, "occupied": False, "id": None, "time_in": None},
    3: {"ir": ir_sensor3, "occupied": False, "id": None, "time_in": None},
}

closed_tickets = []  # Store recent closed tickets
available_ids = [1, 2, 3]  # Pool of available IDs

# ====== CONNECT TO WIFI ======
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(SSID, PASSWORD)
    print("Connecting to WiFi...", end="")
    while not wlan.isconnected():
        print(".", end="")
        sleep(0.5)
    print("\nConnected:", wlan.ifconfig())
    return wlan

# ====== HELPER FUNCTIONS ======
def distance_cm():
    TRIG.off(); sleep_us(2)
    TRIG.on(); sleep_us(10)
    TRIG.off()
    t = time_pulse_us(ECHO, 1, 30000)
    if t < 0:
        return None
    return (t * 0.0343) / 2.0

def set_angle(angle):
    duty = int(25 + (angle / 180 * 100))
    servo.duty(duty)

def _urlencode(d):
    parts = []
    for k, v in d.items():
        if isinstance(v, int):
            v = str(v)
        s = str(v)
        s = s.replace("%", "%25").replace(" ", "%20").replace("\n", "%0A")
        s = s.replace("&", "%26").replace("?", "%3F").replace("=", "%3D")
        parts.append(str(k) + "=" + s)
    return "&".join(parts)

def log(*args):
    if DEBUG:
        print(*args)

def send_telegram(chat_id, text):
    try:
        url = API + "/sendMessage?" + _urlencode({"chat_id": chat_id, "text": text})
        r = urequests.get(url)
        _ = r.text
        r.close()
        log("send_message OK to", chat_id)
    except Exception as e:
        print("send_message error:", e)

def update_lcd():
    # Collect all free slot labels in numeric order (e.g., S1, S2, S3)
    free_slots = [f"S{i}" for i, s in sorted(slots.items()) if not s.get("occupied", False)]
    
    # Clear the LCD before updating
    lcd.clear()

    # Case 1: All slots occupied
    if len(free_slots) == 0:
        lcd.move_to(0, 0)
        lcd.putstr("FULL")

    # Case 2: There are free slots
    else:
        lcd.move_to(0, 0)
        lcd.putstr("Free:")

        # Join free slots into a string and limit to 16 chars (LCD width)
        free_text = " ".join(free_slots)[:16]
        lcd.move_to(0, 1)
        lcd.putstr(free_text)



def get_next_id():
    """Get the lowest available ID"""
    if available_ids:
        return available_ids.pop(0)
    return None

def release_id(car_id):
    """Return ID to the pool"""
    if car_id and car_id not in available_ids:
        available_ids.append(car_id)
        available_ids.sort()

def format_time(timestamp):
    """Format timestamp to readable time"""
    t = localtime(timestamp)
    return f"{t[3]:02d}:{t[4]:02d}:{t[5]:02d}"

def get_elapsed(time_in):
    """Get elapsed time in minutes"""
    return (time() - time_in) / 60

# ====== WEB SERVER ======
def get_dashboard_data():
    """Prepare data for dashboard"""
    free_count = sum(1 for s in slots.values() if not s["occupied"])
    occupied_count = 3 - free_count
    
    # Active tickets
    active_tickets = []
    for slot_num, s in slots.items():
        if s["occupied"] and s["id"] is not None:
            elapsed = get_elapsed(s["time_in"])
            active_tickets.append({
                "id": s["id"],
                "slot": slot_num,
                "time_in": format_time(s["time_in"]),
                "elapsed": f"{elapsed:.1f}"
            })
    
    # Slot status
    slot_status = []
    for slot_num, s in slots.items():
        if s["occupied"]:
            elapsed = get_elapsed(s["time_in"]) if s["time_in"] else 0
            slot_status.append({
                "slot": slot_num,
                "status": "Occupied",
                "id": s["id"],
                "time_in": format_time(s["time_in"]),
                "elapsed": f"{elapsed:.1f}"
            })
        else:
            slot_status.append({
                "slot": slot_num,
                "status": "Free",
                "id": None,
                "time_in": None,
                "elapsed": None
            })
    
    return {
        "total": 3,
        "free": free_count,
        "occupied": occupied_count,
        "status": "FULL" if free_count == 0 else "Available",
        "slots": slot_status,
        "active_tickets": active_tickets,
        "closed_tickets": closed_tickets[-10:]  # Last 10 closed tickets
    }

def serve_dashboard(client):
    """Serve the web dashboard"""
    try:
        request = client.recv(1024).decode()
        
        if "GET /data" in request:
            # API endpoint for JSON data
            data = get_dashboard_data()
            response = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n"
            response += json.dumps(data)
        else:
            # Serve HTML page
            response = """HTTP/1.1 200 OK
Content-Type: text/html

<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Smart Parking System</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #e91e63 0%, #9c27b0 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        .header {
            background: white;
            padding: 25px;
            border-radius: 15px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            margin-bottom: 25px;
        }
        h1 {
            color: #e91e63;
            font-size: 32px;
            margin-bottom: 20px;
            text-align: center;
        }
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-top: 20px;
        }
        .stat-box {
            background: linear-gradient(135deg, #e91e63, #9c27b0);
            color: white;
            padding: 20px;
            border-radius: 10px;
            text-align: center;
        }
        .stat-box.available { background: linear-gradient(135deg, #00bcd4, #0097a7); }
        .stat-box.full { background: linear-gradient(135deg, #ff5722, #e64a19); }
        .stat-label { font-size: 14px; opacity: 0.9; margin-bottom: 5px; }
        .stat-value { font-size: 28px; font-weight: bold; }
        .slots-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 20px;
            margin-bottom: 25px;
        }
        .slot-card {
            background: white;
            border-radius: 15px;
            padding: 20px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
        }
        .slot-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }
        .slot-number {
            font-size: 24px;
            font-weight: bold;
            color: #e91e63;
        }
        .slot-badge {
            padding: 5px 15px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: bold;
        }
        .slot-badge.free {
            background: #00bcd4;
            color: white;
        }
        .slot-badge.occupied {
            background: #ff5722;
            color: white;
        }
        .slot-info {
            display: grid;
            gap: 8px;
            font-size: 14px;
            color: #555;
        }
        .info-row {
            display: flex;
            justify-content: space-between;
        }
        .info-label { font-weight: 600; }
        .table-container {
            background: white;
            border-radius: 15px;
            padding: 25px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            margin-bottom: 25px;
        }
        h2 {
            color: #e91e63;
            margin-bottom: 20px;
            font-size: 22px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
        }
        th {
            background: #e91e63;
            color: white;
            padding: 12px;
            text-align: left;
            font-weight: 600;
        }
        td {
            padding: 12px;
            border-bottom: 1px solid #eee;
        }
        tr:hover { background: #fce4ec; }
        .empty-state {
            text-align: center;
            color: #999;
            padding: 30px;
            font-style: italic;
        }
        .refresh-info {
            text-align: center;
            color: white;
            margin-top: 20px;
            font-size: 14px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚗 Smart Parking System</h1>
            <div class="stats" id="stats"></div>
        </div>

        <div class="slots-grid" id="slots-grid"></div>

        <div class="table-container">
            <h2>🟢 Active Tickets (OPEN)</h2>
            <table>
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Slot</th>
                        <th>Time In</th>
                        <th>Elapsed (min)</th>
                    </tr>
                </thead>
                <tbody id="active-tickets"></tbody>
            </table>
        </div>

        <div class="table-container">
            <h2>✅ Recent Tickets (CLOSED)</h2>
            <table>
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Slot</th>
                        <th>Duration (min)</th>
                        <th>Fee</th>
                        <th>Time Out</th>
                    </tr>
                </thead>
                <tbody id="closed-tickets"></tbody>
            </table>
        </div>

        <div class="refresh-info">Auto-refresh every 3 seconds</div>
    </div>

    <script>
        function updateDashboard() {
            fetch('/data')
                .then(r => r.json())
                .then(data => {
                    // Update stats
                    const statsClass = data.status === 'FULL' ? 'full' : 'available';
                    document.getElementById('stats').innerHTML = `
                        <div class="stat-box">
                            <div class="stat-label">Total Slots</div>
                            <div class="stat-value">${data.total}</div>
                        </div>
                        <div class="stat-box">
                            <div class="stat-label">Free</div>
                            <div class="stat-value">${data.free}</div>
                        </div>
                        <div class="stat-box">
                            <div class="stat-label">Occupied</div>
                            <div class="stat-value">${data.occupied}</div>
                        </div>
                        <div class="stat-box ${statsClass}">
                            <div class="stat-label">Status</div>
                            <div class="stat-value">${data.status}</div>
                        </div>
                    `;

                    
                    
                    // Update slots (sorted by slot number)
                    const sortedSlots = data.slots.sort((a, b) => a.slot - b.slot);

                    document.getElementById('slots-grid').innerHTML = sortedSlots.map(s => `
                     
                        <div class="slot-card">
                            <div class="slot-header">
                                <div class="slot-number">Slot ${s.slot}</div>
                                <div class="slot-badge ${s.status.toLowerCase()}">${s.status}</div>
                            </div>
                            ${s.status === 'Occupied' ? `
                                <div class="slot-info">
                                    <div class="info-row">
                                        <span class="info-label">Car ID:</span>
                                        <span>${s.id}</span>
                                    </div>
                                    <div class="info-row">
                                        <span class="info-label">Time In:</span>
                                        <span>${s.time_in}</span>
                                    </div>
                                    <div class="info-row">
                                        <span class="info-label">Elapsed:</span>
                                        <span>${s.elapsed} min</span>
                                    </div>
                                </div>
                            ` : '<div class="slot-info" style="text-align:center;color:#00bcd4;font-weight:bold;">Available</div>'}
                        </div>
                    `).join('');

                    // Update active tickets
                    const activeHTML = data.active_tickets.length > 0 
                        ? data.active_tickets.map(t => `
                            <tr>
                                <td>${t.id}</td>
                                <td>S${t.slot}</td>
                                <td>${t.time_in}</td>
                                <td>${t.elapsed}</td>
                            </tr>
                        `).join('')
                        : '<tr><td colspan="4" class="empty-state">No active tickets</td></tr>';
                    document.getElementById('active-tickets').innerHTML = activeHTML;

                    // Update closed tickets
                    const closedHTML = data.closed_tickets.length > 0
                        ? data.closed_tickets.map(t => `
                            <tr>
                                <td>${t.id}</td>
                                <td>S${t.slot}</td>
                                <td>${t.duration}</td>
                                <td>$${t.fee}</td>
                                <td>${t.time_out}</td>
                            </tr>
                        `).join('')
                        : '<tr><td colspan="5" class="empty-state">No closed tickets yet</td></tr>';
                    document.getElementById('closed-tickets').innerHTML = closedHTML;
                })
                .catch(e => console.error('Update failed:', e));
        }

        updateDashboard();
        setInterval(updateDashboard, 3000);
    </script>
</body>
</html>"""
        
        client.send(response.encode())
    except Exception as e:
        print("Server error:", e)
    finally:
        client.close()

def start_web_server():
    """Start the web server"""
    addr = socket.getaddrinfo('0.0.0.0', 80)[0][-1]
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(addr)
    s.listen(1)
    s.setblocking(False)
    print('Web server running on port 80')
    return s

# ====== MAIN LOOP ======
wlan = connect_wifi()
web_server = start_web_server()
print(f"Dashboard: http://{wlan.ifconfig()[0]}")

set_angle(0)
update_lcd()

while True:
    # Handle web requests (non-blocking)
    try:
        client, addr = web_server.accept()
        serve_dashboard(client)
    except:
        pass

    d = distance_cm()
    free_slots = [s for s in slots if not slots[s]["occupied"]]
    full = len(free_slots) == 0
    
    # Entry Detection
    if d is not None and d < 15:
        if not full:
            update_lcd()
            set_angle(90)
            sleep(5)
            set_angle(0)
        else:
            lcd.clear()
            lcd.putstr("FULL")
            sleep(2)
            update_lcd()
    
    # Slot Monitoring
    for i, s in slots.items():
        val = s["ir"].value()
        # Car arrives
        if val == 0 and not s["occupied"]:
            car_id = get_next_id()
            if car_id:
                s["occupied"] = True
                s["id"] = car_id
                s["time_in"] = time()
                print(f"Car ID {car_id} entered Slot {i}")
                update_lcd()
        
        # Car leaves
        elif val == 1 and s["occupied"]:
            sleep(1)
            if s["ir"].value() == 1:
                duration = get_elapsed(s["time_in"])
                fee = round(duration * RATE, 2)
                
                # Store closed ticket
                closed_tickets.append({
                    "id": s["id"],
                    "slot": i,
                    "duration": f"{duration:.1f}",
                    "fee": f"{fee:.2f}",
                    "time_out": format_time(time())
                })
                
                message = (
                    f"✅ Ticket CLOSED\n"
                    f"ID: {s['id']} Slot: S{i}\n"
                    f"Duration: {duration:.1f} minutes\n"
                    f"Fee: ${fee}"
                )
                send_telegram(CHAT_ID, message)
                print(message)
                
                release_id(s["id"])
                s["occupied"] = False
                s["id"] = None
                s["time_in"] = None
                update_lcd()
    
    sleep(0.1)