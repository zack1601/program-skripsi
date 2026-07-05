import streamlit as st

def render_table(df_filtered):
    """
    Renders the live monitoring landscape data table with index column.
    """
    # Header area for Table and Download Button
    col1, col2 = st.columns([8, 2])
    with col1:
        st.markdown("<p style='font-size:0.8rem; font-weight:800; color:#8B949E; margin-bottom:10px;'>LIVE MONITORING TABLE (FULL VIEW)</p>", unsafe_allow_html=True)
    
    if not df_filtered.empty:
        df_table = df_filtered.copy()
        df_table = df_table.reset_index(drop=True)
        df_table.insert(0, 'No', range(1, len(df_table) + 1))
        cols = ["No", "OLT", "Nama/ID Pelanggan", "Port", "Serial Number", "Category", "Power/Cause"]
        
        # Add Download Button on the right
        with col2:
            csv_data = df_table[cols].to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download Data (CSV)",
                data=csv_data,
                file_name="data_monitoring.csv",
                mime="text/csv",
                use_container_width=True
            )
            
        st.dataframe(df_table[cols], use_container_width=True, height=540, hide_index=True)
    else:
        st.info("Click 'SCAN' to populate data.")
