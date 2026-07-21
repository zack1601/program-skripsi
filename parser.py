#!/usr/bin/env python3
"""
Modul Parser Output OLT
========================
Parsing output Huawei OLT menggunakan regex.

Author : Zaki Mubarok
Project: Program Skripsi
"""

import re
import logging
import math

logger = logging.getLogger(__name__)


def parse_ont_status(raw_output: str) -> dict:
    """Parse output 'display ont info by-sn'."""
    result = {
        "status": "Data Kosong",
        "ont_id": "",
        "fsp": "",
        "last_down_cause": "",
        "raw": raw_output,
    }
    
    if not raw_output or not raw_output.strip():
        return result
    
    lower = raw_output.lower()
    
    if '% unknown command' in lower or '% parameter error' in lower:
        result["status"] = "Error Perintah"
        return result
    
    if 'the ont does not exist' in lower or 'failure' in lower:
        result["status"] = "SN Tidak Ditemukan"
        return result
    
    # Control flag
    ctrl = re.search(r'Control flag\s*:\s*(\w+)', raw_output, re.IGNORECASE)
    if ctrl:
        flag = ctrl.group(1).lower()
        result["status"] = "Online" if flag == 'active' else "Offline"
    
    # Run state (fallback)
    if result["status"] == "Data Kosong":
        run = re.search(r'Run state\s*:\s*(\w+)', raw_output, re.IGNORECASE)
        if run:
            result["status"] = "Online" if run.group(1).lower() == 'online' else "Offline"
    
    # Text fallback
    if result["status"] == "Data Kosong":
        if 'online' in lower:
            result["status"] = "Online"
        elif 'offline' in lower:
            result["status"] = "Offline"
    
    # F/S/P
    fsp = re.search(r'F/S/P\s*:\s*(\S+)', raw_output, re.IGNORECASE)
    if fsp:
        result["fsp"] = fsp.group(1)
    
    # ONT ID
    ont_id = re.search(r'ONT[\s-]*ID\s*:\s*(\d+)', raw_output, re.IGNORECASE)
    if ont_id:
        result["ont_id"] = ont_id.group(1)
    
    # Last Down Cause
    down = re.search(r'Last down cause\s*:\s*(.+)', raw_output, re.IGNORECASE)
    if down:
        result["last_down_cause"] = down.group(1).strip()
    
    return result


def parse_ont_optical_info(raw_output: str) -> dict:
    """Parse output optical info (TX/RX power, dll)."""
    result = {
        "rx_power": "", "tx_power": "", "olt_rx_power": "",
        "temperature": "", "voltage": "", "bias_current": "",
        "raw": raw_output,
    }
    
    if not raw_output or not raw_output.strip():
        return result
    
    patterns = {
        "rx_power": r'Rx optical power\(dBm\)\s*:\s*([\-\d.]+)',
        "tx_power": r'Tx optical power\(dBm\)\s*:\s*([\-\d.]+)',
        "olt_rx_power": r'OLT Rx ONT optical power\(dBm\)\s*:\s*([\-\d.]+)',
        "temperature": r'Temperature\(C\)\s*:\s*([\-\d.]+)',
        "voltage": r'Voltage\(V\)\s*:\s*([\-\d.]+)',
        "bias_current": r'Bias current\(mA\)\s*:\s*([\-\d.]+)',
    }
    
    for key, pattern in patterns.items():
        match = re.search(pattern, raw_output, re.IGNORECASE)
        if match:
            result[key] = match.group(1)
    
    return result


def strip_ansi(text: str) -> str:
    """Hapus ANSI escape codes dari teks."""
    return re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)


def parse_ont_summary(raw_output: str) -> list:
    """
    Parse output 'display ont info summary' (mendukung format 1 tabel atau 2 tabel).
    Returns: list of dict [{ont_id, sn, status, rx_power, last_down_cause, description}]
    """
    if not raw_output:
        return []
        
    clean_output = strip_ansi(raw_output)
    lines = clean_output.splitlines()
    
    ont_data_map = {}
    current_port = "default"
    
    for line in lines:
        line_strip = line.strip()
        
        # Deteksi port jika command level slot (contoh: 0/7) memunculkan "In port 0/7/0..." atau "In GPON port 0/7/0"
        port_match = re.search(r'port\s+(\d+/\d+/\d+)', line_strip, re.IGNORECASE)
        if port_match:
            current_port = port_match.group(1)
            continue
            
        parts = line_strip.split()
        
        if not parts or not parts[0].isdigit():
            continue
            
        ont_id = parts[0]
        unique_key = f"{current_port}_{ont_id}"
        
        if unique_key not in ont_data_map:
            ont_data_map[unique_key] = {
                "ont_id": ont_id,
                "port_override": current_port,
                "sn": "",
                "status": "Offline",
                "rx_power": "",
                "last_down_cause": "",
                "description": ""
            }
            
        ont = ont_data_map[unique_key]
        line_lower = line_strip.lower()
        
        # 1. Cari SN (12-16 karakter alphanumeric)
        sn_idx = -1
        for i, p in enumerate(parts[1:], start=1):
            if len(p) >= 12 and p.isalnum():
                if p.lower() not in ['offline', 'online', 'active', 'normal', 'match', 'running']:
                    ont["sn"] = p.upper()
                    sn_idx = i
                    break
                    
        # 2. Cari Status (Online/Offline)
        if " online " in f" {line_lower} ":
            ont["status"] = "Online"
        elif " offline " in f" {line_lower} ":
            ont["status"] = "Offline"
            
        # 3. Cari Rx Power (biasanya format Rx/Tx misal -22.90/1.20)
        power_match = re.search(r'(-?\d+\.\d+)/', line_strip)
        if power_match:
            ont["rx_power"] = power_match.group(1)
            
        # 4. Cari Last Down Cause & Description
        known_causes = ["losi/lobi", "dying-gasp", "los", "power-off", "deactivate", "config-is-not-exist", "off-line", "reset", "fiber-cut", "comm-fail", "autorun-failed", "losi", "lobi", "-"]
        known_types = ["EG8041V5", "EG8141H5", "EG8141A5", "EG8141A", "EG8141", "EG8145V5", "HG8245H", "HG8245Q", "HG8546M", "EG8010H", "EG8145V5-V2"]
        
        # Deteksi khusus format Tabel 2 (ID Run-state UpTime DownTime Cause)
        if len(parts) >= 7 and parts[1].lower() in ["online", "offline", "active", "deactive"]:
            potential_cause = parts[-1].lower()
            if potential_cause in known_causes and potential_cause != "-":
                ont["last_down_cause"] = parts[-1]
        
        # Cari cause di seluruh kata dalam baris (pencarian kata utuh)
        for word in parts:
            word_clean = word.lower().strip()
            if word_clean in known_causes and word_clean != "-":
                if not ont["last_down_cause"] or ont["last_down_cause"] == "-":
                    ont["last_down_cause"] = word
                break

        if sn_idx != -1 and sn_idx + 1 < len(parts):
            next_word = parts[sn_idx + 1]
            
            # Lewati jika kata berikutnya adalah Tipe ONT
            start_desc_idx = sn_idx + 1
            if next_word := parts[sn_idx+1] if sn_idx + 1 < len(parts) else "":
                if next_word.upper() in known_types:
                    start_desc_idx = sn_idx + 2

            # Loop untuk melewati kolom Distance atau Power yang mungkin ada sebelum Description
            while start_desc_idx < len(parts):
                current_word = parts[start_desc_idx]
                current_lower = current_word.lower().strip()

                # JIKA ini adalah salah satu penyebab mati (known_causes), JANGAN dilewati
                if current_lower in known_causes and current_lower != "-":
                    break
                
                # Cek apakah ini Tipe ONT (mungkin ada lebih dari satu kata)
                if current_lower.upper() in known_types:
                    start_desc_idx += 1
                    continue
                
                # Cek apakah ini format redaman (misal -25.00/ atau -)
                if "/" in current_lower or current_lower == "-":
                    start_desc_idx += 1
                break

            if start_desc_idx < len(parts):
                next_word = parts[start_desc_idx]
                if next_word.lower() in known_causes:
                    if not ont["last_down_cause"] or ont["last_down_cause"] == "-":
                        ont["last_down_cause"] = "LOS" if next_word.lower() == "los" else next_word
                    if start_desc_idx + 1 < len(parts):
                        ont["description"] = " ".join(parts[start_desc_idx+1:])
                else:
                    ont["description"] = " ".join(parts[start_desc_idx:])
            
    # Proses akhir
    all_onts = []
    for ont in ont_data_map.values():
        if not ont["sn"]: ont["sn"] = "-"
        
        # Set Dismantle jika status Offline dan BENAR-BENAR tidak ada info cause
        if ont["status"] == "Offline":
            if not ont["last_down_cause"] or ont["last_down_cause"] == "-":
                # Kita set ke "-" dulu di parser, main.py yang akan mengubahnya ke Dismantle
                ont["last_down_cause"] = "-"
                
        all_onts.append(ont)
    
    # Sortir berdasarkan ont_id (numerik)
    all_onts.sort(key=lambda x: int(x["ont_id"]))
    
    return all_onts

def parse_ont_detail(raw_output: str) -> dict:
    """
    Parsing output detail dari 'display ont info by-sn'.
    Format:
        F/S/P                : 0/1/0
        ONT-ID               : 11
        Run state            : online
        Description          : 111...
        Last down cause      : dying-gasp
    """
    if not raw_output or "Failure" in raw_output or "does not exist" in raw_output:
        return None

    ont = {
        "port_override": "-",
        "ont_id": "-",
        "status": "-",
        "last_down_cause": "-",
        "description": "-",
        "rx_power": "-"
    }

    lines = raw_output.splitlines()
    fsp = ""
    ont_id = ""

    for line in lines:
        line_strip = line.strip()
        if not line_strip or ":" not in line_strip:
            continue
            
        parts = line_strip.split(":", 1)
        key = parts[0].strip().lower()
        val = parts[1].strip()

        if key == "f/s/p":
            fsp = val
            ont["port_override"] = val
        elif key == "ont-id":
            ont_id = val
            ont["ont_id"] = val
        elif key == "run state":
            if val.lower() in ["online", "active", "normal"]:
                ont["status"] = "Online"
            else:
                ont["status"] = "Offline"
        elif key == "description":
            ont["description"] = val
        elif key == "last down cause":
            ont["last_down_cause"] = "LOS" if val.lower() == "los" else val

    if fsp and ont_id:
        return ont
    
    return None


def calculate_haversine_distance(lat1, lon1, lat2, lon2) -> float:
    """
    Menghitung jarak dalam meter antara dua titik koordinat GPS menggunakan rumus Haversine.
    """
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return 0.0
    try:
        lat1, lon1, lat2, lon2 = map(float, [lat1, lon1, lat2, lon2])
        # Radius bumi dalam meter
        R = 6371000.0
        
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)
        
        a = math.sin(delta_phi / 2.0)**2 + \
            math.cos(phi1) * math.cos(phi2) * \
            math.sin(delta_lambda / 2.0)**2
            
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
        
        distance = R * c
        return distance
    except Exception as e:
        logger.error(f"Error calculating distance: {e}")
        return 0.0


def sanitize_coordinate(val, is_latitude=True):
    """
    Sanitize coordinate strings that might have multiple dots or wrong decimal placement.
    Example:
      '-63.026.788' -> -6.3026788
      '1.067.978.546' -> 106.7978546
    """
    import math
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    
    val_str = str(val).strip().replace(" ", "")
    if not val_str or val_str == "-" or val_str.lower() == "nan":
        return None
        
    try:
        # Check negative
        is_negative = val_str.startswith("-")
        # Keep only digits
        digits = "".join([c for c in val_str if c.isdigit()])
        
        if not digits:
            return None
            
        if is_latitude:
            # Latitude for Jakarta/Indonesia is around -6.xx
            # We expect the integer part to be 6 (or -6)
            if digits.startswith("6"):
                clean_str = "6." + digits[1:]
            else:
                clean_str = digits[0] + "." + digits[1:]
            
            final_val = float(clean_str)
            if is_negative:
                final_val = -final_val
            return final_val
        else:
            # Longitude for Jakarta/Indonesia is around 106.xx
            # We expect the integer part to be 106 (or 107)
            if digits.startswith("106") or digits.startswith("107"):
                clean_str = digits[:3] + "." + digits[3:]
            elif digits.startswith("10") and len(digits) >= 3:
                clean_str = digits[:3] + "." + digits[3:]
            else:
                clean_str = digits[:3] + "." + digits[3:] if len(digits) > 3 else digits
            
            final_val = float(clean_str)
            if is_negative:
                final_val = -final_val
            return final_val
    except Exception:
        try:
            # Fallback to removing all dots except first
            parts = val_str.split('.')
            if len(parts) > 1:
                cleaned = parts[0] + '.' + ''.join(parts[1:])
            else:
                cleaned = val_str
            return float(cleaned)
        except Exception:
            return None


def check_coordinate_anomaly(raw_lat, raw_lon, sanitized_lat, sanitized_lon) -> bool:
    """
    Menentukan apakah input koordinat memiliki anomali (format salah, typo dot, dll).
    """
    if raw_lat is None or raw_lon is None:
        return True
        
    raw_lat_str = str(raw_lat).strip()
    raw_lon_str = str(raw_lon).strip()
    
    # 1. Anomali format: memiliki lebih dari 1 dot
    if raw_lat_str.count('.') > 1 or raw_lon_str.count('.') > 1:
        return True
        
    # 2. Anomali range: Latitude di luar -10 s/d -5 (Indonesia/Jakarta), Longitude di luar 105 s/d 108
    if sanitized_lat is not None:
        if sanitized_lat < -10.0 or sanitized_lat > -5.0:
            return True
    if sanitized_lon is not None:
        if sanitized_lon < 105.0 or sanitized_lon > 108.0:
            return True
            
    return False
