import sqlite3
import pandas as pd
import os
import datetime

# Timezone Jakarta (WIB = UTC+7)
_WIB = datetime.timezone(datetime.timedelta(hours=7))

def _now_wib() -> str:
    """Return timestamp saat ini dalam format WIB (YYYY-MM-DD HH:MM:SS)."""
    return datetime.datetime.now(_WIB).strftime("%Y-%m-%d %H:%M:%S")

DB_PATH = "noc_database.db"

# Kata kunci reply dari teknisi lapangan
FIELD_KEYWORDS = {
    "progress" : "In Progress",   # Sedang ditangani
    "done"     : "Resolved",      # Gangguan selesai diperbaiki
    "selesai"  : "Resolved",      # Alias "done"
    "cancel"   : "Cancelled",     # Teknisi tidak bisa visit
    "batal"    : "Cancelled",     # Alias "cancel"
}

def get_connection():
    """Create and return a database connection."""
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    """
    Initialize the database — buat tabel alarm_sent jika belum ada.
    Dipanggil sekali saat aplikasi pertama kali start.
    """
    conn = get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alarm_sent (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id  INTEGER UNIQUE,          -- ID pesan Telegram
                sn          TEXT,                    -- Serial Number ONT
                olt         TEXT,                    -- Nama OLT
                pelanggan   TEXT,                    -- Nama/ID Pelanggan
                category    TEXT,                    -- LOS / BadRx
                sent_at     TEXT,                    -- Waktu alarm dikirim
                status      TEXT DEFAULT 'Sent',     -- Sent / In Progress / Resolved / Cancelled
                technician  TEXT DEFAULT '',         -- Username Telegram teknisi
                reply_text  TEXT DEFAULT '',         -- Isi reply teknisi
                reply_at    TEXT DEFAULT ''          -- Waktu reply masuk
            )
        """)
        conn.commit()
    finally:
        conn.close()

def save_scan_results(df):
    """
    Save the final dataframe to two SQLite tables:
    1. latest_scan: Overwritten every time (acts like the old CSV cache)
    2. scan_history: Appended with a timestamp for trending
    """
    if df.empty:
        return
        
    conn = get_connection()
    try:
        # Save to latest_scan (overwrite)
        df.to_sql('latest_scan', conn, if_exists='replace', index=False)
        
        # Prepare for history (add timestamp)
        df_history = df.copy()
        df_history['scan_timestamp'] = _now_wib()
        
        # Append to history
        df_history.to_sql('scan_history', conn, if_exists='append', index=False)
    except Exception as e:
        print(f"Error saving to database: {e}")
    finally:
        conn.close()

def load_latest_scan():
    """Load the most recent scan data from the database."""
    if not os.path.exists(DB_PATH):
        return pd.DataFrame()
        
    conn = get_connection()
    try:
        df = pd.read_sql_query("SELECT * FROM latest_scan", conn)
        return df
    except Exception as e:
        print(f"Error loading from database: {e}")
        return pd.DataFrame()
    finally:
        conn.close()

def get_historical_trend():
    """
    Get a summary of scan history for the line chart.
    Groups by scan_timestamp and Category to count occurrences.
    """
    if not os.path.exists(DB_PATH):
        return pd.DataFrame()
        
    conn = get_connection()
    try:
        # Simple query to get counts of each category per scan session
        query = """
        SELECT 
            scan_timestamp, 
            Category, 
            COUNT(*) as count 
        FROM scan_history 
        GROUP BY scan_timestamp, Category
        ORDER BY scan_timestamp ASC
        """
        df = pd.read_sql_query(query, conn)
        return df
    except Exception as e:
        print(f"Error loading historical trend: {e}")
        return pd.DataFrame()
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# FIELD TECHNICIAN UPDATE FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def save_alarm_sent(message_id: int, record: dict):
    """
    Simpan alarm yang sudah berhasil dikirim ke Telegram ke tabel alarm_sent.
    Dipanggil langsung setelah send_telegram_alarm() berhasil.

    Parameters
    ----------
    message_id : int   ID pesan dari response Telegram API
    record     : dict  Data alarm (SN, OLT, Pelanggan, Category, dst.)
    """
    conn = get_connection()
    try:
        conn.execute("""
            INSERT OR IGNORE INTO alarm_sent
                (message_id, sn, olt, pelanggan, category, sent_at, status)
            VALUES (?, ?, ?, ?, ?, ?, 'Sent')
        """, (
            message_id,
            str(record.get('Serial Number', record.get('sn', ''))).strip().upper(),
            str(record.get('OLT', '')).strip(),
            str(record.get('Nama/ID Pelanggan', '')).strip(),
            str(record.get('Category', '')).strip(),
            _now_wib(),
        ))
        conn.commit()
    except Exception as e:
        print(f"[DB] Error saving alarm_sent: {e}")
    finally:
        conn.close()


def update_alarm_status(
    message_id: int,
    status: str,
    technician: str = "",
    reply_text: str = "",
    reply_at: str = "",
):
    """
    Update status alarm berdasarkan reply teknisi.
    Dipanggil oleh telegram_listener saat mendeteksi reply ke message_id.

    Parameters
    ----------
    message_id  : int  ID pesan Telegram yang di-reply
    status      : str  'In Progress' | 'Resolved' | 'Cancelled'
    technician  : str  Username Telegram teknisi (mis. @budi_tech)
    reply_text  : str  Isi teks reply dari teknisi
    reply_at    : str  Waktu reply (format YYYY-MM-DD HH:MM:SS)
    """
    if not reply_at:
        reply_at = _now_wib()
    conn = get_connection()
    try:
        conn.execute("""
            UPDATE alarm_sent
            SET status     = ?,
                technician = ?,
                reply_text = ?,
                reply_at   = ?
            WHERE message_id = ?
        """, (status, technician, reply_text, reply_at, message_id))
        conn.commit()
    except Exception as e:
        print(f"[DB] Error updating alarm_status: {e}")
    finally:
        conn.close()


def get_alarm_updates(limit: int = 50) -> pd.DataFrame:
    """
    Ambil daftar alarm yang AKTIF (Sent / In Progress) untuk panel dashboard.
    Alarm yang sudah Resolved atau Cancelled TIDAK ditampilkan (dianggap selesai).

    Returns DataFrame berkolom:
        sn, olt, pelanggan, category, sent_at,
        status, technician, reply_text, reply_at
    """
    if not os.path.exists(DB_PATH):
        return pd.DataFrame()
    conn = get_connection()
    try:
        df = pd.read_sql_query(
            """
            SELECT
                message_id, sn, olt, pelanggan, category,
                sent_at, status, technician, reply_text, reply_at
            FROM alarm_sent
            WHERE status IN ('Sent', 'In Progress')
            ORDER BY sent_at DESC
            LIMIT ?
            """,
            conn,
            params=(limit,),
        )
        return df
    except Exception as e:
        print(f"[DB] Error loading alarm_updates: {e}")
        return pd.DataFrame()
    finally:
        conn.close()


def update_alarm_status_by_sn(sn: str, status: str, technician: str = "NOC Dashboard"):
    """
    Update status alarm berdasarkan Serial Number (SN) — dipakai oleh tombol
    ✅ Resolved / ❌ Cancel pada dashboard NOC (bukan dari reply Telegram).

    Parameters
    ----------
    sn         : str  Serial Number ONT
    status     : str  'Resolved' | 'Cancelled'
    technician : str  Identitas yang melakukan update (default: 'NOC Dashboard')
    """
    conn = get_connection()
    try:
        conn.execute("""
            UPDATE alarm_sent
            SET status     = ?,
                technician = ?,
                reply_text = ?,
                reply_at   = ?
            WHERE sn = ? AND status IN ('Sent', 'In Progress')
        """, (status, technician, f"Updated via Dashboard → {status}", _now_wib(), sn.strip().upper()))
        conn.commit()
    except Exception as e:
        print(f"[DB] Error updating alarm_status by SN: {e}")
    finally:
        conn.close()


def get_all_alarm_history() -> pd.DataFrame:
    """
    Ambil SEMUA riwayat alarm (Sent, In Progress, Resolved, Cancelled) untuk
    diekspor ke sheet 'Status Gangguan' pada laporan Excel.
    """
    if not os.path.exists(DB_PATH):
        return pd.DataFrame()
    conn = get_connection()
    try:
        return pd.read_sql_query(
            """
            SELECT
                sn          AS "Serial Number",
                olt         AS "OLT",
                pelanggan   AS "Pelanggan",
                category    AS "Category",
                status      AS "Status Penanganan",
                technician  AS "Teknisi",
                reply_text  AS "Reply Teknisi",
                sent_at     AS "Waktu Alarm Dikirim",
                reply_at    AS "Waktu Update Status"
            FROM alarm_sent
            ORDER BY sent_at DESC
            """,
            conn,
        )
    except Exception as e:
        print(f"[DB] Error loading alarm history: {e}")
        return pd.DataFrame()
    finally:
        conn.close()


def get_last_telegram_update_id() -> int:
    """
    Simpan dan baca offset 'update_id' terakhir yang sudah diproses
    agar getUpdates tidak memproses pesan yang sama dua kali.
    Disimpan di tabel kecil 'meta'.
    """
    conn = get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'last_update_id'"
        ).fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0
    finally:
        conn.close()


def set_last_telegram_update_id(update_id: int):
    """Perbarui offset update_id terakhir di SQLite."""
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO meta (key, value) VALUES ('last_update_id', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (str(update_id),))
        conn.commit()
    except Exception as e:
        print(f"[DB] Error saving last_update_id: {e}")
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# INPUT CACHE  —  Google Sheets → SQLite  (Master Data Caching)
# ─────────────────────────────────────────────────────────────────────────────

def cache_input_from_gsheets(df: pd.DataFrame):
    """
    Simpan data master input dari Google Sheets ke tabel 'input_cache' di SQLite.
    Tabel di-REPLACE setiap sinkronisasi agar selalu mencerminkan data terbaru.
    Waktu sinkronisasi dicatat di tabel meta dengan key 'last_sync'.
    """
    if df is None or df.empty:
        return
    conn = get_connection()
    try:
        df.to_sql('input_cache', conn, if_exists='replace', index=False)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)
        """)
        conn.execute("""
            INSERT INTO meta (key, value) VALUES ('last_sync', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (_now_wib(),))
        conn.commit()
    except Exception as e:
        print(f"[DB] Error caching input_cache: {e}")
    finally:
        conn.close()


def load_input_cache() -> pd.DataFrame:
    """
    Baca data master input (daftar pelanggan & OLT) dari SQLite cache.
    Digunakan sebagai sumber data utama saat START SCAN — tanpa koneksi Google Sheets.
    """
    if not os.path.exists(DB_PATH):
        return pd.DataFrame()
    conn = get_connection()
    try:
        return pd.read_sql_query("SELECT * FROM input_cache", conn)
    except Exception:
        return pd.DataFrame()
    finally:
        conn.close()


def get_last_sync_time() -> str:
    """Kembalikan string waktu terakhir kali Google Sheets di-sync ke SQLite."""
    if not os.path.exists(DB_PATH):
        return "Belum pernah"
    conn = get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)
        """)
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'last_sync'"
        ).fetchone()
        return row[0] if row else "Belum pernah"
    except Exception:
        return "Belum pernah"
    finally:
        conn.close()


def load_scan_history_full() -> pd.DataFrame:
    """
    Ambil seluruh baris riwayat scan (bukan agregasi) untuk ekspor laporan Excel.
    """
    if not os.path.exists(DB_PATH):
        return pd.DataFrame()
    conn = get_connection()
    try:
        return pd.read_sql_query(
            "SELECT * FROM scan_history ORDER BY scan_timestamp DESC", conn
        )
    except Exception:
        return pd.DataFrame()
    finally:
        conn.close()
