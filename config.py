#!/usr/bin/env python3
"""

Author : Zaki Mubarok
Project: Program Skripsi
"""

# ============================================================================
# TACACS / SSH JUMP HOST
# ============================================================================
TACACS_IP   = "10.14.4.5"
TACACS_PORT = 21112
TACACS_USER = "**********"
TACACS_PASS = "**********"

# ============================================================================
# OLT (Huawei) - Telnet dari TACACS
# ============================================================================
OLT_USER = "zaki.mubarok"
OLT_PASS = "Icon2025&"

# ============================================================================
# TIMING PARAMETERS
INTER_CHAR_DELAY = 0.1
RECV_TIMEOUT     = 180
POST_CMD_DELAY   = 5
MAX_IDLE_CYCLES  = 120        
POLL_INTERVAL    = 0.3

# ============================================================================
# SSH / SHELL PARAMETERS
# ============================================================================
SSH_TIMEOUT       = 20       # Timeout koneksi SSH (detik)
SHELL_TERM        = "vt100"  # Terminal emulator type
SHELL_WIDTH       = 200      # Lebar terminal (kolom)
SHELL_HEIGHT      = 50       # Tinggi terminal (baris)

# ============================================================================
# RETRY PARAMETERS
# ============================================================================
MAX_RETRIES       = 3        # Jumlah percobaan ulang koneksi
RETRY_DELAY       = 5        # Delay antar percobaan ulang (detik)

# ============================================================================
# MULTITHREADING
# ============================================================================
MAX_WORKERS       = 3        # Jumlah thread paralel

# ============================================================================
# FILE I/O
# ============================================================================
INPUT_FILE        = "data_noc.xlsx"
OUTPUT_DIR        = "output"
LOG_DIR           = "logs"
