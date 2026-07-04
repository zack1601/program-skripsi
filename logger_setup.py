#!/usr/bin/env python3
"""
Setup Logging
=============
Konfigurasi logging ke console dan file secara bersamaan.

Author : Zaki Mubarok
Project: Program Skripsi
"""

import os
import logging
from datetime import datetime

from config import LOG_DIR


def setup_logger(name: str = "olt_automation") -> logging.Logger:
    """
    Buat logger yang menulis ke console (INFO) dan file (DEBUG).
    
    File log disimpan di folder LOG_DIR dengan format:
        debug_<name>_<timestamp>.txt
    
    Returns:
        logging.Logger
    """
    os.makedirs(LOG_DIR, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(LOG_DIR, f"debug_{name}_{timestamp}.txt")
    
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    
    # Hapus handler lama (jika dipanggil ulang)
    logger.handlers.clear()
    
    # --- File handler (DEBUG level — semua detail) ---
    fh = logging.FileHandler(log_file, encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        '%(asctime)s | %(levelname)-7s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    logger.addHandler(fh)
    
    # --- Console handler (INFO level — ringkas) ---
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(ch)
    
    logger.debug(f"Log file: {log_file}")
    return logger
