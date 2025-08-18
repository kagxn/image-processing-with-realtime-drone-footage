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


def get_hotspot_ip():
    """
    Windows 'ipconfig' çıktısından 'Kablosuz LAN bağdaştırıcısı Yerel Ağ Bağlantısı'
    (veya İng: 'Wireless LAN adapter Local Area Connection*') bloğundaki IPv4'ü döndürür.
    Bulamazsa Wi-Fi, yine yoksa ilk IPv4; en sonda 127.0.0.1.
    Ayrıca eşleşen başlığı da döndürür.
    """
    try:
        out = subprocess.check_output(["ipconfig"], encoding="utf-8", errors="ignore")
    except Exception:
        return "127.0.0.1", "ipconfig okunamadı"

    # bloklara ayır
    blocks = re.split(r"\r?\n\r?\n", out)
    ipv4_regex = re.compile(r"IPv4[^:]*:\s*([\d.]+)")
    title_regex = re.compile(r"^(.*?):\s*$", re.MULTILINE)

    # Hedef adaptör başlık örüntüleri (TR & EN)
    target_patterns = [
        r"Kablosuz\s*LAN.*Yerel\s*Ağ\s*Bağlantısı\*?\s*\d*",   # TR Hotspot Local Area Connection*
        r"Wireless\s*LAN.*Local\s*Area\s*Connection\*?\s*\d*", # EN Hotspot Local Area Connection*
    ]

    # Wi-Fi yedeği (TR & EN)
    wifi_patterns = [
        r"Kablosuz\s*LAN.*Wi-?Fi",
        r"Wireless\s*LAN.*Wi-?Fi",
    ]

    def find_ip_by_patterns(patterns):
        for b in blocks:
            # blok başlığı
            m_title = title_regex.search(b)
            title = m_title.group(1).strip() if m_title else ""
            for pat in patterns:
                if re.search(pat, title, flags=re.IGNORECASE):
                    m_ip = ipv4_regex.search(b)
                    if m_ip:
                        ip = m_ip.group(1)
                        if ip != "127.0.0.1":
                            return ip, title
        return None

    # 1) Önce hotspot Local Area Connection* adaptörü
    res = find_ip_by_patterns(target_patterns)
    if res:
        return res

    # 2) Wi-Fi adaptörü
    res = find_ip_by_patterns(wifi_patterns)
    if res:
        return res

    # 3) Herhangi bir bloktaki ilk IPv4
    for b in blocks:
        m_ip = ipv4_regex.search(b)
        if m_ip:
            ip = m_ip.group(1)
            if ip != "127.0.0.1":
                m_title = title_regex.search(b)
                title = m_title.group(1).strip() if m_title else "(başlık yok)"
                return ip, title

    return "127.0.0.1", "IP bulunamadı, localhost"


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
        try:
            status = subprocess.check_output(
                ["docker", "inspect", "-f", "{{.State.Running}}", SRS_NAME],
                encoding="utf-8"
            ).strip()
        except subprocess.CalledProcessError:
            status = "false"

        if status.lower() == "true":
            return "SRS zaten çalışıyor"
        else:
            rc = subprocess.run(["docker", "start", SRS_NAME],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL).returncode
            return "SRS başlatıldı" if rc == 0 else "SRS başlatılamadı"
    else:
        rc = subprocess.run([
            "docker", "run", "-d",
            "--name", SRS_NAME,
            "-p", "1935:1935", "-p", "8080:8080",
            "--restart", "unless-stopped",
            SRS_IMAGE
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
        return "SRS oluşturulup başlatıldı" if rc == 0 else "SRS oluşturulamadı"


def set_label(lbl, text):
    """Tk label text güncelle (thread-safe)."""
    try:
        lbl.after(0, lbl.config, {"text": text})
    except Exception:
        pass


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

        # Overlay bilgi
        overlay = frame.copy()
        info = f"{rtmp_url} | Buffer: {rtmp_buffer_ms/1000:.0f}s"
        cv2.putText(overlay, info, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (255, 255, 255), 2, cv2.LINE_AA)
        cv2.imshow("DJI Live (Buffered)", overlay)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    try:
        process.terminate()
    except Exception:
        pass

    cv2.destroyAllWindows()
    set_label(connection_label, "Bağlantı: Kapalı")


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
root.geometry("560x380")

# IP ve RTMP url oluştur (özellikle Hotspot Local Area Connection* IP'si hedeflenir)
local_ip, adapter_title = get_hotspot_ip()
rtmp_url = f"rtmp://{local_ip}/live/stream"

# Başlık
tk.Label(root, text="DJI RTMP Görüntüleyici", font=("Segoe UI", 14, "bold")).pack(pady=10)

# Bilgi alanı
info_frame = tk.Frame(root)
info_frame.pack(pady=5, fill="x", padx=12)

tk.Label(info_frame, text=f"Adaptör: {adapter_title}", font=("Segoe UI", 11)).grid(row=0, column=0, sticky="w", padx=4, pady=2)
tk.Label(info_frame, text=f"Yerel IP: {local_ip}", font=("Segoe UI", 11)).grid(row=1, column=0, sticky="w", padx=4, pady=2)
tk.Label(info_frame, text=f"Buffer: {rtmp_buffer_ms/1000:.0f} sn", font=("Segoe UI", 11)).grid(row=2, column=0, sticky="w", padx=4, pady=2)

rtmp_url_var = tk.StringVar(value=rtmp_url)
tk.Label(info_frame, text="RTMP URL:", font=("Segoe UI", 11)).grid(row=3, column=0, sticky="w", padx=4, pady=2)
rtmp_entry = tk.Entry(info_frame, textvariable=rtmp_url_var, width=44, font=("Segoe UI", 10))
rtmp_entry.grid(row=3, column=1, sticky="w", padx=4, pady=2)

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

start_btn = tk.Button(btn_frame, text="Başlat", command=on_start,
                      font=("Segoe UI", 11, "bold"), bg="#2e7d32", fg="white", width=16)
start_btn.grid(row=0, column=0, padx=6)

tk.Label(root, text="OpenCV penceresi açıkken 'q' ile yayından çıkabilirsiniz.", font=("Segoe UI", 9), fg="#666").pack(pady=4)

root.mainloop()
