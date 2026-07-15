import os
import psycopg2
import streamlit as st

def get_connection():
    # Streamlit Cloud automatically reads from the secrets we saved in Step 2
    conn_url = st.secrets["connections"]["postgresql"]["url"]
    return psycopg2.connect(conn_url)

def init_db(conn):
    cursor = conn.cursor()

    # PostgreSQL compatible schema (using SERIAL primary keys)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS trucks (
        id SERIAL PRIMARY KEY,
        emirate TEXT NOT NULL,
        plate_code TEXT NOT NULL,
        plate_number TEXT NOT NULL,
        selling_price_per_liter REAL DEFAULT NULL,
        UNIQUE(emirate, plate_code, plate_number)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        id SERIAL PRIMARY KEY,
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
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE,
        password TEXT,
        role TEXT CHECK(role IN ('ADMIN','OPERATOR'))
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_log (
        id SERIAL PRIMARY KEY,
        "user" TEXT,
        action TEXT,
        timestamp TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        id SERIAL PRIMARY KEY,
        cost_per_liter REAL,
        selling_price_per_liter REAL,
        minimum_stock_level REAL
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS refill_requests (
        id SERIAL PRIMARY KEY,
        truck_id INTEGER,
        requested_liters REAL,
        status TEXT CHECK(status IN ('PENDING','APPROVED','REJECTED')) DEFAULT 'PENDING',
        requested_by TEXT,
        timestamp TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS uploaded_files (
        id SERIAL PRIMARY KEY,
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
