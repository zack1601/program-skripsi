#!/usr/bin/env python3
"""

Author : Zaki Mubarok
Project: Program Skripsi
"""

import os
try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

# Path ke config.toml
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_TOML_PATH = os.path.join(_BASE_DIR, "config.toml")

# Default values
_config_data = {}

if os.path.exists(_TOML_PATH):
    try:
        if tomllib is not None:
            with open(_TOML_PATH, "rb") as f:
                _config_data = tomllib.load(f)
        else:
            print("Warning: tomllib or tomli is not installed. Using fallback defaults.")
    except Exception as e:
        print(f"Warning: Failed to load config.toml: {e}. Using fallback defaults.")

def _get_val(section, key, default):
    return _config_data.get(section, {}).get(key, default)

# ============================================================================
# TACACS / SSH JUMP HOST
# ============================================================================
TACACS_IP   = _get_val("tacacs", "ip", "10.14.4.5")
TACACS_PORT = _get_val("tacacs", "port", 21112)
TACACS_USER = _get_val("tacacs", "user", "**********")
TACACS_PASS = _get_val("tacacs", "pass", "**********")

# ============================================================================
# OLT (Huawei) - Telnet dari TACACS
# ============================================================================
OLT_USER = _get_val("olt", "user", "zaki.mubarok")
OLT_PASS = _get_val("olt", "pass", "Icon2025&")

# ============================================================================
# TIMING PARAMETERS
# ============================================================================
INTER_CHAR_DELAY = _get_val("timing", "inter_char_delay", 0.1)
RECV_TIMEOUT     = _get_val("timing", "recv_timeout", 180)
POST_CMD_DELAY   = _get_val("timing", "post_cmd_delay", 5)
MAX_IDLE_CYCLES  = _get_val("timing", "max_idle_cycles", 120)        
POLL_INTERVAL    = _get_val("timing", "poll_interval", 0.3)

# ============================================================================
# SSH / SHELL PARAMETERS
# ============================================================================
SSH_TIMEOUT       = _get_val("ssh", "timeout", 20)       # Timeout koneksi SSH (detik)
SHELL_TERM        = _get_val("ssh", "shell_term", "vt100")  # Terminal emulator type
SHELL_WIDTH       = _get_val("ssh", "shell_width", 200)      # Lebar terminal (kolom)
SHELL_HEIGHT      = _get_val("ssh", "shell_height", 50)       # Tinggi terminal (baris)

# ============================================================================
# RETRY PARAMETERS
# ============================================================================
MAX_RETRIES       = _get_val("retry", "max_retries", 3)        # Jumlah percobaan ulang koneksi
RETRY_DELAY       = _get_val("retry", "retry_delay", 5)        # Delay antar percobaan ulang (detik)

# ============================================================================
# MULTITHREADING
# ============================================================================
MAX_WORKERS       = _get_val("multithreading", "max_workers", 3)        # Jumlah thread paralel

# ============================================================================
# FILE I/O
# ============================================================================
INPUT_FILE        = _get_val("file_io", "input_file", "data_noc.xlsx")
OUTPUT_DIR        = _get_val("file_io", "output_dir", "output")
LOG_DIR           = _get_val("file_io", "log_dir", "logs")

# ============================================================================
# TELEGRAM
# ============================================================================
TELEGRAM_BOT_TOKEN = _get_val("telegram", "bot_token", "8789834499:AAEeqHkPjSzlkr4egB0sMPvsMyoDUBkG2OU")
TELEGRAM_CHAT_ID   = _get_val("telegram", "chat_id", "-1003975720951")
