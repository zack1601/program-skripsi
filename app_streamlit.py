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
    st.session_state['filter_mode'] = 'All'
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
<style>
    [data-testid="stSidebar"] {{
        min-width: {sidebar_width} !important;
        max-width: {sidebar_width} !important;
        transition: min-width 0.3s cubic-bezier(0.4, 0, 0.2, 1), max-width 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
        overflow-x: hidden !important;
        background-color: #0d0d12 !important;
        padding: 0 !important;
    }}
    [data-testid="stSidebarCollapseButton"] {{ display: none !important; }}
    [data-testid="stSidebar"] > div:first-child {{ padding: 0 !important; overflow: visible !important; }}
    [data-testid="stSidebar"] [data-testid="stSidebarContent"] {{ padding: 0 !important; }}
    [data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {{ padding: 0 !important; }}

    /* Column layout hack */
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] {{
        flex-wrap: nowrap !important;
        gap: 0 !important;
        padding: 0 !important;
        margin: 0 !important;
        height: 100vh !important;
    }}
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] div[data-testid*="olumn"]:nth-of-type(1) {{
        min-width: 64px !important; max-width: 64px !important; flex: 0 0 64px !important;
        background-color: #0d0d12 !important;
        border-right: 1px solid rgba(255,255,255,0.06) !important;
        padding: 12px 0 12px 0 !important;
        display: flex !important;
        flex-direction: column !important;
        align-items: center !important;
    }}
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] div[data-testid*="olumn"]:nth-of-type(2) {{
        min-width: 256px !important; max-width: 256px !important; flex: 0 0 256px !important;
        background-color: #111118 !important;
        padding: 0 !important;
        overflow-y: auto !important;
    }}

    /* ── RAIL ICON BUTTONS (Structural) ── */
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] div[data-testid*="olumn"]:nth-of-type(1) button {{
        width: 44px !important; height: 44px !important;
        border-radius: 14px !important;
        background: rgba(255,255,255,0.06) !important;
        border: none !important;
        color: #6B7280 !important;
        display: flex !important;
        align-items: center !important; justify-content: center !important;
        transition: all 0.2s ease !important;
        padding: 0 !important;
        margin: 0 auto 10px auto !important;
        position: relative !important;
    }}
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] div[data-testid*="olumn"]:nth-of-type(1) button:hover {{
        background: rgba(255,255,255,0.10) !important;
    }}
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] div[data-testid*="olumn"]:nth-of-type(1) button p {{
        font-family: "Font Awesome 6 Free", "FontAwesome" !important;
        font-weight: 900 !important;
        font-size: 1.2rem !important;
        line-height: 1 !important;
        margin: 0 !important; padding: 0 !important;
        color: inherit !important;
    }}

    /* Specific Inactive Icon Colors using marker classes */
    /* System - Amber */
    [data-testid="stSidebar"] div[data-testid="element-container"]:has(.sys-btn-marker) + div[data-testid="element-container"] button p {{
        color: #F59E0B !important;
    }}
    /* Alarm - Red */
    [data-testid="stSidebar"] div[data-testid="element-container"]:has(.alr-btn-marker) + div[data-testid="element-container"] button p {{
        color: #F43F5E !important;
    }}
    /* Filters - Cyan */
    [data-testid="stSidebar"] div[data-testid="element-container"]:has(.flt-btn-marker) + div[data-testid="element-container"] button p {{
        color: #00F0FF !important;
    }}
    /* Quick - Purple */
    [data-testid="stSidebar"] div[data-testid="element-container"]:has(.qck-btn-marker) + div[data-testid="element-container"] button p {{
        color: #A855F7 !important;
    }}

    /* LOGO BUTTON */
    [data-testid="stSidebar"] div[data-testid="element-container"]:has(.logo-btn-marker) + div[data-testid="element-container"] button {{
        background: linear-gradient(135deg, #7C3AED, #4F46E5) !important;
    }}
    [data-testid="stSidebar"] div[data-testid="element-container"]:has(.logo-btn-marker) + div[data-testid="element-container"] button p {{
        color: #fff !important; font-size: 1.4rem !important;
    }}

    /* LOGOUT BUTTON */
    [data-testid="stSidebar"] div[data-testid="element-container"]:has(.out-btn-marker) + div[data-testid="element-container"] button {{
        background: rgba(59, 130, 246, 0.15) !important;
        color: #3B82F6 !important;
    }}
    [data-testid="stSidebar"] div[data-testid="element-container"]:has(.out-btn-marker) + div[data-testid="element-container"] button:hover {{
        background: rgba(59, 130, 246, 0.3) !important;
        color: #60A5FA !important;
    }}

    /* ── PANEL CONTENT STYLING ── */
    .panel-header {{
        display: flex; align-items: flex-start; justify-content: space-between;
        padding: 20px 18px 14px 18px;
        border-bottom: 1px solid rgba(255,255,255,0.06);
        margin-bottom: 18px;
    }}
    .panel-module-label {{
        font-size: 0.65rem; font-weight: 700; color: #6B7280;
        letter-spacing: 2px; text-transform: uppercase; margin-bottom: 2px;
    }}
    .panel-title {{
        font-size: 1.3rem; font-weight: 700; color: #F9FAFB;
        line-height: 1.2;
    }}
    
    /* Close Button Hack */
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] > div:nth-child(2) div[data-testid="element-container"]:has(.panel-header) + div[data-testid="element-container"] button {{
        position: absolute !important;
        top: 20px !important;
        right: 18px !important;
        width: 32px !important; height: 32px !important;
        border-radius: 8px !important;
        background: rgba(255,255,255,0.06) !important;
        border: none !important; color: #6B7280 !important;
        padding: 0 !important;
        display: flex !important; align-items: center !important; justify-content: center !important;
        z-index: 9999 !important;
    }}
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] > div:nth-child(2) div[data-testid="element-container"]:has(.panel-header) + div[data-testid="element-container"] button p {{
        font-size: 1rem !important; margin: 0 !important;
        color: inherit !important;
    }}
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] > div:nth-child(2) div[data-testid="element-container"]:has(.panel-header) + div[data-testid="element-container"] button:hover {{
        background: rgba(255,255,255,0.12) !important; color: #D1D5DB !important;
    }}

    /* Section label */
    .section-label {{
        font-size: 0.65rem; font-weight: 700; color: #6B7280;
        letter-spacing: 2px; text-transform: uppercase;
        margin: 0 0 8px 0;
    }}

    /* START SCAN button (primary CTA) */
    .scan-cta button {{
        background: #1E2030 !important;
        border: 1px solid rgba(255,255,255,0.08) !important;
        color: #F9FAFB !important;
        font-size: 1rem !important; font-weight: 700 !important;
        letter-spacing: 1px !important;
        border-radius: 14px !important;
        height: 56px !important;
        width: 100% !important;
        transition: all 0.2s !important;
    }}
    .scan-cta button:hover {{
        background: #252840 !important;
        border-color: rgba(255,255,255,0.15) !important;
    }}
    .scan-cta button p, .scan-cta button div {{
        font-size: 1rem !important; font-weight: 700 !important;
        letter-spacing: 1px !important;
    }}
    .stop-cta button {{
        background: rgba(244, 63, 94, 0.12) !important;
        border: 1px solid rgba(244, 63, 94, 0.3) !important;
        color: #F43F5E !important;
        border-radius: 14px !important; height: 56px !important;
        font-weight: 700 !important; font-size: 1rem !important; letter-spacing: 1px !important;
    }}

    /* LAST CACHE card */
    .cache-card {{
        background: #161620;
        border: 1px solid rgba(255,255,255,0.07);
        border-radius: 12px;
        padding: 10px 14px;
        margin: 12px 0;
    }}
    .cache-label {{ font-size: 0.6rem; font-weight: 700; color: #6B7280; letter-spacing: 2px; text-transform: uppercase; margin-bottom: 4px; }}
    .cache-val {{ font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; color: #10B981; font-weight: 500; }}

    /* SYNC secondary button */
    .sync-btn button {{
        background: #1A1E2E !important;
        border: 1px solid rgba(255,255,255,0.08) !important;
        color: #9CA3AF !important;
        border-radius: 14px !important;
        height: 48px !important;
        transition: all 0.2s !important;
    }}
    .sync-btn button:hover {{ border-color: rgba(255,255,255,0.15) !important; color: #E5E7EB !important; }}
    .sync-btn button p, .sync-btn button div {{ color: inherit !important; }}

    /* ALARM CENTER */
    .alarm-region label {{ font-size: 0.75rem !important; color: #9CA3AF !important; }}
    .alarm-cta button {{
        background: rgba(244, 63, 94, 0.12) !important;
        border: 1px solid rgba(244, 63, 94, 0.3) !important;
        color: #F43F5E !important;
        border-radius: 14px !important; height: 50px !important;
        font-weight: 700 !important;
    }}
    .alarm-cta button:hover {{ background: rgba(244, 63, 94, 0.2) !important; }}

    /* Quick filter toggle list */
    .qck-list-btn button {{
        justify-content: flex-start !important;
        text-align: left !important;
        background: transparent !important;
        border: 1px solid rgba(255,255,255,0.08) !important;
        border-radius: 10px !important;
        margin-bottom: 6px !important;
        transition: all 0.2s !important;
        height: 42px !important;
        color: #9CA3AF !important;
    }}
    .qck-list-btn button:hover {{ background: rgba(255,255,255,0.04) !important; color: #E5E7EB !important; }}
    .qck-list-btn button p, .qck-list-btn button div {{ color: inherit !important; text-align: left !important; }}
    .qck-active-Online button {{ border-color: rgba(16,185,129,0.5) !important; color: #10B981 !important; background: rgba(16,185,129,0.07) !important; }}
    .qck-active-LOS button {{ border-color: rgba(244,63,94,0.5) !important; color: #F43F5E !important; background: rgba(244,63,94,0.07) !important; }}
    .qck-active-BadRx button {{ border-color: rgba(245,158,11,0.5) !important; color: #F59E0B !important; background: rgba(245,158,11,0.07) !important; }}
    .qck-active-Dyinggasp button {{ border-color: rgba(168,85,247,0.5) !important; color: #A855F7 !important; background: rgba(168,85,247,0.07) !important; }}
    .qck-active-Suspend button {{ border-color: rgba(100,116,139,0.5) !important; color: #64748B !important; background: rgba(100,116,139,0.07) !important; }}
</style>
""", unsafe_allow_html=True)
with st.sidebar:
    rail_col, panel_col = st.columns([1, 4])
    
    with rail_col:
        # Spacer at top
        st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)
        
        # SYSTEM (index 3)
        st.markdown("<div class='sys-btn-marker'></div>", unsafe_allow_html=True)
        if st.button("\uf0e7", key="rail_sys", help="System Controls"):
            st.session_state['active_panel'] = 'system' if active_panel != 'system' else None
            st.rerun()
            
        # ALARM (index 4)
        st.markdown("<div class='alr-btn-marker'></div>", unsafe_allow_html=True)
        if st.button("\uf0f3", key="rail_alr", help="Alarm Center"):
            st.session_state['active_panel'] = 'alarm' if active_panel != 'alarm' else None
            st.rerun()
            
        # FILTERS (index 5)
        st.markdown("<div class='flt-btn-marker'></div>", unsafe_allow_html=True)
        if st.button("\uf0b0", key="rail_flt", help="Data Filters"):
            st.session_state['active_panel'] = 'filters' if active_panel != 'filters' else None
            st.rerun()
            
        # QUICK (index 6)
        st.markdown("<div class='qck-btn-marker'></div>", unsafe_allow_html=True)
        if st.button("\uf00a", key="rail_qck", help="Quick Filters"):
            st.session_state['active_panel'] = 'quick' if active_panel != 'quick' else None
            st.rerun()
            
        # Spacer (index 7)
        st.markdown("<div style='height: 40vh;'></div>", unsafe_allow_html=True)
        
        # LOGOUT (index 8)
        st.markdown("<div class='out-btn-marker'></div>", unsafe_allow_html=True)
        if st.button("\uf2f5", key="rail_out", help="Logout"):
            _delete_session(st.session_state.get('session_token', ''))
            st.session_state['logged_in'] = False
            st.session_state['session_token'] = None
            st.session_state['login_time'] = None
            st.query_params.clear()
            st.rerun()

    # Dynamic CSS for active state and notification dots using marker classes
    dynamic_css = ""
    if active_panel:
        marker_map = {'system': 'sys', 'alarm': 'alr', 'filters': 'flt', 'quick': 'qck'}
        m_name = marker_map.get(active_panel)
        if m_name:
            dynamic_css += f"""
            [data-testid="stSidebar"] div[data-testid="element-container"]:has(.{m_name}-btn-marker) + div[data-testid="element-container"] button {{
                background: #F59E0B !important; color: #1C1C1C !important;
            }}
            [data-testid="stSidebar"] div[data-testid="element-container"]:has(.{m_name}-btn-marker) + div[data-testid="element-container"] button p {{
                color: #1C1C1C !important;
            }}
            """
    if st.session_state.get('is_scanning', False):
        dynamic_css += f"""
        [data-testid="stSidebar"] div[data-testid="element-container"]:has(.sys-btn-marker) + div[data-testid="element-container"] button {{ overflow: visible !important; }}
        [data-testid="stSidebar"] div[data-testid="element-container"]:has(.sys-btn-marker) + div[data-testid="element-container"] button::after {{
            content: ''; position: absolute; top: 6px; right: 6px; width: 9px; height: 9px; background-color: #00F0FF; border-radius: 50%; border: 2px solid #0d0d12; z-index: 10;
        }}
        """
    if st.session_state.get('selected_olt', 'All OLT') != 'All OLT' or st.session_state.get('search_sn_sidebar'):
        dynamic_css += f"""
        [data-testid="stSidebar"] div[data-testid="element-container"]:has(.flt-btn-marker) + div[data-testid="element-container"] button {{ overflow: visible !important; }}
        [data-testid="stSidebar"] div[data-testid="element-container"]:has(.flt-btn-marker) + div[data-testid="element-container"] button::after {{
            content: ''; position: absolute; top: 6px; right: 6px; width: 9px; height: 9px; background-color: #F43F5E; border-radius: 50%; border: 2px solid #0d0d12; z-index: 10;
        }}
        """
    if st.session_state.get('filter_mode', 'All') != 'All':
        dynamic_css += f"""
        [data-testid="stSidebar"] div[data-testid="element-container"]:has(.qck-btn-marker) + div[data-testid="element-container"] button {{ overflow: visible !important; }}
        [data-testid="stSidebar"] div[data-testid="element-container"]:has(.qck-btn-marker) + div[data-testid="element-container"] button::after {{
            content: ''; position: absolute; top: 6px; right: 6px; width: 9px; height: 9px; background-color: #F43F5E; border-radius: 50%; border: 2px solid #0d0d12; z-index: 10;
        }}
        """
    if dynamic_css:
        st.markdown(f"<style>{dynamic_css}</style>", unsafe_allow_html=True)
        
    with panel_col:
        # Render panel header + close button for any active panel
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

        if active_panel == 'system':
            st.markdown("<div class='section-label' style='padding: 0 18px;'>SCAN ENGINE</div>", unsafe_allow_html=True)
            
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
                if st.button("▶  START SCAN", use_container_width=True):
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
            if st.button("⇄  Sync Google Sheets", use_container_width=True):

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
            
        elif active_panel == 'alarm':
            st.markdown("<h3 style='margin-top:0; font-size:1.1rem; color:#fff;'>ALARM CENTER</h3>", unsafe_allow_html=True)
            region_options = ["All Regions", "Fatmawati", "Cipedak", "Pinang/Kalijati", "Lenteng Agung", "Cinere", "Senopati"]
            selected_region_alarm = st.selectbox("Target Alarm Region:", region_options)
            btn_disabled = st.session_state.get('data_final', pd.DataFrame()).empty
            st.markdown('<div class="alarm-btn">', unsafe_allow_html=True)
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
            
            # Mini Log Alarm
            st.markdown("<h4 style='font-size:0.85rem; color:#8B949E; margin-top:20px;'>Recent Sent Alarms</h4>", unsafe_allow_html=True)
            df_log = get_all_alarm_history().head(3)
            if not df_log.empty:
                for _, log in df_log.iterrows():
                    st.markdown(f"<div style='background:rgba(255,255,255,0.02); padding:8px; border-radius:6px; margin-bottom:5px; font-size:0.75rem;'><b style='color:#F43F5E'>{log.get('Category', log.get('category','ALARM'))}</b> - {log.get('Serial Number', log.get('sn',''))} <br><span style='color:#8B949E'>{log.get('Waktu Alarm Dikirim', log.get('timestamp',''))}</span></div>", unsafe_allow_html=True)
            else:
                st.markdown("<p style='font-size:0.75rem; color:#8B949E;'>No recent logs.</p>", unsafe_allow_html=True)
                
        elif active_panel == 'filters':
            st.markdown("<h3 style='margin-top:0; font-size:1.1rem; color:#fff;'>DATA FILTERS</h3>", unsafe_allow_html=True)
            data_final = st.session_state.get('data_final', pd.DataFrame())
            if not data_final.empty:
                from components.telegram import get_region_from_olt
                regions = sorted(list(set(data_final['OLT'].apply(get_region_from_olt))))
                olt_options = ["All OLT"] + regions
                selected_olt = st.selectbox("Select Region:", options=olt_options, index=olt_options.index(st.session_state.get('selected_olt', 'All OLT')))
                st.session_state['selected_olt'] = selected_olt
            else:
                st.selectbox("Select Region:", options=["Waiting for Scan..."], disabled=True)
            
            s_term = st.text_input("Search SN / Name:", value=st.session_state.get('search_sn_sidebar', ''))
            st.session_state['search_sn_sidebar'] = s_term
            
            if st.session_state.get('selected_olt', 'All OLT') != 'All OLT' or st.session_state.get('search_sn_sidebar'):
                if st.button("Clear Filters", use_container_width=True):
                    st.session_state['selected_olt'] = 'All OLT'
                    st.session_state['search_sn_sidebar'] = ''
                    st.rerun()
                    
        elif active_panel == 'quick':
            current_mode = st.session_state.get('filter_mode', 'All')

            # Color palette per filter
            filter_config = {
                "All":       {"color": "#00F0FF", "bg": "rgba(0,240,255,0.08)",   "icon": "●", "label": "ALL"},
                "Online":    {"color": "#10B981", "bg": "rgba(16,185,129,0.08)",  "icon": "●", "label": "ONLINE"},
                "LOS":       {"color": "#F43F5E", "bg": "rgba(244,63,94,0.08)",   "icon": "●", "label": "LOS"},
                "BadRx":     {"color": "#F59E0B", "bg": "rgba(245,158,11,0.08)",  "icon": "●", "label": "BAD RX"},
                "Dyinggasp": {"color": "#A855F7", "bg": "rgba(168,85,247,0.08)",  "icon": "●", "label": "DYING GASP"},
                "Suspend":   {"color": "#64748B", "bg": "rgba(100,116,139,0.08)", "icon": "●", "label": "SUSPEND"},
            }

            # Build HTML chips
            chips_html = "<div style='padding: 60px 12px 16px; display:flex; flex-direction:column; gap:8px;'>"
            chips_html += "<p style='color:#6B7280; font-size:0.65rem; font-weight:700; letter-spacing:2px; text-transform:uppercase; margin:0 0 10px 2px;'>QUICK FILTERS</p>"
            for mode, cfg in filter_config.items():
                is_active = (current_mode == mode)
                bg      = cfg["color"] + "22" if is_active else "rgba(255,255,255,0.03)"
                border  = f"1.5px solid {cfg['color']}" if is_active else "1px solid rgba(255,255,255,0.07)"
                dot_col = cfg["color"] if is_active else "rgba(255,255,255,0.15)"
                txt_col = cfg["color"] if is_active else "#9CA3AF"
                check   = "✓" if is_active else ""
                chips_html += f"""
                <div style='
                    display:flex; align-items:center; gap:10px;
                    background:{bg}; border:{border};
                    border-radius:10px; padding:9px 14px;
                    cursor:pointer; transition:all 0.2s;
                '>
                    <span style='color:{dot_col}; font-size:0.6rem; flex-shrink:0;'>●</span>
                    <span style='color:{txt_col}; font-size:0.8rem; font-weight:600; letter-spacing:0.5px; flex:1;'>{cfg["label"]}</span>
                    <span style='color:{cfg["color"]}; font-size:0.75rem; font-weight:700;'>{check}</span>
                </div>"""
            chips_html += "</div>"
            st.markdown(chips_html, unsafe_allow_html=True)

            # Hidden buttons for interactivity — zero height, invisible
            st.markdown("""
            <style>
            div[data-key="qf_All"],div[data-key="qf_Online"],div[data-key="qf_LOS"],
            div[data-key="qf_BadRx"],div[data-key="qf_Dyinggasp"],div[data-key="qf_Suspend"] {
                position:absolute; top:0; left:0; width:100%; opacity:0;
                pointer-events:none; height:0; overflow:hidden;
            }
            </style>""", unsafe_allow_html=True)

            # Overlay real clickable buttons on top of HTML chips via absolute rows
            qck_btn_css = """
            <style>
            .qck-overlay-row { position: relative; margin-bottom: 8px; }
            .qck-overlay-row > div[data-testid="element-container"] { position:absolute; inset:0; opacity:0; }
            .qck-overlay-row button { width:100% !important; height:52px !important; cursor:pointer !important; }
            </style>"""
            st.markdown(qck_btn_css, unsafe_allow_html=True)

            for f, cfg in filter_config.items():
                if st.button(cfg["label"], key=f"qf_{f}", use_container_width=True):
                    st.session_state['filter_mode'] = f if current_mode != f else 'All'
                    st.rerun()

# --- FILTER DATA FOR DISPLAY ---
# --- FILTER DATA FOR DISPLAY ---
df_raw = st.session_state['data_final']
df_filtered = df_raw.copy()

if not df_raw.empty:
    if st.session_state.get('filter_mode', 'All') != "All":
        df_filtered = df_filtered[df_filtered['Category'] == st.session_state.get('filter_mode', 'All')]
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
