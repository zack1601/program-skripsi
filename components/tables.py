import streamlit as st

import io
import pandas as pd
from components.telegram import get_region_from_olt

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
        st.markdown("<p style='font-size:0.8rem; font-weight:800; color:#8B949E; margin-bottom:10px;'>LIVE MONITORING TABLE (RESUME GANGGUAN)</p>", unsafe_allow_html=True)
    
    if not df_filtered.empty:
        # Agregasi data
        summary_rows = []
        # Gunakan 'Category' atau 'Power/Cause' sesuai struktur df_filtered
        target_col = 'Category' if 'Category' in df_filtered.columns else 'Power/Cause'
        
        for olt, group in df_filtered.groupby('OLT'):
            region = get_region_from_olt(olt)
            
            # Hitung jumlah tiap status (case-insensitive & clean)
            status_counts = group[target_col].astype(str).str.strip().str.lower().value_counts()
            
            badrx = status_counts.get('badrx', 0)
            los = status_counts.get('los', 0)
            dying = status_counts.get('dyinggasp', 0)
            # Menghitung suspend (bisa Suspend atau Suspend/Isolir)
            suspend = sum(v for k, v in status_counts.items() if 'suspend' in k)
            
            summary_rows.append({
                "OLT": olt,
                "Region": region,
                "Bad Rx": badrx,
                "LOS": los,
                "Dying Gasp": dying,
                "Suspend": suspend
            })
            
        df_summary = pd.DataFrame(summary_rows)
        # Tambahkan Nomor Urut (No)
        df_summary.insert(0, 'No', range(1, len(df_summary) + 1))
        
        # Add Download Button on the right
        with col2:
            excel_data = to_excel_with_autofit(df_summary)
            st.download_button(
                label="📥 Download Excel",
                data=excel_data,
                file_name="resume_gangguan.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
            
        st.dataframe(df_summary, use_container_width=True, height=540, hide_index=True)
    else:
        st.info("Click 'SCAN' to populate data.")

