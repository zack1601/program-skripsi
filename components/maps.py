import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import numpy as np
from parser import calculate_haversine_distance

def simple_kmeans(points, k, iterations=3):
    if not points or k <= 0: return []
    # If points less than k, each point is a cluster
    if len(points) <= k: 
        return [[p[0], p[1], [p]] for p in points]
    
    # Initialize centroids with first k points (naive selection)
    centroids = [[points[i][0], points[i][1]] for i in range(k)]
    
    for _ in range(iterations):
        clusters = [[] for _ in range(k)]
        for p in points:
            # Squared Euclidean distance
            dists = [((p[0]-c[0])**2 + (p[1]-c[1])**2) for c in centroids]
            best_idx = dists.index(min(dists))
            clusters[best_idx].append(p)
            
        # Update centroids to mean of assigned points
        for i in range(k):
            if clusters[i]:
                centroids[i] = [
                    sum(p[0] for p in clusters[i]) / len(clusters[i]),
                    sum(p[1] for p in clusters[i]) / len(clusters[i])
                ]
    
    return [[centroids[i][0], centroids[i][1], clusters[i]] for i in range(k)]

def get_olt_coordinate(hostname):
    hostname = str(hostname).upper()
    mapping = {
        'SENOPATI': [-6.2314, 106.8091],
        'KALIJATI': [-6.3023, 106.7915],
        'CIPEDAK': [-6.3476, 106.8202],
        'FATMAWATI': [-6.2652, 106.7971],
        'LENTENG.AGUNG': [-6.3301, 106.8322],
        'CINERE': [-6.3423, 106.7761],
        'CIGANJUR': [-6.3411, 106.8115]
    }
    for key, coords in mapping.items():
        if key in hostname:
            return coords
    return None

def render_map(df_filtered):
    """
    Renders the Geographic Folium Map representing OLT, FDT, FAT clusters and ONT endpoints.
    """
    st.markdown("<p style='font-size:0.8rem; font-weight:800; color:#8B949E; margin-bottom:10px;'>GEOGRAPHIC STATUS DISTRIBUTION</p>", unsafe_allow_html=True)

    if not df_filtered.empty:
        df_disp = df_filtered.copy()
        if df_disp['lat'].notnull().any():
            mean_lat = df_disp['lat'].mean()
            mean_lon = df_disp['lon'].mean()
            m = folium.Map(location=[mean_lat, mean_lon], zoom_start=13, tiles='https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}', attr='Google Hybrid')
            
            # Inject FontAwesome and Share Tech Mono for high-fidelity custom DivIcons inside Folium iframe
            m.get_root().header.add_child(folium.Element('<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">'))
            m.get_root().header.add_child(folium.Element('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap">'))
            
            coordinates_list = []
            for olt_name, olt_df in df_disp.groupby('OLT'):
                o_lat, o_lon = olt_df['olt_lat'].iloc[0], olt_df['olt_lon'].iloc[0]
                if pd.notnull(o_lat):
                    # 📡 OLT Custom Tooltip & Marker (DivIcon)
                    tooltip_olt = f"""
                    <div style='font-family: "Share Tech Mono", monospace; padding: 12px; border-radius: 10px; background: #0d1117; border: 1.5px solid #00F0FF; color: white; min-width: 210px; box-shadow: 0 4px 20px rgba(0,0,0,0.5);'>
                        <div style='color: #00F0FF; font-weight: 800; font-size: 0.95rem; border-bottom: 1px solid #30363d; padding-bottom: 6px; margin-bottom: 8px; display: flex; align-items: center; gap: 6px;'>
                            <i class="fa-solid fa-tower-broadcast"></i> OLT
                        </div>
                        <table style='width: 100%; font-size: 0.85rem; border-collapse: collapse;'>
                            <tr style='border-bottom: 1px solid rgba(255,255,255,0.05);'><td style='padding: 4px 0; color: #8B949E;'>Hostname:</td><td style='padding: 4px 0; font-weight: bold; text-align: right;'>{olt_name}</td></tr>
                            <tr style='border-bottom: 1px solid rgba(255,255,255,0.05);'><td style='padding: 4px 0; color: #8B949E;'>Koordinat:</td><td style='padding: 4px 0; font-family: monospace; text-align: right;'>{o_lat:.5f}, {o_lon:.5f}</td></tr>
                            <tr><td style='padding: 4px 0; color: #8B949E;'>Total ONT:</td><td style='padding: 4px 0; font-weight: bold; color: #00F0FF; text-align: right;'>{len(olt_df)} Pelanggan</td></tr>
                        </table>
                    </div>
                    """
                    folium.Marker(
                        location=[o_lat, o_lon],
                        icon=folium.DivIcon(
                            icon_size=(36, 36),
                            icon_anchor=(18, 18),
                            html=f"""
                            <div style="
                                background: linear-gradient(135deg, #00F0FF, #0072FF);
                                color: white;
                                width: 36px;
                                height: 36px;
                                border-radius: 50%;
                                display: flex;
                                align-items: center;
                                justify-content: center;
                                box-shadow: 0 0 15px rgba(0, 240, 255, 0.8);
                                border: 2px solid #ffffff;
                                font-size: 15px;
                                transition: transform 0.2s ease-in-out;
                                cursor: pointer;
                            " onmouseover="this.style.transform='scale(1.25)';" onmouseout="this.style.transform='scale(1.0)';">
                                <i class="fa-solid fa-tower-broadcast"></i>
                            </div>
                            """
                        ),
                        tooltip=tooltip_olt
                    ).add_to(m)
                    
                    coordinates_list.append([o_lat, o_lon])
                    
                    # Fetch target users: ['lat', 'lon', 'Category', 'Nama/ID Pelanggan', 'Power/Cause', 'maps', 'Serial Number', 'Port']
                    user_points = olt_df[['lat', 'lon', 'Category', 'Nama/ID Pelanggan', 'Power/Cause', 'maps', 'Serial Number', 'Port']].values.tolist()
                    k_fat = max(1, len(user_points) // 14)
                    fat_clusters = simple_kmeans(user_points, k_fat)
                    k_odc = max(1, len(fat_clusters) // 6)
                    fat_points = [[c[0], c[1], c[2]] for c in fat_clusters]
                    odc_clusters = simple_kmeans(fat_points, k_odc)
                    
                    for odc_lat, odc_lon, cluster_fats in odc_clusters:
                        odc_loc = [odc_lat, odc_lon]
                        folium.PolyLine(locations=[[o_lat, o_lon], odc_loc], color="#FACC15", weight=9).add_to(m)
                        
                        dist_olt_odc = calculate_haversine_distance(o_lat, o_lon, odc_lat, odc_lon)
                        dist_str_odc = f"{dist_olt_odc/1000:.2f} km" if dist_olt_odc >= 1000 else f"{dist_olt_odc:.0f} m"
                        
                        # 🗄️ ODC Custom Tooltip & Marker (DivIcon)
                        tooltip_odc = f"""
                        <div style='font-family: "Share Tech Mono", monospace; padding: 12px; border-radius: 10px; background: #0d1117; border: 1.5px solid #10B981; color: white; min-width: 200px; box-shadow: 0 4px 20px rgba(0,0,0,0.5);'>
                            <div style='color: #10B981; font-weight: 800; font-size: 0.95rem; border-bottom: 1px solid #30363d; padding-bottom: 6px; margin-bottom: 8px; display: flex; align-items: center; gap: 6px;'>
                                <i class="fa-solid fa-folder-tree"></i> FDT (Fiber Distribution Terminal)
                            </div>
                            <table style='width: 100%; font-size: 0.85rem; border-collapse: collapse;'>
                                <tr style='border-bottom: 1px solid rgba(255,255,255,0.05);'><td style='padding: 4px 0; color: #8B949E;'>Tipe:</td><td style='padding: 4px 0; font-weight: bold; text-align: right;'>Fiber Distribution Terminal</td></tr>
                                <tr style='border-bottom: 1px solid rgba(255,255,255,0.05);'><td style='padding: 4px 0; color: #8B949E;'>Koordinat:</td><td style='padding: 4px 0; font-family: monospace; text-align: right;'>{odc_lat:.5f}, {odc_lon:.5f}</td></tr>
                                <tr style='border-bottom: 1px solid rgba(255,255,255,0.05);'><td style='padding: 4px 0; color: #8B949E;'>Jarak Kabel Feeder (dari OLT):</td><td style='padding: 4px 0; font-weight: bold; color: #FACC15; text-align: right;'>{dist_str_odc}</td></tr>
                                <tr><td style='padding: 4px 0; color: #8B949E;'>Ratio Splitter:</td><td style='padding: 4px 0; font-weight: bold; color: #10B981; text-align: right;'>1:8 Primary Splitter</td></tr>
                            </table>
                        </div>
                        """
                        folium.Marker(
                            location=odc_loc,
                            icon=folium.DivIcon(
                                icon_size=(26, 26),
                                icon_anchor=(13, 13),
                                html=f"""
                                <div style="
                                    background: linear-gradient(135deg, #10B981, #059669);
                                    color: white;
                                    width: 26px;
                                    height: 26px;
                                    border-radius: 6px;
                                    display: flex;
                                    align-items: center;
                                    justify-content: center;
                                    box-shadow: 0 0 10px rgba(16, 185, 129, 0.7);
                                    border: 1.5px solid #ffffff;
                                    font-size: 12px;
                                    transition: transform 0.2s ease-in-out;
                                    cursor: pointer;
                                " onmouseover="this.style.transform='scale(1.25)';" onmouseout="this.style.transform='scale(1.0)';">
                                    <i class="fa-solid fa-folder-tree"></i>
                                </div>
                                """
                            ),
                            tooltip=tooltip_odc,
                            popup=folium.Popup(tooltip_odc, max_width=350)
                        ).add_to(m)
                        
                        for f_lat, f_lon, cluster_users in cluster_fats:
                            fat_loc = [f_lat, f_lon]
                            folium.PolyLine(locations=[odc_loc, fat_loc], color="#22D3EE", weight=5).add_to(m)
                            
                            dist_odc_fat = calculate_haversine_distance(odc_lat, odc_lon, f_lat, f_lon)
                            dist_str_fat = f"{dist_odc_fat/1000:.2f} km" if dist_odc_fat >= 1000 else f"{dist_odc_fat:.0f} m"
                            
                            # 🔌 ODP Custom Tooltip & Marker (DivIcon)
                            tooltip_fat = f"""
                            <div style='font-family: "Share Tech Mono", monospace; padding: 12px; border-radius: 10px; background: #0d1117; border: 1.5px solid #F59E0B; color: white; min-width: 200px; box-shadow: 0 4px 20px rgba(0,0,0,0.5);'>
                                <div style='color: #F59E0B; font-weight: 800; font-size: 0.95rem; border-bottom: 1px solid #30363d; padding-bottom: 6px; margin-bottom: 8px; display: flex; align-items: center; gap: 6px;'>
                                    <i class="fa-solid fa-circle-nodes"></i> FAT NODE (FIBER ACCESS TERMINAL)
                                </div>
                                <table style='width: 100%; font-size: 0.85rem; border-collapse: collapse;'>
                                    <tr style='border-bottom: 1px solid rgba(255,255,255,0.05);'><td style='padding: 4px 0; color: #8B949E;'>Tipe:</td><td style='padding: 4px 0; font-weight: bold; text-align: right;'>Fiber Access Terminal</td></tr>
                                    <tr style='border-bottom: 1px solid rgba(255,255,255,0.05);'><td style='padding: 4px 0; color: #8B949E;'>Koordinat:</td><td style='padding: 4px 0; font-family: monospace; text-align: right;'>{f_lat:.5f}, {f_lon:.5f}</td></tr>
                                    <tr style='border-bottom: 1px solid rgba(255,255,255,0.05);'><td style='padding: 4px 0; color: #8B949E;'>Jarak Kabel Distribusi (dari FDT):</td><td style='padding: 4px 0; font-weight: bold; color: #22D3EE; text-align: right;'>{dist_str_fat}</td></tr>
                                    <tr style='border-bottom: 1px solid rgba(255,255,255,0.05);'><td style='padding: 4px 0; color: #8B949E;'>Ratio Splitter:</td><td style='padding: 4px 0; font-weight: bold; color: #F59E0B; text-align: right;'>1:8 Secondary Splitter</td></tr>
                                    <tr><td style='padding: 4px 0; color: #8B949E;'>Total ONT:</td><td style='padding: 4px 0; font-weight: bold; color: #F59E0B; text-align: right;'>{len(cluster_users)} Pelanggan</td></tr>
                                </table>
                            </div>
                            """
                            folium.Marker(
                                location=fat_loc,
                                icon=folium.DivIcon(
                                    icon_size=(22, 22),
                                    icon_anchor=(11, 11),
                                    html=f"""
                                    <div style="
                                        background: linear-gradient(135deg, #F59E0B, #D97706);
                                        color: white;
                                        width: 22px;
                                        height: 22px;
                                        border-radius: 50%;
                                        display: flex;
                                        align-items: center;
                                        justify-content: center;
                                        box-shadow: 0 0 8px rgba(245, 158, 11, 0.7);
                                        border: 1.5px solid #ffffff;
                                        font-size: 10px;
                                        transition: transform 0.2s ease-in-out;
                                        cursor: pointer;
                                    " onmouseover="this.style.transform='scale(1.25)';" onmouseout="this.style.transform='scale(1.0)';">
                                        <i class="fa-solid fa-circle-nodes"></i>
                                    </div>
                                    """
                                ),
                                tooltip=tooltip_fat,
                                popup=folium.Popup(tooltip_fat, max_width=350)
                            ).add_to(m)
                            
                            for u in cluster_users:
                                u_loc = [u[0], u[1]]
                                coordinates_list.append(u_loc)
                                
                                # Determine color, icon and label based on Category
                                u_color = "#10B981" # Online
                                u_icon = "fa-house"
                                u_status = str(u[2]).strip()
                                
                                if u_status == 'LOS':
                                    u_color = "#EF4444"
                                    u_icon = "fa-triangle-exclamation"
                                elif u_status == 'BadRx':
                                    u_color = "#F59E0B"
                                    u_icon = "fa-circle-exclamation"
                                elif u_status == 'Dyinggasp':
                                    u_color = "#A855F7"
                                    u_icon = "fa-plug-circle-xmark"
                                elif u_status == 'Suspend':
                                    u_color = "#64748B"
                                    u_icon = "fa-ban"
                                    
                                # Connection Fiber Cable line to ONT
                                folium.PolyLine(locations=[fat_loc, u_loc], color=u_color, weight=2).add_to(m)
                                
                                dist_fat_ont = calculate_haversine_distance(f_lat, f_lon, u_loc[0], u_loc[1])
                                dist_str_ont = f"{dist_fat_ont/1000:.2f} km" if dist_fat_ont >= 1000 else f"{dist_fat_ont:.0f} m"
                                dist_color = "#EF4444" if dist_fat_ont > 500 else "#10B981"
                                
                                # 💻 ONT Custom Tooltip & Marker (DivIcon)
                                tooltip_ont = f"""
                                <div style='font-family: "Share Tech Mono", monospace; padding: 12px; border-radius: 10px; background: #0d1117; border: 1.5px solid {u_color}; color: white; min-width: 230px; box-shadow: 0 4px 20px rgba(0,0,0,0.5);'>
                                    <div style='color: {u_color}; font-weight: 800; font-size: 0.95rem; border-bottom: 1px solid #30363d; padding-bottom: 6px; margin-bottom: 8px; display: flex; align-items: center; gap: 6px;'>
                                        <i class="fa-solid {u_icon}"></i> ONT: {u_status.upper()}
                                    </div>
                                    <table style='width: 100%; font-size: 0.85rem; border-collapse: collapse;'>
                                        <tr style='border-bottom: 1px solid rgba(255,255,255,0.05);'><td style='padding: 4px 0; color: #8B949E;'>Pelanggan:</td><td style='padding: 4px 0; font-weight: bold; text-align: right;'>{u[3]}</td></tr>
                                        <tr style='border-bottom: 1px solid rgba(255,255,255,0.05);'><td style='padding: 4px 0; color: #8B949E;'>SN ONT:</td><td style='padding: 4px 0; font-family: monospace; text-align: right;'>{u[6]}</td></tr>
                                        <tr style='border-bottom: 1px solid rgba(255,255,255,0.05);'><td style='padding: 4px 0; color: #8B949E;'>Port OLT:</td><td style='padding: 4px 0; text-align: right;'>{u[7]}</td></tr>
                                        <tr style='border-bottom: 1px solid rgba(255,255,255,0.05);'><td style='padding: 4px 0; color: #8B949E;'>Jarak Kabel Drop (dari FAT):</td><td style='padding: 4px 0; font-weight: bold; color: {dist_color}; text-align: right;'>{dist_str_ont}</td></tr>
                                        <tr><td style='padding: 4px 0; color: #8B949E;'>Redaman/Penyebab:</td><td style='padding: 4px 0; font-weight: 800; color: {u_color}; text-align: right;'>{u[4]}</td></tr>
                                    </table>
                                    <div style='margin-top: 10px; text-align: center; border-top: 1px solid #30363d; padding-top: 8px;'>
                                        <a href='{u[5]}' target='_blank' style='color: #58A6FF; text-decoration: none; font-size: 0.8rem; font-weight: bold;'>Buka Navigasi Rute ↗</a>
                                    </div>
                                </div>
                                """
                                
                                folium.Marker(
                                    location=u_loc,
                                    icon=folium.DivIcon(
                                        icon_size=(16, 16),
                                        icon_anchor=(8, 8),
                                        html=f"""
                                        <div style="
                                            background: {u_color};
                                            color: white;
                                            width: 16px;
                                            height: 16px;
                                            border-radius: 50%;
                                            display: flex;
                                            align-items: center;
                                            justify-content: center;
                                            box-shadow: 0 0 6px {u_color};
                                            border: 1px solid #ffffff;
                                            font-size: 8px;
                                            transition: transform 0.2s ease-in-out;
                                            cursor: pointer;
                                        " onmouseover="this.style.transform='scale(1.35)';" onmouseout="this.style.transform='scale(1.0)';">
                                            <i class="fa-solid {u_icon}" style="margin: 0; padding: 0;"></i>
                                        </div>
                                        """
                                    ),
                                    tooltip=tooltip_ont,
                                    popup=folium.Popup(tooltip_ont, max_width=350)
                                ).add_to(m)
            if coordinates_list: m.fit_bounds(coordinates_list, padding=(30, 30))
            import hashlib
            df_hash = hashlib.md5(pd.util.hash_pandas_object(df_filtered).values).hexdigest()
            st_folium(m, width="100%", height=350, key=f"ftth_map_{df_hash}", returned_objects=[])
        else:
            st.info("Waiting for GPS Data... (Map will appear here)")
    else:
        st.info("Map will appear here after scanning is complete...")
