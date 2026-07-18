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
import json
import uuid

# --- File-based Session Store (tidak butuh library eksternal) ---
_SESSION_FILE = ".session_store.json"
_SESSION_TIMEOUT = 30 * 60  # 30 menit dalam detik

def _load_sessions():
    try:
        if os.path.exists(_SESSION_FILE):
            with open(_SESSION_FILE, "r") as f:
                return json.load(f)
    except:
        pass
    return {}

def _save_sessions(sessions):
    try:
        with open(_SESSION_FILE, "w") as f:
            json.dump(sessions, f)
    except:
        pass

def _create_session():
    token = str(uuid.uuid4())
    sessions = _load_sessions()
    sessions[token] = time.time()
    _save_sessions(sessions)
    return token

def _validate_session(token):
    if not token:
        return False
    sessions = _load_sessions()
    if token in sessions:
        if time.time() - sessions[token] < _SESSION_TIMEOUT:
            return True
        else:
            del sessions[token]
            _save_sessions(sessions)
    return False

def _delete_session(token):
    sessions = _load_sessions()
    if token in sessions:
        del sessions[token]
        _save_sessions(sessions)

if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'session_token' not in st.session_state:
    st.session_state['session_token'] = None
if 'data_final' not in st.session_state:
    st.session_state['data_final'] = pd.DataFrame()
if 'is_scanning' not in st.session_state:
    st.session_state['is_scanning'] = False
if 'stop_scanning' not in st.session_state:
    st.session_state['stop_scanning'] = False
if 'temp_results' not in st.session_state:
    st.session_state['temp_results'] = []
if 'filter_mode' not in st.session_state:
    st.session_state['filter_mode'] = {'Online', 'LOS', 'BadRx', 'Dyinggasp', 'Suspend'}
if 'tech_page' not in st.session_state:
    st.session_state['tech_page'] = 0
if 'login_time' not in st.session_state:
    st.session_state['login_time'] = None

# Cek query param untuk session persistence (token dikirim via URL)
_qp = st.query_params
_url_token = _qp.get("t", None)
if _url_token and not st.session_state['logged_in']:
    if _validate_session(_url_token):
        st.session_state['logged_in'] = True
        st.session_state['session_token'] = _url_token
        st.session_state['login_time'] = time.time()

# Cek timeout
if st.session_state.get('logged_in') and st.session_state.get('login_time'):
    _elapsed = time.time() - st.session_state['login_time']
    if _elapsed > _SESSION_TIMEOUT:
        _delete_session(st.session_state.get('session_token', ''))
        st.session_state['logged_in'] = False
        st.session_state['session_token'] = None
        st.session_state['login_time'] = None
        st.query_params.clear()
        st.toast("⏰ Sesi habis (30 menit). Silakan login kembali.", icon="🔒")

# --- LOGIN FORM ---
if not st.session_state['logged_in']:
    render_login_page(_create_session)
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
if 'active_panel' not in st.session_state:
    st.session_state['active_panel'] = 'system'

# Dynamic CSS for Slide-in Panel
active_panel = st.session_state['active_panel']
sidebar_width = "320px" if active_panel else "64px"

st.markdown(f"""
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
    /* ══════════════════════════════════════════════════
       DESIGN SYSTEM — CYBERSECURITY COMMAND CENTER
       Color tokens, spacing, radius, typography
       ══════════════════════════════════════════════════ */

    /* ── SIDEBAR CONTAINER ── */
    [data-testid="stSidebar"] {{
        min-width: {sidebar_width} !important;
        max-width: {sidebar_width} !important;
        transition: min-width 0.3s cubic-bezier(0.4, 0, 0.2, 1),
                    max-width 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
        overflow-x: hidden !important;
        background-color: #0B0E14 !important;
        padding: 0 !important;
        border-right: 1px solid rgba(255,255,255,0.04) !important;
    }}
    [data-testid="stSidebarCollapseButton"] {{ display: none !important; }}
    [data-testid="stSidebar"] > div:first-child {{ padding: 0 !important; overflow: visible !important; }}
    [data-testid="stSidebar"] [data-testid="stSidebarContent"] {{ padding: 0 !important; }}
    [data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {{ padding: 0 !important; }}

    /* ── TWO-PANE COLUMN GRID ── */
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] {{
        flex-wrap: nowrap !important;
        gap: 0 !important;
        padding: 0 !important;
        margin: 0 !important;
        height: 100vh !important;
    }}
    /* LEFT PANE — Icon Rail */
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] div[data-testid*="olumn"]:nth-of-type(1) {{
        min-width: 64px !important; max-width: 64px !important; flex: 0 0 64px !important;
        background-color: #0B0E14 !important;
        border-right: 1px solid rgba(255,255,255,0.05) !important;
        padding: 16px 0 16px 0 !important;
        display: flex !important;
        flex-direction: column !important;
        align-items: center !important;
    }}
    /* RIGHT PANE — Module Content */
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] div[data-testid*="olumn"]:nth-of-type(2) {{
        min-width: 256px !important; max-width: 256px !important; flex: 0 0 256px !important;
        background-color: #11151C !important;
        padding: 0 !important;
        overflow-y: auto !important;
    }}

    /* ══════════════════════════════════════════════════
       RAIL ICON BUTTONS — Base structure
       Squircle 44×44, 14px radius, centered
       ══════════════════════════════════════════════════ */
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] div[data-testid*="olumn"]:nth-of-type(1) button {{
        width: 44px !important; height: 44px !important;
        border-radius: 14px !important;
        background: rgba(255,255,255,0.03) !important;
        border: 1px solid rgba(255,255,255,0.04) !important;
        color: #4B5563 !important;
        display: flex !important;
        align-items: center !important; justify-content: center !important;
        transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1) !important;
        padding: 0 !important;
        margin: 0 auto 10px auto !important;
        position: relative !important;
        box-shadow: none !important;
    }}
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] div[data-testid*="olumn"]:nth-of-type(1) button:hover {{
        background: rgba(255,255,255,0.07) !important;
        border-color: rgba(255,255,255,0.10) !important;
        transform: scale(1.05) !important;
    }}
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] div[data-testid*="olumn"]:nth-of-type(1) button p {{
        font-family: "Font Awesome 6 Free", "FontAwesome" !important;
        font-weight: 900 !important;
        font-size: 1.15rem !important;
        line-height: 1 !important;
        margin: 0 !important; padding: 0 !important;
        color: inherit !important;
    }}

    /* ── INDIVIDUAL RAIL ICON COLORS (Inactive default) ── */
    /* LOGO — Purple glowing satellite dish */
    [data-testid="stSidebar"] div[data-testid="element-container"]:has(.logo-btn-marker) + div[data-testid="element-container"] button {{
        background: linear-gradient(145deg, #7C3AED, #5B21B6) !important;
        border: none !important;
        box-shadow: 0 0 16px rgba(124, 58, 237, 0.45),
                    0 0 40px rgba(124, 58, 237, 0.15) !important;
    }}
    [data-testid="stSidebar"] div[data-testid="element-container"]:has(.logo-btn-marker) + div[data-testid="element-container"] button:hover {{
        box-shadow: 0 0 22px rgba(124, 58, 237, 0.6),
                    0 0 50px rgba(124, 58, 237, 0.2) !important;
    }}
    [data-testid="stSidebar"] div[data-testid="element-container"]:has(.logo-btn-marker) + div[data-testid="element-container"] button p {{
        color: #FFFFFF !important; font-size: 1.25rem !important;
    }}

    /* System — Red Lightning */
    [data-testid="stSidebar"] div[data-testid="element-container"]:has(.sys-btn-marker) + div[data-testid="element-container"] button p {{
        color: #EF4444 !important;
    }}
    /* Alarm — Yellow Bell */
    [data-testid="stSidebar"] div[data-testid="element-container"]:has(.alr-btn-marker) + div[data-testid="element-container"] button p {{
        color: #FBBF24 !important;
    }}
    /* Filters — Cyan Grid */
    [data-testid="stSidebar"] div[data-testid="element-container"]:has(.flt-btn-marker) + div[data-testid="element-container"] button p {{
        color: #22D3EE !important;
    }}
    /* Quick — Purple Diamond */
    [data-testid="stSidebar"] div[data-testid="element-container"]:has(.qck-btn-marker) + div[data-testid="element-container"] button p {{
        color: #A78BFA !important;
    }}
    /* Logout — Muted Blue */
    [data-testid="stSidebar"] div[data-testid="element-container"]:has(.out-btn-marker) + div[data-testid="element-container"] button {{
        background: rgba(59, 130, 246, 0.08) !important;
        border-color: rgba(59, 130, 246, 0.12) !important;
    }}
    [data-testid="stSidebar"] div[data-testid="element-container"]:has(.out-btn-marker) + div[data-testid="element-container"] button p {{
        color: #3B82F6 !important;
    }}
    [data-testid="stSidebar"] div[data-testid="element-container"]:has(.out-btn-marker) + div[data-testid="element-container"] button:hover {{
        background: rgba(59, 130, 246, 0.18) !important;
    }}

    /* ══════════════════════════════════════════════════
       PANEL CONTENT — Headers, labels, cards
       ══════════════════════════════════════════════════ */
    .panel-header {{
        display: flex; align-items: flex-start; justify-content: space-between;
        padding: 22px 18px 14px 18px;
        border-bottom: 1px solid rgba(255,255,255,0.05);
        margin-bottom: 18px;
        position: relative;
    }}
    .panel-module-label {{
        font-family: 'Inter', sans-serif;
        font-size: 0.6rem; font-weight: 700; color: #4B5563;
        letter-spacing: 2.5px; text-transform: uppercase; margin-bottom: 4px;
    }}
    .panel-title {{
        font-family: 'Inter', sans-serif;
        font-size: 1.35rem; font-weight: 800; color: #F9FAFB;
        line-height: 1.2;
    }}

    /* Close Button — absolute top-right ✕ */
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] div[data-testid*="olumn"]:nth-of-type(2) div[data-testid="element-container"]:has(.panel-header) + div[data-testid="element-container"] button {{
        position: absolute !important;
        top: 22px !important;
        right: 18px !important;
        width: 30px !important; height: 30px !important;
        border-radius: 8px !important;
        background: rgba(255,255,255,0.04) !important;
        border: 1px solid rgba(255,255,255,0.06) !important;
        color: #6B7280 !important;
        padding: 0 !important;
        display: flex !important; align-items: center !important; justify-content: center !important;
        z-index: 9999 !important;
        transition: all 0.2s !important;
    }}
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] div[data-testid*="olumn"]:nth-of-type(2) div[data-testid="element-container"]:has(.panel-header) + div[data-testid="element-container"] button p {{
        font-size: 0.9rem !important; margin: 0 !important; color: inherit !important;
    }}
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] div[data-testid*="olumn"]:nth-of-type(2) div[data-testid="element-container"]:has(.panel-header) + div[data-testid="element-container"] button:hover {{
        background: rgba(255,255,255,0.08) !important; color: #D1D5DB !important;
    }}

    /* Section label (reusable) */
    .section-label {{
        font-family: 'Inter', sans-serif;
        font-size: 0.6rem; font-weight: 700; color: #4B5563;
        letter-spacing: 2.5px; text-transform: uppercase;
        margin: 0 0 10px 0;
    }}

    /* ══════════════════════════════════════════════════
       SYSTEM MODULE — Scan CTA, Cache Card, Sync Btn
       ══════════════════════════════════════════════════ */
    .scan-cta button {{
        background: #161B2E !important;
        border: 1px solid rgba(255,255,255,0.07) !important;
        color: #F9FAFB !important;
        font-family: 'Inter', sans-serif !important;
        font-size: 0.9rem !important; font-weight: 700 !important;
        letter-spacing: 0.5px !important;
        border-radius: 14px !important;
        height: 52px !important; width: 100% !important;
        transition: all 0.25s !important;
        display: inline-flex !important; align-items: center !important; justify-content: center !important;
    }}
    .scan-cta button:hover {{
        background: #1D2440 !important;
        border-color: rgba(59,130,246,0.25) !important;
        box-shadow: 0 0 14px rgba(59,130,246,0.08) !important;
    }}
    .scan-cta button p {{ display: inline-flex !important; align-items: center !important; }}
    .scan-cta button p::before {{
        content: "\\f04b";
        font-family: "Font Awesome 6 Free", "FontAwesome"; font-weight: 900;
        display: inline-flex; align-items: center; justify-content: center;
        background: #3B82F6 !important; color: #FFFFFF !important;
        width: 24px; height: 24px; border-radius: 7px;
        margin-right: 12px; font-size: 0.65rem;
    }}

    .stop-cta button {{
        background: rgba(244, 63, 94, 0.10) !important;
        border: 1px solid rgba(244, 63, 94, 0.25) !important;
        color: #F43F5E !important;
        border-radius: 14px !important; height: 52px !important;
        font-family: 'Inter', sans-serif !important;
        font-weight: 700 !important; font-size: 0.9rem !important;
        box-shadow: 0 0 12px rgba(244,63,94,0.1) !important;
    }}
    .stop-cta button:hover {{
        background: rgba(244, 63, 94, 0.18) !important;
        box-shadow: 0 0 20px rgba(244,63,94,0.2) !important;
    }}

    /* LAST CACHE card */
    .cache-card {{
        background: #161B2E;
        border: 1px solid rgba(255,255,255,0.05);
        border-radius: 14px;
        padding: 14px 16px;
        margin: 16px 0;
    }}
    .cache-label {{
        font-family: 'Inter', sans-serif;
        font-size: 0.55rem; font-weight: 700; color: #4B5563;
        letter-spacing: 2px; text-transform: uppercase; margin-bottom: 6px;
    }}
    .cache-val {{
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.85rem; color: #10B981; font-weight: 500;
        text-shadow: 0 0 8px rgba(16,185,129,0.3);
    }}

    /* SYNC button */
    .sync-btn button {{
        background: #161B2E !important;
        border: 1px solid rgba(255,255,255,0.07) !important;
        color: #9CA3AF !important;
        border-radius: 14px !important; height: 48px !important;
        font-family: 'Inter', sans-serif !important;
        transition: all 0.25s !important;
        display: inline-flex !important; align-items: center !important; justify-content: center !important;
    }}
    .sync-btn button:hover {{
        border-color: rgba(59,130,246,0.2) !important;
        color: #E5E7EB !important; background: #1D2440 !important;
    }}
    .sync-btn button p {{ display: inline-flex !important; align-items: center !important; }}
    .sync-btn button p::before {{
        content: "\\f021";
        font-family: "Font Awesome 6 Free", "FontAwesome"; font-weight: 900;
        display: inline-flex; align-items: center; justify-content: center;
        background: #3B82F6 !important; color: #FFFFFF !important;
        width: 22px; height: 22px; border-radius: 6px;
        margin-right: 12px; font-size: 0.6rem;
    }}

    /* ══════════════════════════════════════════════════
       ALARM MODULE — Send Alarm CTA, Recent Cards
       ══════════════════════════════════════════════════ */
    .alarm-cta button {{
        background: #EF4444 !important;
        border: none !important;
        color: #FFFFFF !important;
        border-radius: 14px !important; height: 52px !important;
        font-family: 'Inter', sans-serif !important;
        font-weight: 700 !important; font-size: 0.9rem !important; letter-spacing: 0.5px !important;
        box-shadow: 0 0 18px rgba(239, 68, 68, 0.35),
                    0 0 40px rgba(239, 68, 68, 0.10) !important;
        transition: all 0.25s !important;
        display: inline-flex !important; align-items: center !important; justify-content: center !important;
    }}
    .alarm-cta button:hover {{
        background: #DC2626 !important;
        box-shadow: 0 0 25px rgba(220, 38, 38, 0.5),
                    0 0 50px rgba(220, 38, 38, 0.15) !important;
        transform: translateY(-1px) !important;
    }}
    .alarm-cta button p {{ display: inline-flex !important; align-items: center !important; }}
    .alarm-cta button p::before {{
        content: "\\f0f3";
        font-family: "Font Awesome 6 Free", "FontAwesome"; font-weight: 900;
        color: #FBBF24 !important;
        margin-right: 12px; font-size: 1rem;
    }}

    /* ══════════════════════════════════════════════════
       FILTERS MODULE — Inputs & Dropdowns
       ══════════════════════════════════════════════════ */
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] div[data-testid*="olumn"]:nth-of-type(2) [data-testid="stSelectbox"] {{
        font-family: 'Inter', sans-serif !important;
    }}
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] div[data-testid*="olumn"]:nth-of-type(2) [data-testid="stSelectbox"] > div > div {{
        background: #161B2E !important;
        border: 1px solid rgba(255,255,255,0.07) !important;
        border-radius: 12px !important;
        color: #E5E7EB !important;
    }}
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] div[data-testid*="olumn"]:nth-of-type(2) [data-testid="stTextInput"] input {{
        background: #161B2E !important;
        border: 1px solid rgba(255,255,255,0.07) !important;
        border-radius: 12px !important;
        color: #E5E7EB !important;
        font-family: 'Inter', sans-serif !important;
    }}
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] div[data-testid*="olumn"]:nth-of-type(2) [data-testid="stTextInput"] input:focus {{
        border-color: rgba(59,130,246,0.4) !important;
        box-shadow: 0 0 0 2px rgba(59,130,246,0.1) !important;
    }}

    /* ══════════════════════════════════════════════════
       GLOBAL STREAMLIT OVERRIDES for sidebar
       ══════════════════════════════════════════════════ */
    [data-testid="stSidebar"] * {{
        font-family: 'Inter', sans-serif !important;
    }}
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] div[data-testid*="olumn"]:nth-of-type(2) [data-testid="stVerticalBlockBorderWrapper"] {{
        padding: 0 18px !important;
    }}
</style>
""", unsafe_allow_html=True)
with st.sidebar:
    rail_col, panel_col = st.columns([1, 4])
    
    with rail_col:
        # LOGO — Glowing Purple Satellite Dish
        st.markdown("<div class='logo-btn-marker'></div>", unsafe_allow_html=True)
        if st.button("\uf7c0", key="rail_logo", help="NETWATCH OPS CENTER"):
            st.session_state['active_panel'] = None
            st.rerun()

        st.markdown("<div style='height: 18px;'></div>", unsafe_allow_html=True)
        
        # SYSTEM — Red Lightning Bolt
        st.markdown("<div class='sys-btn-marker'></div>", unsafe_allow_html=True)
        if st.button("\uf0e7", key="rail_sys", help="System Controls"):
            st.session_state['active_panel'] = 'system' if active_panel != 'system' else None
            st.rerun()
            
        # ALARM — Yellow Bell
        st.markdown("<div class='alr-btn-marker'></div>", unsafe_allow_html=True)
        if st.button("\uf0f3", key="rail_alr", help="Alarm Center"):
            st.session_state['active_panel'] = 'alarm' if active_panel != 'alarm' else None
            st.rerun()
            
        # FILTERS — Cyan Grid/Layout
        st.markdown("<div class='flt-btn-marker'></div>", unsafe_allow_html=True)
        if st.button("\uf0db", key="rail_flt", help="Data Filters"):
            st.session_state['active_panel'] = 'filters' if active_panel != 'filters' else None
            st.rerun()
            
        # QUICK — Purple Diamond
        st.markdown("<div class='qck-btn-marker'></div>", unsafe_allow_html=True)
        if st.button("\uf219", key="rail_qck", help="Quick Filters"):
            st.session_state['active_panel'] = 'quick' if active_panel != 'quick' else None
            st.rerun()
            
        # Spacer to push logout to bottom
        st.markdown("<div style='flex:1; min-height: 30vh;'></div>", unsafe_allow_html=True)
        
        # LOGOUT — Muted Blue Sign-out
        st.markdown("<div class='out-btn-marker'></div>", unsafe_allow_html=True)
        if st.button("\uf2f5", key="rail_out", help="Logout"):
            _delete_session(st.session_state.get('session_token', ''))
            st.session_state['logged_in'] = False
            st.session_state['session_token'] = None
            st.session_state['login_time'] = None
            st.query_params.clear()
            st.rerun()

    # ── Dynamic CSS: Active state glow + notification dots ──
    dynamic_css = ""
    if active_panel:
        marker_map = {'system': 'sys', 'alarm': 'alr', 'filters': 'flt', 'quick': 'qck'}
        m_name = marker_map.get(active_panel)
        if m_name:
            # Active icon gets brighter bg + subtle glow
            dynamic_css += f"""
            [data-testid="stSidebar"] div[data-testid="element-container"]:has(.{m_name}-btn-marker) + div[data-testid="element-container"] button {{
                background: rgba(255, 255, 255, 0.10) !important;
                border: 1px solid rgba(255, 255, 255, 0.18) !important;
                box-shadow: 0 0 12px rgba(255,255,255,0.04) !important;
            }}
            """

    # Scanning indicator dot on System
    if st.session_state.get('is_scanning', False):
        dynamic_css += """
        [data-testid="stSidebar"] div[data-testid="element-container"]:has(.sys-btn-marker) + div[data-testid="element-container"] button { overflow: visible !important; }
        [data-testid="stSidebar"] div[data-testid="element-container"]:has(.sys-btn-marker) + div[data-testid="element-container"] button::after {
            content: ''; position: absolute; top: 5px; right: 5px;
            width: 10px; height: 10px; background: #00F0FF;
            border-radius: 50%; border: 2px solid #0B0E14; z-index: 10;
            box-shadow: 0 0 6px rgba(0,240,255,0.5);
        }
        """

    # Filter active dot on Filters icon
    if st.session_state.get('selected_olt', 'All OLT') != 'All OLT' or st.session_state.get('search_sn_sidebar'):
        dynamic_css += """
        [data-testid="stSidebar"] div[data-testid="element-container"]:has(.flt-btn-marker) + div[data-testid="element-container"] button { overflow: visible !important; }
        [data-testid="stSidebar"] div[data-testid="element-container"]:has(.flt-btn-marker) + div[data-testid="element-container"] button::after {
            content: ''; position: absolute; top: 5px; right: 5px;
            width: 10px; height: 10px; background: #F43F5E;
            border-radius: 50%; border: 2px solid #0B0E14; z-index: 10;
            box-shadow: 0 0 6px rgba(244,63,94,0.5);
        }
        """
    
    # Quick filter active dot
    active_filters_dot = st.session_state.get('filter_mode', {'Online', 'LOS', 'BadRx', 'Dyinggasp', 'Suspend'})
    is_filtered_dot = False
    if isinstance(active_filters_dot, str):
        is_filtered_dot = (active_filters_dot != 'All')
    else:
        is_filtered_dot = (len(active_filters_dot) < 5)
        
    if is_filtered_dot:
        dynamic_css += """
        [data-testid="stSidebar"] div[data-testid="element-container"]:has(.qck-btn-marker) + div[data-testid="element-container"] button { overflow: visible !important; }
        [data-testid="stSidebar"] div[data-testid="element-container"]:has(.qck-btn-marker) + div[data-testid="element-container"] button::after {
            content: ''; position: absolute; top: 5px; right: 5px;
            width: 10px; height: 10px; background: #F43F5E;
            border-radius: 50%; border: 2px solid #0B0E14; z-index: 10;
            box-shadow: 0 0 6px rgba(244,63,94,0.5);
        }
        """

    # Alarm bell notification dot (always show on alarm icon)
    dynamic_css += """
    [data-testid="stSidebar"] div[data-testid="element-container"]:has(.alr-btn-marker) + div[data-testid="element-container"] button { overflow: visible !important; }
    [data-testid="stSidebar"] div[data-testid="element-container"]:has(.alr-btn-marker) + div[data-testid="element-container"] button::after {
        content: ''; position: absolute; top: 5px; right: 5px;
        width: 10px; height: 10px; background: #EF4444;
        border-radius: 50%; border: 2px solid #0B0E14; z-index: 10;
        box-shadow: 0 0 6px rgba(239,68,68,0.5);
    }
    """

    if dynamic_css:
        st.markdown(f"<style>{dynamic_css}</style>", unsafe_allow_html=True)
        
    with panel_col:
        # ── Panel Header: MODULE label + title + close ──
        if active_panel:
            panel_titles = {'system': 'System', 'alarm': 'Alarm', 'filters': 'Filters', 'quick': 'Quick'}
            st.markdown(f"""
            <div class='panel-header'>
                <div>
                    <div class='panel-module-label'>MODULE</div>
                    <div class='panel-title'>{panel_titles.get(active_panel, '')}</div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            if st.button("✕", key="panel_close"):
                st.session_state['active_panel'] = None
                st.rerun()

        # ════════════════════════════════════════════════
        # STATE A — SYSTEM MODULE
        # ════════════════════════════════════════════════
        if active_panel == 'system':
            st.markdown("<div class='section-label' style='padding: 0 0;'>SCAN ENGINE</div>", unsafe_allow_html=True)
            
            is_running = st.session_state.get('is_scanning', False)
            if is_running:
                st.markdown("<div class='stop-cta'>", unsafe_allow_html=True)
                if st.button("⏹  STOP SCANNING", use_container_width=True):
                    st.session_state['is_scanning'] = False
                    st.session_state['stop_scanning'] = True
                    if 'temp_results' in st.session_state and st.session_state['temp_results']:
                        final_df = pd.DataFrame(st.session_state['temp_results'])
                        if not final_df.empty:
                            final_df['Serial Number'] = final_df['Serial Number'].astype(str).str.strip().str.upper()
                            final_df['Nama/ID Pelanggan'] = final_df['Nama/ID Pelanggan'].astype(str).str.strip().str.upper()
                            final_df = final_df.drop_duplicates(subset=['Serial Number'], keep='first')
                            st.session_state['data_final'] = final_df
                            save_scan_results(final_df)
                    st.rerun()
                st.markdown("</div>", unsafe_allow_html=True)
            else:
                st.markdown("<div class='scan-cta'>", unsafe_allow_html=True)
                if st.button("START SCAN", use_container_width=True):
                    st.session_state['is_scanning'] = True
                    st.session_state['stop_scanning'] = False
                    st.session_state['temp_results'] = []
                    st.session_state['data_final'] = pd.DataFrame()
                    st.rerun()
                st.markdown("</div>", unsafe_allow_html=True)

            _last_sync = get_last_sync_time()
            st.markdown(f"""
            <div class='cache-card'>
                <div class='cache-label'>LAST CACHE</div>
                <div class='cache-val'>{_last_sync}</div>
            </div>
            """, unsafe_allow_html=True)
            
            st.markdown("<div class='sync-btn'>", unsafe_allow_html=True)
            if st.button("Sync Google Sheets", use_container_width=True):

                with st.spinner("Fetching data from all Google Sheets tabs..."):
                    try:
                        _gconn = st.connection("gsheets", type=GSheetsConnection)
                        from io import StringIO
                        import pandas as pd
                        SPREADSHEET_ID = "1lQYkUIFhzW5oWDUWSjOlR1PGhSBl8gMH7uQQxeX3_xw"
                        target_sheets_gid = {
                            "Fatmawati": "0", "Senopati": "570642648", "Cinere": "912514856",
                            "Lenteng Agung": "162726682", "Cipedak": "2107355748", "Pinang/kalijati": "1647719979"
                        }
                        all_data = []
                        _sheet_errors = {}
                        for sheet_name, _gid in target_sheets_gid.items():
                            try:
                                _csv_url = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid={_gid}"
                                df_sheet = pd.read_csv(_csv_url)
                                if df_sheet is not None and not df_sheet.empty:
                                    if sheet_name == "Senopati" and str(df_sheet.columns[0]).startswith("Unnamed:"):
                                        expected_cols = ['OLT', 'IP_OLT', 'SN', 'PORT', 'NAMA_ID PELANGGAN', 'Unnamed: 5', 'NAMA PELANGGAN', 'ID_PELANGGAN', 'ID SPLITTER', 'ALAMAT', 'Latitude', 'Longitude', 'Link Maps']
                                        df_sheet.columns = expected_cols[:len(df_sheet.columns)]
                                    all_data.append(df_sheet)
                            except Exception as e_sheet:
                                _sheet_errors[sheet_name] = str(e_sheet)
                        if _sheet_errors:
                            for _sn, _se in _sheet_errors.items(): st.error(f"❌ Tab '{_sn}': {_se}")
                        if all_data:
                            _df_sync_combined = pd.concat(all_data, ignore_index=True)
                            cache_input_from_gsheets(_df_sync_combined)
                            st.success(f"✅ {len(_df_sync_combined)} rows from {len(all_data)} regions successfully cached to SQLite!")
                        else:
                            st.warning("⚠️ Google Sheets returned no data from all tabs.")
                    except Exception as _e:
                        st.error(f"❌ Failed to connect to Google Sheets: {_e}")
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

        # ════════════════════════════════════════════════
        # STATE B — ALARM MODULE
        # ════════════════════════════════════════════════
        elif active_panel == 'alarm':
            region_options = ["All Regions", "Fatmawati", "Cipedak", "Pinang/Kalijati", "Lenteng Agung", "Cinere", "Senopati"]
            st.markdown("<p style='color:#4B5563; font-size:0.6rem; font-weight:700; letter-spacing:2.5px; text-transform:uppercase; margin:12px 0 5px 0;'>TARGET REGION</p>", unsafe_allow_html=True)
            selected_region_alarm = st.selectbox("Target Alarm Region:", region_options, label_visibility="collapsed")
            
            btn_disabled = st.session_state.get('data_final', pd.DataFrame()).empty
            st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
            st.markdown('<div class="alarm-cta">', unsafe_allow_html=True)
            if st.button("SEND ALARM", use_container_width=True, disabled=btn_disabled):
                df_problems = st.session_state['data_final'][st.session_state['data_final']['Category'].isin(['LOS', 'BadRx'])]
                if df_problems.empty:
                    st.sidebar.info("System Healthy: No Alarms Needed")
                else:
                    to_send = []
                    for row in df_problems.to_dict('records'):
                        row_region = get_region_from_olt(row.get('OLT', ''))
                        if selected_region_alarm != "All Regions" and row_region != selected_region_alarm: continue
                        if should_send_alarm(row.get('Serial Number', ''), row.get('Category', '')): to_send.append(row)
                    if to_send:
                        st.success(f"{len(to_send)} Alarms Sent to {selected_region_alarm}!")
                        for row in to_send:
                            msg_id = send_telegram_alarm(row)
                            if msg_id: save_alarm_sent(msg_id, row)
                    else:
                        st.info("No new alarms to send (or already sent).")
            st.markdown('</div>', unsafe_allow_html=True)
            
            # RECENT ALARMS — Badge + card list
            st.markdown("<p style='color:#4B5563; font-size:0.6rem; font-weight:700; letter-spacing:2.5px; text-transform:uppercase; margin:25px 0 12px 0;'>RECENT ALARMS</p>", unsafe_allow_html=True)
            df_log = get_all_alarm_history().head(3)
            if not df_log.empty:
                for _, log in df_log.iterrows():
                    cat = str(log.get('Category', log.get('category','ALARM'))).upper()
                    sn = log.get('Serial Number', log.get('sn',''))
                    ts = log.get('Waktu Alarm Dikirim', log.get('timestamp',''))
                    
                    try:
                        t_str = ts.split(" ")[1][:5] if " " in str(ts) else str(ts)[:5]
                    except:
                        t_str = "08:00"
                        
                    sev = "HIGH" if cat in ['LOS', 'OFFLINE'] else ("MED" if cat in ['BADRX', 'WARNING'] else "LOW")
                    sev_color = "#F43F5E" if sev == "HIGH" else ("#F59E0B" if sev == "MED" else "#3B82F6")
                    sev_bg = "rgba(244,63,94,0.12)" if sev == "HIGH" else ("rgba(245,158,11,0.12)" if sev == "MED" else "rgba(59,130,246,0.12)")
                    
                    st.markdown(f"""
                    <div style='display:flex; align-items:center; gap:10px;
                        background:#161B2E; border:1px solid rgba(255,255,255,0.05);
                        padding:11px 14px; border-radius:12px; margin-bottom:8px;'>
                        <span style='background:{sev_bg}; color:{sev_color}; font-size:0.6rem; font-weight:700;
                            padding:3px 10px; border-radius:6px; min-width:42px; text-align:center;
                            letter-spacing:0.5px;'>{sev}</span>
                        <span style='color:#E5E7EB; font-size:0.8rem; font-weight:500; flex:1;
                            white-space:nowrap; overflow:hidden; text-overflow:ellipsis;'>{sn}</span>
                        <span style='color:#4B5563; font-size:0.72rem; font-weight:500;'>{t_str}</span>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.markdown("<p style='font-size:0.75rem; color:#4B5563;'>No recent logs.</p>", unsafe_allow_html=True)

        # ════════════════════════════════════════════════
        # STATE C — FILTERS MODULE
        # ════════════════════════════════════════════════
        elif active_panel == 'filters':
            st.markdown("<p style='color:#4B5563; font-size:0.6rem; font-weight:700; letter-spacing:2.5px; text-transform:uppercase; margin:12px 0 5px 0;'>SELECT REGION</p>", unsafe_allow_html=True)
            data_final = st.session_state.get('data_final', pd.DataFrame())
            if not data_final.empty:
                from components.telegram import get_region_from_olt
                regions = sorted(list(set(data_final['OLT'].apply(get_region_from_olt))))
                olt_options = ["All OLT"] + regions
                selected_olt = st.selectbox("Select Region:", options=olt_options, index=olt_options.index(st.session_state.get('selected_olt', 'All OLT')), label_visibility="collapsed")
                st.session_state['selected_olt'] = selected_olt
            else:
                st.selectbox("Select Region:", options=["Waiting for Scan..."], disabled=True, label_visibility="collapsed")
            
            st.markdown("<p style='color:#4B5563; font-size:0.6rem; font-weight:700; letter-spacing:2.5px; text-transform:uppercase; margin:20px 0 5px 0;'>SEARCH SN / NAME</p>", unsafe_allow_html=True)
            s_term = st.text_input("Search SN / Name:", value=st.session_state.get('search_sn_sidebar', ''), label_visibility="collapsed", placeholder="🔍  Search...")
            st.session_state['search_sn_sidebar'] = s_term
            
            if st.session_state.get('selected_olt', 'All OLT') != 'All OLT' or st.session_state.get('search_sn_sidebar'):
                st.markdown("<div style='height:15px;'></div>", unsafe_allow_html=True)
                if st.button("Clear Filters", use_container_width=True):
                    st.session_state['selected_olt'] = 'All OLT'
                    st.session_state['search_sn_sidebar'] = ''
                    st.rerun()

        # ════════════════════════════════════════════════
        # STATE D — QUICK FILTERS MODULE
        # ════════════════════════════════════════════════
        elif active_panel == 'quick':
            active_filters = st.session_state.get('filter_mode', {'Online', 'LOS', 'BadRx', 'Dyinggasp', 'Suspend'})
            if isinstance(active_filters, str):
                active_filters = {'Online', 'LOS', 'BadRx', 'Dyinggasp', 'Suspend'} if active_filters == 'All' else {active_filters}
                st.session_state['filter_mode'] = active_filters

            filter_config = {
                "Online":    {"color": "#10B981", "icon_bg": "rgba(16,185,129,0.15)",  "fa_code": "\\f0ac",  "label": "Online"},
                "LOS":       {"color": "#EF4444", "icon_bg": "rgba(239,68,68,0.15)",   "fa_code": "\\f00d",  "label": "Offline"},
                "BadRx":     {"color": "#F59E0B", "icon_bg": "rgba(245,158,11,0.15)",  "fa_code": "\\f071",  "label": "Warning"},
                "Dyinggasp": {"color": "#A855F7", "icon_bg": "rgba(168,85,247,0.15)",  "fa_code": "\\f1e6",  "label": "Power"},
                "Suspend":   {"color": "#6B7280", "icon_bg": "rgba(107,114,128,0.15)", "fa_code": "\\f023",  "label": "Locked"},
            }

            active_count = len(active_filters)

            # Section header
            st.markdown("""
            <p style='color:#4B5563; font-size:0.6rem; font-weight:700; letter-spacing:2.5px;
                text-transform:uppercase; margin:12px 0 14px 0;'>STATUS FILTERS</p>
            """, unsafe_allow_html=True)

            # ── Generate per-chip CSS: transform st.button into styled chip ──
            chip_css = "<style>"
            for mode, cfg in filter_config.items():
                is_active = (mode in active_filters)
                bg      = f"{cfg['color']}14" if is_active else "rgba(255,255,255,0.02)"
                border  = f"1.5px solid {cfg['color']}50" if is_active else "1px solid rgba(255,255,255,0.05)"
                border_active = f"1.5px solid {cfg['color']}" if is_active else border
                txt_col = "#F3F4F6" if is_active else "#6B7280"
                chk_bg  = cfg['color'] if is_active else "rgba(255,255,255,0.06)"
                chk_ch  = "\\2713" if is_active else ""
                chk_col = "#fff" if is_active else "transparent"
                m       = f"qck-m-{mode.lower()}"

                chip_css += f"""
                /* ── {cfg['label']} chip ── */
                div[data-testid="element-container"]:has(.{m}) {{
                    margin-bottom: 0 !important;
                    padding: 0 !important;
                    height: 0 !important;
                    overflow: visible !important;
                }}
                div[data-testid="element-container"]:has(.{m}) + div[data-testid="element-container"] {{
                    margin-bottom: 10px !important;
                }}
                div[data-testid="element-container"]:has(.{m}) + div[data-testid="element-container"] button {{
                    background: {bg} !important;
                    border: {border_active} !important;
                    border-radius: 14px !important;
                    height: 52px !important;
                    width: 100% !important;
                    padding: 0 14px !important;
                    display: flex !important;
                    align-items: center !important;
                    justify-content: flex-start !important;
                    gap: 12px !important;
                    cursor: pointer !important;
                    transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1) !important;
                    box-shadow: none !important;
                }}
                div[data-testid="element-container"]:has(.{m}) + div[data-testid="element-container"] button:hover {{
                    background: {cfg['color']}20 !important;
                    border-color: {cfg['color']}80 !important;
                }}
                div[data-testid="element-container"]:has(.{m}) + div[data-testid="element-container"] button::before {{
                    content: "{cfg['fa_code']}";
                    font-family: "Font Awesome 6 Free", "FontAwesome";
                    font-weight: 900;
                    background: {cfg['icon_bg']};
                    color: {cfg['color']};
                    min-width: 34px; width: 34px; height: 34px;
                    border-radius: 10px;
                    display: inline-flex;
                    align-items: center; justify-content: center;
                    font-size: 0.85rem;
                    flex-shrink: 0;
                }}
                div[data-testid="element-container"]:has(.{m}) + div[data-testid="element-container"] button p {{
                    flex: 1 !important;
                    text-align: left !important;
                    color: {txt_col} !important;
                    font-size: 0.88rem !important;
                    font-weight: 600 !important;
                    margin: 0 !important;
                    font-family: 'Inter', sans-serif !important;
                }}
                div[data-testid="element-container"]:has(.{m}) + div[data-testid="element-container"] button::after {{
                    content: "{chk_ch}";
                    background: {chk_bg};
                    color: {chk_col};
                    min-width: 22px; width: 22px; height: 22px;
                    border-radius: 50%;
                    display: inline-flex;
                    align-items: center; justify-content: center;
                    font-size: 0.55rem; font-weight: 800;
                    margin-left: auto;
                    flex-shrink: 0;
                    border: {f"2px solid {cfg['color']}40" if is_active else "1.5px solid rgba(255,255,255,0.08)"};
                }}
                """
            chip_css += "</style>"
            st.markdown(chip_css, unsafe_allow_html=True)

            # ── Render each chip as a real st.button ──
            for mode, cfg in filter_config.items():
                m = f"qck-m-{mode.lower()}"
                st.markdown(f"<div class='{m}'></div>", unsafe_allow_html=True)
                if st.button(cfg["label"], key=f"qf_toggle_{mode}", use_container_width=True):
                    if mode in active_filters:
                        active_filters.discard(mode)
                    else:
                        active_filters.add(mode)
                    st.session_state['filter_mode'] = active_filters
                    st.rerun()

            # ── Footer: "X of 5 active" + Select/Clear all ──
            has_all = active_count == 5
            lnk_label = "Clear all" if has_all else "Select all"
            st.markdown(f"""
            <style>
            div[data-testid="element-container"]:has(.qck-footer-marker) + div[data-testid="element-container"] button {{
                background: transparent !important; border: none !important;
                color: #3B82F6 !important; font-size: 0.7rem !important;
                font-weight: 600 !important; padding: 0 !important;
                height: auto !important; min-height: 0 !important;
                box-shadow: none !important; cursor: pointer !important;
            }}
            div[data-testid="element-container"]:has(.qck-footer-marker) + div[data-testid="element-container"] button:hover {{
                color: #60A5FA !important; text-decoration: underline !important;
            }}
            div[data-testid="element-container"]:has(.qck-footer-marker) + div[data-testid="element-container"] button p {{
                color: inherit !important; font-size: inherit !important;
            }}
            </style>
            <div style='display:flex; align-items:center; justify-content:space-between; margin-top:8px; padding:0;'>
                <span style='font-size:0.72rem; color:#4B5563; font-weight:500;
                    font-family:Inter,sans-serif;'>{active_count} of 5 active</span>
            </div>
            <div class='qck-footer-marker'></div>
            """, unsafe_allow_html=True)
            if st.button(lnk_label, key="qf_clear_all", use_container_width=False):
                st.session_state['filter_mode'] = set() if has_all else {'Online', 'LOS', 'BadRx', 'Dyinggasp', 'Suspend'}
                st.rerun()
# --- FILTER DATA FOR DISPLAY ---
df_raw = st.session_state['data_final']
df_filtered = df_raw.copy()

if not df_raw.empty:
    active_filters = st.session_state.get('filter_mode', {'Online', 'LOS', 'BadRx', 'Dyinggasp', 'Suspend'})
    if isinstance(active_filters, str):
        if active_filters == 'All':
            active_filters = {'Online', 'LOS', 'BadRx', 'Dyinggasp', 'Suspend'}
        else:
            active_filters = {active_filters}
        st.session_state['filter_mode'] = active_filters
    
    if len(active_filters) < 5:
        df_filtered = df_filtered[df_filtered['Category'].isin(active_filters)]
    if st.session_state.get('selected_olt', 'All OLT') != "All OLT":
        from components.telegram import get_region_from_olt
        df_filtered = df_filtered[df_filtered['OLT'].apply(get_region_from_olt) == st.session_state.get('selected_olt')]
    if st.session_state.get('search_sn_sidebar'):
        s_term = st.session_state.get('search_sn_sidebar')
        df_filtered = df_filtered[df_filtered.astype(str).apply(lambda x: x.str.contains(s_term, case=False)).any(axis=1)]

# --- RENDER DASHBOARD (Hanya tampil jika TIDAK sedang proses scan) ---
if not st.session_state.get('is_scanning', False):
    # Brand Header
    st.markdown("""
    <div style='margin-bottom: 25px;'>
        <h1 style='color: #00F0FF; font-size: 2rem; font-weight: 800; margin-bottom: 5px; text-shadow: 0 0 10px rgba(0, 240, 255, 0.2);'>
            NETWATCH OPS CENTER
        </h1>
        <p style='color: #8B949E; font-size: 0.9rem; margin-top: 0px;'>
            Enterprise Cybersecurity Command Center | Integrated OLT Monitoring System
        </p>
    </div>
    """, unsafe_allow_html=True)

    # --- RENDER METRICS & RISK SCORE GAUGE (STICKY HEADER) ---
    render_metrics(df_filtered)


    st.markdown("<br>", unsafe_allow_html=True)
    tab1, tab2, tab3 = st.tabs(["🌍 Live Monitoring", "📈 Analytics & Trend", "🛠️ Field Updates"])
    
    with tab1:

        render_map(df_filtered)
        st.markdown("<div style='margin-top: 1rem;'></div>", unsafe_allow_html=True)
        render_table(df_filtered)

    with tab2:
        # --- RENDER HISTORICAL TREND CHART ---
        df_trend = get_historical_trend()
        with st.expander("📈 Historical Problem Trend", expanded=True):
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
    # PANEL: FIELD TECHNICIAN UPDATES  (auto-refresh setiap 12 detik via fragment)
    # ─────────────────────────────────────────────────────────────────────────────
    import math

    @st.fragment(run_every=12)
    def render_field_tech_panel():
        def _resolve_alarm_cb(sn_val):
            update_alarm_status_by_sn(sn_val, 'Resolved')
            
        def _cancel_alarm_cb(sn_val):
            update_alarm_status_by_sn(sn_val, 'Cancelled')

        df_field_updates = get_alarm_updates(limit=200)

        col_h1, col_h2 = st.columns([5, 1])
        with col_h1:
            # Timestamp auto-refresh kecil di pojok judul
            _now_str = dt.datetime.now(dt.timezone(dt.timedelta(hours=7))).strftime("%H:%M:%S")
            st.markdown(f"""<div style='
                margin-top: 12px;
                padding: 16px 20px 12px 20px;
                border-radius: 10px;
                border: 1px solid #30363D;
                background: rgba(22,27,34,0.85);
            '>
                <p style='margin:0; font-size:1rem; font-weight:700;
                          letter-spacing:1px; color:#c9d1d9;'>
                    🛠️ FIELD TECHNICIAN UPDATES
                    <span style='font-size:0.75rem; font-weight:400; color:#484f58; margin-left:8px;'>
                        — hanya menampilkan alarm aktif (Sent / In Progress)
                    </span>
                    <span style='font-size:0.72rem; font-weight:400; color:#3fb950; margin-left:16px;'>
                        🔴 LIVE · Upd {_now_str}
                    </span>
                </p>
            </div>
            """, unsafe_allow_html=True)
        with col_h2:
            st.markdown("<div style='margin-top:20px;'></div>", unsafe_allow_html=True)
            if st.button("🔄 Refresh", key="refresh_tech", use_container_width=True):
                st.rerun(scope="fragment")

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
                    f"<span style='font-family:\"JetBrains Mono\", monospace; font-size:0.85rem; color:#c9d1d9; text-transform:uppercase; "
                    f"letter-spacing:0.5px; font-weight:800;'>{ht}</span>",
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
                    f"<span style='font-family:\"JetBrains Mono\", monospace; font-size:0.95rem; color:#58a6ff; font-weight:700;'>{sn[:14]}</span>",
                    unsafe_allow_html=True
                )
                row_cols[1].markdown(
                    f"<span style='font-family:\"JetBrains Mono\", monospace; font-size:0.95rem; color:#ffffff; font-weight:600;'>{r.get('pelanggan', '-')}</span>",
                    unsafe_allow_html=True
                )
                row_cols[2].markdown(
                    f"<span style='font-family:\"JetBrains Mono\", monospace; font-size:0.95rem; color:#f5a623; font-weight:700;'>{r.get('category', '-')}</span>",
                    unsafe_allow_html=True
                )
                row_cols[3].markdown(_badge(status), unsafe_allow_html=True)
                row_cols[4].markdown(
                    f"<span style='font-family:\"JetBrains Mono\", monospace; font-size:0.95rem; color:#e6edf3; font-weight:500;'>{tech}</span>",
                    unsafe_allow_html=True
                )
                row_cols[5].markdown(
                    f"<span style='font-family:\"JetBrains Mono\", monospace; font-size:0.95rem; color:#e6edf3; font-weight:500;'>{reply}</span>",
                    unsafe_allow_html=True
                )
                row_cols[6].markdown(
                    f"<span style='font-family:\"JetBrains Mono\", monospace; font-size:0.85rem; color:#a5d6ff; font-weight:500;'>Sent {sent_short}<br>Upd {ra_short}</span>",
                    unsafe_allow_html=True
                )

                # --- TOMBOL AKSI ---
                with row_cols[7]:
                    btn_col1, btn_col2 = st.columns(2)
                    with btn_col1:
                        st.button("✅", key=f"resolve_{sn}_{idx}", help="Tandai Selesai (Resolved)", on_click=_resolve_alarm_cb, args=(sn,))
                    with btn_col2:
                        st.button("❌", key=f"cancel_{sn}_{idx}", help="Batalkan (Cancelled)", on_click=_cancel_alarm_cb, args=(sn,))

                st.markdown("<hr style='margin:2px 0; border-color:#21262d;'>", unsafe_allow_html=True)
            
            # --- PAGINATION CONTROLS ---
            st.markdown("<br>", unsafe_allow_html=True)
            p_col1, p_col2, p_col3, _ = st.columns([1, 1, 2, 4])
            with p_col1:
                if st.button("⬅️ Prev", disabled=(st.session_state['tech_page'] == 0), use_container_width=True):
                    st.session_state['tech_page'] -= 1
                    st.rerun(scope="fragment")
            with p_col2:
                if st.button("Next ➡️", disabled=(st.session_state['tech_page'] >= total_pages - 1), use_container_width=True):
                    st.session_state['tech_page'] += 1
                    st.rerun(scope="fragment")
            with p_col3:
                st.markdown(f"<div style='padding-top:8px; color:#8b949e; font-size:0.85rem;'>Page {st.session_state['tech_page'] + 1} of {total_pages} (Total: {len(df_field_updates)})</div>", unsafe_allow_html=True)

        st.markdown("<hr style='border-color:#21262d; margin-top:8px;'>", unsafe_allow_html=True)

        # Spacer
        st.write("")
        st.write("")

    with tab3:
        render_field_tech_panel()


# --- SCANNING ENGINE ---
if st.session_state['is_scanning']:
    st.toast("Starting Audit Engine...")
    
    # Header for Stopwatch & Status
    status_placeholder = st.empty()
    terminal_placeholder = st.empty()
    loader = st.progress(0)
    term_lines = []
    
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
                    "→ Klik **SYNC GOOGLE SHEETS** di sidebar untuk mengisi cache."
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
                
                active_olts = [olt_map[futures_to_ip[f]]["name"] for f in pending][:3]
                running_text = "<br>".join([f"<div class='terminal-line'><span class='term-warn term-blink'>[RUNNING]</span> Pinging {name}...</div>" for name in active_olts])
                
                term_content = "".join(term_lines) + running_text
                terminal_placeholder.markdown(f"<div class='terminal-scanner'>{term_content}</div>", unsafe_allow_html=True)
                
                for f in done:
                    ip_done = futures_to_ip[f]
                    name_done = olt_map[ip_done]['name']
                    scan_results = f.result()
                    term_lines.append(f"<div class='terminal-line'><span class='term-ok'>[OK]</span> {name_done}: Scanned {len(scan_results)} ONT endpoints.</div>")
                    if len(term_lines) > 20: term_lines.pop(0)
                    
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
                    terminal_placeholder.empty()
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
            time.sleep(0.2)
        
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
            time.sleep(0.2)

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
        terminal_placeholder.empty()
        st.rerun()
        
    except Exception as e:
        if "getaddrinfo failed" in str(e):
            st.error("❌ Google Sheets Connection Error: Hostname could not be resolved. Please check your internet connection or DNS settings.")
        else:
            st.error(f"❌ Scan Engine Error: {str(e)}")
        st.session_state['is_scanning'] = False
        st.session_state['stop_scanning'] = False

# --- LAPORAN EXCEL ---
if not st.session_state.get('is_scanning', False):
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
