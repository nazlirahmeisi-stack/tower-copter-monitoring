import sqlite3

def get_connection():
    connection = sqlite3.connect("tower_copter.db", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # 1. Tabel Telemetry (Data Real-time)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS telemetry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            altitude REAL,
            setpoint REAL,
            error REAL,
            rpm REAL,
            pwm REAL,
            current REAL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 2. Tabel Test Sessions (Hasil Pengujian & Analisis Respon)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS test_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            method TEXT NOT NULL,
            kp REAL DEFAULT NULL,
            ki REAL DEFAULT NULL,
            kd REAL DEFAULT NULL,
            status TEXT NOT NULL DEFAULT 'WAITING',
            started_at DATETIME DEFAULT NULL,
            ended_at DATETIME DEFAULT NULL,
            start_telemetry_id INTEGER DEFAULT NULL,
            y0 REAL DEFAULT NULL,
            setpoint REAL DEFAULT NULL,
            samples INTEGER DEFAULT 0,
            rise_time REAL DEFAULT NULL,
            overshoot REAL DEFAULT NULL,
            settling_time REAL DEFAULT NULL,
            sse REAL DEFAULT NULL,
            iae REAL DEFAULT NULL,
            ise REAL DEFAULT NULL,
            itae REAL DEFAULT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()
    conn.close()

# Otomatis buat kedua tabel saat database.py dipanggil
init_db()