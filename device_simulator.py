import json
import time
import paho.mqtt.client as mqtt

MQTT_BROKER = "localhost"
MQTT_PORT = 1883

COMMAND_TOPIC = "towercopter/control/command"
SETPOINT_TOPIC = "towercopter/control/setpoint"
ACK_TOPIC = "towercopter/control/ack"
TELEMETRY_TOPIC = "towercopter/telemetry"

altitude = 100.0
setpoint = 120.0
running = False


def on_connect(client, userdata, flags, reason_code, properties):
    print("Simulator ESP32 terhubung ke MQTT Broker.")

    client.subscribe(COMMAND_TOPIC)
    client.subscribe(SETPOINT_TOPIC)

    print(f"Subscribe: {COMMAND_TOPIC}")
    print(f"Subscribe: {SETPOINT_TOPIC}")


def on_message(client, userdata, msg):
    global setpoint
    global running

    message = msg.payload.decode()

    print()
    print("Pesan diterima")
    print(f"Topic  : {msg.topic}")
    print(f"Message: {message}")

    try:
        payload = json.loads(message)
    except json.JSONDecodeError:
        print("Payload bukan JSON yang valid.")
        return

    command_id = payload.get("command_id")
    command = payload.get("command")

    if msg.topic == COMMAND_TOPIC:
        if command == "START":
            running = True
        elif command == "STOP":
            running = False

        ack = {
            "command_id": command_id,
            "command": command,
            "status": "ACKNOWLEDGED"
        }

    elif msg.topic == SETPOINT_TOPIC:
        new_setpoint = payload.get("setpoint")

        if new_setpoint is None:
            print("SETPOINT tidak ditemukan.")
            return

        setpoint = float(new_setpoint)

        ack = {
            "command_id": command_id,
            "command": "SETPOINT",
            "setpoint": setpoint,
            "status": "ACKNOWLEDGED"
        }

    else:
        return

    client.publish(
        ACK_TOPIC,
        json.dumps(ack)
    )

    print(f"ACK dikirim: {json.dumps(ack)}")


def send_telemetry():
    global altitude

    # Ketinggian hanya berubah jika status sistem running = True
    if running:
        if altitude < setpoint:
            altitude += 2.0
        elif altitude > setpoint:
            altitude -= 2.0

    error = setpoint - altitude

    telemetry = {
        "altitude": altitude,
        "rpm": 3520 if running else 0,  # Nilai RPM mengikuti kondisi running
        "pwm": 145 if running else 0,    # Nilai PWM mengikuti kondisi running
        "current": 2.1 if running else 0.0,
        "setpoint": setpoint,
        "error": error
    }

    message = json.dumps(telemetry)

    client.publish(
        TELEMETRY_TOPIC,
        message
    )

    print()
    print("Telemetry dikirim")
    print(f"Topic  : {TELEMETRY_TOPIC}")
    print(f"Message: {message}")


client = mqtt.Client(
    mqtt.CallbackAPIVersion.VERSION2,
    client_id="tower-copter-device-simulator"
)

client.on_connect = on_connect
client.on_message = on_message

print("Menghubungkan simulator ESP32 ke MQTT Broker...")

client.connect(MQTT_BROKER, MQTT_PORT, 60)
client.loop_start()

while True:
    send_telemetry()
    time.sleep(1)