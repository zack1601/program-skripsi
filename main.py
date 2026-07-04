#!/usr/bin/env python3
"""
OLT-ONT Audit Port Automation
==============================
Mengambil SEMUA data ONT dari port tertentu pada Huawei OLT.

Alur kerja:
    1. Baca file Excel berisi list OLT dan PORT.
    2. Grup data berdasarkan OLT IP.
    3. Untuk setiap OLT:
       a. SSH ke TACACS -> Telnet ke OLT -> enable.
       b. Jalankan 'display ont info summary <PORT>' untuk setiap port.
       c. Ambil SEMUA ONT yang ada di port tersebut.
    4. Tulis hasil lengkap ke 'hasil_pengecekan_ont.xlsx'.

Author : Zaki Mubarok
Project: Program Skripsi
"""

import os
import sys
import time
from datetime import datetime
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

import re
from config import INPUT_FILE, OUTPUT_DIR, MAX_WORKERS
from connection import OLTConnection
from parser import parse_ont_summary, parse_ont_detail
from logger_setup import setup_logger

# Setup logger global
logger = setup_logger("olt_audit")

def mask_sn(sn: str) -> str:
    """Sensor SN: 48575443CE51CAAD -> 48575443C*****AD"""
    if not sn or len(sn) < 16 or sn == "-":
        return sn
    return f"{sn[:9]}*****{sn[-2:]}"

def process_olt_audit(olt_name: str, olt_ip: str, slots: list, target_sns: list = None) -> list:
    """
    Audit port: Ambil semua data ONT dari list slot di satu OLT.
    Jika ada SN yang tidak ditemukan di slot, coba cari lewat 'display ont info by-sn'.
    """
    label = f"{olt_name} ({olt_ip})"
    results = []
    found_sns = set()
    target_sns = target_sns or []

    logger.debug(f"[{label}] Audit {len(slots)} slot...")

    conn = OLTConnection(olt_ip=olt_ip, olt_name=olt_name)

    if not conn.connect_with_retry():
        return [] # OLT gagal total

    try:
        for slot in slots:
            if not slot: continue
            
            logger.debug(f"[{olt_name}] Scanning slot: {slot}...")
            command = f"display ont info summary {slot} | no-more"
            raw_output = conn.send_command(command)
            
            ont_list = parse_ont_summary(raw_output)
            logger.info(f"[{olt_name}] Slot {slot}: Ditemukan {len(ont_list)} ONT")
            
            results.extend(ont_list)

    finally:
        conn.close()

    # Inject OLT name into results for better mapping
    for ont in results:
        ont["olt_name"] = olt_name

    return results

def main():
    """Entry point utama untuk mode Audit Port."""
    logger.info("="*50)
    logger.info("MEMULAI SCANNING")
    logger.info("="*50)

    # --- 1. Baca input Excel ---
    if not os.path.exists(INPUT_FILE):
        logger.error(f"File input tidak ditemukan: {INPUT_FILE}")
        sys.exit(1)

    logger.info(f"Membaca file input: {os.path.basename(INPUT_FILE)}...")
    df = pd.read_excel(INPUT_FILE)
    logger.info(f"Berhasil membaca {len(df)} baris data.")
    
    # Handle merged cells
    cols_to_fill = ["OLT", "IP_OLT", "IP OLT", "ip_olt", "PORT", "Port", "port"]
    for col in cols_to_fill:
        if col in df.columns:
            df[col] = df[col].ffill()

    # Deteksi kolom IP
    ip_col = None
    for candidate in ["IP_OLT", "IP OLT", "ip_olt", "IP_olt"]:
        if candidate in df.columns:
            ip_col = candidate
            break
    if ip_col is None:
        logger.error("Kolom IP OLT tidak ditemukan!")
        sys.exit(1)

    # Deteksi kolom Port
    port_col = None
    for candidate in ["PORT", "Port", "port"]:
        if candidate in df.columns:
            port_col = candidate
            break
    if port_col is None:
        logger.error("Kolom PORT tidak ditemukan!")
        sys.exit(1)

    # Deteksi kolom ID/Nama Pelanggan (untuk fallback)
    id_pel_col = None
    possible_id_cols = ["ID_PELANGGAN", "ID PELANGGAN", "Id Pelanggan", "id_pelanggan", "ID", "id"]
    for candidate in possible_id_cols:
        if candidate in df.columns:
            id_pel_col = candidate
            break

    nama_pel_col = None
    possible_nama_cols = ["NAMA PELANGGAN", "NAMA_PELANGGAN", "Nama Pelanggan", "nama_pelanggan", "NAMA", "nama", "CUSTOMER", "PELANGGAN"]
    for candidate in possible_nama_cols:
        if candidate in df.columns:
            nama_pel_col = candidate
            break

    logger.debug("Menganalisis daftar OLT dan Port...")
    # --- 2. Grup Slot per OLT IP & Simpan Target VLOOKUP ---
    olt_groups = defaultdict(lambda: {"name": "", "slots": set()})
    
    target_onts = {} # key: (olt_ip, "0/7/0 3")
    sn_to_target = {} # key: (olt_ip, "48575443...")
    excel_results = [] # Menjaga urutan asli Excel

    for _, row in df.iterrows():
        olt_ip = str(row[ip_col]).strip()
        olt_name = str(row["OLT"]).strip()
        raw_port = str(row[port_col]).strip() # contoh: "0/ 7/0   3"
        sn = str(row.get("SERIAL NUMBER", "-")).strip()
        if sn == "nan": sn = "-"
        
        # Ambil ID & Nama dari input Excel jika ada (sebagai data awal)
        id_pel_input = "-"
        if id_pel_col:
            id_pel_input = str(row.get(id_pel_col, "-")).strip()
        
        nama_pel_input = "-"
        if nama_pel_col:
            nama_pel_input = str(row.get(nama_pel_col, "-")).strip()
        
        if id_pel_input == "nan": id_pel_input = "-"
        if nama_pel_input == "nan": nama_pel_input = "-"
        
        if olt_ip and raw_port and raw_port.lower() != "nan":
            # Ekstrak F/S/P dan ONT ID
            import re
            match = re.search(r'(\d+)\s*/\s*(\d+)\s*/\s*(\d+)\s+(\d+)', raw_port)
            if match:
                f, s, p, ont_id = match.groups()
                clean_target = f"{f}/{s}/{p} {ont_id}"
                slot_cmd = f"{f}/{s}"  # Command level slot (0/7)
            else:
                # Jika formatnya beda, gunakan fallback
                clean_target = " ".join(raw_port.split())
                slot_cmd = clean_target.split()[0] if ' ' in clean_target else clean_target
                if '/' in slot_cmd and slot_cmd.count('/') >= 2:
                    # Ambil F/S saja
                    parts = slot_cmd.split('/')
                    slot_cmd = f"{parts[0]}/{parts[1]}"
                
            olt_groups[olt_ip]["name"] = olt_name
            olt_groups[olt_ip]["slots"].add(slot_cmd)
            
            entry = {
                "olt_name": olt_name,
                "olt_ip": olt_ip,
                "port_ont": clean_target,
                "sn": sn,
                "status": "Not Found",
                "rx_power": "-",
                "last_down_cause": "-",
                "description": "-",
                "id_pelanggan": id_pel_input,
                "nama_pelanggan": nama_pel_input
            }
            target_onts[(olt_ip, clean_target)] = entry
            
            # Tambahkan ke mapping SN jika SN valid
            if sn and sn != "-" and len(sn) >= 12:
                sn_to_target[(olt_ip, sn.upper())] = entry
                
            excel_results.append(entry)

    if not olt_groups:
        logger.warning("Tidak ada data OLT/Port yang valid!")
        sys.exit(0)

    logger.debug(f"Memulai Audit pada {len(olt_groups)} OLT (Multi-threaded)...")
    logger.info("\nSCANNING....")
    start_time = time.time()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures_list = []
        for olt_ip, group in olt_groups.items():
            # Kumpulkan target SN untuk OLT ini agar bisa dilakukan rescue search jika tidak ketemu di port
            olt_sns = [target["sn"] for target in excel_results if target["olt_ip"] == olt_ip]
            
            future = executor.submit(
                process_olt_audit,
                group["name"], olt_ip, list(group["slots"]), olt_sns
            )
            futures_list.append((future, group["name"], olt_ip))

        for future, olt_name, olt_ip in futures_list:
            try:
                results = future.result()
                
                # Sinkronisasi (VLOOKUP) hasil scan dengan target Excel
                if results:
                    for ont in results:
                        actual_port = ont.get("port_override", "default")
                        ont_id = ont.get("ont_id", "")
                        sn_found = ont.get("sn", "").strip().upper()
                        
                        combined_str = f"{actual_port} {ont_id}"
                        key_port = (olt_ip, combined_str)
                        key_sn = (olt_ip, sn_found)
                        
                        target = None
                        # Prioritas 1: Cocokkan lewat SN (paling akurat)
                        if sn_found != "-" and key_sn in sn_to_target:
                            target = sn_to_target[key_sn]
                        # Prioritas 2: Cocokkan lewat Port ID
                        elif key_port in target_onts:
                            target = target_onts[key_port]
                        
                        if target:
                            target["status"] = ont["status"]
                            target["last_down_cause"] = ont["last_down_cause"]
                            target["rx_power"] = ont.get("rx_power", "-")
                            if ont.get("description"):
                                target["description"] = ont["description"]
                            if target["sn"] == "-" and sn_found != "-":
                                target["sn"] = sn_found
                                
                    # Tampilkan hanya data yang ada di Excel (Segmentasi per OLT)
                    logger.info(f"\n{olt_name}")
                    header = f"{'Nama/ID Pelanggan':<35} | {'Port':<12} | {'Serial Number':<18} | {'Status':<8} | {'Power/Cause'}"
                    logger.info("-" * len(header))
                    logger.info(header)
                    logger.info("-" * len(header))
                    for target in excel_results:
                        if target["olt_ip"] == olt_ip:
                            # Ekstrak ID/Nama dari Description OLT jika baru saja diupdate
                            desc = target.get("description", "").strip()
                            if desc and desc != "-" and (target["id_pelanggan"] == "-" or target["nama_pelanggan"] == "-"):
                                # Cari pola ID di mana saja dalam string (minimal 5-15 digit)
                                # Mendukung format: 111002638851_Muhamad atau "713 -16.30 111002638851_Muhamad"
                                match = re.search(r'(\d{5,15})([-_\s]+(.*))?$', desc)
                                if match:
                                    if target["id_pelanggan"] == "-":
                                        target["id_pelanggan"] = match.group(1)
                                    if target["nama_pelanggan"] == "-":
                                        target["nama_pelanggan"] = match.group(3).strip() if match.group(3) else "-"
                                
                                # Jika masih kosong, coba ambil seluruh string selama bukan murni power
                                if target["id_pelanggan"] == "-" and target["nama_pelanggan"] == "-":
                                    if not re.match(r'^[\d./-]+$', desc):
                                        target["nama_pelanggan"] = desc
                            
                            # Bersihkan Nama dari karakter sampah
                            if target["nama_pelanggan"] != "-" and target["nama_pelanggan"] != "":
                                # Jika nama mengandung format power (x.x/x.x) di dalamnya, bersihkan bagian tersebut
                                target["nama_pelanggan"] = re.sub(r'-?\d+\.\d+/-?\d+\.\d+', '', target["nama_pelanggan"]).strip()
                                # Hapus angka-angka pendek di awal nama (misal sisa Distance '713')
                                target["nama_pelanggan"] = re.sub(r'^\d{1,4}\s+', '', target["nama_pelanggan"]).strip()
                                # Jika sisa nama hanya karakter sampah, set ke "-"
                                if not target["nama_pelanggan"] or target["nama_pelanggan"] in ["-/-", "-"]:
                                    target["nama_pelanggan"] = "-"
                            
                            # Format ID-NAMA untuk logging (Gunakan '-' sebagai separator)
                            id_part = target["id_pelanggan"] if target["id_pelanggan"] != "-" else ""
                            nama_part = target["nama_pelanggan"] if target["nama_pelanggan"] != "-" else ""
                            
                            if id_part and nama_part:
                                id_nama = f"{id_part}-{nama_part}"
                            else:
                                id_nama = id_part or nama_part or "Unknown"
                            
                            info_extra = target["rx_power"] if target["status"] == "Online" else target["last_down_cause"]
                            if target["status"] == "Offline" and (not info_extra or info_extra == "-"):
                                info_extra = "Suspend/Isolir"
                            elif not info_extra:
                                info_extra = "-"
                            
                            # Tampilan model TABEL (padding agar rata kiri/kanan)
                            # Format: Nama/ID - Port - SN (Masked) - Status - Power/Cause
                            masked_sn = mask_sn(target['sn'])
                            row_log = f"{id_nama:<35} | {target['port_ont']:<12} | {masked_sn:<18} | {target['status']:<8} | {info_extra}"
                            logger.info(row_log)
                            
            except Exception as e:
                logger.error(f"Thread error on {olt_name}: {e}")

    elapsed = time.time() - start_time

    # --- 4. Tulis output ---
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # File name sesuai permintaan: hasil_pengecekan_ont.xlsx
    output_file = os.path.join(OUTPUT_DIR, f"hasil_pengecekan_ont_{timestamp}.xlsx")

    if excel_results:
        df_out = pd.DataFrame(excel_results)
        
        # Hapus kolom description agar tidak mengotori Excel hasil
        if "description" in df_out.columns:
            df_out.drop(columns=["description"], inplace=True)
            
        # Susun urutan kolom agar rapi
        cols = ["olt_name", "olt_ip", "port_ont", "sn", "status", "rx_power", "last_down_cause", "id_pelanggan", "nama_pelanggan"]
        # Filter kolom yang ada saja (jika ada yang miss)
        cols = [c for c in cols if c in df_out.columns]
        df_out = df_out[cols]
        
        # Rename header agar lebih human readable
        df_out.rename(columns={"port_ont": "Port"}, inplace=True)
        df_out.columns = [c.replace("_", " ").title() for c in df_out.columns]
        
        df_out.to_excel(output_file, index=False, engine='openpyxl')
    else:
        logger.warning("Tidak ada data ONT yang berhasil disinkronisasi.")

    # --- 5. Summary Akhir ---
    total_ont = len(excel_results)
    online_count = 0
    high_loss_count = 0
    losi_lobi_count = 0
    suspend_count = 0
    power_off_count = 0
    not_found_count = 0
    not_found_details = []
    others_count = 0
    
    for item in excel_results:
        status = str(item.get("status", "")).strip()
        cause = str(item.get("last_down_cause", "")).lower()
        
        if status == "Online":
            online_count += 1
            # Hitung High Loss (>25.99)
            try:
                rx_str = str(item.get("rx_power", "0")).replace("-", "").strip()
                if rx_str and float(rx_str) > 25.99:
                    high_loss_count += 1
            except (ValueError, TypeError):
                pass
        elif status == "Not Found":
            not_found_count += 1
            not_found_details.append(f"{item.get('sn')} ({item.get('olt_name')})")
        elif status == "Offline":
            if not item.get("last_down_cause") or item.get("last_down_cause") == "-" or "dismantle" in cause:
                suspend_count += 1
            elif "losi" in cause or "lobi" in cause:
                losi_lobi_count += 1
            elif "power-off" in cause or "dying-gasp" in cause:
                power_off_count += 1
            else:
                others_count += 1
        else:
            others_count += 1

    logger.info("="*50)
    logger.info("RINGKASAN HASIL SCANNING")
    logger.info("="*50)
    logger.info(f"Jumlah OLT             : {len(olt_groups)}")
    logger.info(f"Jumlah ONT terscanning : {total_ont}")
    logger.info(f"Online                 : {online_count}")
    logger.info(f"redaman >25.99         : {high_loss_count}")
    logger.info(f"LOSi/LOBi              : {losi_lobi_count}")
    logger.info(f"Suspend/Isolir         : {suspend_count}")
    logger.info(f"Power Off/Dying        : {power_off_count}")
    logger.info(f"Lainnya                : {others_count}")
    logger.info(f"Not Found (di OLT)     : {not_found_count}")
    
    # --- 6. Segmentasi Detail (Problematic ONTs: LOS & Redaman Buruk) ---
    problem_found = False
    olt_problems = defaultdict(list)
    
    for item in excel_results:
        is_problem = False
        status = str(item.get("status", "")).strip()
        cause = str(item.get("last_down_cause", "")).lower()
        rx_power = item.get("rx_power", "-")
        
        # Segmentasi 1: LOSi/LOBi (Hanya jika offline karena LOS)
        if status == "Offline" and ("losi" in cause or "lobi" in cause):
            is_problem = True
        
        # Segmentasi 2: Redaman > 25.99 (Hanya jika Online)
        if status == "Online" and rx_power != "-":
            try:
                # Ambil angka saja, misal "-27.50" -> 27.50
                rx_val_str = str(rx_power).replace("-", "").strip()
                if rx_val_str:
                    rx_val = float(rx_val_str)
                    if rx_val > 25.99:
                        is_problem = True
            except (ValueError, TypeError):
                pass
        
        if is_problem:
            olt_problems[item.get("olt_name")].append(item)
            problem_found = True

    if problem_found:
        logger.info("\n" + "="*50)
        logger.info("DETAIL PELANGGAN BERMASALAH (LOS & REDAMAN BURUK)")
        logger.info("="*50)
        
        for olt_name, problems in olt_problems.items():
            logger.info(f"\n{olt_name}")
            header = f"{'Nama/ID Pelanggan':<35} | {'Port':<12} | {'Serial Number':<18} | {'Status':<8} | {'Power/Cause'}"
            logger.info("-" * len(header))
            logger.info(header)
            logger.info("-" * len(header))
            
            for p in problems:
                id_pel = p.get("id_pelanggan", "-")
                nama_pel = p.get("nama_pelanggan", "-")
                id_nama = f"{id_pel}-{nama_pel}"[:35]
                
                info_extra = p.get("rx_power") if p.get("status") == "Online" else p.get("last_down_cause")
                masked_sn = mask_sn(str(p.get("sn", "-")))
                
                logger.info(f"{id_nama:<35} | {p.get('port_ont', '-'):<12} | {masked_sn:<18} | {p.get('status', '-'):<8} | {info_extra}")

    if not_found_details:
        logger.info("-" * 20)
        logger.info("Daftar SN Not Found:")
        for detail in not_found_details:
            # detail format: "SN (OLT_NAME)"
            if " (" in detail:
                parts_nf = detail.split(" (", 1)
                sn_nf = parts_nf[0]
                olt_nf = parts_nf[1]
                logger.info(f"  > {mask_sn(sn_nf)} ({olt_nf}")
            else:
                logger.info(f"  > {detail}")
            
    logger.info("="*50)
    logger.info(f"Jumlah Keseluruhan     : {total_ont}")
    logger.info("="*50)
    logger.info(f"Audit selesai dalam {time.time() - start_time:.1f} detik.")

if __name__ == "__main__":
    main()
