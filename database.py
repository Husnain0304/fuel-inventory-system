import psycopg2
import streamlit as st
from threading import RLock
from security import hash_password


@st.cache_resource(show_spinner=False)
def _connection_manager():
    return ConnectionManager(st.secrets["connections"]["postgresql"]["url"])


class ConnectionManager:
    def __init__(self, url):
        self.url = url
        self.connection = None
        self.lock = RLock()

    def get(self):
        with self.lock:
            if self.connection is None or self.connection.closed:
                self.connection = self._connect()
                return self.connection
            try:
                with self.connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    cursor.fetchone()
                return self.connection
            except (psycopg2.InterfaceError, psycopg2.OperationalError):
                try:
                    self.connection.close()
                except Exception:
                    pass
                self.connection = self._connect()
                return self.connection
            except psycopg2.Error:
                # Recover from an earlier failed transaction before reuse.
                self.connection.rollback()
                return self.connection

    def _connect(self):
        return psycopg2.connect(
            self.url,
            connect_timeout=10,
            application_name="fillit",
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=5,
        )


def get_connection():
    return _connection_manager().get()


@st.cache_resource(show_spinner="Preparing FILLIT…")
def init_db(_conn) -> bool:
    cursor = _conn.cursor()
    try:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS trucks (
            id SERIAL PRIMARY KEY,
            emirate TEXT NOT NULL,
            plate_code TEXT NOT NULL,
            plate_number TEXT NOT NULL,
            selling_price_per_liter REAL DEFAULT NULL,
            UNIQUE(emirate, plate_code, plate_number)
        )""")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id SERIAL PRIMARY KEY,
            truck_id INTEGER REFERENCES trucks(id),
            date TEXT NOT NULL,
            liters REAL NOT NULL CHECK(liters > 0),
            type TEXT NOT NULL CHECK(type IN ('IN','OUT')),
            row_hash TEXT UNIQUE,
            supplier TEXT,
            supplier_id INTEGER,
            transfer_partner_id INTEGER,
            created_by TEXT,
            ticket_number TEXT,
            file_id INTEGER
        )""")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('ADMIN','OPERATOR'))
        )""")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS login_sessions (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash TEXT UNIQUE NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            revoked BOOLEAN DEFAULT FALSE
        )""")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id SERIAL PRIMARY KEY, "user" TEXT, action TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            id SERIAL PRIMARY KEY, cost_per_liter REAL,
            selling_price_per_liter REAL, minimum_stock_level REAL
        )""")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS refill_requests (
            id SERIAL PRIMARY KEY, truck_id INTEGER REFERENCES trucks(id),
            requested_liters REAL CHECK(requested_liters > 0),
            status TEXT CHECK(status IN ('PENDING','APPROVED','REJECTED')) DEFAULT 'PENDING',
            requested_by TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS uploaded_files (
            id SERIAL PRIMARY KEY, file_name TEXT UNIQUE,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        cursor.execute("CREATE TABLE IF NOT EXISTS suppliers (id SERIAL PRIMARY KEY, name TEXT UNIQUE NOT NULL)")

        # Compatibility migrations for databases created by earlier FILLIT versions.
        migrations = (
            "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS supplier TEXT",
            "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS supplier_id INTEGER",
            "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS transfer_partner_id INTEGER",
            "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS created_by TEXT",
            "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS ticket_number TEXT",
            "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS file_id INTEGER",
        )
        for statement in migrations:
            cursor.execute(statement)

        cursor.execute("INSERT INTO suppliers (name) VALUES ('Default Supplier') ON CONFLICT (name) DO NOTHING")
        cursor.execute("""
            INSERT INTO settings (cost_per_liter, selling_price_per_liter, minimum_stock_level)
            SELECT 3.0, 4.0, 500.0 WHERE NOT EXISTS (SELECT 1 FROM settings)
        """)

        # These indexes make the dashboard, ledger, history, and audit pages scale better.
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_truck_date ON transactions(truck_id, date DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_type_date ON transactions(type, date DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_file_id ON transactions(file_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_id_desc ON audit_log(id DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_refill_status ON refill_requests(status, id DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_login_sessions_token ON login_sessions(token_hash, expires_at)")

        cursor.execute("SELECT COUNT(*) FROM users")
        if cursor.fetchone()[0] == 0:
            bootstrap = st.secrets.get("bootstrap", {})
            username = str(bootstrap.get("username", "")).strip()
            password = str(bootstrap.get("password", ""))
            if username and password:
                cursor.execute(
                    "INSERT INTO users (username, password, role) VALUES (%s, %s, 'ADMIN')",
                    (username, hash_password(password)),
                )
        _conn.commit()
        return True
    except Exception:
        _conn.rollback()
        raise
