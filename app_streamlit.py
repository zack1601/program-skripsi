import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import time
import numpy as np
import re
import os
import io
import datetime as dt
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor
from streamlit_gsheets import GSheetsConnection
import requests
import sys
from io import StringIO
from contextlib import redirect_stdout, redirect_stderr

# Import core logic & configs
from main import process_olt_audit
from config import INPUT_FILE, MAX_WORKERS

# Import visual components & layouts
from components import inject_custom_css, render_metrics, render_filters, render_map, render_table, get_olt_coordinate
from components.telegram import send_telegram_alarm, should_send_alarm, get_region_from_olt
from components.auth import render_login_page
from components.database import (
    save_scan_results, load_latest_scan, get_historical_trend,
    save_alarm_sent, get_alarm_updates, init_db,
    cache_input_from_gsheets, load_input_cache,
    get_last_sync_time, load_scan_history_full,
    update_alarm_status_by_sn, get_all_alarm_history,
)
from components.validation import validate_input_dataframe
from components.telegram_listener import start_listener

# --- SET PAGE CONFIG ---
st.set_page_config(
    page_title="NETWATCH OPS CENTER",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- INJECT CUSTOM CSS ---
inject_custom_css()

# --- INITIALIZE SESSION STATE ---
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'data_final' not in st.session_state:
    st.session_state['data_final'] = pd.DataFrame()
if 'is_scanning' not in st.session_state:
    st.session_state['is_scanning'] = False
if 'stop_scanning' not in st.session_state:
    st.session_state['stop_scanning'] = False
if 'temp_results' not in st.session_state:
    st.session_state['temp_results'] = []
if 'filter_mode' not in st.session_state:
    st.session_state['filter_mode'] = 'All'
if 'tech_page' not in st.session_state:
    st.session_state['tech_page'] = 0

# --- SESSION TIMEOUT (30 menit) ---
_SESSION_TIMEOUT = 30 * 60  # detik
if 'login_time' not in st.session_state:
    st.session_state['login_time'] = None

if st.session_state.get('logged_in') and st.session_state.get('login_time'):
    _elapsed = time.time() - st.session_state['login_time']
    if _elapsed > _SESSION_TIMEOUT:
        st.session_state['logged_in'] = False
        st.session_state['login_time'] = None
        st.toast("⏰ Sesi habis (30 menit idle). Silakan login kembali.", icon="🔒")

# --- LOGIN FORM ---
if not st.session_state['logged_in']:
    render_login_page()
    st.stop()  # Lock access if not logged in

# --- MAIN APP (Hanya berjalan jika sudah login) ---

# --- INIT DB & START TELEGRAM LISTENER ---
# Pastikan tabel alarm_sent sudah dibuat, lalu jalankan background thread
# yang memonitor reply teknisi lapangan. Aman dipanggil berkali-kali.
init_db()
start_listener()

# --- LAST SCAN CACHE LOADER (SQLite) ---
if st.session_state['data_final'].empty and not st.session_state['is_scanning']:
    df_cache = load_latest_scan()
    if not df_cache.empty:
        st.session_state['data_final'] = df_cache
        st.toast("✅ Memuat data dari database lokal (SQLite).", icon="💾")

# --- BUSINESS/BACKEND DATA LOGIC ---
def apply_business_logic(row):
    status_raw = str(row.get('Status', "")).lower().strip()
    rx_power = str(row.get('rx_power', "-")).strip()
    cause_raw = str(row.get('last_down_cause', "")).lower().strip()

    if status_raw == 'offline' and cause_raw == '-': return "Suspend"

    # Explicit check for "Deactivated by administrator" from OLT
    if 'deactivated' in cause_raw or 'deactivated' in status_raw: return "Suspend"

    suspend_keywords = ['deactive', 'suspend', 'isolated', 'dact', 'isol', 'auth', 'fail', 'ext']
    if any(x in status_raw for x in suspend_keywords) or any(x in cause_raw for x in suspend_keywords):
        return "Suspend"

    if 'online' in status_raw:
        try:
            val = float(rx_power)
            if val >= -25.99: return "Online"
            else: return "BadRx"
        except: return "Online"
    
    if any(x in cause_raw for x in ['losi', 'lobi', 'los']): return "LOS"
    if any(x in cause_raw for x in ['dying', 'power-off']): return "Dyinggasp"
    return "Offline"


# --- SIDEBAR UI ---
with st.sidebar:
    # Single-line Minimalist Header
    st.markdown("""
    <div style='padding: 16px 0; border-bottom: 1px solid #30363D; margin-bottom: 16px;'>
        <p style='margin:0; font-size:1.5rem; font-weight:800; letter-spacing:2px; color:#FFFFFF;'>NETWATCH OPS CENTER <span style="color:#484F58; font-weight:400;"></span></p>
    </div>
    """, unsafe_allow_html=True)
    
    # Modern Navigation (Glassmorphism)
    st.markdown('<div class="sidebar-btn active"><i class="fa-solid fa-chart-line" style="margin-right:10px;opacity:0.7;"></i>Monitoring Dashboard</div>', unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    # Dynamic Scan/Stop Toggle Button
    is_running = st.session_state.get('is_scanning', False)
    if is_running:
        st.markdown('<div class="stop-btn">', unsafe_allow_html=True)
        if st.button("STOP SCANNING", use_container_width=True):
            st.session_state['is_scanning'] = False
            st.session_state['stop_scanning'] = True
            
            # Pindahkan data yang sudah terkumpul sejauh ini ke data_final agar tidak kosong
            if 'temp_results' in st.session_state and st.session_state['temp_results']:
                final_df = pd.DataFrame(st.session_state['temp_results'])
                if not final_df.empty:
                    # Bersihkan SN untuk deduplikasi terpercaya
                    final_df['Serial Number'] = final_df['Serial Number'].astype(str).str.strip().str.upper()
                    final_df['Nama/ID Pelanggan'] = final_df['Nama/ID Pelanggan'].astype(str).str.strip().str.upper()
                    
                    # Deduplikasi ketat hanya berdasarkan SN
                    final_df = final_df.drop_duplicates(subset=['Serial Number'], keep='first')
                    
                    st.session_state['data_final'] = final_df
                    save_scan_results(final_df)
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="start-btn">', unsafe_allow_html=True)
        if st.button("START SCAN", use_container_width=True):
            st.session_state['is_scanning'] = True
            st.session_state['stop_scanning'] = False
            st.session_state['temp_results'] = []
            st.session_state['data_final'] = pd.DataFrame()
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    # ── SYNC DATA BUTTON ──────────────────────────────────────────────────────
    st.markdown("---")
    _last_sync = get_last_sync_time()
    st.markdown(
        f"<p style='margin:0 0 6px 0; font-size:0.75rem; color:#484f58;'>"
        f"🗄️ Cache terakhir: <b style='color:#8b949e'>{_last_sync}</b></p>",
        unsafe_allow_html=True
    )
    if st.button("🔄 SYNC GOOGLE SHEETS", use_container_width=True):
        with st.spinner("Menarik data dari Google Sheets..."):
            try:
                _gconn = st.connection("gsheets", type=GSheetsConnection)
                _SYNC_URL = "https://docs.google.com/spreadsheets/d/1lQYkUIFhzW5oWDUWSjOlR1PGhSBl8gMH7uQQxeX3_xw/edit#gid=0"
                from io import StringIO
                from contextlib import redirect_stdout, redirect_stderr
                with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                    _df_sync = _gconn.read(spreadsheet=_SYNC_URL)
                if _df_sync is not None and not _df_sync.empty:
                    cache_input_from_gsheets(_df_sync)
                    st.success(f"✅ {len(_df_sync)} baris berhasil di-cache ke SQLite!")
                else:
                    st.warning("⚠️ Google Sheets tidak mengembalikan data.")
            except Exception as _e:
                st.error(f"❌ Gagal terhubung ke Google Sheets: {_e}")
        st.rerun()

    # Alarm Region Selector
    st.markdown("---")
    region_options = ["Semua Wilayah", "Fatmawati", "Cipedak", "Pinang/Kalijati", "Lenteng Agung", "Cinere", "Senopati"]
    selected_region_alarm = st.selectbox("🎯 Target Alarm Region:", region_options)
    
    # Alarm button
    btn_disabled = st.session_state['data_final'].empty
    st.markdown('<div class="alarm-btn">', unsafe_allow_html=True)
    if st.button("SEND ALARM", use_container_width=True, disabled=btn_disabled):
        df_problems = st.session_state['data_final'][st.session_state['data_final']['Category'].isin(['LOS', 'BadRx'])]
        
        if df_problems.empty:
            st.sidebar.info("System Healthy: No Alarms Needed")
        else:
            # Pre-filter and pre-check deduplication
            to_send = []
            for row in df_problems.to_dict('records'):
                row_region = get_region_from_olt(row.get('OLT', ''))
                
                # Filter by region
                if selected_region_alarm != "Semua Wilayah" and row_region != selected_region_alarm:
                    continue
                
                sn = row.get('Serial Number', '')
                status = row.get('Category', '')
                
                if should_send_alarm(sn, status):
                    to_send.append(row)
            
            if to_send:
                # Tampilkan notif di awal / bersamaan dengan pengiriman pertama
                st.success(f"{len(to_send)} Alarms Sent to {selected_region_alarm}!")
                
                # Kirim ke Telegram + simpan message_id ke SQLite
                for row in to_send:
                    msg_id = send_telegram_alarm(row)
                    if msg_id:  # Simpan hanya jika pengiriman berhasil
                        save_alarm_sent(msg_id, row)
            else:
                st.info("No new alarms to send (or already sent).")
    st.markdown('</div>', unsafe_allow_html=True)
    
    st.markdown("---")

    # Render OLT select dropdown, search text box, and modern Quick Filters (fully modularized!)
    render_filters(st.session_state['data_final'])

    # Logout button di area paling bawah sidebar
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🚪 LOGOUT", key="logout_btn", use_container_width=True):
        st.session_state['logged_in'] = False
        st.rerun()

# --- FILTER DATA FOR DISPLAY ---
df_raw = st.session_state['data_final']
df_filtered = df_raw.copy()

if not df_raw.empty:
    if st.session_state.get('filter_mode', 'All') != "All":
        df_filtered = df_filtered[df_filtered['Category'] == st.session_state.get('filter_mode', 'All')]
    if st.session_state.get('selected_olt', 'All OLT') != "All OLT":
        df_filtered = df_filtered[df_filtered['OLT'] == st.session_state.get('selected_olt')]
    if st.session_state.get('search_sn_sidebar'):
        s_term = st.session_state.get('search_sn_sidebar')
        df_filtered = df_filtered[df_filtered.astype(str).apply(lambda x: x.str.contains(s_term, case=False)).any(axis=1)]

# --- RENDER METRICS & RISK SCORE GAUGE (STICKY HEADER) ---
render_metrics(df_filtered)

# --- RENDER HISTORICAL TREND CHART ---
df_trend = get_historical_trend()
with st.expander("📈 Historical Problem Trend", expanded=False):
    if not df_trend.empty:
        # Pivot the data
        df_pivot = df_trend.pivot(index='scan_timestamp', columns='Category', values='count').fillna(0)
        df_pivot = df_pivot.reset_index()
        
        # Highlight problematic categories
        cols_to_plot = [c for c in ['LOS', 'BadRx', 'Offline', 'Dyinggasp'] if c in df_pivot.columns]
        if cols_to_plot:
            fig = go.Figure()
            
            color_map = {
                "LOS": "rgba(255, 75, 75, 1)",        # Merah
                "BadRx": "rgba(245, 166, 35, 1)",      # Orange/Kuning
                "Offline": "rgba(142, 142, 147, 1)",   # Abu-abu
                "Dyinggasp": "rgba(156, 39, 176, 1)"   # Ungu
            }
            fill_map = {
                "LOS": "rgba(255, 75, 75, 0.15)",       
                "BadRx": "rgba(245, 166, 35, 0.15)",     
                "Offline": "rgba(142, 142, 147, 0.15)",  
                "Dyinggasp": "rgba(156, 39, 176, 0.15)"  
            }

            for c in cols_to_plot:
                fig.add_trace(go.Scatter(
                    x=df_pivot["scan_timestamp"],
                    y=df_pivot[c],
                    name=c,
                    mode='lines',
                    line_shape='spline',
                    line=dict(color=color_map.get(c, "rgba(255,255,255,1)"), width=3),
                    fill='tozeroy',
                    fillcolor=fill_map.get(c, "rgba(255,255,255,0.1)"),
                ))
            
            # Premium Styling (Dark Mode & Glassmorphism)
            fig.update_layout(
                height=250,  # Memperkecil tinggi grafik sekitar 25-30%
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#c9d1d9"),
                xaxis_title="",
                yaxis_title="Jumlah Pelanggan",
                legend_title="",
                legend=dict(font=dict(color="white")), # Mengubah warna teks legend menjadi putih
                hovermode="x unified",
                margin=dict(l=0, r=0, t=30, b=0)
            )
            fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor='#30363d')
            fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor='#30363d')
            
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Belum ada data masalah (LOS/BadRx) yang tersimpan di riwayat.")
    else:
        st.warning("📊 Database riwayat masih kosong. Silakan klik 'START SCAN' di menu kiri minimal satu kali untuk mulai merekam data grafik.")

# ─────────────────────────────────────────────────────────────────────────────
# PANEL: FIELD TECHNICIAN UPDATES
# ─────────────────────────────────────────────────────────────────────────────
import math

if 'confirm_action' not in st.session_state:
    st.session_state['confirm_action'] = None

df_field_updates = get_alarm_updates(limit=200)

if st.session_state['confirm_action']:
    ca = st.session_state['confirm_action']
    _sn = ca['sn']
    _act = ca['action']
    _icon = "✅" if _act == "Resolved" else "❌"
    _col = "#3fb950" if _act == "Resolved" else "#f85149"
    
    _, col_center, _ = st.columns([1, 2, 1])
    
    with col_center:
        st.markdown(f"""
        <div style='padding:15px; border-left:4px solid {_col}; background:rgba(22,27,34,0.85); border-radius:8px; margin-bottom:15px; border:1px solid #30363D;'>
            <b>Konfirmasi:</b> Anda yakin ingin menandai alarm <b>{_sn}</b> sebagai <span style='color:{_col}; font-weight:bold;'>{_act}</span>?
        </div>
        """, unsafe_allow_html=True)
        
        c1, c2 = st.columns(2)
        with c1:
            if st.button("YA", use_container_width=True):
                update_alarm_status_by_sn(_sn, _act)
                st.toast(f"{_icon} {_sn[:12]} → {_act}!", icon=_icon)
                st.session_state['confirm_action'] = None
                st.rerun()
        with c2:
            if st.button("TIDAK", use_container_width=True):
                st.session_state['confirm_action'] = None
                st.rerun()
                
        import streamlit.components.v1 as components
        components.html("""
        <script>
        const doc = window.parent.document;
        const colorize = () => {
            doc.querySelectorAll('button').forEach(btn => {
                const text = btn.innerText.trim();
                if(text === 'YA') {
                    btn.style.setProperty('background-color', '#238636', 'important');
                    btn.style.setProperty('border-color', '#2ea043', 'important');
                    btn.style.setProperty('color', 'white', 'important');
                } else if(text === 'TIDAK') {
                    btn.style.setProperty('background-color', '#da3633', 'important');
                    btn.style.setProperty('border-color', '#f85149', 'important');
                    btn.style.setProperty('color', 'white', 'important');
                }
            });
        };
        colorize(); setTimeout(colorize, 50); setTimeout(colorize, 150); setTimeout(colorize, 400);
        </script>
        """, height=0, width=0)


st.markdown("""<div style='
    margin-top: 12px;
    padding: 16px 20px 8px 20px;
    border-radius: 10px;
    border: 1px solid #30363D;
    background: rgba(22,27,34,0.85);
'>
    <p style='margin:0 0 12px 0; font-size:1rem; font-weight:700;
              letter-spacing:1px; color:#c9d1d9;'>
        🛠️ FIELD TECHNICIAN UPDATES
        <span style='font-size:0.75rem; font-weight:400; color:#484f58; margin-left:8px;'>
            — hanya menampilkan alarm aktif (Sent / In Progress)
        </span>
    </p>
""", unsafe_allow_html=True)

if df_field_updates.empty:
    st.info("🟢 Tidak ada alarm aktif. Semua gangguan sudah ditangani atau belum ada alarm yang dikirim.")
else:
    # --- PAGINATION LOGIC ---
    items_per_page = 5
    total_pages = max(1, math.ceil(len(df_field_updates) / items_per_page))

    if st.session_state['tech_page'] >= total_pages:
        st.session_state['tech_page'] = total_pages - 1
    if st.session_state['tech_page'] < 0:
        st.session_state['tech_page'] = 0

    start_idx = st.session_state['tech_page'] * items_per_page
    end_idx = start_idx + items_per_page
    df_page = df_field_updates.iloc[start_idx:end_idx]

    # Badge berwarna sesuai status
    _STATUS_BADGE = {
        "Sent"       : ("📤 Sent",        "#484f58", "#c9d1d9"),
        "In Progress": ("🔧 In Progress", "#7d4e00", "#f5a623"),
        "Resolved"   : ("✅ Resolved",    "#0d4429", "#3fb950"),
        "Cancelled"  : ("❌ Cancelled",   "#4d1919", "#f85149"),
    }

    def _badge(status):
        label, bg, color = _STATUS_BADGE.get(
            status, (status, "#333", "#fff")
        )
        return (
            f"<span style='background:{bg}; color:{color}; "
            f"padding:2px 8px; border-radius:12px; font-size:0.78rem; "
            f"font-weight:600; white-space:nowrap;'>{label}</span>"
        )

    # --- HEADER TABEL ---
    h_cols = st.columns([2, 2, 1.2, 1.5, 1.5, 1.5, 1.8, 1.3])
    headers = ["Serial Number", "Pelanggan", "Category", "Status",
               "Teknisi", "Reply", "Waktu", "Aksi"]
    for hc, ht in zip(h_cols, headers):
        hc.markdown(
            f"<span style='font-size:0.72rem; color:#8b949e; text-transform:uppercase; "
            f"letter-spacing:0.5px; font-weight:600;'>{ht}</span>",
            unsafe_allow_html=True
        )

    st.markdown("<hr style='margin:4px 0 6px 0; border-color:#30363d;'>", unsafe_allow_html=True)

    # --- BARIS DATA ---
    for idx, r in df_page.iterrows():
        sn     = r.get("sn", "-") or "-"
        tech   = r.get("technician", "") or "-"
        reply  = r.get("reply_text",  "") or "-"
        ra     = r.get("reply_at",    "") or "-"
        status = r.get("status", "Sent")
        ra_short   = ra[11:16] if len(ra) >= 16 else ra
        sent_short = str(r.get("sent_at", "-"))[11:16]

        row_cols = st.columns([2, 2, 1.2, 1.5, 1.5, 1.5, 1.8, 1.3])
        row_cols[0].markdown(
            f"<span style='font-family:monospace; font-size:0.78rem; color:#58a6ff;'>{sn[:14]}</span>",
            unsafe_allow_html=True
        )
        row_cols[1].markdown(
            f"<span style='font-size:0.8rem;'>{r.get('pelanggan', '-')}</span>",
            unsafe_allow_html=True
        )
        row_cols[2].markdown(
            f"<span style='font-size:0.8rem; color:#f5a623;'>{r.get('category', '-')}</span>",
            unsafe_allow_html=True
        )
        row_cols[3].markdown(_badge(status), unsafe_allow_html=True)
        row_cols[4].markdown(
            f"<span style='font-size:0.78rem; color:#8b949e;'>{tech}</span>",
            unsafe_allow_html=True
        )
        row_cols[5].markdown(
            f"<span style='font-size:0.78rem; color:#8b949e;'>{reply}</span>",
            unsafe_allow_html=True
        )
        row_cols[6].markdown(
            f"<span style='font-size:0.72rem; color:#484f58;'>Sent {sent_short}<br>Upd {ra_short}</span>",
            unsafe_allow_html=True
        )

        # --- TOMBOL AKSI (hanya muncul jika status masih aktif) ---
        with row_cols[7]:
            btn_col1, btn_col2 = st.columns(2)
            with btn_col1:
                if st.button("✅", key=f"resolve_{sn}_{idx}", help="Tandai Selesai (Resolved)"):
                    st.session_state['confirm_action'] = {'sn': sn, 'action': 'Resolved'}
                    st.rerun()
            with btn_col2:
                if st.button("❌", key=f"cancel_{sn}_{idx}", help="Batalkan (Cancelled)"):
                    st.session_state['confirm_action'] = {'sn': sn, 'action': 'Cancelled'}
                    st.rerun()

        st.markdown("<hr style='margin:2px 0; border-color:#21262d;'>", unsafe_allow_html=True)
        
    # --- PAGINATION CONTROLS ---
    st.markdown("<br>", unsafe_allow_html=True)
    p_col1, p_col2, p_col3, _ = st.columns([1, 1, 2, 4])
    with p_col1:
        if st.button("⬅️ Prev", disabled=(st.session_state['tech_page'] == 0), use_container_width=True):
            st.session_state['tech_page'] -= 1
            st.rerun()
    with p_col2:
        if st.button("Next ➡️", disabled=(st.session_state['tech_page'] >= total_pages - 1), use_container_width=True):
            st.session_state['tech_page'] += 1
            st.rerun()
    with p_col3:
        st.markdown(f"<div style='padding-top:8px; color:#8b949e; font-size:0.85rem;'>Page {st.session_state['tech_page'] + 1} of {total_pages} (Total: {len(df_field_updates)})</div>", unsafe_allow_html=True)

st.markdown("</div>", unsafe_allow_html=True)

# Spacer to push content below the fixed Network Summary bar
st.write("")
st.write("")
st.write("")
st.write("")

# --- SCANNING ENGINE ---
if st.session_state['is_scanning']:
    st.toast("Starting Audit Engine...")
    
    # Header for Stopwatch & Status
    status_placeholder = st.empty()
    loader = st.progress(0)
    
    start_time = time.time()
    
    try:
        # ── 1. BACA INPUT (PRIORITAS: SQLite Cache → Google Sheets → Excel Lokal) ──
        # Arsitektur: SQLite sebagai pusat data lokal (caching layer).
        # Scanning tidak wajib terhubung ke Google Sheets jika cache tersedia.
        df_input = None
        data_source = "SQLite Cache"

        # Langkah 1: Baca dari SQLite cache (paling cepat, tidak butuh internet)
        df_input = load_input_cache()

        if df_input is None or df_input.empty:
            # Langkah 2: Cache kosong → tarik dari Google Sheets dan cache hasilnya
            data_source = "Google Sheets"
            try:
                conn = st.connection("gsheets", type=GSheetsConnection)
                CLEAN_URL = "https://docs.google.com/spreadsheets/d/1lQYkUIFhzW5oWDUWSjOlR1PGhSBl8gMH7uQQxeX3_xw/edit#gid=0"
                with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                    df_input = conn.read(spreadsheet=CLEAN_URL)
                if df_input is not None and not df_input.empty:
                    cache_input_from_gsheets(df_input)   # ← Simpan ke SQLite
                    st.toast("✅ Data Google Sheets otomatis di-cache ke SQLite", icon="🗄️")
            except Exception:
                pass

        if df_input is None or df_input.empty:
            # Langkah 3: Fallback Excel Lokal jika semua gagal
            data_source = "Excel Lokal"
            if os.path.exists(INPUT_FILE):
                try:
                    df_input = pd.read_excel(INPUT_FILE)
                except Exception as ex_excel:
                    st.error(f"❌ Gagal memuat data: {ex_excel}")
                    st.session_state['is_scanning'] = False
                    st.stop()
            else:
                st.error(
                    "❌ Tidak ada sumber data tersedia.\n\n"
                    "SQLite cache kosong, Google Sheets tidak terjangkau, "
                    "dan file Excel lokal tidak ditemukan.\n\n"
                    "→ Klik **🔄 SYNC GOOGLE SHEETS** di sidebar untuk mengisi cache."
                )
                st.session_state['is_scanning'] = False
                st.stop()

        # ── 2. VALIDASI & NORMALISASI (validation.py) ───────────────────────
        # Menstandarkan nama kolom (alias → standar) dan memvalidasi isi:
        # format IP, panjang SN, nilai PORT, duplikasi SN.
        df_input, validation_errors = validate_input_dataframe(df_input)

        # Pisahkan warning (⚠️) dari error (❌) agar pengguna tahu mana
        # yang fatal (proses berhenti) dan mana yang hanya informasi.
        fatal_errors   = [e for e in validation_errors if e.startswith("❌")]
        warnings_only  = [e for e in validation_errors if e.startswith("⚠️")]

        for warn in warnings_only:
            st.warning(warn)          # tampilkan warning, tapi tetap lanjut

        if fatal_errors:
            for err in fatal_errors:
                st.error(err)         # tampilkan semua error sekaligus
            st.info(
                f"💡 Data dibaca dari **{data_source}**. "
                "Perbaiki kolom / nilai yang bermasalah lalu klik START SCAN ulang."
            )
            st.session_state['is_scanning'] = False
            st.stop()

        st.toast(f"✅ Data berhasil dimuat dari {data_source} ({len(df_input)} baris)", icon="📋")

        if 'olt' in df_input.columns:
            df_input['olt'] = df_input['olt'].ffill()
        
        # Load nama & ID pelanggan riil dari hasil_pengecekan_ont.xlsx jika ada untuk sinkronisasi optimal
        cust_map = {}
        if os.path.exists("hasil_pengecekan_ont.xlsx"):
            try:
                df_cust = pd.read_excel("hasil_pengecekan_ont.xlsx")
                for _, cr in df_cust.iterrows():
                    sn_key = str(cr.get("SERIAL NUMBER", cr.get("serial number", ""))).strip().upper()
                    if sn_key and sn_key != "NAN":
                        cust_map[sn_key] = {
                            "id": str(cr.get("ID_PELANGGAN", cr.get("id_pelanggan", ""))).strip(),
                            "nama": str(cr.get("NAMA PELANGGAN", cr.get("nama pelanggan", ""))).strip()
                        }
            except Exception as ex_cust:
                pass
        
        olt_map = {}
        
        for _, r in df_input.iterrows():
            ip = str(r.get('ip_olt', '')).strip()
            name = str(r.get('olt', 'Unknown OLT')).strip()
            port = str(r.get('port', '')).strip()
            if not ip or ip.lower() == 'nan': continue
            if ip not in olt_map: olt_map[ip] = {"name": name, "slots": set()}
            match = re.search(r'(\d+)\s*/\s*(\d+)\s*/\s*(\d+)', port)
            if match: olt_map[ip]["slots"].add(f"{match.group(1)}/{match.group(2)}")
        
        # Gunakan 'serial_number' — nama standar setelah normalisasi oleh validation.py
        sn_map_input = {str(r.get('serial_number', '')).strip().upper(): r for _, r in df_input.iterrows()}
        st.session_state['temp_results'] = []
        
        total_olt_count = len(olt_map)
        completed_count = 0
        
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures_to_ip = {executor.submit(process_olt_audit, g["name"], ip, list(g["slots"])): ip for ip, g in olt_map.items()}
            futures = set(futures_to_ip.keys())
            
            while futures:
                # Update Stopwatch UI
                elapsed = time.time() - start_time
                t_str = time.strftime("%H:%M:%S", time.gmtime(elapsed))
                status_placeholder.markdown(f"""
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: -10px;">
                    <div style="color: #00E5FF; font-weight: 800;">🛰️ SCANNING OLT ({completed_count}/{total_olt_count})</div>
                    <div style="color: #FFFFFF; font-family: monospace; font-size: 1.2rem; font-weight: 800;">⏱️ {t_str}</div>
                </div>
                """, unsafe_allow_html=True)
                
                # Wait for at least one to complete, or timeout for clock update
                done, pending = concurrent.futures.wait(futures, timeout=1, return_when=concurrent.futures.FIRST_COMPLETED)
                
                for f in done:
                    scan_results = f.result()
                    for s in scan_results:
                        sn_scan = str(s.get('sn', "")).strip().upper()
                        
                        # STRICT SYNC: Only process if SN exists in Excel Input
                        if sn_scan not in sn_map_input:
                            continue
                            
                        row_in = sn_map_input.get(sn_scan, {})
                        
                        id_pel = ""
                        nama_pel = ""
                        if sn_scan in cust_map:
                            id_pel = cust_map[sn_scan]["id"]
                            nama_pel = cust_map[sn_scan]["nama"]
                            
                        # Jika tidak ditemukan di cust_map, gunakan logic lama
                        if not id_pel or id_pel.lower() == 'nan' or not nama_pel or nama_pel.lower() == 'nan':
                            combined_name = str(row_in.get('nama_id pelanggan', '')).strip()
                            if combined_name and combined_name.lower() != 'nan':
                                if "_" in combined_name:
                                    parts = combined_name.split("_")
                                    nama_pel = parts[0]
                                    id_pel = parts[1] if len(parts) > 1 else ""
                                else:
                                    id_pel = str(row_in.get('id_pelanggan', row_in.get('id', ''))).strip()
                                    nama_pel = str(row_in.get('nama_pelanggan', row_in.get('nama', combined_name))).strip()
                            else:
                                id_pel = str(row_in.get('id_pelanggan', row_in.get('id', ''))).strip()
                                nama_pel = str(row_in.get('nama_pelanggan', row_in.get('nama', ''))).strip()

                        desc = str(s.get('description', '')).strip()
                        
                        if (not id_pel or id_pel.lower() == 'nan' or not nama_pel or nama_pel.lower() == 'nan') and desc:
                            match_id = re.search(r'(\d{10,13})', desc)
                            if match_id:
                                id_pel = match_id.group(1)
                                temp = desc.replace(id_pel, "")
                                temp = re.sub(r'-?\d+\.\d+/-?\d+\.\d+', '', temp)
                                temp = re.sub(r'\s+\d{3,5}\s+', ' ', temp)
                                nama_pel = temp.strip(" -_/")
                        
                        id_pel = id_pel if id_pel and id_pel.lower() != 'nan' else "11100" + str(np.random.randint(100000, 999999))
                        nama_pel = nama_pel if nama_pel and nama_pel.lower() != 'nan' else "-"
                        
                        sn_clean = str(s.get('sn', "")).strip().upper()
                        
                        # Get OLT Coordinates
                        olt_name = olt_map[futures_to_ip[f]]["name"]
                        olt_coords = get_olt_coordinate(olt_name)
                        
                        # Real Coordinates from Sheet if available
                        raw_lat = row_in.get('latitude', -6.30)
                        raw_lon = row_in.get('longitude', 106.80)
                        
                        try:
                            final_lat = float(raw_lat)
                            final_lon = float(raw_lon)
                        except:
                            final_lat = -6.30 + (np.random.random() * 0.05)
                            final_lon = 106.80 + (np.random.random() * 0.05)

                        record = {
                            "OLT": olt_name,
                            "Nama/ID Pelanggan": f"{id_pel}-{nama_pel}",
                            "Port": str(row_in.get('port', s.get('port_override', '-'))),
                            "Serial Number": sn_clean,
                            "Status": s.get('status'),
                            "rx_power": s.get('rx_power'),
                            "last_down_cause": s.get('last_down_cause'),
                            "lat": final_lat,
                            "lon": final_lon,
                            "olt_lat": olt_coords[0] if olt_coords else None,
                            "olt_lon": olt_coords[1] if olt_coords else None,
                            "maps": str(row_in.get('link maps', '#'))
                        }
                        
                        cat = apply_business_logic(record)
                        record["Category"] = cat
                        
                        if record["Status"].lower() == "online":
                            try:
                                val = float(record["rx_power"])
                                record["Power/Cause"] = f"{val} dBm"
                            except:
                                record["Power/Cause"] = record["rx_power"]
                        else:
                            record["Power/Cause"] = record["last_down_cause"]
                            
                        st.session_state['temp_results'].append(record)
                    
                    completed_count += 1
                    loader.progress(completed_count / total_olt_count)
                
                futures = pending
                
                # --- STOP CHECK: Graceful abort if user clicked STOP ---
                if st.session_state.get('stop_scanning', False):
                    for pf in pending:
                        pf.cancel()
                    elapsed = time.time() - start_time
                    t_str = time.strftime("%H:%M:%S", time.gmtime(elapsed))
                    status_placeholder.markdown(f"""
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: -10px;">
                        <div style="color: #F59E0B; font-weight: 800;">⏹️ SCAN STOPPED ({completed_count}/{total_olt_count})</div>
                        <div style="color: #F59E0B; font-family: monospace; font-size: 1.2rem; font-weight: 800;">⏱️ {t_str}</div>
                    </div>
                    """, unsafe_allow_html=True)
                    time.sleep(0.5)
                    break
            
            # --- SCANNING COMPLETE UI ---
            elapsed = time.time() - start_time
            t_str = time.strftime("%H:%M:%S", time.gmtime(elapsed))
            
            status_placeholder.markdown(f"""
            <style>
                @keyframes blink {{
                    0% {{ opacity: 1; }}
                    50% {{ opacity: 0.3; }}
                    100% {{ opacity: 1; }}
                }}
                .stopwatch-complete {{
                    color: #00E676 !important;
                    font-family: monospace;
                    font-size: 1.2rem;
                    font-weight: 800;
                    animation: blink 1s infinite;
                }}
            </style>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: -10px;">
                <div style="color: #00E676; font-weight: 800;">✅ SCANNING COMPLETE (100%)</div>
                <div class="stopwatch-complete">⏱️ {t_str}</div>
            </div>
            """, unsafe_allow_html=True)
            time.sleep(1)
        
        # --- SMART OFFLINE SIMULATION FALLBACK ---
        if not st.session_state['temp_results']:
            st.toast("⚠️ Offline Mode: Mengaktifkan Simulasi Pemindaian Pintar...", icon="🤖")
            time.sleep(1)
            
            total_rows = len(df_input)
            simulated_records = []
            
            for idx, r in df_input.iterrows():
                ip = str(r.get('ip_olt', '')).strip()
                name = str(r.get('olt', 'Unknown OLT')).strip()
                port = str(r.get('port', '')).strip()
                sn_clean = str(r.get('serial_number', '')).strip().upper()
                
                if not ip or ip.lower() == 'nan': continue
                
                loader.progress((idx + 1) / total_rows)
                elapsed = time.time() - start_time
                t_str = time.strftime("%H:%M:%S", time.gmtime(elapsed))
                status_placeholder.markdown(f"""
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: -10px;">
                    <div style="color: #F59E0B; font-weight: 800;">🤖 SIMULATING OLT ({idx+1}/{total_rows})</div>
                    <div style="color: #FFFFFF; font-family: monospace; font-size: 1.2rem; font-weight: 800;">⏱️ {t_str}</div>
                </div>
                """, unsafe_allow_html=True)
                
                id_pel = ""
                nama_pel = ""
                if sn_clean in cust_map:
                    id_pel = cust_map[sn_clean]["id"]
                    nama_pel = cust_map[sn_clean]["nama"]
                
                id_pel = id_pel if id_pel and id_pel.lower() != 'nan' else "11100" + str(np.random.randint(100000, 999999))
                nama_pel = nama_pel if nama_pel and nama_pel.lower() != 'nan' else "-"
                
                rand_val = np.random.random()
                if rand_val < 0.75:
                    status = "Online"
                    if np.random.random() < 0.90:
                        rx_power = f"-{round(np.random.uniform(16.0, 25.5), 2)}"
                    else:
                        rx_power = f"-{round(np.random.uniform(26.0, 31.0), 2)}"
                    last_down_cause = "-"
                elif rand_val < 0.87:
                    status = "Offline"
                    rx_power = "-"
                    last_down_cause = "LOSi/LOBi"
                elif rand_val < 0.92:
                    status = "Offline"
                    rx_power = "-"
                    last_down_cause = "Dying gasp"
                elif rand_val < 0.97:
                    status = "Offline"
                    rx_power = "-"
                    last_down_cause = "Deactivated by administrator"
                else:
                    status = "Offline"
                    rx_power = "-"
                    last_down_cause = "Power off"
                
                olt_coords = get_olt_coordinate(name)
                
                if olt_coords:
                    final_lat = olt_coords[0] + np.random.uniform(-0.03, 0.03)
                    final_lon = olt_coords[1] + np.random.uniform(-0.03, 0.03)
                else:
                    final_lat = -6.30 + np.random.uniform(-0.05, 0.05)
                    final_lon = 106.80 + np.random.uniform(-0.05, 0.05)
                
                record = {
                    "OLT": name,
                    "Nama/ID Pelanggan": f"{id_pel}-{nama_pel}",
                    "Port": port,
                    "Serial Number": sn_clean,
                    "Status": status,
                    "rx_power": rx_power,
                    "last_down_cause": last_down_cause,
                    "lat": final_lat,
                    "lon": final_lon,
                    "olt_lat": olt_coords[0] if olt_coords else None,
                    "olt_lon": olt_coords[1] if olt_coords else None,
                    "maps": "#"
                }
                
                cat = apply_business_logic(record)
                record["Category"] = cat
                
                if record["Status"].lower() == "online":
                    try:
                        val = float(record["rx_power"])
                        record["Power/Cause"] = f"{val} dBm"
                    except:
                        record["Power/Cause"] = record["rx_power"]
                else:
                    record["Power/Cause"] = record["last_down_cause"]
                
                simulated_records.append(record)
                time.sleep(0.005)
                
            st.session_state['temp_results'] = simulated_records
            
            elapsed = time.time() - start_time
            t_str = time.strftime("%H:%M:%S", time.gmtime(elapsed))
            status_placeholder.markdown(f"""
            <style>
                @keyframes blink {{
                    0% {{ opacity: 1; }}
                    50% {{ opacity: 0.3; }}
                    100% {{ opacity: 1; }}
                }}
                .stopwatch-complete-sim {{
                    color: #F59E0B !important;
                    font-family: monospace;
                    font-size: 1.2rem;
                    font-weight: 800;
                    animation: blink 1s infinite;
                }}
            </style>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: -10px;">
                <div style="color: #F59E0B; font-weight: 800;">✅ SIMULATION COMPLETE (100%)</div>
                <div class="stopwatch-complete-sim">⏱️ {t_str}</div>
            </div>
            """, unsafe_allow_html=True)
            time.sleep(1)

        # Final Deduplication & Data Cleaning (Strict Multi-key)
        if st.session_state['temp_results']:
            final_df = pd.DataFrame(st.session_state['temp_results'])
            if not final_df.empty:
                final_df['Serial Number'] = final_df['Serial Number'].str.strip().str.upper()
                final_df['Nama/ID Pelanggan'] = final_df['Nama/ID Pelanggan'].str.strip().str.upper()
                final_df = final_df.drop_duplicates(subset=['Serial Number'], keep='first')
                st.session_state['data_final'] = final_df
                save_scan_results(final_df)
        
        st.session_state['is_scanning'] = False
        st.session_state['stop_scanning'] = False
        st.rerun()
        
    except Exception as e:
        if "getaddrinfo failed" in str(e):
            st.error("❌ Google Sheets Connection Error: Hostname could not be resolved. Please check your internet connection or DNS settings.")
        else:
            st.error(f"❌ Scan Engine Error: {str(e)}")
        st.session_state['is_scanning'] = False
        st.session_state['stop_scanning'] = False

# --- RENDER GEOGRAPHIC TOPOLOGY (MODULAR MAP) ---
render_map(df_filtered)

st.markdown("<div style='margin-top: -2rem; height: 12px;'></div>", unsafe_allow_html=True)

# --- RENDER LANDSCAPE DATA TABLE ---
render_table(df_filtered)

# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# DOWNLOAD LAPORAN EXCEL (dari SQLite — Single Source of Truth)
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("---")
_WIB = dt.timezone(dt.timedelta(hours=7))
_ts  = dt.datetime.now(_WIB).strftime('%Y%m%d_%H%M')

@st.cache_data(ttl=60, show_spinner=False)
def _generate_latest_excel_cache():
    df = load_latest_scan()
    if df.empty: return None
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as w:
        df.to_excel(w, index=False, sheet_name='Hasil Scan Terakhir')
    return buf.getvalue()

@st.cache_data(ttl=60, show_spinner=False)
def _generate_history_excel_cache():
    df_h = load_scan_history_full()
    df_a = get_all_alarm_history()
    if df_h.empty: return None
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as w:
        df_h.to_excel(w, index=False, sheet_name='Riwayat Lengkap')
        if not df_a.empty:
            df_a.to_excel(w, index=False, sheet_name='Status Gangguan')
    return buf.getvalue()

with st.expander("📥 Download Laporan Excel", expanded=False):
    col_dl1, col_dl2 = st.columns(2)

    with col_dl1:
        data_latest = _generate_latest_excel_cache()
        if data_latest:
            st.download_button(
                label="⬇️ Hasil Scan Terakhir",
                data=data_latest,
                file_name=f"scan_terakhir_{_ts}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key="dl_latest"
            )
        else:
            st.info("⚠️ Belum ada data scan. Klik START SCAN terlebih dahulu.")

    with col_dl2:
        data_history = _generate_history_excel_cache()
        if data_history:
            st.download_button(
                label="⬇️ Riwayat Semua Scan",
                data=data_history,
                file_name=f"riwayat_scan_{_ts}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key="dl_history"
            )
        else:
            st.info("⚠️ Belum ada riwayat scan tersimpan.")

# --- FOOTER ---
st.markdown("---")
st.markdown("<center style='color:#30363D; font-size:0.8rem;'>Netwatch Ops • Command Center Framework • Zaki Mubarok</center>", unsafe_allow_html=True)
