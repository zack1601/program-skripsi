import streamlit as st

def render_login_page():
    st.markdown("""
        <style>
        /* Sembunyikan elemen sidebar dan header bawaan saat login */
        [data-testid="stSidebar"] { display: none; }
        header { display: none; }
        
        /* Input styling */
        .stTextInput > div > div > input {
            border: 1px solid #555 !important;
            border-radius: 4px !important;
            background-color: transparent !important;
            color: white !important;
        }
        
        /* Button Neon styling */
        .stButton > button {
            border: 1px solid #00E5FF !important; /* Neon Cyan Border */
            border-radius: 4px !important;
            background-color: transparent !important;
            color: #00E5FF !important;
            width: 100% !important; /* Full width */
            text-transform: uppercase !important;
            font-weight: bold;
            letter-spacing: 1px;
            transition: all 0.3s ease;
        }
        .stButton > button:hover {
            box-shadow: 0 0 10px #00E5FF;
            background-color: rgba(0, 229, 255, 0.1) !important;
        }
        </style>
    """, unsafe_allow_html=True)
    
    st.write("<br><br><br>", unsafe_allow_html=True)
    
    with st.container():
        _, center_col, _ = st.columns([1, 2, 1])
        
        with center_col:
            # Header form
            st.markdown("<h2 style='text-align: center; margin-bottom: 40px; font-weight: bold;'>Netwatch Ops Center</h2>", unsafe_allow_html=True)
            
            # Membuat form input posisinya di tengah
            _, form_col, _ = st.columns([1, 2, 1])
            
            with form_col:
                # Input Username & Password
                user = st.text_input("Username |", value="Noc.fm")
                password = st.text_input("Password |", type="password")
                
                # Checkbox
                st.checkbox("Remember Me")
                
                # Button
                if st.button("LOGIN"):
                    if user.lower() == "noc.fm" and password == "noc123":
                        st.session_state['logged_in'] = True
                        st.rerun()
                    else:
                        st.error("Username atau Password salah!")
