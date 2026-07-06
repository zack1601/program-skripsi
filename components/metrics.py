import streamlit as st

def render_metrics(df_filtered):
    """
    Renders Network Summary Cards + Risk Gauge as a STICKY HEADER.
    All output is pure HTML so position:sticky works reliably in Streamlit.
    """
    # ── Calculations ──────────────────────────────────────────────
    total_ont = len(df_filtered) if not df_filtered.empty else 0
    online    = len(df_filtered[df_filtered['Category'] == 'Online']) if not df_filtered.empty else 0
    los       = len(df_filtered[df_filtered['Category'] == 'LOS'])      if not df_filtered.empty else 0
    badrx     = len(df_filtered[df_filtered['Category'] == 'BadRx'])    if not df_filtered.empty else 0
    dying     = len(df_filtered[df_filtered['Category'] == 'Dyinggasp'])if not df_filtered.empty else 0
    suspend   = len(df_filtered[df_filtered['Category'] == 'Suspend'])  if not df_filtered.empty else 0
    risk      = round(((los + badrx + dying) / total_ont * 100), 1) if total_ont > 0 else 0

    # ── Risk gauge colour ─────────────────────────────────────────
    if risk < 30:
        gauge_color  = "#10B981"
        risk_label   = "LOW RISK"
    elif risk < 70:
        gauge_color  = "#F59E0B"
        risk_label   = "MEDIUM"
    else:
        gauge_color  = "#F43F5E"
        risk_label   = "HIGH RISK"

    # ── SVG donut gauge (no Plotly, no iframe) ────────────────────
    # Circumference of r=40 circle = 2π×40 ≈ 251.3
    R          = 40
    CIRC       = 2 * 3.14159 * R
    filled     = round(CIRC * (risk / 100), 2)
    empty      = round(CIRC - filled, 2)

    gauge_svg = f"""<svg viewBox="0 0 100 100" width="110" height="110">
<circle cx="50" cy="50" r="{R}" fill="none" stroke="#21262d" stroke-width="10"/>
<circle cx="50" cy="50" r="{R}" fill="none" stroke="{gauge_color}" stroke-width="10" stroke-dasharray="{filled} {empty}" stroke-dashoffset="{CIRC * 0.25}" stroke-linecap="round"/>
<text x="50" y="46" text-anchor="middle" font-size="16" font-weight="800" fill="#ffffff" font-family="Share Tech Mono, monospace">{risk}%</text>
<text x="50" y="60" text-anchor="middle" font-size="7.5" font-weight="700" fill="{gauge_color}" font-family="Share Tech Mono, monospace">{risk_label}</text>
</svg>"""

    # ── Full sticky HTML block ────────────────────────────────────
    st.markdown(f"""
<div class="nw-sticky-bar">
<div class="nw-sticky-inner">
<p class="nw-section-label">NETWORK SUMMARY</p>
<div class="nw-cards-gauge-row">
<div class="nw-cards-row">
<div class="nw-card nw-total"><div class="nw-card-label">TOTAL</div><div class="nw-card-val">{total_ont}</div></div>
<div class="nw-card nw-online"><div class="nw-card-label">ONLINE</div><div class="nw-card-val" style="color:#10B981;">{online}</div></div>
<div class="nw-card nw-los"><div class="nw-card-label">LOS</div><div class="nw-card-val" style="color:#F43F5E;">{los}</div></div>
<div class="nw-card nw-badrx"><div class="nw-card-label">BADRX</div><div class="nw-card-val" style="color:#F59E0B;">{badrx}</div></div>
<div class="nw-card nw-dying"><div class="nw-card-label">DYING</div><div class="nw-card-val" style="color:#A855F7;">{dying}</div></div>
<div class="nw-card nw-suspend"><div class="nw-card-label">SUSPEND</div><div class="nw-card-val" style="color:#64748B;">{suspend}</div></div>
</div>
<div class="nw-gauge">
{gauge_svg}
</div>
</div>
</div>
</div>
""", unsafe_allow_html=True)


