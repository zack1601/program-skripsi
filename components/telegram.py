import requests
import time
import streamlit as st
import json
import os

ALARM_HISTORY_FILE = "output/alarm_history.json"

def get_region_from_olt(olt_name):
    """
    Menentukan wilayah berdasarkan nama OLT.
    """
    olt_name_upper = str(olt_name).upper()
    if "FATMAWATI" in olt_name_upper:
        return "Fatmawati"
    elif "CIPEDAK" in olt_name_upper:
        return "Cipedak"
    elif "PINANG" in olt_name_upper or "KALIJATI" in olt_name_upper:
        return "Pinang/Kalijati"
    elif "LENTENG" in olt_name_upper and "AGUNG" in olt_name_upper:
        return "Lenteng Agung"
    elif "CINERE" in olt_name_upper:
        return "Cinere"
    elif "SENOPATI" in olt_name_upper:
        return "Senopati"
    return "Lainnya"

def should_send_alarm(sn, status):
    """
    Mengecek apakah alarm untuk SN dan Status yang sama sudah pernah dikirim.
    Mencegah spam Telegram berulang (1 User 1 Alarm).
    """
    if not sn:
        return True # Jika SN kosong, tetap kirim saja atau bisa di skip
        
    os.makedirs("output", exist_ok=True)
    history = {}
    
    # Baca riwayat yang ada
    if os.path.exists(ALARM_HISTORY_FILE):
        try:
            with open(ALARM_HISTORY_FILE, 'r') as f:
                history = json.load(f)
        except Exception:
            history = {}
            
    # Key unik untuk setiap kombinasi SN + Status
    key = f"{str(sn).strip().upper()}_{str(status).strip().upper()}"
    
    if key in history:
        # Sudah pernah dikirim
        return False
    else:
        # Belum pernah dikirim, catat sekarang
        history[key] = time.strftime('%Y-%m-%d %H:%M:%S')
        try:
            with open(ALARM_HISTORY_FILE, 'w') as f:
                json.dump(history, f)
        except Exception:
            pass
        return True

def send_telegram_alarm(record):
    """
    Sends a formatted alert message to the configured Telegram Bot channel.
    """
    # Kredensial Resmi User
    TOKEN = "8789834499:AAEeqHkPjSzlkr4egB0sMPvsMyoDUBkG2OU"
    CHAT_ID = "-1003975720951"
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    
    # Parsing ID & Nama dari "id-nama"
    id_nama = str(record.get('Nama/ID Pelanggan', "-")).split("-")
    cust_id = id_nama[0] if len(id_nama) > 0 else "-"
    cust_name = id_nama[1] if len(id_nama) > 1 else "-"
    
    region = get_region_from_olt(record.get('OLT', ''))
    
    # Template Markdown Sesuai Permintaan
    template = f"""━━━━━━━━━━━━━━━
🚨 <b>NOC ALARM REPORT</b> 🚨
━━━━━━━━━━━━━━━
📌 <b>Status:</b> {record.get('Category', 'Unknown')}
🏢 <b>OLT:</b> {record.get('OLT', '-')}
📍 <b>Region:</b> {region}
🔌 <b>Port:</b> {record.get('Port', '-')}
👤 <b>User:</b> {cust_id} - {cust_name}
📡 <b>Power:</b> {record.get('Power/Cause', '-')}
⏰ <b>Time:</b> {time.strftime('%Y-%m-%d %H:%M:%S')}
━━━━━━━━━━━━━━━
🛠️ Sent via NETWATCH OPS CENTER"""

    payload = {"chat_id": CHAT_ID, "text": template, "parse_mode": "HTML"}
    try:
        res = requests.post(url, json=payload, timeout=10)
        return res.ok
    except Exception as e:
        st.sidebar.error(f"Telegram Error: {str(e)}")
        return False
