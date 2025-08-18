# main.py
import subprocess
import cv2
import numpy as np
import os
import sys
import time
import threading
import tkinter as tk
from tkinter import messagebox
import re

# ============= CONFIG =============
# -> FFmpeg tam yolunu kendi PC'ne göre düzenle
ffmpeg_path = r"C:\ffmpeg\bin\ffmpeg.exe"   # Örn: r"C:\ffmpeg\bin\ffmpeg.exe"

# Gecikme/buffer (ms ve µs cinsinden)
rtmp_buffer_ms = 15000       # 15 sn (ms)
max_delay_us   = 15000000    # 15 sn (microseconds)

# Görüntü çözünürlüğü (DJI GO 4 yayın çözünürlüğüne göre ayarla)
width = 1280
height = 720

# Docker container adı ve image
SRS_NAME  = "dji_live_srs"
SRS_IMAGE = "ossrs/srs:5"
# ==================================


def get_local_ip():
    """
    Windows 'ipconfig' çıktısından IPv4 adresini bulur.
    Öncelik: 'Ethernet bağdaştırıcısı Yerel Ağ Bağlantısı' (yerel ağ),
    sonra 'Kablosuz LAN bağdaştırıcısı Wi-Fi'.
    Hiçbiri bulunamazsa ilk bulunan IPv4'ü döndürür, olmadı 127.0.0.1.
    """
    try:
        # Türkçe Windows'ta kod sayfası farklı olabilir; ignore ile güvenli
        out = subprocess.check_output(["ipconfig"], encoding="utf-8", errors="ignore")
    except Exception:
        return "127.0.0.1"

    # bloklara ayır
    blocks = re.split(r"\r?\n\r?\n", out)

    ipv4_regex = re.compile(r"IPv4[^:]*:\s*([\d.]+)")

    target_order = [
        # Türkçe başlık örnekleri
        r"Ethernet.*Yerel.*Ağ.*Bağlantısı",    # Ethernet bağdaştırıcısı Yerel Ağ Bağlantısı
        r"Kablosuz.*LAN.*(Wi-?Fi|Kablosuz)",   # Kablosuz LAN bağdaştırıcısı Wi-Fi
        r"Wireless.*LAN.*(Wi-?Fi)",            # İngilizce olasılık
        r"Ethernet adapter.*Local Area",       # İngilizce olasılık
    ]

    # 1) Öncelikli başlıklarda ara
    for pat in target_order:
        for b in blocks:
            if re.search(pat, b, flags=re.IGNORECASE):
                m = ipv4_regex.search(b)
                if m:
                    ip = m.group(1)
                    if ip != "127.0.0.1":
                        return ip

    # 2) Herhangi bir bloktaki ilk IPv4
    for b in blocks:
        m = ipv4_regex.search(b)
        if m:
            ip = m.group(1)
            if ip != "127.0.0.1":
                return ip

    return "127.0.0.1"


def docker_available():
    """Docker yüklü mü/kullanılabilir mi?"""
    try:
        subprocess.run(["docker", "--version"],
                       stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL,
                       check=True)
        return True
    except Exception:
        return False


def ensure_srs():
    """
    SRS container'ını çalışır hale getir.
    - Docker yoksa uyarı ver.
    - Container varsa 'start', yoksa 'run'.
    """
    if not docker_available():
        return "Docker bulunamadı (Docker Desktop yüklü/açık mı?)"

    # Var mı?
    exists = subprocess.run(
        ["docker", "inspect", SRS_NAME],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    ).returncode == 0

    if exists:
        # Çalışıyor mu?
        status = subprocess.check_output(
            ["docker", "inspect", "-f", "{{.State.Running}}", SRS_NAME],
            encoding="utf-8"
        ).strip()
        if status.lower() == "true":
            return "SRS zaten çalışıyor"
        else:
            # start et
            rc = subprocess.run(["docker", "start", SRS_NAME],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL).returncode
            return "SRS başlatıldı" if rc == 0 else "SRS başlatılamadı"
    else:
        # yeni container oluştur
        rc = subprocess.run([
            "docker", "run", "-d",
            "--name", SRS_NAME,
            "-p", "1935:1935", "-p", "8080:8080",
            "--restart", "unless-stopped",
            SRS_IMAGE
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
        return "SRS oluşturulup başlatıldı" if rc == 0 else "SRS oluşturulamadı"


def start_stream(rtmp_url):
    """FFmpeg + OpenCV ile RTMP yayını oynat (ayrı thread)."""
    if not os.path.isfile(ffmpeg_path):
        messagebox.showerror("Hata", f"FFmpeg yolu bulunamadı:\n{ffmpeg_path}")
        return

    cmd = [
        ffmpeg_path,
        "-fflags", "+genpts",
        "-rtmp_buffer", str(rtmp_buffer_ms),
        "-i", rtmp_url,
        "-max_delay", str(max_delay_us),
        "-f", "image2pipe",
        "-pix_fmt", "bgr24",
        "-vcodec", "rawvideo",
        "-"
    ]

    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=10**8)
    except FileNotFoundError:
        messagebox.showerror("Hata", "FFmpeg çalıştırılamadı!")
        return

    # UI durumları
    set_label(connection_label, "Bağlantı: Bağlanıyor...")

    frame_count = 0
    t0 = time.time()

    while True:
        raw = process.stdout.read(width * height * 3)
        if not raw:
            set_label(connection_label, "Bağlantı: HATA - Yayın yok!")
            break

        frame = np.frombuffer(raw, dtype=np.uint8).reshape((height, width, 3))

        # FPS
        frame_count += 1
        elapsed = time.time() - t0
        if elapsed >= 2.0:
            fps = frame_count / elapsed
            set_label(fps_label, f"FPS: {fps:.2f}")
            set_label(connection_label, "Bağlantı: Aktif")
            frame_count = 0
            t0 = time.time()

        # İstersek overlay ile bilgi yazalım (ekstra)
        overlay = frame.copy()
        info = f"{rtmp_url} | Buffer: {rtmp_buffer_ms/1000:.0f}s"
        cv2.putText(overlay, info, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.imshow("DJI Live (Buffered)", overlay)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    try:
        process.terminate()
    except Exception:
        pass

    cv2.destroyAllWindows()
    set_label(connection_label, "Bağlantı: Kapalı")


def set_label(lbl, text):
    """Tk label text güncelle (thread-safe)."""
    try:
        lbl.after(0, lbl.config, {"text": text})
    except Exception:
        pass


def on_start():
    """UI: Başlat butonu."""
    # Docker
    s = ensure_srs()
    set_label(docker_label, f"Docker: {s}")

    # Stream
    threading.Thread(target=start_stream, args=(rtmp_url_var.get(),), daemon=True).start()


# ==== UI Hazırlık ====
root = tk.Tk()
root.title("DJI RTMP Stream Controller")
root.geometry("520x360")

# IP ve RTMP url oluştur
local_ip = get_local_ip()
rtmp_url = f"rtmp://{local_ip}/live/stream"

# Başlık
tk.Label(root, text="DJI RTMP Görüntüleyici", font=("Segoe UI", 14, "bold")).pack(pady=10)

# Bilgi alanı
info_frame = tk.Frame(root)
info_frame.pack(pady=5, fill="x", padx=12)

tk.Label(info_frame, text=f"Yerel IP: {local_ip}", font=("Segoe UI", 11)).grid(row=0, column=0, sticky="w", padx=4, pady=2)
tk.Label(info_frame, text=f"Buffer: {rtmp_buffer_ms/1000:.0f} sn", font=("Segoe UI", 11)).grid(row=1, column=0, sticky="w", padx=4, pady=2)

rtmp_url_var = tk.StringVar(value=rtmp_url)
tk.Label(info_frame, text="RTMP URL:", font=("Segoe UI", 11)).grid(row=2, column=0, sticky="w", padx=4, pady=2)
rtmp_entry = tk.Entry(info_frame, textvariable=rtmp_url_var, width=40, font=("Segoe UI", 10))
rtmp_entry.grid(row=2, column=1, sticky="w", padx=4, pady=2)

# Durum alanları
status_frame = tk.Frame(root)
status_frame.pack(pady=10, fill="x", padx=12)

docker_label = tk.Label(status_frame, text="Docker: -", font=("Segoe UI", 11))
docker_label.pack(anchor="w", pady=2)

connection_label = tk.Label(status_frame, text="Bağlantı: -", font=("Segoe UI", 11))
connection_label.pack(anchor="w", pady=2)

fps_label = tk.Label(status_frame, text="FPS: -", font=("Segoe UI", 11))
fps_label.pack(anchor="w", pady=2)

# Buton
btn_frame = tk.Frame(root)
btn_frame.pack(pady=16)

start_btn = tk.Button(btn_frame, text="Başlat", command=on_start, font=("Segoe UI", 11, "bold"), bg="#2e7d32", fg="white", width=14)
start_btn.grid(row=0, column=0, padx=6)

tk.Label(root, text="Pencere açıkken 'q' ile yayından çıkabilirsiniz.", font=("Segoe UI", 9), fg="#666").pack(pady=4)

root.mainloop()
