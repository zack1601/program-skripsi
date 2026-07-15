"""
reset_cache.py — Hapus input_cache lama dari SQLite agar sync ulang bersih.
Jalankan di VPS: python3 reset_cache.py
"""
import sqlite3
import os

DB_PATH = "noc_database.db"

if not os.path.exists(DB_PATH):
    print("Database tidak ditemukan:", DB_PATH)
else:
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("DROP TABLE IF EXISTS input_cache")
        conn.commit()
        print("✓ Tabel input_cache berhasil dihapus.")
        print("  Silakan buka dashboard → klik 'SYNC GOOGLE SHEETS' → klik 'START SCAN'")
    except Exception as e:
        print("Error:", e)
    finally:
        conn.close()
