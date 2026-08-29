import psycopg2
import streamlit as st
from threading import RLock
from time import sleep
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

    def close(self):
        with self.lock:
            if self.connection is not None:
                try:
                    self.connection.close()
                except Exception:
                    pass
                self.connection = None

    def _connect(self):
        last_error = None
        for attempt in range(3):
            try:
                return psycopg2.connect(
                    self.url,
                    connect_timeout=10,
                    application_name="fuel_inventory_control",
                    keepalives=1,
                    keepalives_idle=30,
                    keepalives_interval=10,
                    keepalives_count=5,
                )
            except psycopg2.OperationalError as error:
                last_error = error
                if attempt < 2:
                    sleep(1.5 * (attempt + 1))
        raise last_error


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
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT UNIQUE NOT NULL,
            unit TEXT NOT NULL DEFAULT 'L', active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS company_profile (
            id SERIAL PRIMARY KEY, company_name TEXT NOT NULL DEFAULT 'FILLIT',
            application_name TEXT NOT NULL DEFAULT 'Fuel Inventory Control',
            tagline TEXT, primary_color TEXT DEFAULT '#8C1C1C',
            secondary_color TEXT DEFAULT '#171717', accent_color TEXT DEFAULT '#05AF52',
            currency TEXT DEFAULT 'AED', timezone TEXT DEFAULT 'Asia/Dubai',
            date_format TEXT DEFAULT 'DD MMM YYYY', volume_unit TEXT DEFAULT 'L',
            logo_path TEXT DEFAULT 'assets/fillit-logo.png', report_footer TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_by TEXT
        )""")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS module_settings (
            module_key TEXT PRIMARY KEY, display_name TEXT NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT TRUE, sort_order INTEGER NOT NULL DEFAULT 0
        )""")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_events (
            id BIGSERIAL PRIMARY KEY, occurred_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            user_id INTEGER, username TEXT NOT NULL DEFAULT 'System', user_role TEXT,
            action TEXT NOT NULL, module TEXT NOT NULL, entity_type TEXT, entity_id TEXT,
            description TEXT, old_values JSONB, new_values JSONB,
            status TEXT NOT NULL DEFAULT 'SUCCESS', severity TEXT NOT NULL DEFAULT 'INFO',
            business_location TEXT, session_reference TEXT
        )""")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_reconciliations (
            id BIGSERIAL PRIMARY KEY,
            truck_id INTEGER NOT NULL REFERENCES trucks(id),
            reading_at TIMESTAMPTZ NOT NULL,
            system_quantity REAL NOT NULL,
            physical_quantity REAL NOT NULL CHECK(physical_quantity >= 0),
            variance_quantity REAL NOT NULL,
            variance_percent REAL NOT NULL DEFAULT 0,
            reason TEXT NOT NULL,
            reference TEXT,
            notes TEXT,
            status TEXT NOT NULL DEFAULT 'PENDING'
                CHECK(status IN ('PENDING','APPROVED','REJECTED','POSTED','CANCELLED')),
            recorded_by TEXT NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            reviewed_by TEXT,
            reviewed_at TIMESTAMPTZ,
            review_comment TEXT,
            adjustment_transaction_id INTEGER REFERENCES transactions(id),
            posted_at TIMESTAMPTZ,
            UNIQUE(adjustment_transaction_id)
        )""")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS transaction_change_requests (
            id BIGSERIAL PRIMARY KEY,
            transaction_id INTEGER NOT NULL REFERENCES transactions(id),
            partner_transaction_id INTEGER REFERENCES transactions(id),
            request_type TEXT NOT NULL CHECK(request_type IN ('CORRECTION','REVERSAL')),
            reason TEXT NOT NULL,
            proposed_date TEXT,
            proposed_liters REAL,
            proposed_supplier_id INTEGER REFERENCES suppliers(id),
            status TEXT NOT NULL DEFAULT 'PENDING'
                CHECK(status IN ('PENDING','APPROVED','REJECTED','POSTED','CANCELLED')),
            requested_by TEXT NOT NULL,
            requested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            reviewed_by TEXT,
            reviewed_at TIMESTAMPTZ,
            review_comment TEXT,
            reversal_transaction_id INTEGER REFERENCES transactions(id),
            replacement_transaction_id INTEGER REFERENCES transactions(id)
        )""")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS depots (
            id SERIAL PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
            address TEXT, emirate TEXT, manager_name TEXT, phone TEXT,
            latitude REAL, longitude REAL, status TEXT NOT NULL DEFAULT 'ACTIVE',
            notes TEXT, created_by TEXT, created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )""")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS storage_tanks (
            id SERIAL PRIMARY KEY, depot_id INTEGER NOT NULL REFERENCES depots(id),
            code TEXT NOT NULL, name TEXT NOT NULL, product_id INTEGER NOT NULL REFERENCES products(id),
            capacity_liters REAL NOT NULL CHECK(capacity_liters > 0),
            safe_capacity_liters REAL NOT NULL CHECK(safe_capacity_liters > 0),
            minimum_stock_liters REAL NOT NULL DEFAULT 0,
            reorder_level_liters REAL NOT NULL DEFAULT 0,
            dead_stock_liters REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'AVAILABLE', notes TEXT,
            created_by TEXT, created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(depot_id, code)
        )""")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS tank_transactions (
            id BIGSERIAL PRIMARY KEY, tank_id INTEGER NOT NULL REFERENCES storage_tanks(id),
            movement_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            liters REAL NOT NULL CHECK(liters > 0), type TEXT NOT NULL CHECK(type IN ('IN','OUT')),
            movement_category TEXT NOT NULL DEFAULT 'STANDARD', product_id INTEGER REFERENCES products(id),
            partner_tank_transaction_id BIGINT, truck_transaction_id INTEGER,
            reference TEXT, notes TEXT, created_by TEXT,
            record_status TEXT NOT NULL DEFAULT 'POSTED', created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )""")

        cursor.execute("""
            INSERT INTO company_profile
            (company_name, application_name, tagline, report_footer)
            SELECT 'FILLIT', 'Fuel Inventory Control',
                   'Inventory intelligence for fuel operations',
                   'Confidential inventory report'
            WHERE NOT EXISTS (SELECT 1 FROM company_profile)
        """)
        modules = (
            ('dashboard','Command Centre',True,10), ('transactions','Fuel Operations',True,20),
            ('fleet','Fleet Inventory',True,30), ('ledger','Truck Ledger',True,40),
            ('imports','Integration Inbox',True,50), ('approvals','Approvals',True,60),
            ('reports','Report Centre',True,70), ('audit','Audit Centre',True,80),
            ('settings','Configuration',True,90), ('users','User Access',True,100),
            ('storage','Depots & Tanks',False,110), ('procurement','Procurement',False,120),
            ('forecasting','Forecasting',False,130)
        )
        cursor.executemany("""
            INSERT INTO module_settings (module_key, display_name, enabled, sort_order)
            VALUES (%s,%s,%s,%s) ON CONFLICT (module_key) DO NOTHING
        """, modules)

        # Compatibility migrations for databases created by earlier FILLIT versions.
        migrations = (
            "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS supplier TEXT",
            "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS supplier_id INTEGER",
            "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS transfer_partner_id INTEGER",
            "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS created_by TEXT",
            "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS ticket_number TEXT",
            "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS file_id INTEGER",
            "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS product_id INTEGER REFERENCES products(id)",
            "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS movement_category TEXT DEFAULT 'STANDARD'",
            "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP",
            "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS record_status TEXT DEFAULT 'POSTED'",
            "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS reversal_of_transaction_id INTEGER",
            "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS reversed_by_transaction_id INTEGER",
            "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS correction_of_transaction_id INTEGER",
            "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS change_reason TEXT",
            "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS tank_transaction_id BIGINT",
            "ALTER TABLE trucks ADD COLUMN IF NOT EXISTS product_id INTEGER REFERENCES products(id)",
            "ALTER TABLE trucks ADD COLUMN IF NOT EXISTS capacity_liters REAL",
            "ALTER TABLE trucks ADD COLUMN IF NOT EXISTS minimum_stock_liters REAL",
            "ALTER TABLE trucks ADD COLUMN IF NOT EXISTS reorder_level_liters REAL",
            "ALTER TABLE trucks ADD COLUMN IF NOT EXISTS operational_status TEXT DEFAULT 'ACTIVE'",
            "ALTER TABLE trucks ADD COLUMN IF NOT EXISTS notes TEXT",
            "ALTER TABLE trucks ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE",
        )
        for statement in migrations:
            cursor.execute(statement)

        cursor.execute("INSERT INTO suppliers (name) VALUES ('Default Supplier') ON CONFLICT (name) DO NOTHING")
        cursor.execute("INSERT INTO products (code, name, unit) VALUES ('DSL', 'Diesel', 'L') ON CONFLICT (code) DO NOTHING")
        cursor.execute("UPDATE trucks SET product_id=(SELECT id FROM products WHERE code='DSL') WHERE product_id IS NULL")
        cursor.execute("UPDATE transactions tx SET product_id=tr.product_id FROM trucks tr WHERE tx.truck_id=tr.id AND tx.product_id IS NULL")
        cursor.execute("""
            INSERT INTO settings (cost_per_liter, selling_price_per_liter, minimum_stock_level)
            SELECT 3.0, 4.0, 500.0 WHERE NOT EXISTS (SELECT 1 FROM settings)
        """)

        # These indexes make the dashboard, ledger, history, and audit pages scale better.
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_truck_date ON transactions(truck_id, date DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_type_date ON transactions(type, date DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_file_id ON transactions(file_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_product_date ON transactions(product_id, date DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trucks_status ON trucks(operational_status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_id_desc ON audit_log(id DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_refill_status ON refill_requests(status, id DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_login_sessions_token ON login_sessions(token_hash, expires_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_time ON audit_events(occurred_at DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_entity ON audit_events(entity_type, entity_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_user ON audit_events(username, occurred_at DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reconciliation_status ON stock_reconciliations(status, recorded_at DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reconciliation_truck ON stock_reconciliations(truck_id, reading_at DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_change_requests_status ON transaction_change_requests(status, requested_at DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_record_status ON transactions(record_status, id DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tanks_depot ON storage_tanks(depot_id, status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tank_transactions_tank_time ON tank_transactions(tank_id, movement_at DESC)")
        tank_migrations = (
            "ALTER TABLE tank_transactions ADD COLUMN IF NOT EXISTS supplier_id INTEGER REFERENCES suppliers(id)",
            "ALTER TABLE tank_transactions ADD COLUMN IF NOT EXISTS transport_method TEXT",
            "ALTER TABLE tank_transactions ADD COLUMN IF NOT EXISTS vehicle_number TEXT",
            "ALTER TABLE tank_transactions ADD COLUMN IF NOT EXISTS driver_name TEXT",
            "ALTER TABLE tank_transactions ADD COLUMN IF NOT EXISTS ordered_liters REAL",
            "ALTER TABLE tank_transactions ADD COLUMN IF NOT EXISTS dispatched_liters REAL",
            "ALTER TABLE tank_transactions ADD COLUMN IF NOT EXISTS accepted_liters REAL",
            "ALTER TABLE tank_transactions ADD COLUMN IF NOT EXISTS variance_liters REAL",
        )
        for statement in tank_migrations:
            cursor.execute(statement)

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
