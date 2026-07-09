"""
components/validation.py
========================
Validasi dan normalisasi DataFrame input (dari Google Sheets / Excel)
sebelum diteruskan ke Scanning Engine.

Mencegah:
  - Crash akibat nama kolom berubah (spasi, huruf kapital, underscore)
  - Koneksi SSH/Telnet ke IP yang tidak valid
  - Parser menerima Serial Number dengan format salah
  - Port bernilai non-numerik atau di luar rentang wajar
"""

import re
import pandas as pd
from typing import Tuple, List


# ─────────────────────────────────────────────────────────────────────────────
# 1.  KAMUS ALIAS KOLOM
#     key   = nama kolom STANDAR yang akan digunakan oleh kode selanjutnya
#     value = semua variasi nama yang mungkin dikirim dari Sheets / Excel
# ─────────────────────────────────────────────────────────────────────────────
_ALIAS_MAP: dict[str, List[str]] = {
    "ip_olt": [
        "ip_olt", "ip olt", "ip", "olt ip", "olt_ip",
        "ip address", "ip_address", "ipaddress"
    ],
    "serial_number": [
        "serial number", "sn", "serial_number", "serialnumber",
        "serial-number", "no seri", "no_seri", "nomor seri"
    ],
    "port": [
        "port", "slot", "slot number", "slot_number",
        "port number", "port_number", "gpon port"
    ],
    # Kolom opsional — tidak wajib, tapi dinormalisasi bila ada
    "olt": [
        "olt", "nama olt", "nama_olt", "olt name", "olt_name",
        "nama olt/hostname", "hostname"
    ],
    "latitude": ["latitude", "lat", "lintang"],
    "longitude": ["longitude", "lon", "long", "bujur"],
    "nama_pelanggan": [
        "nama pelanggan", "nama_pelanggan", "customer name",
        "customer_name", "pelanggan"
    ],
    "id_pelanggan": [
        "id pelanggan", "id_pelanggan", "id", "customer id",
        "customer_id", "id pelanggan/id", "no pelanggan"
    ],
}

# Kolom yang WAJIB ada setelah normalisasi
_REQUIRED_COLUMNS = ["ip_olt", "serial_number", "port"]


# ─────────────────────────────────────────────────────────────────────────────
# 2.  NORMALISASI NAMA KOLOM
# ─────────────────────────────────────────────────────────────────────────────
def _normalize_col(name: str) -> str:
    """Ubah nama kolom: strip → lowercase → ganti spasi/strip/dash → underscore."""
    return re.sub(r"[\s\-]+", "_", str(name).strip().lower())


def standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalisasi nama kolom DataFrame:
      1. Lowercase + strip spasi di awal/akhir
      2. Ganti spasi / tanda hubung dengan underscore
      3. Petakan alias → nama standar

    Returns DataFrame dengan nama kolom yang sudah distandarkan.
    """
    df = df.rename(columns=_normalize_col)

    rename_dict: dict[str, str] = {}
    for std_name, aliases in _ALIAS_MAP.items():
        for col in df.columns:
            # Hanya petakan bila kolom belum punya nama standar
            if col in aliases and col not in rename_dict:
                rename_dict[col] = std_name
                break

    return df.rename(columns=rename_dict)


# ─────────────────────────────────────────────────────────────────────────────
# 3.  VALIDATOR INDIVIDUAL
# ─────────────────────────────────────────────────────────────────────────────
_IP_RE = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")

def _is_valid_ip(val) -> bool:
    """Cek format IPv4 yang valid (mis. 10.0.0.1, bukan 999.x.y.z atau teks kosong)."""
    if not isinstance(val, str):
        return False
    val = val.strip()
    if not _IP_RE.match(val):
        return False
    octets = val.split(".")
    return all(0 <= int(o) <= 255 for o in octets)


_SN_RE = re.compile(r"^[A-Z0-9]{8,20}$", re.IGNORECASE)

def _is_valid_sn(val) -> bool:
    """Serial Number: 8–20 karakter alfanumerik (sesuai format ONT Huawei)."""
    if not isinstance(val, str):
        return False
    return bool(_SN_RE.fullmatch(val.strip()))


def _is_valid_port(val) -> bool:
    """Port harus berupa angka, rentang 0–48 (slot GPON OLT Huawei)."""
    try:
        v = int(str(val).strip())
        return 0 <= v <= 48
    except (ValueError, TypeError):
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 4.  FUNGSI UTAMA
# ─────────────────────────────────────────────────────────────────────────────
def validate_input_dataframe(
    df_raw: pd.DataFrame,
) -> Tuple[pd.DataFrame, List[str]]:
    """
    Validasi dan normalisasi DataFrame input.

    Parameters
    ----------
    df_raw : pd.DataFrame
        Data mentah dari Google Sheets atau Excel.

    Returns
    -------
    clean_df : pd.DataFrame
        DataFrame dengan kolom yang sudah distandarkan.
        Baris dengan IP / SN tidak valid sudah ditandai (tidak dihapus),
        sehingga UI bisa menampilkan detail ke pengguna.
    errors : list[str]
        Daftar pesan kesalahan. Kosong berarti data valid.
    """
    errors: List[str] = []

    # — Langkah 1: normalisasi nama kolom —
    clean_df = standardize_columns(df_raw)

    # — Langkah 2: cek kolom wajib —
    missing_cols = [c for c in _REQUIRED_COLUMNS if c not in clean_df.columns]
    if missing_cols:
        hint = ", ".join(missing_cols)
        found = ", ".join(clean_df.columns.tolist())
        errors.append(
            f"Kolom wajib tidak ditemukan: [{hint}]. "
            f"Kolom yang tersedia: [{found}]. "
            f"Periksa nama kolom di Google Sheets / Excel."
        )
        # Tidak bisa lanjut validasi baris jika kolom saja tidak ada
        return clean_df, errors

    # — Langkah 3: drop baris yang seluruhnya kosong —
    before = len(clean_df)
    clean_df = clean_df.dropna(how="all").reset_index(drop=True)
    dropped = before - len(clean_df)
    if dropped > 0:
        errors.append(
            f"⚠️  {dropped} baris kosong ditemukan dan diabaikan."
        )

    # — Langkah 4: normalisasi nilai kolom kunci —
    clean_df["ip_olt"] = (
        clean_df["ip_olt"].astype(str).str.strip()
    )
    clean_df["serial_number"] = (
        clean_df["serial_number"].astype(str).str.strip().str.upper()
    )
    clean_df["port"] = clean_df["port"].astype(str).str.strip()

    # — Langkah 5: validasi format IP —
    mask_bad_ip = ~clean_df["ip_olt"].apply(_is_valid_ip)
    # Kecualikan sel yang berisi "nan" (berasal dari NaN asli)
    mask_bad_ip = mask_bad_ip & (clean_df["ip_olt"].str.lower() != "nan")
    if mask_bad_ip.any():
        bad_rows = clean_df[mask_bad_ip].index.tolist()
        bad_vals = clean_df.loc[mask_bad_ip, "ip_olt"].tolist()
        errors.append(
            f"❌ IP OLT tidak valid pada {len(bad_rows)} baris "
            f"(mis. baris {bad_rows[:5]}): {bad_vals[:5]}"
        )

    # — Langkah 6: validasi Serial Number —
    mask_bad_sn = ~clean_df["serial_number"].apply(_is_valid_sn)
    mask_bad_sn = mask_bad_sn & (clean_df["serial_number"].str.lower() != "nan")
    if mask_bad_sn.any():
        bad_rows = clean_df[mask_bad_sn].index.tolist()
        bad_vals = clean_df.loc[mask_bad_sn, "serial_number"].tolist()
        errors.append(
            f"❌ Serial Number tidak valid pada {len(bad_rows)} baris "
            f"(mis. baris {bad_rows[:5]}): {bad_vals[:5]}"
        )

    # — Langkah 7: validasi PORT —
    mask_bad_port = ~clean_df["port"].apply(_is_valid_port)
    mask_bad_port = mask_bad_port & (clean_df["port"].str.lower() != "nan")
    if mask_bad_port.any():
        bad_rows = clean_df[mask_bad_port].index.tolist()
        bad_vals = clean_df.loc[mask_bad_port, "port"].tolist()
        errors.append(
            f"❌ Port tidak valid pada {len(bad_rows)} baris "
            f"(mis. baris {bad_rows[:5]}): {bad_vals[:5]}"
        )

    # — Langkah 8: cek duplikasi Serial Number —
    dup_mask = clean_df.duplicated(subset=["serial_number"], keep=False)
    dup_count = dup_mask.sum()
    if dup_count > 0:
        dup_sns = clean_df.loc[dup_mask, "serial_number"].unique().tolist()
        errors.append(
            f"⚠️  Ditemukan {dup_count} baris dengan Serial Number duplikat "
            f"(mis. {dup_sns[:5]}). Hanya entri pertama yang akan diproses."
        )

    return clean_df, errors
