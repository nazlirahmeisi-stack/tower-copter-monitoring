import json
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, model_validator
from database import get_connection
from mqtt_client import connect_mqtt, publish_message

app = FastAPI(title="Tower Copter Monitoring System")

# Enable CORS agar Web Dashboard bisa mengakses API tanpa diblokir browser
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Hubungkan MQTT Client saat server FastAPI dinyalakan
connect_mqtt()

class ControlCommand(BaseModel):
    command: str
    setpoint: float | None = None

    @model_validator(mode="after")
    def validate_command(self):
        self.command = self.command.upper()
        if self.command not in ["START", "STOP", "SETPOINT"]:
            raise ValueError("command harus START, STOP, atau SETPOINT")
        if self.command == "SETPOINT" and self.setpoint is None:
            raise ValueError("setpoint wajib diisi untuk command SETPOINT")
        if self.command in ["START", "STOP"] and self.setpoint is not None:
            raise ValueError("setpoint tidak diperlukan untuk command START atau STOP")
        return self

class SessionStart(BaseModel):
    method: Literal["ZN", "CPO", "SO", "GJO", "MANUAL"]
    kp: float | None = None
    ki: float | None = None
    kd: float | None = None

# 1. Sajikan index.html langsung saat membuka http://localhost:8000 atau http://192.168.1.17:8000
@app.get("/")
def serve_dashboard():
    index_path = Path(__file__).resolve().parent / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"message": "File index.html tidak ditemukan di root folder"}

@app.get("/telemetry")
def get_telemetry():
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT * FROM telemetry ORDER BY id DESC")
        data = cursor.fetchall()
        return [dict(row) for row in data]
    finally:
        connection.close()

@app.get("/telemetry/latest")
def get_latest_telemetry():
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT * FROM telemetry ORDER BY id DESC LIMIT 1")
        data = cursor.fetchone()
        return dict(data) if data else {}
    finally:
        connection.close()

@app.get("/control/latest")
def get_latest_control():
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT * FROM control_logs ORDER BY id DESC LIMIT 1")
        data = cursor.fetchone()
        return dict(data) if data else {}
    finally:
        connection.close()

@app.get("/stats")
def get_stats():
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT COUNT(*) AS n, MAX(timestamp) AS last_ts FROM telemetry")
        tele = cursor.fetchone()
        
        cursor.execute("SELECT COUNT(*) AS n FROM control_logs")
        cmd = cursor.fetchone()
        
        cursor.execute("SELECT COUNT(*) AS n FROM control_logs WHERE status = 'ACKNOWLEDGED'")
        acked = cursor.fetchone()
        
        try:
            cursor.execute("SELECT COUNT(*) AS n FROM test_sessions WHERE status = 'COMPLETED'")
            sessions = cursor.fetchone()["n"]
        except Exception:
            sessions = 0

        return {
            "telemetry": tele["n"] if tele else 0,
            "last_telemetry": tele["last_ts"] if tele else None,
            "commands": cmd["n"] if cmd else 0,
            "commands_acked": acked["n"] if acked else 0,
            "sessions_completed": sessions,
        }
    finally:
        connection.close()

@app.post("/control")
def send_control(control: ControlCommand):
    connection = get_connection()
    try:
        cursor = connection.cursor()
        # Sintaks SQLite menggunakan datetime('now') dan tanda tanya (?)
        sql = """
            INSERT INTO control_logs (timestamp, command, setpoint, status)
            VALUES (datetime('now'), ?, ?, ?)
        """
        cursor.execute(sql, (control.command, control.setpoint, "SENT"))
        connection.commit()
        command_id = cursor.lastrowid

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

        message = json.dumps(payload)
        publish_message(topic, message)

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

@app.post("/sessions/start")
def start_session(body: SessionStart):
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT id FROM test_sessions WHERE status IN ('WAITING','RUNNING') LIMIT 1")
        if cursor.fetchone():
            raise HTTPException(
                status_code=409,
                detail="Masih ada sesi aktif. Batalkan atau tunggu sampai selesai."
            )

        cursor.execute("SELECT id, altitude, setpoint FROM telemetry ORDER BY id DESC LIMIT 1")
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
            VALUES (?, ?, ?, ?, 'WAITING', datetime('now'), ?, ?, ?)
            """,
            (body.method, body.kp, body.ki, body.kd,
             latest["id"], latest["altitude"], latest["setpoint"])
        )
        connection.commit()
        session_id = cursor.lastrowid
        return {"id": session_id, "method": body.method, "status": "WAITING"}
    finally:
        connection.close()

@app.post("/sessions/{session_id}/cancel")
def cancel_session(session_id: int):
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            UPDATE test_sessions
            SET status='CANCELLED', ended_at=datetime('now'), updated_at=datetime('now')
            WHERE id=? AND status IN ('WAITING','RUNNING')
            """,
            (session_id,)
        )
        connection.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Sesi aktif tidak ditemukan.")
        return {"id": session_id, "status": "CANCELLED"}
    finally:
        connection.close()

@app.get("/sessions/current")
def get_current_session():
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT * FROM test_sessions WHERE status IN ('WAITING','RUNNING') ORDER BY id DESC LIMIT 1")
        data = cursor.fetchone()
        if data is None:
            cursor.execute("SELECT * FROM test_sessions WHERE status='COMPLETED' ORDER BY id DESC LIMIT 1")
            data = cursor.fetchone()
        return dict(data) if data else {}
    finally:
        connection.close()

@app.get("/sessions")
def list_sessions(limit: int = Query(50, ge=1, le=500)):
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT * FROM test_sessions WHERE status <> 'CANCELLED' ORDER BY id DESC LIMIT ?", (limit,))
        data = cursor.fetchall()
        return [dict(row) for row in data]
    finally:
        connection.close()
