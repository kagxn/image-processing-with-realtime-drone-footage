import tkinter as tk
from tkinter import messagebox
import subprocess
import threading
import os
import time
import cv2
import numpy as np

# --- Global ayarlar ---
FFMPEG_PATH = r"C:\ffmpeg\bin\ffmpeg.exe"  # kendi ffmpeg yolunu yaz
SRS_IMAGE = "ossrs/srs:5"
SRS_NAME = "srs"
RTMP_URL = "rtmp://192.168.137.1/live/stream"  # mobil etkin nokta IP'si sabit
FPS = 30
BUFFER_SECONDS = 15


# --- Yardımcı fonksiyonlar ---
def docker_available():
    """Docker CLI var mı kontrol et"""
    try:
        subprocess.run(["docker", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except Exception:
        return False


def ensure_srs():
    """Docker Desktop aç, sonra SRS'yi başlat"""
    if not docker_available():
        return "Docker CLI bulunamadı (Docker Desktop kurulu mu?)"

    # Docker Desktop'ı aç
    docker_desktop_path = r"C:\Program Files\Docker\Docker\Docker Desktop.exe"
    if os.path.isfile(docker_desktop_path):
        subprocess.Popen([docker_desktop_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Docker Engine açılana kadar bekle
    for _ in range(40):  # max ~40 sn
        try:
            subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            break
        except Exception:
            time.sleep(1)
    else:
        return "Docker Engine başlatılamadı!"

    # Container var mı kontrol et
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


def open_mobile_hotspot():
    """Windows mobil etkin nokta ayarlarını aç"""
    try:
        subprocess.Popen("start ms-settings:network-mobilehotspot", shell=True)
    except Exception as e:
        messagebox.showerror("Hata", f"Mobil etkin nokta açılamadı: {e}")


def start_stream():
    """FFmpeg üzerinden RTMP yayını al ve göster"""
    if not os.path.isfile(FFMPEG_PATH):
        messagebox.showerror("Hata", f"FFmpeg bulunamadı: {FFMPEG_PATH}")
        return

    cmd = [
        FFMPEG_PATH,
        "-fflags", "+genpts",
        "-rtmp_buffer", str(BUFFER_SECONDS * 1000),
        "-i", RTMP_URL,
        "-max_delay", str(BUFFER_SECONDS * 1000000),
        "-f", "image2pipe",
        "-pix_fmt", "bgr24",
        "-vcodec", "rawvideo",
        "-"
    ]

    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=10**8)
    except Exception as e:
        messagebox.showerror("Hata", f"FFmpeg başlatılamadı: {e}")
        return

    width, height = 1280, 720  # yayının çözünürlüğü

    while True:
        raw_image = process.stdout.read(width * height * 3)
        if not raw_image:
            break

        frame = np.frombuffer(raw_image, dtype=np.uint8).reshape((height, width, 3))
        cv2.imshow("DJI Live Stream", frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    process.terminate()
    cv2.destroyAllWindows()


# --- UI fonksiyonları ---
def on_docker_start():
    def task():
        status = ensure_srs()
        lbl_status.config(text=f"Docker: {status}")
    threading.Thread(target=task, daemon=True).start()


def on_stream_start():
    threading.Thread(target=start_stream, daemon=True).start()


# --- Arayüz ---
root = tk.Tk()
root.title("DJI RTMP Viewer")
root.geometry("500x300")

btn_hotspot = tk.Button(root, text="Mobil Etkin Nokta Aç", command=open_mobile_hotspot, height=2, width=25)
btn_hotspot.pack(pady=10)

btn_docker = tk.Button(root, text="Docker Başlat (SRS)", command=on_docker_start, height=2, width=25)
btn_docker.pack(pady=10)

lbl_status = tk.Label(root, text="Docker: Durum bilinmiyor", fg="blue")
lbl_status.pack(pady=5)

lbl_info = tk.Label(
    root,
    text=f"RTMP URL: {RTMP_URL}\nFPS: {FPS}\nGecikme: {BUFFER_SECONDS} sn",
    fg="black"
)
lbl_info.pack(pady=10)

btn_start = tk.Button(root, text="Bağlan ve Görüntüyü Aç", command=on_stream_start, height=2, width=25)
btn_start.pack(pady=10)

root.mainloop()
