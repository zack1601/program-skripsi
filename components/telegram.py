import requests
import time
import streamlit as st

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
    
    # Template Markdown Sesuai Permintaan
    template = f"""━━━━━━━━━━━━━━━
🚨 <b>NOC ALARM REPORT</b> 🚨
━━━━━━━━━━━━━━━
📌 <b>Status:</b> {record.get('Category', 'Unknown')}
🏢 <b>OLT:</b> {record.get('OLT', '-')}
🔌 <b>Port:</b> {record.get('Port', '-')}
👤 <b>User:</b> {cust_id} - {cust_name}
📡 <b>Power:</b> {record.get('Power/Cause', '-')}
🚨 NOC ALARM REPORT 🚨
━━━━━━━━━━━━━━━
📌 Status: {record.get('Category', 'Unknown')}
🏢 OLT: {record.get('OLT', '-')}
🔌 Port: {record.get('Port', '-')}
👤 User: {cust_id} - {cust_name}
📡 Power: {record.get('Power/Cause', '-')}
⏰ Time: {time.strftime('%Y-%m-%d %H:%M:%S')}
━━━━━━━━━━━━━━━
🛠️ Sent via NETWATCH OPS CENTER"""

    payload = {"chat_id": CHAT_ID, "text": template, "parse_mode": "HTML"}
    try:
        res = requests.post(url, json=payload, timeout=10)
        return res.ok
    except Exception as e:
        st.sidebar.error(f"Telegram Error: {str(e)}")
        return False
