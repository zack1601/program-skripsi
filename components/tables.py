import streamlit as st

import io
import pandas as pd

def to_excel_with_autofit(df: pd.DataFrame) -> bytes:
    """Generates Excel file in memory with auto-adjusting column widths."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Monitoring Data')
        worksheet = writer.sheets['Monitoring Data']
        
        # Auto-adjust column widths
        for col in worksheet.columns:
            max_len = 0
            col_letter = col[0].column_letter
            for cell in col:
                val_to_check = str(cell.value or '')
                # Handle potential line breaks
                lines = val_to_check.split('\n')
                for line in lines:
                    if len(line) > max_len:
                        max_len = len(line)
            # Add padding and set minimum width
            worksheet.column_dimensions[col_letter].width = max(max_len + 3, 11)
            
    return output.getvalue()

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
            excel_data = to_excel_with_autofit(df_table[cols])
            st.download_button(
                label="📥 Download Excel (XLSX)",
                data=excel_data,
                file_name="data_monitoring.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
            
        st.dataframe(df_table[cols], use_container_width=True, height=540, hide_index=True)
    else:
        st.info("Click 'SCAN' to populate data.")

