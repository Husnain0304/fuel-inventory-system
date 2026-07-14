import sqlite3

def get_connection():
    return sqlite3.connect("fuel_inventory.db", check_same_thread=False)

def init_db(conn):
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS trucks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        emirate TEXT NOT NULL,
        plate_code TEXT NOT NULL,
        plate_number TEXT NOT NULL,
        selling_price_per_liter REAL DEFAULT NULL,
        UNIQUE(emirate, plate_code, plate_number)
    )
    """)

    # We only keep the correct transactions table schema here:
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        truck_id INTEGER,
        date TEXT,
        liters REAL,
        type TEXT CHECK(type IN ('IN','OUT')),
        row_hash TEXT UNIQUE,
        FOREIGN KEY(truck_id) REFERENCES trucks(id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        role TEXT CHECK(role IN ('ADMIN','OPERATOR'))
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user TEXT,
        action TEXT,
        timestamp TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cost_per_liter REAL,
        selling_price_per_liter REAL,
        minimum_stock_level REAL
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS refill_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        truck_id INTEGER,
        requested_liters REAL,
        status TEXT CHECK(status IN ('PENDING','APPROVED','REJECTED')) DEFAULT 'PENDING',
        requested_by TEXT,
        timestamp TEXT
    )
    """)

    # Create the uploaded_files table to track duplicate uploads
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS uploaded_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_name TEXT UNIQUE,
        uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("SELECT * FROM settings")
    if not cursor.fetchone():
        cursor.execute("""
        INSERT INTO settings (cost_per_liter, selling_price_per_liter, minimum_stock_level)
        VALUES (3.0, 4.0, 500.0)
        """)

    conn.commit()