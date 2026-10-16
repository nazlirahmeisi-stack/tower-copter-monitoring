import json
import paho.mqtt.client as mqtt
from database import get_connection

MQTT_BROKER = "localhost"
MQTT_PORT = 1883
ACK_TOPIC = "towercopter/control/ack"
TELEMETRY_TOPIC = "towercopter/telemetry"

mqtt_client = mqtt.Client(
    mqtt.CallbackAPIVersion.VERSION2,
    client_id="tower-copter-backend"
)

def on_message(client, userdata, msg):
    message = msg.payload.decode()

    try:
        payload = json.loads(message)
    except json.JSONDecodeError:
        print("Pesan bukan JSON yang valid.")
        return

    # ACK CONTROL
    if msg.topic == ACK_TOPIC:
        command_id = payload.get("command_id")
        status = payload.get("status")

        if status != "ACKNOWLEDGED" or not command_id:
            return

        connection = get_connection()
        try:
            cursor = connection.cursor()
            sql = """
                UPDATE control_logs
                SET status = ?, ack_timestamp = datetime('now')
                WHERE id = ?
            """
            cursor.execute(sql, ("ACKNOWLEDGED", command_id))
            connection.commit()
        finally:
            connection.close()

    # TELEMETRY DATA
    elif msg.topic == TELEMETRY_TOPIC:
        altitude = payload.get("altitude")
        rpm = payload.get("rpm")
        pwm = payload.get("pwm")
        current = payload.get("current")
        setpoint = payload.get("setpoint")
        error = payload.get("error")

        if None in [altitude, rpm, pwm, current, setpoint, error]:
            print("Telemetry tidak lengkap.")
            return

        connection = get_connection()
        try:
            cursor = connection.cursor()
            # Simpan ke tabel telemetry utama (yang dibaca main.py)
            sql_main = """
                INSERT INTO telemetry (altitude, setpoint, error, rpm, pwm, current, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            """
            cursor.execute(sql_main, (altitude, setpoint, error, rpm, pwm, current))

            # Simpan juga ke telemetry_logs
            sql_log = """
                INSERT INTO telemetry_logs (timestamp, altitude, rpm, pwm, current, setpoint, error)
                VALUES (datetime('now'), ?, ?, ?, ?, ?, ?)
            """
            cursor.execute(sql_log, (altitude, rpm, pwm, current, setpoint, error))

            connection.commit()
            print("Telemetry berhasil disimpan ke database.")
        finally:
            connection.close()

def connect_mqtt():
    mqtt_client.on_message = on_message
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
    mqtt_client.subscribe(ACK_TOPIC)
    mqtt_client.subscribe(TELEMETRY_TOPIC)
    mqtt_client.loop_start()

def publish_message(topic, message):
    result = mqtt_client.publish(topic, message)
    if result.rc != mqtt.MQTT_ERR_SUCCESS:
        raise Exception(f"Gagal publish MQTT. Error code: {result.rc}")
