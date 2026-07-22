import streamlit as st
import io
import pandas as pd
from components.telegram import get_region_from_olt

@st.cache_data(show_spinner=False)
def to_excel_with_autofit(df: pd.DataFrame) -> bytes:
    """Generates Excel file in memory with auto-adjusting column widths (cached)."""
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
                lines = val_to_check.split('\n')
                for line in lines:
                    if len(line) > max_len:
                        max_len = len(line)
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
        target_col = 'Category' if 'Category' in df_filtered.columns else 'Power/Cause'
        
        df_work = df_filtered.copy()
        df_work['Region'] = df_work['OLT'].apply(get_region_from_olt)
        
        import re
        def normalize_olt(name):
            name = re.sub(r'\s+OLT[-\s]+\d+\s*$', '', str(name), flags=re.IGNORECASE).strip()
            name = re.sub(r'\s*-\s*OLT-\d+\s*$', '', name, flags=re.IGNORECASE).strip()
            return name
            
        summary_rows = []
        for region, group in df_work.groupby('Region'):
            olt_list_raw  = sorted(set(group['OLT'].unique()))
            olt_list_norm = sorted(set(normalize_olt(o) for o in olt_list_raw))
            olt_display = ", ".join(olt_list_norm)

            status_counts = group[target_col].astype(str).str.strip().str.lower().value_counts()
            
            badrx = status_counts.get('badrx', 0)
            los = status_counts.get('los', 0)
            dying = status_counts.get('dyinggasp', 0)
            suspend = sum(v for k, v in status_counts.items() if 'suspend' in k)
            
            summary_rows.append({
                "Region": region,
                "Total User": len(group),
                "OLT (Detail)": olt_display,
                "Bad Rx": badrx,
                "LOS": los,
                "Dying Gasp": dying,
                "Suspend": suspend
            })
            
        df_summary = pd.DataFrame(summary_rows)
        df_summary = df_summary[
            (df_summary['Bad Rx'] + df_summary['LOS'] + df_summary['Dying Gasp'] + df_summary['Suspend']) > 0
        ].reset_index(drop=True)
        df_summary.insert(0, 'No', range(1, len(df_summary) + 1))
        
        with col2:
            excel_data = to_excel_with_autofit(df_summary)
            st.download_button(
                label="📥 Download Excel",
                data=excel_data,
                file_name="resume_gangguan.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
        
        def fmt_m(val, color, bg_color):
            if val > 0:
                return f"<span style='background-color:{bg_color}; color:{color}; padding:3px 10px; border-radius:12px; font-size:0.85rem; font-weight:800;'>{val}</span>"
            return "<span style='color:rgba(255,255,255,0.15); font-size:0.85rem;'>—</span>"

        rows_html = ""
        for idx, r in df_summary.iterrows():
            rows_html += f"""
            <tr style='border-bottom:1px solid #21262d;'>
                <td style='padding:10px 8px; font-size:0.85rem; color:#484f58; font-weight:600;'>{idx+1}</td>
                <td style='padding:10px 8px; font-size:0.95rem; color:#e6edf3; font-weight:700;'>{r['Region']}</td>
                <td style='padding:10px 8px;'><span style='background:rgba(63,185,80,0.12); color:#3fb950; padding:3px 10px; border-radius:8px; font-size:0.85rem; font-weight:700;'>{r['Total User']}</span></td>
                <td style='padding:10px 8px;'>{fmt_m(r['Bad Rx'], "#F59E0B", "rgba(245,158,11,0.15)")}</td>
                <td style='padding:10px 8px;'>{fmt_m(r['LOS'], "#F43F5E", "rgba(244,63,94,0.15)")}</td>
                <td style='padding:10px 8px;'>{fmt_m(r['Dying Gasp'], "#A855F7", "rgba(168,85,247,0.15)")}</td>
                <td style='padding:10px 8px;'>{fmt_m(r['Suspend'], "#94A3B8", "rgba(100,116,139,0.15)")}</td>
            </tr>
            """

        table_html = f"""
        <div style='background:#0d1117; border:1px solid #30363d; border-radius:12px; padding:12px 16px; margin-top:8px;'>
            <table style='width:100%; border-collapse:collapse; text-align:left; font-family:Inter,sans-serif;'>
                <thead>
                    <tr style='border-bottom:1.5px solid #30363d;'>
                        <th style='padding:8px; font-size:0.72rem; color:#8b949e; font-weight:700; text-transform:uppercase; width:40px;'>No</th>
                        <th style='padding:8px; font-size:0.72rem; color:#8b949e; font-weight:700; text-transform:uppercase;'>Region</th>
                        <th style='padding:8px; font-size:0.72rem; color:#8b949e; font-weight:700; text-transform:uppercase;'>Total User</th>
                        <th style='padding:8px; font-size:0.72rem; color:#8b949e; font-weight:700; text-transform:uppercase;'>Bad Rx</th>
                        <th style='padding:8px; font-size:0.72rem; color:#8b949e; font-weight:700; text-transform:uppercase;'>LOS</th>
                        <th style='padding:8px; font-size:0.72rem; color:#8b949e; font-weight:700; text-transform:uppercase;'>Dying Gasp</th>
                        <th style='padding:8px; font-size:0.72rem; color:#8b949e; font-weight:700; text-transform:uppercase;'>Suspend</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
        """
        st.markdown(table_html, unsafe_allow_html=True)
    else:
        st.info("Click 'START SCAN' to populate data.")
