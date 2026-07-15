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
            olt_list = group['OLT'].unique()
            olt_display = ", ".join(sorted(set(olt_list)))
            
            # Hitung jumlah tiap status (case-insensitive & clean)
            status_counts = group[target_col].astype(str).str.strip().str.lower().value_counts()
            
            badrx = status_counts.get('badrx', 0)
            los = status_counts.get('los', 0)
            dying = status_counts.get('dyinggasp', 0)
            suspend = sum(v for k, v in status_counts.items() if 'suspend' in k)
            
            summary_rows.append({
                "OLT": olt_display,
                "Region": region,
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
            
        def style_los(val):
            return 'background-color: rgba(244,63,94,0.15); color: #F43F5E; font-weight: 800;' if val > 0 else 'color: rgba(255,255,255,0.2);'
        def style_badrx(val):
            return 'background-color: rgba(245,158,11,0.15); color: #F59E0B; font-weight: 800;' if val > 0 else 'color: rgba(255,255,255,0.2);'
        def style_dying(val):
            return 'background-color: rgba(168,85,247,0.15); color: #A855F7; font-weight: 800;' if val > 0 else 'color: rgba(255,255,255,0.2);'
        def style_suspend(val):
            return 'background-color: rgba(100,116,139,0.15); color: #94A3B8; font-weight: 800;' if val > 0 else 'color: rgba(255,255,255,0.2);'

        styled_df = df_summary.style.applymap(style_los, subset=['LOS']) \
                                    .applymap(style_badrx, subset=['Bad Rx']) \
                                    .applymap(style_dying, subset=['Dying Gasp']) \
                                    .applymap(style_suspend, subset=['Suspend'])

        st.dataframe(
            styled_df,
            use_container_width=True,
            height=540,
            hide_index=True,
            column_config={
                "No": st.column_config.NumberColumn("No", width=40),
                "OLT": st.column_config.TextColumn("OLT", width="large"),
                "Region": st.column_config.TextColumn("Region", width="medium"),
                "Bad Rx": st.column_config.NumberColumn("Bad Rx", width="small"),
                "LOS": st.column_config.NumberColumn("LOS", width="small"),
                "Dying Gasp": st.column_config.NumberColumn("Dying Gasp", width="small"),
                "Suspend": st.column_config.NumberColumn("Suspend", width="small"),
            }
        )
    else:
        st.info("Click 'SCAN' to populate data.")

