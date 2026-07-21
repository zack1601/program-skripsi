import streamlit as st
import pandas as pd
import numpy as np
import folium
import plotly.graph_objects as go
import plotly.express as px
import re
import time
import os
from datetime import datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from streamlit_folium import st_folium

# Import Backend
from config import INPUT_FILE, MAX_WORKERS
from main import process_olt_audit, mask_sn

# --- Page Configuration ---
st.set_page_config(
    page_title="NETWATCH OPS CENTER",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Helper: Inject External Files (CSS/JS) ---
def local_css(file_name):
    if os.path.exists(file_name):
        with open(file_name) as f:
            st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)

def local_js(file_name):
    if os.path.exists(file_name):
        with open(file_name) as f:
            st.markdown(f'<script>{f.read()}</script>', unsafe_allow_html=True)

# Inject Styling and Logic
local_css("style.css")
local_js("script.js")

# --- State Initialization ---
if 'data_final' not in st.session_state:
    st.session_state['data_final'] = pd.DataFrame()
if 'is_scanning' not in st.session_state:
    st.session_state['is_scanning'] = False

# --- Business Logic ---
def apply_business_logic(row):
    status = str(row.get('Status', "")).strip().capitalize()
    rx_power = row.get('rx_power', "-")
    cause_raw = str(row.get('last_down_cause', "")).lower()

    if status == 'Online':
        try:
            val = float(rx_power)
            if val < -25.99: return "BadRx"
            return f"{val} dBm"
        except: return rx_power if rx_power != "-" else "-"
    
    # Deteksi Suspend/Isolir lebih agresif (mencakup deactive dari OLT)
    if any(x in cause_raw for x in ['admin', 'suspend', 'isolated', 'deactive', 'deactivated']): 
        return "Suspend/Isolir"
        
    if any(x in cause_raw for x in ['losi', 'lobi', 'los']): return "LOS"
    if any(x in cause_raw for x in ['dying', 'power-off']): return "Dyinggasp"
    return "Offline"

# --- SIDEBAR (CONTROL & FILTER) ---
with st.sidebar:
    st.markdown("<h1 style='font-size:1.8rem; margin-bottom:0;'>🛡️ NETWATCH</h1>", unsafe_allow_html=True)
    st.markdown("<p style='font-size:0.7rem; color:#8B949E; margin-top:0;'>OPS CENTER v6.0</p>", unsafe_allow_html=True)
    st.markdown("---")
    
    # Tombol Scan dengan Feedback
    if st.button("🚀 START SCANNING", use_container_width=True):
        if not os.path.exists(INPUT_FILE):
            st.error(f"File input '{INPUT_FILE}' tidak ditemukan!")
        else:
            st.session_state['is_scanning'] = True
            st.session_state['data_final'] = pd.DataFrame()
            st.rerun() # Pastikan rerun untuk masuk ke mode scanning
    
    st.markdown("---")
    st.markdown("### 🔍 Filters")
    filter_mode = st.radio(
        "Status Category:",
        options=["All Data", "Online", "LOS", "BadRx", "Dyinggasp", "Suspend/Isolir"],
        index=0
    )
    search_sn = st.text_input("Search SN/ID:", placeholder="Search Serial Number...")

# --- REAL-TIME SCANNING ENGINE ---
if st.session_state.get('is_scanning', False):
    st.toast("🚀 Memulai Audit OLT...", icon="📡")
    loader_placeholder = st.empty()
    
    # Inisialisasi Loader di 0% agar tidak kosong saat mulai
    loader_placeholder.markdown("""
    <div class="loader-container">
        <div class="custom-loader">
            <div class="progress-fill" style="width: 0%;"></div>
        </div>
        <div class="loading-text">INITIALIZING ...</div>
    </div>
    """, unsafe_allow_html=True)
    
    try:
        df_input = pd.read_excel(INPUT_FILE)
        df_input.columns = df_input.columns.str.strip().str.lower()
        
        olt_map = defaultdict(lambda: {"name": "", "slots": set()})
        ip_col = next((c for c in df_input.columns if 'ip' in c), 'ip_olt')
        for _, r in df_input.iterrows():
            ip = str(r.get(ip_col, "")).strip()
            olt_map[ip]["name"] = str(r.get('olt', "")).strip()
            port = str(r.get('port', "")).strip()
            match = re.search(r'(\d+)\s*/\s*(\d+)\s*/\s*(\d+)', port)
            if match: olt_map[ip]["slots"].add(f"{match.group(1)}/{match.group(2)}")

        processed_data = []
        total_olt = len(olt_map)
        
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(process_olt_audit, g["name"], ip, list(g["slots"])): ip for ip, g in olt_map.items()}
            sn_map_input = {str(r.get('serial number', '')).strip().upper(): r for _, r in df_input.iterrows()}

            for i, future in enumerate(as_completed(futures)):
                # Update Custom Loader UI
                progress_percent = int(((i + 1) / total_olt) * 100)
                loader_placeholder.markdown(f"""
                <div class="loader-container">
                    <div class="custom-loader">
                        <div class="progress-fill" style="width: {progress_percent}%;"></div>
                    </div>
                    <div class="loading-text">SCANNING OLT ({i+1}/{total_olt}) ...</div>
                </div>
                """, unsafe_allow_html=True)
                
                scan_results = future.result()
                for s in scan_results:
                    sn_scan = str(s.get('sn', "")).strip().upper()
                    
                    # STRICT SYNC: Only process if SN exists in Excel Input
                    if sn_scan not in sn_map_input:
                        continue
                        
                    row_in = sn_map_input.get(sn_scan, {})
                    
                    # Name & ID Extraction Strategy
                    id_pel = str(row_in.get('id_pelanggan', row_in.get('id', ''))).strip()
                    nama_pel = str(row_in.get('nama_pelanggan', row_in.get('nama', ''))).strip()
                    desc = str(s.get('description', '')).strip()
                    
                    # Logika Pemulihan Data dari Description (Jika Excel Kosong/NAN)
                    if (not id_pel or id_pel.lower() == 'nan' or not nama_pel or nama_pel.lower() == 'nan') and desc:
                        # Mencari pola ID Pelanggan (10-13 digit)
                        match_id = re.search(r'(\d{10,13})', desc)
                        if match_id:
                            extracted_id = match_id.group(1)
                            if not id_pel or id_pel.lower() == 'nan': id_pel = extracted_id
                            
                            # Membersihkan sisa deskripsi dari noise (Distance/Power)
                            temp_name = desc.replace(extracted_id, "")
                            temp_name = re.sub(r'-?\d+\.\d+/-?\d+\.\d+', '', temp_name) # Hapus Redaman
                            temp_name = re.sub(r'\s+\d{3,5}\s+', ' ', temp_name)        # Hapus Jarak
                            temp_name = re.sub(r'^[\s\-_/0-9]+', '', temp_name)        # Hapus karakter sampah di awal
                            
                            remaining = temp_name.strip(" -_/")
                            if remaining and (not nama_pel or nama_pel.lower() == 'nan'):
                                nama_pel = remaining
                    
                    # Final Fallback jika benar-benar tidak ada data
                    id_pel = id_pel if id_pel and id_pel.lower() != 'nan' else "11100" + str(np.random.randint(100000, 999999))
                    nama_pel = nama_pel if nama_pel and nama_pel.lower() != 'nan' else "-"
                    
                    record = {
                        "OLT": str(row_in.get('olt', s.get('olt_name', '-'))),
                        "Nama/ID Pelanggan": f"{id_pel}-{nama_pel}",
                        "Port": str(row_in.get('port', s.get('port_override', '-'))),
                        "Serial Number": s.get('sn'),
                        "Status": s.get('status'),
                        "rx_power": s.get('rx_power'),
                        "last_down_cause": s.get('last_down_cause')
                    }
                    record["Power/Cause"] = apply_business_logic(record)
                    processed_data.append(record)
                
                # Strict Multi-layered Deduplication
                final_df = pd.DataFrame(processed_data)
                if not final_df.empty:
                    final_df['Serial Number'] = final_df['Serial Number'].str.strip().str.upper()
                    final_df['Nama/ID Pelanggan'] = final_df['Nama/ID Pelanggan'].str.strip().str.upper()
                    # Layer 1: By SN
                    final_df = final_df.drop_duplicates(subset=['Serial Number'], keep='first')
                    # Layer 2: By Customer ID
                    final_df = final_df.drop_duplicates(subset=['Nama/ID Pelanggan'], keep='first')
                    
                st.session_state['data_final'] = final_df
            
            loader_placeholder.markdown("""
            <div class="loader-container">
                <div class="custom-loader">
                    <div class="progress-fill" style="width: 100%;"></div>
                </div>
                <div class="loading-text">COMPLETE</div>
            </div>
            """, unsafe_allow_html=True)
            time.sleep(1)
            
            st.session_state['is_scanning'] = False
            st.rerun()
        
    except Exception as e:
        st.error(f"Scan Failure: {e}")
        st.session_state['is_scanning'] = False

# --- MAIN DASHBOARD LAYOUT (Side-by-Side) ---
if not st.session_state['data_final'].empty:
    df_raw = st.session_state['data_final'].copy()
    
    # 1. TOP SUMMARY BOARD — Sticky Header (Pure HTML)
    total_users    = len(df_raw)
    total_online   = len(df_raw[df_raw['Status'] == 'Online'])
    total_los      = len(df_raw[df_raw['Power/Cause'] == 'LOS'])
    total_badrx    = len(df_raw[df_raw['Power/Cause'] == 'BadRx'])
    total_dying    = len(df_raw[df_raw['Power/Cause'] == 'Dyinggasp'])
    total_suspend  = len(df_raw[df_raw['Power/Cause'] == 'Suspend/Isolir'])

    st.markdown(f"""
    <div class="sticky-header-bar">
        <div class="sticky-cards-row">
            <div class="metric-card glow-gray sticky-card">
                <div class="sticky-card-icon">👥</div>
                <div class="sticky-card-val">{total_users}</div>
                <div class="sticky-card-label">TOTAL USERS</div>
            </div>
            <div class="metric-card glow-green sticky-card">
                <div class="sticky-card-icon">🟢</div>
                <div class="sticky-card-val">{total_online}</div>
                <div class="sticky-card-label">ONLINE</div>
            </div>
            <div class="metric-card glow-red sticky-card">
                <div class="sticky-card-icon">🚨</div>
                <div class="sticky-card-val">{total_los}</div>
                <div class="sticky-card-label">LOS</div>
            </div>
            <div class="metric-card glow-orange sticky-card">
                <div class="sticky-card-icon">⚠️</div>
                <div class="sticky-card-val">{total_badrx}</div>
                <div class="sticky-card-label">BAD RX</div>
            </div>
            <div class="metric-card glow-blue sticky-card">
                <div class="sticky-card-icon">🔋</div>
                <div class="sticky-card-val">{total_dying}</div>
                <div class="sticky-card-label">DYINGGASP</div>
            </div>
            <div class="metric-card glow-gray sticky-card">
                <div class="sticky-card-icon">🔒</div>
                <div class="sticky-card-val">{total_suspend}</div>
                <div class="sticky-card-label">SUSPEND</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # 2. MAIN GRID (Left: Filter, Middle: Map/Table, Right: Analytics)
    # Using columns for the side-by-side structure
    col_mid, col_right = st.columns([5, 2])
    
    with col_mid:
        # MAPS SECTION
        st.markdown("<h3 class='section-title'>🌍 Topology Awareness</h3>", unsafe_allow_html=True)
        df_map = df_raw.copy()
        if filter_mode != "All Data":
            if filter_mode == "Online": df_map = df_map[df_map['Status'] == 'Online']
            else: df_map = df_map[df_map['Power/Cause'] == filter_mode]
        
        # Coordinates Mockup
        df_map['lat'] = -6.20 + (np.arange(len(df_map)) * 0.003)
        df_map['lon'] = 106.81 + (np.arange(len(df_map)) * 0.003)

        if not df_map.empty:
            # Pastikan nilai mean bukan NaN sebelum membuat peta
            center_lat = df_map['lat'].mean()
            center_lon = df_map['lon'].mean()
            
            if not np.isnan(center_lat) and not np.isnan(center_lon):
                m = folium.Map(location=[center_lat, center_lon], zoom_start=14, tiles="CartoDB dark_matter")
                for _, row in df_map.iterrows():
                    color = "#00E5FF"
                    is_critical = False
                    if row['Power/Cause'] == 'LOS': color = "#FF4D4D"; is_critical = True
                    elif row['Power/Cause'] == 'BadRx': color = "#FFA500"; is_critical = True
                    
                    if is_critical:
                        folium.Marker(
                            location=[row['lat'], row['lon']],
                            icon=folium.DivIcon(html=f'<div class="blinker" style="background:{color};"></div>'),
                            popup=f"{row['Nama/ID Pelanggan']}: {row['Power/Cause']}"
                        ).add_to(m)
                    else:
                        folium.CircleMarker(
                            location=[row['lat'], row['lon']],
                            radius=5, color=color, fill=True, fill_color=color, fill_opacity=0.6,
                            popup=row['Nama/ID Pelanggan']
                        ).add_to(m)
                st_folium(m, width="100%", height=400, key="center_map")
            else:
                st.warning("⚠️ Koordinat tidak valid untuk ditampilkan pada peta.")
        else:
            st.info("ℹ️ Tidak ada data yang sesuai dengan filter saat ini untuk ditampilkan di peta.")

        # MONITORING TABLE SECTION
        st.markdown("<h3 class='section-title'>📋 Live Node Monitoring</h3>", unsafe_allow_html=True)
        display_df = df_map.copy()
        if search_sn:
            display_df = display_df[display_df.astype(str).apply(lambda x: x.str.contains(search_sn, case=False)).any(axis=1)]
        
        # Reset Index & Add No
        display_df = display_df.reset_index(drop=True)
        display_df.insert(0, 'No', range(1, len(display_df) + 1))
        
        display_df['Serial Number'] = display_df['Serial Number'].apply(mask_sn)
        cols_order = ["No", "OLT", "Nama/ID Pelanggan", "Port", "Serial Number", "Power/Cause"]
        
        st.dataframe(display_df[cols_order], use_container_width=True, height=450, hide_index=True)

    with col_right:
        st.markdown("<h3 class='section-title'>📈 Visual Analytics</h3>", unsafe_allow_html=True)
        
        # Status Composition
        st.markdown("<div class='metric-card' style='height:320px;'>", unsafe_allow_html=True)
        st.markdown("<p style='font-size:0.8rem; color:#8B949E;'>ONT STATUS COMPOSITION</p>", unsafe_allow_html=True)
        fig_donut = px.pie(df_raw, names='Status', hole=0.7, color_discrete_map={'Online': '#00E676', 'Offline': '#FF4D4D'})
        fig_donut.update_layout(height=250, showlegend=True, paper_bgcolor="rgba(0,0,0,0)", font={'color': "#FFFFFF"},
                               legend=dict(orientation="h", yanchor="bottom", y=-0.3, xanchor="center", x=0.5))
        st.plotly_chart(fig_donut, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        # Network Health Gauge
        st.markdown("<div class='metric-card' style='height:320px;'>", unsafe_allow_html=True)
        st.markdown("<p style='font-size:0.8rem; color:#8B949E;'>NETWORK HEALTH SCORE</p>", unsafe_allow_html=True)
        online_rate = (len(df_raw[df_raw['Status'] == 'Online']) / len(df_raw)) * 100 if len(df_raw) > 0 else 100
        fig_gauge = go.Figure(go.Indicator(
            mode="gauge+number", value=round(online_rate, 1),
            number={'suffix': "%", 'font': {'color': "#FFFFFF"}},
            gauge={'axis': {'range': [0, 100], 'tickcolor': "white"}, 'bar': {'color': "#00E5FF"}, 'bgcolor': "#161B22"}
        ))
        fig_gauge.update_layout(height=220, margin=dict(t=0, b=0, l=10, r=10), paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig_gauge, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

else:
    # Empty State
    st.markdown("""
    <div style='display:flex; flex-direction:column; align-items:center; justify-content:center; height:60vh; border:2px dashed #30363D; border-radius:20px;'>
        <h1 style='color:#00E5FF; font-size:4rem; margin-bottom:0;'>NETWATCH</h1>
        <p style='color:#FFFFFF; font-size:1.2rem; margin-top:0;'>Integrated OLT Monitoring System v6.0</p>
        <p style='color:#8B949E; font-size:0.9rem;'>Sistem Siap. Klik 'START SCANNING' pada panel kontrol untuk memulai.</p>
    </div>
    """, unsafe_allow_html=True)

# --- Footer ---
st.markdown("<center style='color:#30363D; padding:20px;'>Enterprise Command Center Framework | Program Skripsi - Zaki Mubarok</center>", unsafe_allow_html=True)
