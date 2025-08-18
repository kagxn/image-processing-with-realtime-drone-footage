# main.py
import subprocess
import cv2
import numpy as np
import os
import time
import threading
import tkinter as tk
from tkinter import messagebox
import re

# ============= CONFIG =============
ffmpeg_path = r"C:\ffmpeg\bin\ffmpeg.exe"   # FFmpeg yolu
rtmp_buffer_ms = 15000       # 15 sn
max_delay_us   = 15000000    # 15 sn
width = 1280
height = 720

SRS_NAME  = "dji_live_srs"
SRS_IMAGE = "ossrs/srs:5"
# ==================================


def open_mobile_hotspot_settings():
    """Windows Mobil Etkin Nokta ayarlarını aç."""
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-Command", "Start-Process ms-settings:network-mobilehotspot"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except Exception:
        subprocess.Popen(
            ["explorer.exe", "ms-settings:network-mobilehotspot"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )


def parse_blocks_from_ipconfig(text: str):
    return re.split(r"\r?\n\r?\n", text)


def get_hotspot_ip():
    """ipconfig’ten özellikle hotspot adaptöründeki IPv4’ü bul."""
    try:
        out = subprocess.check_output(["ipconfig"], encoding="utf-8", errors="ignore")
    except Exception:
        return "127.0.0.1", "ipconfig okunamadı"

    blocks = parse_blocks_from_ipconfig(out)
    ipv4_regex = re.compile(r"IPv4[^:]*:\s*([\d.]+)")
    title_regex = re.compile(r"^(.*?):\s*$", re.MULTILINE)

    # 1) Hedef: Wireless LAN adapter Yerel Ağ Bağlantısı*
    hotspot_patterns = [
        r"Wireless\s*LAN.*Yerel\s*Ağ\s*Bağlantısı\*?\s*\d*",
        r"Kablosuz\s*LAN.*Yerel\s*Ağ\s*Bağlantısı\*?\s*\d*",
        r"Wireless\s*LAN.*Local\s*Area\s*Connection\*?\s*\d*",
    ]

    def find_ip(patterns):
        for b in blocks:
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

    res = find_ip(hotspot_patterns)
    if res: return res

    # fallback: ilk bulunan IPv4
    for b in blocks:
        m_ip = ipv4_regex.search(b)
        if m_ip:
            ip = m_ip.group(1)
            if ip != "127.0.0.1":
                m_title = title_regex.search(b)
                title = m_title.group(1).strip() if m_title else "(başlık yok)"
                return ip, title

    return "127.0.0.1", "IP bulunamadı"


def docker_available():
    try:
        subprocess.run(["docker", "--version"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except Exception:
        return False


def ensure_srs():
    if not docker_available():
        return "Docker bulunamadı"
    exists = subprocess.run(["docker", "inspect", SRS_NAME],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    if exists:
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
            rc = subprocess.run(["docker", "start", SRS_NAME]).returncode
            return "SRS başlatıldı" if rc == 0 else "SRS başlatılamadı"
    else:
        rc = subprocess.run([
            "docker", "run", "-d",
            "--name", SRS_NAME,
            "-p", "1935:1935", "-p", "8080:8080",
            "--restart", "unless-stopped",
            SRS_IMAGE
        ]).returncode
        return "SRS oluşturuldu" if rc == 0 else "SRS oluşturulamadı"


def start_stream(rtmp_url):
    if not os.path.isfile(ffmpeg_path):
        messagebox.showerror("Hata", f"FFmpeg bulunamadı: {ffmpeg_path}")
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

    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=10**8)
    set_label(connection_label, "Bağlantı: Bağlanıyor...")

    frame_count, t0 = 0, time.time()

    while True:
        raw = process.stdout.read(width * height * 3)
        if not raw:
            set_label(connection_label, "Bağlantı: HATA - Yayın yok!")
            break

        frame = np.frombuffer(raw, dtype=np.uint8).reshape((height, width, 3))
        frame_count += 1
        elapsed = time.time() - t0
        if elapsed >= 2.0:
            fps = frame_count / elapsed
            set_label(fps_label, f"FPS: {fps:.2f}")
            set_label(connection_label, "Bağlantı: Aktif")
            frame_count, t0 = 0, time.time()

        overlay = frame.copy()
        info = f"{rtmp_url} | Buffer: {rtmp_buffer_ms/1000:.0f}s"
        cv2.putText(overlay, info, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (255,255,255), 2, cv2.LINE_AA)
        cv2.imshow("DJI Live (Buffered)", overlay)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    process.terminate()
    cv2.destroyAllWindows()
    set_label(connection_label, "Bağlantı: Kapalı")


def set_label(lbl, text):
    try:
        lbl.after(0, lbl.config, {"text": text})
    except Exception:
        pass


# ==== UI ====
root = tk.Tk()
root.title("DJI RTMP Stream Controller")
root.geometry("560x420")

# mobil etkin nokta ekranını aç
open_mobile_hotspot_settings()

tk.Label(root, text="DJI RTMP Görüntüleyici", font=("Segoe UI", 14, "bold")).pack(pady=10)

info_frame = tk.Frame(root)
info_frame.pack(pady=5, fill="x", padx=12)

adapter_label = tk.Label(info_frame, text="Adaptör: -", font=("Segoe UI", 11))
adapter_label.grid(row=0, column=0, sticky="w", padx=4, pady=2, columnspan=2)

ip_label = tk.Label(info_frame, text="Yerel IP: -", font=("Segoe UI", 11))
ip_label.grid(row=1, column=0, sticky="w", padx=4, pady=2, columnspan=2)

rtmp_label = tk.Label(info_frame, text="RTMP URL: -", font=("Segoe UI", 11))
rtmp_label.grid(row=2, column=0, sticky="w", padx=4, pady=2, columnspan=2)

buffer_label = tk.Label(info_frame, text=f"Buffer: {rtmp_buffer_ms/1000:.0f} sn", font=("Segoe UI", 11))
buffer_label.grid(row=3, column=0, sticky="w", padx=4, pady=2)

status_frame = tk.Frame(root)
status_frame.pack(pady=10, fill="x", padx=12)

docker_label = tk.Label(status_frame, text="Docker: -", font=("Segoe UI", 11))
docker_label.pack(anchor="w", pady=2)

connection_label = tk.Label(status_frame, text="Bağlantı: -", font=("Segoe UI", 11))
connection_label.pack(anchor="w", pady=2)

fps_label = tk.Label(status_frame, text="FPS: -", font=("Segoe UI", 11))
fps_label.pack(anchor="w", pady=2)


def on_fetch_ip():
    ip, title = get_hotspot_ip()
    rtmp_url = f"rtmp://{ip}/live/stream"
    set_label(adapter_label, f"Adaptör: {title}")
    set_label(ip_label, f"Yerel IP: {ip}")
    set_label(rtmp_label, f"RTMP URL: {rtmp_url}")


def on_connect():
    rtmp_url = rtmp_label.cget("text").replace("RTMP URL: ", "")
    s = ensure_srs()
    set_label(docker_label, f"Docker: {s}")
    threading.Thread(target=start_stream, args=(rtmp_url,), daemon=True).start()


btn_frame = tk.Frame(root)
btn_frame.pack(pady=16)

tk.Button(btn_frame, text="IP’yi Çek", command=on_fetch_ip,
          font=("Segoe UI", 11, "bold"), bg="#0277bd", fg="white", width=14).grid(row=0, column=0, padx=6)

tk.Button(btn_frame, text="Bağlan", command=on_connect,
          font=("Segoe UI", 11, "bold"), bg="#2e7d32", fg="white", width=14).grid(row=0, column=1, padx=6)

tk.Label(root, text="OpenCV penceresi açıkken 'q' ile çıkabilirsiniz.", font=("Segoe UI", 9), fg="#666").pack(pady=4)

root.mainloop()
