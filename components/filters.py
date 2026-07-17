import streamlit as st

def render_filters(data_final):
    """
    Renders OLT Dropdown, Search Input, and Modern QUICK FILTERS Buttons in the Sidebar.
    """
    # 1. OLT SELECT FILTER
    if not data_final.empty:
        from components.telegram import get_region_from_olt
        regions = sorted(list(set(data_final['OLT'].apply(get_region_from_olt))))
        olt_options = ["All OLT"] + regions
        selected_olt = st.selectbox("Select Region:", options=olt_options, key="olt_select_sidebar")
        st.session_state['selected_olt'] = selected_olt
    else:
        st.selectbox("Select Region:", options=["Waiting for Scan..."], disabled=True, key="olt_select_sidebar_disabled")

    # 2. SEARCH INPUT
    st.text_input("Search SN / Name:", placeholder="Search...", key="search_sn_sidebar")
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # 3. MODERN QUICK FILTER BUTTONS
    st.markdown("QUICK FILTERS")
    
    # CSS Sakti untuk memaksa tombol berbentuk KOTAK SEMPURNA (Identik) di Sidebar
    st.markdown("""
    <style>
        /* Hilangkan background abu-abu bawaan container kolom di sidebar */
        [data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] {
            background: transparent !important;
            background-color: transparent !important;
            gap: 5px !important;
        }

        /* Paksa semua kolom sidebar memiliki lebar yang sama rata (tidak ter-squish) */
        [data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] > div {
            flex: 1 1 0% !important;
            min-width: 0 !important;
        }

        /* Paksa tombol menjadi kotak sempurna tanpa toleransi (Sesuai spesifikasi, disesuaikan ke 54px agar pas di sidebar - Diperbesar 20%) */
        [data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] button {
            width: 54px !important;
            height: 54px !important;
            min-width: 54px !important; /* Kunci lebar minimum */
            max-width: 54px !important; /* Kunci lebar maksimum */
            min-height: 54px !important;
            max-height: 54px !important;
            aspect-ratio: 1 / 1 !important; /* Paksa rasio 1:1 */
            border-radius: 12px !important;
            font-size: 24px !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            flex-shrink: 0 !important; /* Mencegah tombol menciut atau melar */
            padding: 0 !important;
            line-height: 1 !important;
            overflow: hidden !important; /* Mencegah konten dalam merentangkan box tombol */
            transition: all 0.2s ease-in-out !important;
        }

        /* Paksa semua isi di dalam tombol untuk terpusat sempurna dan tidak merenggangkan tombol */
        [data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] button * {
            max-height: 100% !important;
            max-width: 100% !important;
            box-sizing: border-box !important;
        }

        /* Warna border neon & background per status menggunakan selector nth-child yang valid di HTML Streamlit */
        [data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] > div:nth-child(1) button { background: #0e251b !important; border: 2px solid #10B981 !important; color: #10B981 !important; }
        [data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] > div:nth-child(2) button { background: #250e13 !important; border: 2px solid #F43F5E !important; color: #F43F5E !important; }
        [data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] > div:nth-child(3) button { background: #251b0e !important; border: 2px solid #F59E0B !important; color: #F59E0B !important; }
        [data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] > div:nth-child(4) button { background: #1b0e25 !important; border: 2px solid #A855F7 !important; color: #A855F7 !important; }
        [data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] > div:nth-child(5) button { background: #11141a !important; border: 2px solid #64748B !important; color: #64748B !important; }

        /* Hover effect modern */
        [data-testid="stSidebar"] div.stButton > button:hover {
            transform: translateY(-4px) !important;
            box-shadow: 0 4px 15px rgba(255, 255, 255, 0.1) !important;
            border-color: white !important;
            color: white !important;
        }
    </style>
    """, unsafe_allow_html=True)

    # Render 5 Kolom Native presisi rapat di Sidebar
    f_col1, f_col2, f_col3, f_col4, f_col5 = st.columns(5)
    with f_col1:
        if st.button(" ", key="btn_online", help="ONLINE"):
            st.session_state['filter_mode'] = 'Online'
            st.rerun()
    with f_col2:
        if st.button(" ", key="btn_los", help="LOS"):
            st.session_state['filter_mode'] = 'LOS'
            st.rerun()
    with f_col3:
        if st.button(" ", key="btn_badrx", help="BadRx"):
            st.session_state['filter_mode'] = 'BadRx'
            st.rerun()
    with f_col4:
        if st.button(" ", key="btn_dying", help="Dyinggasp"):
            st.session_state['filter_mode'] = 'Dyinggasp'
            st.rerun()
    with f_col5:
        if st.button(" ", key="btn_suspend", help="Suspend"):
            st.session_state['filter_mode'] = 'Suspend'
            st.rerun()

    if st.session_state.get('filter_mode', 'All') != 'All':
        if st.button("Reset Status", key="qf_reset", use_container_width=True):
            st.session_state['filter_mode'] = 'All'
            st.rerun()

    filter_val = st.session_state.get('filter_mode', 'All')
    color_class = filter_val if filter_val != 'All' else 'gray'
    st.markdown(f"**Selected Status:** :{color_class}[{filter_val}]")
    st.markdown("---")
