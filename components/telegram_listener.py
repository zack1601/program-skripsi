"""
components/telegram_listener.py
================================
Background thread yang mem-polling Telegram Bot API (getUpdates) setiap
30 detik untuk mendeteksi reply dari teknisi lapangan.

Cara kerja:
  1. Ambil semua update baru dari Telegram (sejak update_id terakhir)
  2. Filter update yang berupa reply (punya reply_to_message.message_id)
  3. Cek apakah teks reply mengandung kata kunci:
       - "progress" → status "In Progress"   (sedang ditangani)
       - "done" / "selesai" → "Resolved"     (gangguan selesai)
       - "cancel" / "batal" → "Cancelled"    (tidak bisa visit)
  4. Update tabel alarm_sent di SQLite
  5. Simpan update_id terakhir agar tidak proses dua kali

Thread ini berjalan sebagai daemon — akan berhenti otomatis
ketika proses Streamlit berhenti.
"""

import threading
import time
import requests
import datetime

from components.database import (
    FIELD_KEYWORDS,
    update_alarm_status,
    get_last_telegram_update_id,
    set_last_telegram_update_id,
)

# ─────────────────────────────────────────────────────────────────────────────
# Konfigurasi Bot (sama dengan telegram.py)
# ─────────────────────────────────────────────────────────────────────────────
TOKEN   = "8789834499:AAEeqHkPjSzlkr4egB0sMPvsMyoDUBkG2OU"
POLL_INTERVAL = 30   # detik antar polling

_UPDATES_URL = f"https://api.telegram.org/bot{TOKEN}/getUpdates"

# Guard agar thread hanya dijalankan satu kali per sesi Streamlit
_listener_started = False
_listener_lock    = threading.Lock()


# ─────────────────────────────────────────────────────────────────────────────
# Core polling logic
# ─────────────────────────────────────────────────────────────────────────────

def _parse_technician(update: dict) -> str:
    """
    Ekstrak nama/username teknisi dari objek Telegram update.
    Mengembalikan '@username' jika ada, atau 'First Last' sebagai fallback.
    """
    sender = (
        update.get("message", {}).get("from", {})
        or update.get("edited_message", {}).get("from", {})
    )
    username = sender.get("username", "")
    if username:
        return f"@{username}"
    first = sender.get("first_name", "")
    last  = sender.get("last_name", "")
    return f"{first} {last}".strip() or "Unknown"


def poll_telegram_replies():
    """
    Satu siklus polling: ambil update baru, proses reply yang valid.
    Bisa dipanggil manual untuk testing:
        python -c "from components.telegram_listener import poll_telegram_replies; poll_telegram_replies()"
    """
    offset = get_last_telegram_update_id()
    params = {
        "offset"  : offset + 1 if offset else None,
        "timeout" : 10,
        "limit"   : 100,
    }
    # Hapus key None agar tidak dikirim ke API
    params = {k: v for k, v in params.items() if v is not None}

    try:
        resp = requests.get(_UPDATES_URL, params=params, timeout=15)
        if not resp.ok:
            print(f"[Listener] getUpdates gagal: {resp.status_code}")
            return

        updates = resp.json().get("result", [])
        if not updates:
            return

        max_update_id = offset

        for upd in updates:
            upd_id  = upd.get("update_id", 0)
            message = upd.get("message", {})

            # Simpan update_id tertinggi untuk offset berikutnya
            if upd_id > max_update_id:
                max_update_id = upd_id

            # Hanya proses jika ini adalah REPLY ke pesan lain
            reply_to = message.get("reply_to_message")
            if not reply_to:
                continue

            replied_msg_id = reply_to.get("message_id")
            if not replied_msg_id:
                continue

            # Ambil teks reply, normalkan ke lowercase
            text_raw  = (message.get("text") or "").strip()
            text_norm = text_raw.lower()

            # Cek apakah mengandung salah satu kata kunci
            matched_status = None
            for keyword, status in FIELD_KEYWORDS.items():
                if keyword in text_norm:
                    matched_status = status
                    break  # Ambil kata kunci pertama yang cocok

            if not matched_status:
                continue   # Bukan reply dengan kata kunci yang dikenali

            technician = _parse_technician(upd)
            reply_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Update status di SQLite
            update_alarm_status(
                message_id  = replied_msg_id,
                status      = matched_status,
                technician  = technician,
                reply_text  = text_raw,
                reply_at    = reply_time,
            )
            print(
                f"[Listener] message_id={replied_msg_id} "
                f"→ status='{matched_status}' oleh {technician}"
            )

        # Simpan offset terbaru
        if max_update_id > offset:
            set_last_telegram_update_id(max_update_id)

    except Exception as e:
        print(f"[Listener] Exception saat polling: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Background thread
# ─────────────────────────────────────────────────────────────────────────────

def _listener_loop():
    """Loop tak terbatas yang dijalankan di background thread."""
    print(f"[Listener] Thread dimulai — polling setiap {POLL_INTERVAL} detik.")
    while True:
        try:
            poll_telegram_replies()
        except Exception as e:
            print(f"[Listener] Error tidak terduga: {e}")
        time.sleep(POLL_INTERVAL)


def start_listener():
    """
    Jalankan background polling thread (daemon) — aman dipanggil berkali-kali,
    thread hanya akan dibuat SATU KALI per sesi.

    Dipanggil dari app_streamlit.py saat aplikasi pertama kali load.
    """
    global _listener_started
    with _listener_lock:
        if _listener_started:
            return   # Sudah berjalan, tidak perlu membuat thread baru
        t = threading.Thread(target=_listener_loop, daemon=True, name="TelegramListener")
        t.start()
        _listener_started = True
        print("[Listener] Background thread berhasil dijalankan.")
