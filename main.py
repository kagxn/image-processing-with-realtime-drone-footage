import subprocess
import re
import os
import sys
import time
import cv2
import numpy as np
import tkinter as tk
from tkinter import ttk, messagebox

# ================= #
# Hotspot Açma      #
# ================= #
def start_hotspot():
    try:
        subprocess.run(
            'netsh wlan set hostednetwork mode=allow ssid=DJIHotspot key=12345678',
            shell=True, check=True
        )
        subprocess.run(
            'netsh wlan start hostednetwork',
            shell=True, check=True
        )
        time.sleep(5)
    except subprocess.CalledProcessError:
        messagebox.showerror("Hata", "Hotspot açılamadı! Scripti Yönetici olarak çalıştır.")
        sys.exit(1)

# ================= #
# IP Alma           #
# ================= #
def get_hotspot_ip():
    result = subprocess.check_output("ipconfig", encoding="utf-8", errors="ignore")
    blocks = result.split("\n\n")
    for block in blocks:
        if "Wireless LAN adapter" in block and "Yerel Ağ Bağlantısı" in block:
            match = re.search(r"IPv4.*?:\s*([\d.]+)", block)
            if match:
                return match.group(1)
    return None

# ================= #
# Docker SRS Run    #
# ================= #
def start_docker_srs():
    cmd = "docker ps -q --filter 'name=srs'"
    running = subprocess.check_output(cmd, shell=True).decode().strip()
    if not running:
        subprocess.run("docker run -d --name srs --restart always -p 1935:1935 ossrs/srs:5", shell=True)
        time.sleep(3)

# ================= #
# FFmpeg Yayını     #
# ================= #
def start_ffmpeg_stream(rtmp_url, ffmpeg_path, width=1280, height=720, delay=15):
    cmd = [
        ffmpeg_path,
        "-fflags", "+genpts",
        "-rtmp_buffer", str(delay * 1000),
        "-i", rtmp_url,
        "-max_delay", str(delay * 1000000),
        "-f", "image2pipe",
        "-pix_fmt", "bgr24",
        "-vcodec", "rawvideo",
        "-"
    ]
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=10**8)

    while True:
        raw_image = process.stdout.read(width * height * 3)
        if not raw_image:
            break

        frame = np.frombuffer(raw_image, dtype=np.uint8).reshape((height, width, 3))
        cv2.imshow("DJI Live (Buffer)", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    process.terminate()
    cv2.destroyAllWindows()

# ================= #
# GUI Arayüz        #
# ================= #
class App:
    def __init__(self, root):
        self.root = root
        self.root.title("DJI RTMP Stream")
        self.root.geometry("400x250")

        # ffmpeg yolu
        self.ffmpeg_path = r"C:\ffmpeg\bin\ffmpeg.exe"

        # Hotspot + Docker başlat
        start_hotspot()
        self.ip = get_hotspot_ip()
        if not self.ip:
            messagebox.showerror("Hata", "Hotspot IP bulunamadı!")
            sys.exit(1)

        start_docker_srs()

        # RTMP URL
        self.rtmp_url = f"rtmp://{self.ip}/live/stream"

        # UI Elemanları
        ttk.Label(root, text=f"RTMP URL: {self.rtmp_url}").pack(pady=10)

        ttk.Label(root, text="FPS:").pack()
        self.fps_entry = ttk.Entry(root)
        self.fps_entry.insert(0, "30")
        self.fps_entry.pack(pady=5)

        ttk.Label(root, text="Buffer (saniye):").pack()
        self.delay_entry = ttk.Entry(root)
        self.delay_entry.insert(0, "15")
        self.delay_entry.pack(pady=5)

        self.start_btn = ttk.Button(root, text="Yayını Başlat", command=self.run_stream)
        self.start_btn.pack(pady=15)

    def run_stream(self):
        try:
            fps = int(self.fps_entry.get())
            delay = int(self.delay_entry.get())
        except ValueError:
            messagebox.showerror("Hata", "FPS ve Buffer sayı olmalı.")
            return

        if not os.path.isfile(self.ffmpeg_path):
            messagebox.showerror("Hata", f"ffmpeg bulunamadı: {self.ffmpeg_path}")
            return

        self.root.destroy()  # UI kapat
        start_ffmpeg_stream(self.rtmp_url, self.ffmpeg_path, delay=delay)

# ================= #
# MAIN              #
# ================= #
if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
