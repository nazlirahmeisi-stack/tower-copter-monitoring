import json
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, model_validator
from database import get_connection
from mqtt_client import connect_mqtt, publish_message

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

connect_mqtt()

class ControlCommand(BaseModel):
    command: str
    setpoint: float | None = None

    @model_validator(mode="after")
    def validate_command(self):
        self.command = self.command.upper()

        if self.command not in ["START", "STOP", "SETPOINT"]:
            raise ValueError(
                "command harus START, STOP, atau SETPOINT"
            )

        if self.command == "SETPOINT" and self.setpoint is None:
            raise ValueError(
                "setpoint wajib diisi untuk command SETPOINT"
            )

        if self.command in ["START", "STOP"] and self.setpoint is not None:
            raise ValueError(
                "setpoint tidak diperlukan untuk command START atau STOP"
            )

        return self


class SessionStart(BaseModel):
    method: Literal["ZN", "CPO", "SO", "GJO", "MANUAL"]
    kp: float | None = None
    ki: float | None = None
    kd: float | None = None


@app.get("/")
def root():
    return {"message": "Tower Copter Backend is running"}

@app.get("/telemetry")
def get_telemetry():
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT *
                FROM telemetry_logs
                ORDER BY timestamp DESC
            """
            cursor.execute(sql)
            data = cursor.fetchall()
            return data
    finally:
        connection.close()

@app.get("/telemetry/latest")
def get_latest_telemetry():
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT *
                FROM telemetry_logs
                ORDER BY timestamp DESC
                LIMIT 1
            """
            cursor.execute(sql)
            data = cursor.fetchone()
            return data
    finally:
        connection.close()

@app.get("/control/latest")
def get_latest_control():
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT *
                FROM control_logs
                ORDER BY timestamp DESC
                LIMIT 1
            """
            cursor.execute(sql)
            data = cursor.fetchone()
            return data
    finally:
        connection.close()

@app.get("/stats")
def get_stats():
    """Ringkasan jumlah data untuk halaman beranda."""
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS n, MAX(timestamp) AS last_ts FROM telemetry_logs")
            tele = cursor.fetchone()
            cursor.execute("SELECT COUNT(*) AS n FROM control_logs")
            cmd = cursor.fetchone()
            cursor.execute("SELECT COUNT(*) AS n FROM control_logs WHERE status = 'ACKNOWLEDGED'")
            acked = cursor.fetchone()
            try:
                cursor.execute("SELECT COUNT(*) AS n FROM test_sessions WHERE status = 'COMPLETED'")
                sessions = cursor.fetchone()["n"]
            except Exception:
                sessions = 0  # tabel test_sessions belum dibuat
        return {
            "telemetry": tele["n"],
            "last_telemetry": tele["last_ts"],
            "commands": cmd["n"],
            "commands_acked": acked["n"],
            "sessions_completed": sessions,
        }
    finally:
        connection.close()

@app.post("/control")
def send_control(control: ControlCommand):
    connection = get_connection()

    try:
        # 1. Simpan command ke database
        with connection.cursor() as cursor:
            sql = """
                INSERT INTO control_logs
                (timestamp, command, setpoint, status)
                VALUES (NOW(), %s, %s, %s)
            """

            cursor.execute(
                sql,
                (control.command, control.setpoint, "SENT")
            )

            connection.commit()

            command_id = cursor.lastrowid

        # 2. Tentukan topic dan payload MQTT
        if control.command == "SETPOINT":
            topic = "towercopter/control/setpoint"
            payload = {
                "command_id": command_id,
                "command": "SETPOINT",
                "setpoint": control.setpoint
            }
        else:
            topic = "towercopter/control/command"
            payload = {
                "command_id": command_id,
                "command": control.command
            }

        # Format dictionary menjadi string JSON
        message = json.dumps(payload)

        # 3. Publish ke MQTT
        publish_message(topic, message)

        # 4. Kirim response
        return {
            "id": command_id,
            "command": control.command,
            "setpoint": control.setpoint,
            "status": "SENT",
            "mqtt_topic": topic,
            "mqtt_message": message
        }

    finally:
        connection.close()


# =====================================================
# SESI PENGUJIAN: metrik dihitung di backend (metrics.py),
# diperbarui otomatis tiap telemetry masuk, disimpan di test_sessions.
# =====================================================

@app.post("/sessions/start")
def start_session(body: SessionStart):
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM test_sessions WHERE status IN ('WAITING','RUNNING') LIMIT 1"
            )
            if cursor.fetchone():
                raise HTTPException(
                    status_code=409,
                    detail="Masih ada sesi aktif. Batalkan atau tunggu sampai selesai (tekan STOP)."
                )

            cursor.execute(
                "SELECT id, altitude, setpoint FROM telemetry_logs ORDER BY id DESC LIMIT 1"
            )
            latest = cursor.fetchone()
            if not latest:
                raise HTTPException(
                    status_code=400,
                    detail="Belum ada data telemetry. Pastikan perangkat sudah mengirim data."
                )

            cursor.execute(
                """
                INSERT INTO test_sessions
                (method, kp, ki, kd, status, started_at, start_telemetry_id, y0, setpoint)
                VALUES (%s, %s, %s, %s, 'WAITING', NOW(), %s, %s, %s)
                """,
                (body.method, body.kp, body.ki, body.kd,
                 latest["id"], latest["altitude"], latest["setpoint"])
            )
            session_id = cursor.lastrowid

        connection.commit()
        return {"id": session_id, "method": body.method, "status": "WAITING"}
    finally:
        connection.close()

@app.post("/sessions/{session_id}/cancel")
def cancel_session(session_id: int):
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE test_sessions
                SET status='CANCELLED', ended_at=NOW(), updated_at=NOW()
                WHERE id=%s AND status IN ('WAITING','RUNNING')
                """,
                (session_id,)
            )
            changed = cursor.rowcount
        connection.commit()
        if changed == 0:
            raise HTTPException(status_code=404, detail="Sesi aktif dengan id tersebut tidak ditemukan.")
        return {"id": session_id, "status": "CANCELLED"}
    finally:
        connection.close()

@app.get("/sessions/current")
def get_current_session():
    """Sesi yang sedang aktif; bila tidak ada, sesi selesai terakhir."""
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM test_sessions WHERE status IN ('WAITING','RUNNING') ORDER BY id DESC LIMIT 1"
            )
            data = cursor.fetchone()
            if data is None:
                cursor.execute(
                    "SELECT * FROM test_sessions WHERE status='COMPLETED' ORDER BY id DESC LIMIT 1"
                )
                data = cursor.fetchone()
            return data
    finally:
        connection.close()

@app.get("/sessions/summary")
def get_sessions_summary():
    """Sesi terbaik (ITAE terendah) per metode, hanya dari sesi selesai dengan step valid."""
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM test_sessions
                WHERE status='COMPLETED' AND itae IS NOT NULL AND ABS(setpoint - y0) >= 1
                ORDER BY id DESC LIMIT 1000
                """
            )
            rows = cursor.fetchall()
    finally:
        connection.close()

    summary = {}
    for row in rows:
        item = summary.setdefault(row["method"], {"method": row["method"], "runs": 0, "best": None})
        item["runs"] += 1
        if item["best"] is None or row["itae"] < item["best"]["itae"]:
            item["best"] = row
    return list(summary.values())

@app.get("/sessions")
def list_sessions(limit: int = Query(50, ge=1, le=500)):
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM test_sessions WHERE status <> 'CANCELLED' ORDER BY id DESC LIMIT %s",
                (limit,)
            )
            return cursor.fetchall()
    finally:
        connection.close()


# =====================================================
# Sajikan dashboard dari server yang sama (buka http://IP-LAPTOP:8000/dashboard/)
# Taruh index.html di folder "frontend" sejajar dengan main.py.
# =====================================================
_frontend_dir = Path(__file__).resolve().parent / "frontend"
if _frontend_dir.is_dir():
    app.mount("/dashboard", StaticFiles(directory=_frontend_dir, html=True), name="dashboard")
