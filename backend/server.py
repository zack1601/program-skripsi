from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import json
import asyncio
import pandas as pd
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np

# Import existing logic
from config import INPUT_FILE, MAX_WORKERS
from main import process_olt_audit

app = FastAPI()

# Enable CORS for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def apply_business_logic(row):
    status = str(row.get('status', "")).strip().capitalize()
    rx_power = row.get('rx_power', "-")
    cause_raw = str(row.get('last_down_cause', "")).lower()

    if status == 'Online':
        try:
            val = float(rx_power)
            if val < -25.99: return "BadRx"
            return f"{val} dBm"
        except: return rx_power if rx_power != "-" else "-"
    
    if any(x in cause_raw for x in ['admin', 'suspend', 'isolated', 'deactive']): 
        return "Suspend"
    if any(x in cause_raw for x in ['losi', 'lobi', 'los']): 
        return "LOS"
    if any(x in cause_raw for x in ['dying', 'power-off']): 
        return "Dyinggasp"
    
    return "Offline"

@app.get("/api/scan")
async def scan_olt():
    async def event_generator():
        try:
            # Read input Excel
            df_input = pd.read_excel(INPUT_FILE)
            df_input.columns = df_input.columns.str.strip().str.lower()
            
            olt_map = defaultdict(lambda: {"name": "", "slots": set()})
            ip_col = next((c for c in df_input.columns if 'ip' in c), 'ip_olt')
            
            # Fill OLT names for rows where they might be merged
            df_input['olt'] = df_input['olt'].ffill()
            
            for _, r in df_input.iterrows():
                ip = str(r.get(ip_col, "")).strip()
                olt_map[ip]["name"] = str(r.get('olt', "")).strip()
                port = str(r.get('port', "")).strip()
                match = re.search(r'(\d+)\s*/\s*(\d+)\s*/\s*(\d+)', port)
                if match: 
                    olt_map[ip]["slots"].add(f"{match.group(1)}/{match.group(2)}")

            sn_map_input = {str(r.get('serial number', '')).strip().upper(): r for _, r in df_input.iterrows()}
            total_olt = len(olt_map)
            
            yield json.dumps({"type": "info", "message": f"Starting scan on {total_olt} OLTs..."}) + "\n"

            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = {executor.submit(process_olt_audit, g["name"], ip, list(g["slots"])): ip for ip, g in olt_map.items()}
                
                for future in as_completed(futures):
                    scan_results = future.result()
                    for s in scan_results:
                        sn_scan = str(s.get('sn', "")).strip().upper()
                        row_in = sn_map_input.get(sn_scan, {})
                        
                        # ID & Name Extraction
                        id_pel = str(row_in.get('id_pelanggan', row_in.get('id', ''))).strip()
                        nama_pel = str(row_in.get('nama_pelanggan', row_in.get('nama', ''))).strip()
                        desc = str(s.get('description', '')).strip()
                        
                        if (not id_pel or id_pel.lower() == 'nan') and desc:
                            match_id = re.search(r'(\d{10,13})', desc)
                            if match_id:
                                id_pel = match_id.group(1)
                                remaining = desc.replace(id_pel, "").strip(" -_/")
                                if not nama_pel or nama_pel.lower() == 'nan':
                                    nama_pel = remaining
                        
                        id_pel = id_pel if id_pel and id_pel.lower() != 'nan' else "11100" + str(np.random.randint(100000, 999999))
                        nama_pel = nama_pel if nama_pel and nama_pel.lower() != 'nan' else "-"

                        # Coordinates Mockup (Random for Demo)
                        lat = -6.20 + (np.random.random() * 0.1)
                        lon = 106.81 + (np.random.random() * 0.1)

                        record = {
                            "olt": str(row_in.get('olt', s.get('olt_name', '-'))),
                            "customer": f"{id_pel}-{nama_pel}",
                            "port": str(row_in.get('port', s.get('port_override', '-'))),
                            "sn": s.get('sn'),
                            "status": s.get('status'),
                            "rx_power": s.get('rx_power'),
                            "last_down_cause": s.get('last_down_cause'),
                            "lat": lat,
                            "lon": lon
                        }
                        record["power_cause"] = apply_business_logic(record)
                        
                        yield json.dumps({"type": "data", "payload": record}) + "\n"
                        await asyncio.sleep(0.01) # Tiny sleep to help streaming

            yield json.dumps({"type": "done", "message": "Scan completed."}) + "\n"
            
        except Exception as e:
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
