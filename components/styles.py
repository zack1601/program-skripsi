import streamlit as st

def inject_custom_css():
    """
    Injects the custom CSS for the modern, premium, and futuristic dark slate theme.
    """
    # --- CUSTOM CSS (ULTRA DARK SLATE THEME) ---
    st.markdown("""
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
<style>
    /* Global Styles */
    @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');
    
    html, body, [data-testid="stAppViewContainer"] {
        background-color: #0E1117 !important;
        color: #FFFFFF !important;
        font-family: 'Share Tech Mono', monospace;
    }
    
    [data-testid="stSidebar"] {
        background-color: #161B22 !important;
        border-right: 1px solid #30363D;
        font-family: 'Share Tech Mono', monospace !important;
    }
    
    [data-testid="stSidebar"] p, 
    [data-testid="stSidebar"] label, 
    [data-testid="stSidebar"] input {
        font-family: 'Share Tech Mono', monospace !important;
    }
    
    /* Ensure Streamlit's sidebar collapse icon renders as an icon, not raw text */
    [data-testid="stSidebar"] button span,
    [data-testid="stSidebar"] button svg,
    [data-testid="stSidebarCollapseButton"] span,
    [data-testid="stSidebar"] .material-icons,
    [data-testid="stSidebar"] [class*="material-"] {
        font-family: "Material Symbols Outlined", "Material Symbols Rounded", "Material Icons" !important;
    }
    
    /* Sidebar Text Fix: Ensure high contrast white */
    [data-testid="stSidebar"] .stMarkdown p, 
    [data-testid="stSidebar"] label, 
    [data-testid="stSidebar"] .stRadio span {
        color: #FFFFFF !important;
        font-weight: 600 !important;
    }
    
    /* Header Color */
    h1, h2, h3 {
        color: #FFFFFF !important;
        font-weight: 800 !important;
    }
    
    .stMarkdown p {
        color: #FFFFFF !important;
    }

    /* Metric Cards (Modern Matte & Glassmorphism) - Diperbesar 20% */
    .metric-card {
        background: rgba(255, 255, 255, 0.03);
        backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
        border: 1px solid rgba(255, 255, 255, 0.08);
        padding: 19px 24px;
        border-radius: 19px;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        min-height: 108px;
        display: flex;
        align-items: center;
    }
    .metric-card:hover {
        transform: translateY(-4px);
        background: rgba(255, 255, 255, 0.06);
        border-color: rgba(255, 255, 255, 0.15);
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
    }
    .metric-content {
        display: flex;
        align-items: center;
        gap: 18px;
        width: 100%;
    }
    .metric-icon {
        font-size: 2.16rem;
        opacity: 0.9;
        display: flex;
        align-items: center;
        justify-content: center;
        min-width: 48px;
    }
    .metric-data {
        display: flex;
        flex-direction: column;
        justify-content: center;
    }
    .metric-label {
        font-size: 0.78rem;
        text-transform: uppercase;
        letter-spacing: 1.8px;
        color: #8B949E;
        font-weight: 700;
        margin-top: 2px;
    }
    .metric-value {
        font-size: 2.16rem;
        font-weight: 800;
        font-family: 'Share Tech Mono', monospace;
        line-height: 1.1;
    }

    /* Dataframe Styling */
    .stDataFrame {
        border: 1px solid #30363D;
        border-radius: 10px;
    }
    
    /* Vivid Cyan Header for Table */
    [data-testid="stHeader"] {
        background-color: rgba(14, 17, 23, 0.8);
    }
    
    /* Pulse Animation for Map Legend */
    @keyframes pulse-red {
        0% { transform: scale(0.9); box-shadow: 0 0 0 0 rgba(255, 77, 77, 0.7); }
        70% { transform: scale(1); box-shadow: 0 0 0 10px rgba(255, 77, 77, 0); }
        100% { transform: scale(0.9); box-shadow: 0 0 0 0 rgba(255, 77, 77, 0); }
    }
    .pulse-dot {
        width: 10px; height: 10px; border-radius: 50%; display: inline-block;
        margin-right: 5px; animation: pulse-red 2s infinite;
    }
</style>
""", unsafe_allow_html=True)

    # --- CUSTOM CSS (Professional Minimalist UI) ---
    st.markdown("""
<style>
    /* Global Styles */
    @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Share Tech Mono', monospace;
    }

    /* Clean Headers */
    h1, h2, h3 {
        color: #FFFFFF !important;
        font-weight: 800 !important;
        letter-spacing: -0.5px !important;
        border: none !important;
    }

    /* Sidebar Active State Simulation */
    [data-testid="stSidebarNav"] {
        background-color: #0D1117;
    }
    
    .sidebar-btn {
        display: flex;
        align-items: center;
        padding: 12px 18px;
        margin: 4px 0;
        border-radius: 10px;
        color: #8B949E;
        text-decoration: none;
        transition: all 0.3s ease;
        cursor: pointer;
        background: rgba(255,255,255,0.04);
        backdrop-filter: blur(8px);
        border: 1px solid rgba(255,255,255,0.06);
    }
    
    .sidebar-btn:hover {
        background: rgba(255, 255, 255, 0.08);
        color: white;
        border-color: rgba(255,255,255,0.12);
    }
    
    .sidebar-btn.active {
        background: rgba(255,255,255,0.12);
        color: #FFFFFF !important;
        font-weight: 600;
        border-color: rgba(0,229,255,0.3);
        box-shadow: 0 0 12px rgba(0,229,255,0.1);
    }

    /* Scan button styles */
    @keyframes scan-pulse {
        0% { box-shadow: 0 0 0 0 rgba(245,158,11,0.5); }
        70% { box-shadow: 0 0 0 8px rgba(245,158,11,0); }
        100% { box-shadow: 0 0 0 0 rgba(245,158,11,0); }
    }
    [data-testid="stSidebar"] .stButton > button {
        border-radius: 12px !important;
    }
    [data-testid="stSidebar"] .stSelectbox > div > div {
        border-radius: 12px !important;
    }
    [data-testid="stSidebar"] .stTextInput > div > div > input {
        border-radius: 12px !important;
    }

    /* Futuristic & Modern Premium Button Base */
    .stButton > button {
        border-radius: 14px !important;
        background: rgba(255, 255, 255, 0.03) !important;
        backdrop-filter: blur(12px) !important;
        -webkit-backdrop-filter: blur(12px) !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        color: #FFFFFF !important;
        transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1) !important;
        font-weight: 700 !important;
        text-transform: uppercase !important;
        letter-spacing: 1.5px !important;
        font-size: 0.85rem !important;
        padding: 12px 20px !important;
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        gap: 8px !important;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2) !important;
    }

    .stButton > button:hover {
        background: rgba(255, 255, 255, 0.08) !important;
        border-color: rgba(255, 255, 255, 0.2) !important;
        box-shadow: 0 6px 20px rgba(0, 0, 0, 0.3) !important;
        transform: translateY(-2px) !important;
    }

    /* 1. START SCAN BUTTON: Futuristic Cyan-Teal Neon Glow */
    .start-btn button,
    div:has(> .start-btn) + div button,
    .start-btn + div.stButton > button,
    div.start-btn + div.element-container button {
        background: linear-gradient(135deg, rgba(0, 229, 255, 0.08), rgba(16, 185, 129, 0.08)) !important;
        border: 1px solid rgba(0, 229, 255, 0.3) !important;
        color: #00E5FF !important;
        box-shadow: 0 4px 12px rgba(0, 229, 255, 0.15), inset 0 0 8px rgba(0, 229, 255, 0.05) !important;
    }
    .start-btn button:hover,
    div:has(> .start-btn) + div button:hover,
    .start-btn + div.stButton > button:hover,
    div.start-btn + div.element-container button:hover {
        background: linear-gradient(135deg, rgba(0, 229, 255, 0.2), rgba(16, 185, 129, 0.2)) !important;
        border-color: #00E5FF !important;
        color: #FFFFFF !important;
        box-shadow: 0 0 25px rgba(0, 229, 255, 0.45), inset 0 0 12px rgba(0, 229, 255, 0.1) !important;
        text-shadow: 0 0 8px rgba(0, 229, 255, 0.5) !important;
    }
    .start-btn button::before,
    div:has(> .start-btn) + div button::before,
    .start-btn + div.stButton > button::before,
    div.start-btn + div.element-container button::before {
        content: "\\f04b" !important; /* Play icon */
        font-family: "Font Awesome 6 Free" !important;
        font-weight: 900 !important;
        font-size: 0.95rem !important;
        opacity: 0.9 !important;
        transition: transform 0.3s ease !important;
    }
    .start-btn button:hover::before,
    div:has(> .start-btn) + div button:hover::before,
    .start-btn + div.stButton > button:hover::before,
    div.start-btn + div.element-container button:hover::before {
        transform: scale(1.25) !important;
    }

    /* 2. STOP SCANNING BUTTON: Neon Orange/Gold Alarm Pulse */
    .stop-btn button,
    div:has(> .stop-btn) + div button,
    .stop-btn + div.stButton > button,
    div.stop-btn + div.element-container button {
        background: linear-gradient(135deg, rgba(245, 158, 11, 0.08), rgba(217, 119, 6, 0.08)) !important;
        border: 1px solid rgba(245, 158, 11, 0.3) !important;
        color: #F59E0B !important;
        box-shadow: 0 4px 12px rgba(245, 158, 11, 0.15), inset 0 0 8px rgba(245, 158, 11, 0.05) !important;
        animation: neon-orange-pulse 2s infinite !important;
    }
    .stop-btn button:hover,
    div:has(> .stop-btn) + div button:hover,
    .stop-btn + div.stButton > button:hover,
    div.stop-btn + div.element-container button:hover {
        background: linear-gradient(135deg, rgba(245, 158, 11, 0.2), rgba(217, 119, 6, 0.2)) !important;
        border-color: #F59E0B !important;
        color: #FFFFFF !important;
        box-shadow: 0 0 25px rgba(245, 158, 11, 0.45), inset 0 0 12px rgba(245, 158, 11, 0.1) !important;
        text-shadow: 0 0 8px rgba(245, 158, 11, 0.5) !important;
    }
    .stop-btn button::before,
    div:has(> .stop-btn) + div button::before,
    .stop-btn + div.stButton > button::before,
    div.stop-btn + div.element-container button::before {
        content: "\\f04d" !important; /* Square icon */
        font-family: "Font Awesome 6 Free" !important;
        font-weight: 900 !important;
        font-size: 0.95rem !important;
        opacity: 0.9 !important;
        transition: transform 0.3s ease !important;
    }
    .stop-btn button:hover::before,
    div:has(> .stop-btn) + div button:hover::before,
    .stop-btn + div.stButton > button:hover::before,
    div.stop-btn + div.element-container button:hover::before {
        transform: scale(1.25) rotate(90deg) !important;
    }

    /* 3. SEND ALARM BUTTON: Premium Glowing Crimson Alert */
    .alarm-btn button,
    div:has(> .alarm-btn) + div button,
    .alarm-btn + div.stButton > button,
    div.alarm-btn + div.element-container button {
        background: linear-gradient(135deg, rgba(239, 68, 68, 0.08), rgba(153, 0, 51, 0.08)) !important;
        border: 1px solid rgba(239, 68, 68, 0.3) !important;
        color: #EF4444 !important;
        box-shadow: 0 4px 12px rgba(239, 68, 68, 0.15), inset 0 0 8px rgba(239, 68, 68, 0.05) !important;
    }
    .alarm-btn button:hover,
    div:has(> .alarm-btn) + div button:hover,
    .alarm-btn + div.stButton > button:hover,
    div.alarm-btn + div.element-container button:hover {
        background: linear-gradient(135deg, rgba(239, 68, 68, 0.2), rgba(153, 0, 51, 0.2)) !important;
        border-color: #EF4444 !important;
        color: #FFFFFF !important;
        box-shadow: 0 0 25px rgba(239, 68, 68, 0.45), inset 0 0 12px rgba(239, 68, 68, 0.1) !important;
        text-shadow: 0 0 8px rgba(239, 68, 68, 0.5) !important;
    }
    .alarm-btn button::before,
    div:has(> .alarm-btn) + div button::before,
    .alarm-btn + div.stButton > button::before,
    div.alarm-btn + div.element-container button::before {
        content: "\\f0f3" !important; /* Bell icon */
        font-family: "Font Awesome 6 Free" !important;
        font-weight: 900 !important;
        font-size: 0.95rem !important;
        opacity: 0.9 !important;
        transition: transform 0.3s ease !important;
    }
    .alarm-btn button:hover::before,
    div:has(> .alarm-btn) + div button:hover::before,
    .alarm-btn + div.stButton > button:hover::before,
    div.alarm-btn + div.element-container button:hover::before {
        transform: scale(1.25) rotate(15deg) !important;
    }

    /* Stop Button Glowing Pulse Animation */
    @keyframes neon-orange-pulse {
        0% { border-color: rgba(245, 158, 11, 0.3); box-shadow: 0 0 0 0 rgba(245, 158, 11, 0.15); }
        70% { border-color: rgba(245, 158, 11, 0.7); box-shadow: 0 0 15px 5px rgba(245, 158, 11, 0); }
        100% { border-color: rgba(245, 158, 11, 0.3); box-shadow: 0 0 0 0 rgba(245, 158, 11, 0); }
    }

    /* 1. TEXT INPUT STYLING (Embossed, modern & glowing) */
    .stTextInput > div > div > input {
        border-radius: 10px !important;
        background: linear-gradient(135deg, rgba(22, 28, 38, 0.95), rgba(13, 17, 23, 0.95)) !important;
        border: 1px solid rgba(0, 240, 255, 0.25) !important;
        color: #E6EDF3 !important;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.6), inset 0 1px 1.5px rgba(255, 255, 255, 0.08), 0 0 1px rgba(0, 240, 255, 0.1) !important;
        font-family: 'Share Tech Mono', monospace !important;
        font-size: 0.9rem !important;
        padding: 10px 14px !important;
        transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1) !important;
    }
    
    .stTextInput > div > div > input:hover {
        border-color: rgba(0, 240, 255, 0.5) !important;
        box-shadow: 0 6px 18px rgba(0, 240, 255, 0.12), inset 0 1px 1.5px rgba(255, 255, 255, 0.15) !important;
    }
    
    .stTextInput > div > div > input:focus {
        border-color: #00F0FF !important;
        box-shadow: 0 0 15px rgba(0, 240, 255, 0.45), inset 0 1px 1px rgba(255, 255, 255, 0.1) !important;
    }

    /* 2. SELECTBOX / COMBO BOX STYLING (Matching embossed & modern design) */
    .stSelectbox [data-baseweb="select"] {
        border-radius: 10px !important;
        background: linear-gradient(135deg, rgba(22, 28, 38, 0.95), rgba(13, 17, 23, 0.95)) !important;
        border: 1px solid rgba(0, 240, 255, 0.25) !important;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.6), inset 0 1px 1.5px rgba(255, 255, 255, 0.08), 0 0 1px rgba(0, 240, 255, 0.1) !important;
        transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1) !important;
    }
    
    .stSelectbox [data-baseweb="select"]:hover {
        border-color: rgba(0, 240, 255, 0.5) !important;
        box-shadow: 0 6px 18px rgba(0, 240, 255, 0.12), inset 0 1px 1.5px rgba(255, 255, 255, 0.15) !important;
    }

    .stSelectbox [data-baseweb="select"]:focus-within {
        border-color: #00F0FF !important;
        box-shadow: 0 0 15px rgba(0, 240, 255, 0.45), inset 0 1px 1px rgba(255, 255, 255, 0.1) !important;
    }

    /* Fix selectbox inner elements color and font */
    .stSelectbox [data-baseweb="select"] > div {
        color: #E6EDF3 !important;
        font-family: 'Share Tech Mono', monospace !important;
        font-size: 0.9rem !important;
        font-weight: 500 !important;
        background: transparent !important;
    }

    /* Clean Table */
    [data-testid="stDataFrame"] {
        border: none !important;
        background: transparent !important;
    }
</style>
""", unsafe_allow_html=True)

    # --- STICKY HEADER CSS ---
    st.markdown("""
<style>
    /* ============================================================
       STICKY HEADER — Network Summary Cards + Risk Gauge
       Streamlit scrolls inside .main .block-container.
       Setting overflow-y:auto there makes it the scroll context,
       allowing position:sticky on .nw-sticky-bar to work.
    ============================================================ */

    /* Enable scroll context on Streamlit main area */
    section.main > div.block-container {
        overflow-y: visible !important;
        padding-top: 0.5rem !important;
    }

    /* ── Fixed Network Summary Bar ── */
    .nw-sticky-bar {
        position: fixed !important;
        top: 0 !important;
        /* offset untuk sidebar Streamlit (default ~21rem / 336px) */
        left: 21rem !important;
        right: 0 !important;
        z-index: 9999 !important;
        background: rgba(13, 17, 23, 0.97) !important;
        backdrop-filter: blur(16px) !important;
        -webkit-backdrop-filter: blur(16px) !important;
        border-bottom: 1px solid rgba(48, 54, 61, 0.8) !important;
        box-shadow: 0 6px 24px rgba(0, 0, 0, 0.55) !important;
        padding: 10px 1.5rem 12px 1.5rem !important;
    }

    /* ── Inner content container ── */
    .nw-sticky-inner {
        width: 100%;
    }

    /* ── Section label ── */
    .nw-section-label {
        font-family: 'Share Tech Mono', monospace !important;
        font-size: 0.72rem !important;
        font-weight: 800 !important;
        color: #484F58 !important;
        letter-spacing: 2px !important;
        margin: 0 0 8px 2px !important;
        text-transform: uppercase;
    }

    /* ── Cards + Gauge flex row ── */
    .nw-cards-gauge-row {
        display: flex;
        align-items: center;
        gap: 14px;
        width: 100%;
    }

    /* ── Six cards row ── */
    .nw-cards-row {
        display: flex;
        flex: 1;
        gap: 10px;
        align-items: stretch;
    }

    /* ── Individual card ── */
    .nw-card {
        flex: 1;
        min-width: 0;
        border-radius: 12px;
        padding: 10px 8px;
        text-align: center;
        font-family: 'Share Tech Mono', monospace;
        transition: transform 0.18s ease, box-shadow 0.18s ease;
        cursor: default;
    }
    .nw-card:hover {
        transform: translateY(-3px);
        box-shadow: 0 6px 18px rgba(255,255,255,0.08);
    }

    /* Card colour variants */
    .nw-total   { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.10); }
    .nw-online  { background: rgba(16,185,129,0.05);  border: 1px solid rgba(16,185,129,0.25); }
    .nw-los     { background: rgba(244,63,94,0.05);   border: 1px solid rgba(244,63,94,0.25);  }
    .nw-badrx   { background: rgba(245,158,11,0.05);  border: 1px solid rgba(245,158,11,0.25); }
    .nw-dying   { background: rgba(168,85,247,0.05);  border: 1px solid rgba(168,85,247,0.25); }
    .nw-suspend { background: rgba(100,116,139,0.05); border: 1px solid rgba(100,116,139,0.25);}

    /* Card label & value */
    .nw-card-label {
        font-size: 0.70rem;
        font-weight: 700;
        color: #8B949E;
        letter-spacing: 1.2px;
        margin-bottom: 4px;
        white-space: nowrap;
    }
    .nw-card-val {
        font-size: 1.80rem;
        font-weight: 800;
        color: #FFFFFF;
        line-height: 1.1;
    }

    /* ── Gauge container ── */
    .nw-gauge {
        flex-shrink: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        width: 120px;
    }
    .nw-gauge svg {
        display: block;
    }
</style>
""", unsafe_allow_html=True)
