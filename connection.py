#!/usr/bin/env python3
"""
Modul Koneksi SSH & Telnet
===========================
Mengelola koneksi SSH ke TACACS jump host dan sesi Telnet ke Huawei OLT.

Fitur utama:
- SSH ke TACACS (jump host) menggunakan paramiko
- Telnet ke OLT dari dalam sesi SSH
- Pengiriman perintah character-by-character (mengatasi bug spasi Huawei)
- Deteksi prompt interaktif (Username, Password, >, #)
- Retry logic untuk koneksi yang sering putus

Author : Zaki Mubarok
Project: Program Skripsi
"""

import time
import re
import logging
import paramiko

from config import (
    TACACS_IP, TACACS_PORT, TACACS_USER, TACACS_PASS,
    OLT_USER, OLT_PASS,
    INTER_CHAR_DELAY, RECV_TIMEOUT, POST_CMD_DELAY,
    MAX_IDLE_CYCLES, POLL_INTERVAL,
    SSH_TIMEOUT, SHELL_TERM, SHELL_WIDTH, SHELL_HEIGHT,
    MAX_RETRIES, RETRY_DELAY,
)

logger = logging.getLogger(__name__)


# ============================================================================
# HELPER: Pengiriman Perintah
# ============================================================================

def send_slow(channel, text: str, delay: float = 0.02):
    """
    Kirim teks karakter per karakter dengan delay kecil.
    Digunakan untuk input sederhana: username, password.
    """
    for char in text:
        channel.send(char)
        time.sleep(delay)


def drain_buffer(channel):
    """Bersihkan sisa data di receive buffer sebelum kirim perintah baru."""
    drained = ""
    while channel.recv_ready():
        chunk = channel.recv(4096).decode('utf-8', errors='replace')
        drained += chunk
        time.sleep(0.1)
    if drained:
        logger.debug(f"Drained {len(drained)} chars dari buffer")
    return drained


def send_olt_command(channel, command: str):
    """
    Kirim perintah ke Huawei OLT KARAKTER PER KARAKTER.
    - Karakter biasa: delay 0.1 detik
    - Karakter SPASI: delay 0.3 detik (Huawei butuh waktu ekstra)
    
    Sebelum mengirim, buffer di-drain untuk mencegah echo interference.
    """
    # Drain sisa output dari perintah sebelumnya
    drain_buffer(channel)
    
    logger.debug(f"Sending OLT command: '{command}'")
    # print(f"  DEBUG SEND: '{command}'")
    
    for char in command:
        channel.send(char)
        if char == ' ':
            time.sleep(0.3)  # Extra delay untuk spasi
        else:
            time.sleep(INTER_CHAR_DELAY)  # 0.1s untuk karakter biasa
    
    # Kirim Enter 2x
    channel.send('\n')
    time.sleep(0.5)
    channel.send('\n')


# ============================================================================
# HELPER: Menunggu Prompt
# ============================================================================

def strip_ansi(text: str) -> str:
    """Hapus ANSI escape codes dari teks."""
    return re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)


def wait_for_prompt(channel, prompts=None, timeout=None):
    """
    Baca output dari channel SSH hingga salah satu prompt terdeteksi.
    Strip ANSI escape codes sebelum pengecekan prompt.
    
    Args:
        channel: paramiko channel object
        prompts: list string prompt yang ditunggu (default: ['>', '#', 'name:', 'assword:'])
        timeout: timeout maksimal (detik)
    
    Returns:
        str: seluruh output yang diterima
    """
    if prompts is None:
        prompts = ['>', '#', 'name:', 'assword:']
    if timeout is None:
        timeout = RECV_TIMEOUT
    
    buffer = ""
    start_time = time.time()
    
    while (time.time() - start_time) < timeout:
        if channel.recv_ready():
            chunk = channel.recv(4096).decode('utf-8', errors='replace')
            # Bersihkan null character
            chunk = chunk.replace('\x00', '')
            buffer += chunk
            
            # Strip ANSI codes, lalu cek baris terakhir
            clean_buf = strip_ansi(buffer)
            # Cek per baris terakhir (bukan seluruh buffer)
            last_line = clean_buf.strip().split('\n')[-1].strip()
            
            for prompt in prompts:
                if last_line.endswith(prompt) or prompt in last_line:
                    return buffer
        else:
            time.sleep(POLL_INTERVAL)
    
    logger.warning(f"wait_for_prompt timeout setelah {timeout}s. "
                   f"Last line: '{strip_ansi(buffer).strip().split(chr(10))[-1].strip()}'")
    return buffer


def read_full_output(channel, min_lines=3, timeout=None):
    """
    Baca output lengkap dari OLT setelah mengirim perintah.
    Menggunakan accumulation loop — terus baca sampai prompt OLT muncul.
    
    Args:
        channel: paramiko channel object
        min_lines: minimal jumlah baris sebelum dianggap valid
        timeout: timeout maksimal
    
    Returns:
        str: output lengkap dari OLT
    """
    if timeout is None:
        timeout = RECV_TIMEOUT
    
    # Tunggu OLT mulai mengirim output
    time.sleep(POST_CMD_DELAY)
    
    full_output = ""
    idle_count = 0
    start_time = time.time()
    
    while (time.time() - start_time) < timeout:
        if channel.recv_ready():
            chunk = channel.recv(4096).decode('utf-8', errors='replace')
            chunk = chunk.replace('\x00', '')
            full_output += chunk
            idle_count = 0
            
            # Handle pagination
            clean_chunk = strip_ansi(chunk)
            if "---- More" in clean_chunk or "Press 'Q' to break" in clean_chunk or "More ( Press" in clean_chunk:
                # Kirim spacebar untuk lanjut
                channel.send(" ")
                time.sleep(0.2)
                idle_count = 0
                continue
                
            # Cek apakah prompt OLT sudah muncul kembali (> atau # di akhir baris)
            clean_accum = strip_ansi(full_output)
            # Bersihkan sisa-sisa string pagination yang menempel di output akhir
            clean_accum = re.sub(r'---- More.*?----', '', clean_accum, flags=re.IGNORECASE)
            
            lines = clean_accum.strip().split('\n')
            if len(lines) >= min_lines:
                last_line = lines[-1].strip()
                if last_line.endswith('>') or last_line.endswith('#'):
                    logger.debug(f"Prompt terdeteksi setelah {len(lines)} baris")
                    return full_output
        else:
            idle_count += 1
            if idle_count >= MAX_IDLE_CYCLES:
                logger.debug(f"Max idle cycles tercapai ({MAX_IDLE_CYCLES})")
                break
            time.sleep(POLL_INTERVAL)
    
    return full_output


# ============================================================================
# KONEKSI UTAMA
# ============================================================================

class OLTConnection:
    """
    Mengelola koneksi dari PC → TACACS (SSH) → OLT (Telnet).
    
    Lifecycle:
        1. connect_ssh()    - Buka koneksi SSH ke TACACS
        2. telnet_to_olt()  - Dari TACACS, telnet ke OLT
        3. send_command()   - Kirim perintah ke OLT & baca output
        4. close()          - Tutup semua koneksi
    
    Usage:
        conn = OLTConnection(olt_ip="10.x.x.x", olt_name="OLT-01")
        try:
            conn.connect_ssh()
            conn.telnet_to_olt()
            output = conn.send_command("display ont info by-sn XXXXXXXX")
        finally:
            conn.close()
    """
    
    def __init__(self, olt_ip: str, olt_name: str = ""):
        self.olt_ip = olt_ip
        self.olt_name = olt_name or olt_ip
        self.label = f"{self.olt_name} ({self.olt_ip})"
        
        self.ssh_client = None
        self.channel = None
        self._connected = False
    
    def connect_ssh(self):
        """
        Buka koneksi SSH ke TACACS jump host.
        
        Raises:
            paramiko.AuthenticationException: Jika credential salah
            paramiko.SSHException: Jika koneksi SSH gagal
            TimeoutError: Jika timeout
        """
        logger.debug(f"[{self.label}] Connecting SSH ke TACACS {TACACS_IP}:{TACACS_PORT}...")
        
        self.ssh_client = paramiko.SSHClient()
        self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        self.ssh_client.connect(
            TACACS_IP,
            port=TACACS_PORT,
            username=TACACS_USER,
            password=TACACS_PASS,
            timeout=SSH_TIMEOUT,
            look_for_keys=False,
            allow_agent=False
        )
        
        self.channel = self.ssh_client.invoke_shell(
            term=SHELL_TERM,
            width=SHELL_WIDTH,
            height=SHELL_HEIGHT
        )
        self.channel.settimeout(RECV_TIMEOUT)
        
        # Tunggu prompt TACACS shell
        tacacs_output = wait_for_prompt(self.channel, prompts=['$', '#', '>'])
        logger.debug(f"[{self.label}] TACACS prompt: ...{tacacs_output[-100:]}")
        
        logger.debug(f"[{self.label}] SSH ke TACACS berhasil ✓")
    
    def telnet_to_olt(self):
        """
        Dari sesi TACACS, buka koneksi Telnet ke OLT.
        Menangani login OLT (Username + Password atau Password only).
        
        Raises:
            ConnectionError: Jika telnet gagal atau login ditolak
        """
        logger.debug(f"[{self.label}] Telnet ke OLT {self.olt_ip}...")
        
        # Kirim perintah telnet
        send_slow(self.channel, f"telnet {self.olt_ip}\n")
        
        # Tunggu response — bisa Username, Password, atau "Connection closed"
        login_output = wait_for_prompt(
            self.channel,
            prompts=['name:', 'assword:', '>', '#', 'closed']
        )
        clean_output = login_output.strip().lower()
        
        # Cek jika koneksi ditolak
        if 'connection closed' in clean_output or 'refused' in clean_output:
            raise ConnectionError(
                f"[{self.label}] Telnet ditolak: Connection closed by foreign host"
            )
        
        # Handle login flow
        if 'name:' in clean_output:
            # Username + Password flow
            logger.debug(f"[{self.label}] OLT meminta Username")
            send_slow(self.channel, f"{OLT_USER}\n")
            
            pwd_output = wait_for_prompt(self.channel, prompts=['assword:'])
            if 'assword:' in pwd_output.lower():
                send_slow(self.channel, f"{OLT_PASS}\n")
            else:
                raise ConnectionError(f"[{self.label}] Tidak menerima prompt password")
        
        elif 'assword:' in clean_output:
            # Password only flow
            logger.debug(f"[{self.label}] OLT meminta Password saja")
            send_slow(self.channel, f"{OLT_PASS}\n")
        
        # Tunggu prompt OLT (> atau #)
        olt_prompt = wait_for_prompt(self.channel, prompts=['>', '#'])
        
        if not (olt_prompt.strip().endswith('>') or olt_prompt.strip().endswith('#')):
            raise ConnectionError(
                f"[{self.label}] Login OLT gagal. Output: {olt_prompt[-200:]}"
            )
        
        logger.debug(f"[{self.label}] Login OLT berhasil ✓")
        
        # Masuk ke mode privileged (enable) — dari > ke #
        send_olt_command(self.channel, "enable")
        enable_output = wait_for_prompt(self.channel, prompts=['#', '>'])
        if enable_output.strip().endswith('#'):
            logger.debug(f"[{self.label}] Mode enable (privileged) aktif ✓")
        else:
            logger.warning(f"[{self.label}] Enable mungkin gagal, lanjut...")
        
        # Disable pagination agar output tidak terpotong
        send_olt_command(self.channel, "screen-length 0 temporary")
        wait_for_prompt(self.channel, prompts=['#', '>'])
        logger.debug(f"[{self.label}] Pagination disabled")
        
        self._connected = True
    
    def send_command(self, command: str) -> str:
        """
        Kirim perintah ke OLT dan baca output lengkap.
        Drain buffer sebelum kirim, dan tunggu setelah baca output.
        
        Args:
            command: perintah OLT (contoh: "display ont info by-sn XXXXX")
        
        Returns:
            str: output lengkap dari OLT
        """
        if not self._connected:
            raise RuntimeError(f"[{self.label}] Belum terhubung ke OLT")
        
        logger.debug(f"[{self.label}] Executing: {command}")
        
        # Tunggu OLT siap sebelum perintah baru
        time.sleep(2)
        
        send_olt_command(self.channel, command)
        
        output = read_full_output(self.channel)
        
        # Print raw output dipindahkan ke logger.debug
        logger.debug(f"\n{'='*60}\nRAW OUTPUT [{self.label}]\n{'='*60}\n{output}\n{'='*60}\n")
        
        return output
    
    def connect_with_retry(self):
        """
        Coba koneksi SSH + Telnet ke OLT dengan retry logic.
        
        Returns:
            bool: True jika berhasil terhubung
        """
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                logger.debug(f"[{self.label}] Percobaan ke-{attempt}/{MAX_RETRIES}")
                self.connect_ssh()
                self.telnet_to_olt()
                return True
                
            except Exception as e:
                logger.warning(f"[{self.label}] Percobaan {attempt} gagal: {e}")
                self.close()
                
                if attempt < MAX_RETRIES:
                    logger.debug(f"[{self.label}] Menunggu {RETRY_DELAY}s sebelum retry...")
                    time.sleep(RETRY_DELAY)
        
        logger.error(f"[{self.label}] Semua {MAX_RETRIES} percobaan gagal!")
        return False
    
    def close(self):
        """Tutup semua koneksi."""
        self._connected = False
        try:
            if self.channel:
                self.channel.close()
        except Exception:
            pass
        try:
            if self.ssh_client:
                self.ssh_client.close()
        except Exception:
            pass
        self.channel = None
        self.ssh_client = None
        logger.debug(f"[{self.label}] Koneksi ditutup")
    
    def __enter__(self):
        """Context manager: otomatis connect_with_retry."""
        self.connect_with_retry()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager: otomatis close."""
        self.close()
        return False
