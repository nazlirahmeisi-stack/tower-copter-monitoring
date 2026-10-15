import json
import paho.mqtt.client as mqtt
from database import get_connection
# from metrics import refresh_active_session

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

    # =========================
    # ACK
    # =========================
    if msg.topic == ACK_TOPIC:

        print()
        print("ACK diterima")
        print(f"Topic  : {msg.topic}")
        print(f"Message: {message}")

        command_id = payload.get("command_id")
        status = payload.get("status")

        if status != "ACKNOWLEDGED":
            return

        if not command_id:
            print("ACK tidak memiliki command_id.")
            return

        connection = get_connection()

        try:
            with connection.cursor() as cursor:
                sql = """
                    UPDATE control_logs
                    SET status = %s,
                        ack_timestamp = NOW()
                    WHERE id = %s
                """

                cursor.execute(
                    sql,
                    ("ACKNOWLEDGED", command_id)
                )

                connection.commit()

                if cursor.rowcount > 0:
                    print(
                        f"Command ID {command_id} berhasil di-update menjadi ACKNOWLEDGED."
                    )
                else:
                    print(
                        f"Command ID {command_id} tidak ditemukan di control_logs."
                    )

        finally:
            connection.close()

    # =========================
    # TELEMETRY
    # =========================
    elif msg.topic == TELEMETRY_TOPIC:

        print()
        print("Telemetry diterima")
        print(f"Topic  : {msg.topic}")
        print(f"Message: {message}")

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
            with connection.cursor() as cursor:
                sql = """
                    INSERT INTO telemetry_logs
                    (timestamp, altitude, rpm, pwm, current, setpoint, error)
                    VALUES (NOW(), %s, %s, %s, %s, %s, %s)
                """

                cursor.execute(
                    sql,
                    (
                        altitude,
                        rpm,
                        pwm,
                        current,
                        setpoint,
                        error
                    )
                )

                connection.commit()

                print("Telemetry berhasil disimpan ke telemetry_logs.")

            # Hitung ulang metrik sesi pengujian yang sedang aktif (jika ada).
            # try:
            #     refresh_active_session(connection)
            # except Exception as exc:
            #     print(f"Gagal memperbarui metrik sesi: {exc}")

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