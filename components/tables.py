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
        # Gunakan 'Category' atau 'Power/Cause' sesuai struktur df_filtered
        target_col = 'Category' if 'Category' in df_filtered.columns else 'Power/Cause'
        
        # Tambahkan kolom Region ke dataframe
        df_work = df_filtered.copy()
        df_work['Region'] = df_work['OLT'].apply(get_region_from_olt)
        
        # Agregasi per REGION (bukan per OLT individual)
        summary_rows = []
        for region, group in df_work.groupby('Region'):
            # Kumpulkan nama OLT unik di region ini
            olt_list = sorted(set(group['OLT'].unique()))
            olt_count = len(olt_list)
            olt_display = ", ".join(olt_list)  # Untuk Excel saja
            
            # Hitung jumlah tiap status (case-insensitive & clean)
            status_counts = group[target_col].astype(str).str.strip().str.lower().value_counts()
            
            badrx = status_counts.get('badrx', 0)
            los = status_counts.get('los', 0)
            dying = status_counts.get('dyinggasp', 0)
            suspend = sum(v for k, v in status_counts.items() if 'suspend' in k)
            
            summary_rows.append({
                "Region": region,
                "Jumlah OLT": olt_count,
                "OLT (Detail)": olt_display,  # Kolom Excel
                "Bad Rx": badrx,
                "LOS": los,
                "Dying Gasp": dying,
                "Suspend": suspend
            })
            
        df_summary = pd.DataFrame(summary_rows)
        # Filter: hanya tampilkan Region yang punya gangguan (total > 0)
        df_summary = df_summary[
            (df_summary['Bad Rx'] + df_summary['LOS'] + df_summary['Dying Gasp'] + df_summary['Suspend']) > 0
        ].reset_index(drop=True)
        # Tambahkan Nomor Urut (No)
        df_summary.insert(0, 'No', range(1, len(df_summary) + 1))
        
        # Add Download Button on the right (Excel menyertakan kolom OLT Detail)
        with col2:
            excel_data = to_excel_with_autofit(df_summary)
            st.download_button(
                label="📥 Download Excel",
                data=excel_data,
                file_name="resume_gangguan.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
        
        # Helper untuk badge metrik
        def format_metric(val, color, bg_color):
            if val > 0:
                return f"<span style='background-color:{bg_color}; color:{color}; padding:3px 10px; border-radius:12px; font-size:0.9rem; font-weight:800;'>{val}</span>"
            return f"<span style='color:rgba(255,255,255,0.15); font-size:0.9rem;'>—</span>"

        # --- TABLE HEADER ---
        h_cols = st.columns([0.3, 2.0, 0.8, 1, 1, 1, 1])
        headers = ["No", "Region", "OLT", "Bad Rx", "LOS", "Dying Gasp", "Suspend"]
        for hc, ht in zip(h_cols, headers):
            hc.markdown(
                f"<span style='font-size:0.72rem; color:#8b949e; font-weight:700; text-transform:uppercase; letter-spacing:1px;'>{ht}</span>",
                unsafe_allow_html=True
            )
            
        st.markdown("<hr style='margin:4px 0 8px 0; border-color:#30363d;'>", unsafe_allow_html=True)
        
        # --- TABLE ROWS ---
        for idx, r in df_summary.iterrows():
            row_cols = st.columns([0.3, 2.0, 0.8, 1, 1, 1, 1])
            
            # No
            row_cols[0].markdown(
                f"<span style='font-size:0.9rem; color:#484f58; font-weight:600;'>{idx+1}</span>",
                unsafe_allow_html=True
            )
            # Region - nama besar & terang
            row_cols[1].markdown(
                f"<span style='font-size:1rem; color:#e6edf3; font-weight:700; letter-spacing:0.3px;'>{r['Region']}</span>",
                unsafe_allow_html=True
            )
            # Jumlah OLT - badge kecil
            row_cols[2].markdown(
                f"<span style='background:rgba(88,166,255,0.12); color:#58a6ff; padding:2px 8px; border-radius:8px; font-size:0.82rem; font-weight:600;'>{r['Jumlah OLT']} OLT</span>",
                unsafe_allow_html=True
            )
            # Metrics
            row_cols[3].markdown(format_metric(r['Bad Rx'],    "#F59E0B", "rgba(245,158,11,0.15)"),  unsafe_allow_html=True)
            row_cols[4].markdown(format_metric(r['LOS'],       "#F43F5E", "rgba(244,63,94,0.15)"),   unsafe_allow_html=True)
            row_cols[5].markdown(format_metric(r['Dying Gasp'],"#A855F7", "rgba(168,85,247,0.15)"), unsafe_allow_html=True)
            row_cols[6].markdown(format_metric(r['Suspend'],   "#94A3B8", "rgba(100,116,139,0.15)"),unsafe_allow_html=True)
            
            st.markdown("<hr style='margin:4px 0; border-color:#21262d;'>", unsafe_allow_html=True)
    else:
        st.info("Click 'SCAN' to populate data.")
