# main.py
import tkinter as tk
from tkinter import messagebox
import subprocess
import threading
import os
import time
import cv2
import numpy as np

# ==================== AYARLAR ====================
FFMPEG_PATH = r"C:\ffmpeg\bin\ffmpeg.exe"   # <-- kendi ffmpeg yolunu yaz
SRS_IMAGE   = "ossrs/srs:5"
SRS_NAME    = "dji_live_srs"

FIXED_IP    = "192.168.137.1"               # Windows Mobil Etkin Nokta varsayılan gateway IP
RTMP_URL    = f"rtmp://{FIXED_IP}/live/stream"

WIDTH, HEIGHT = 1280, 720                    # beklenen yayın çözünürlüğü
FPS           = 30                           # hedef oynatma hızı
BUFFER_SECONDS= 15                           # gecikme (akıcı oynatma için büyük buffer)

# FFmpeg param karşılıkları
RTMP_BUFFER_MS = BUFFER_SECONDS * 1000       # -rtmp_buffer (ms)
MAX_DELAY_US   = BUFFER_SECONDS * 1_000_000  # -max_delay (µs)
# =================================================


# ---- Yardımcılar ----
def docker_available():
    """Docker CLI var mı?"""
    try:
        subprocess.run(["docker", "--version"], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=True)
        return True
    except Exception:
        return False


def ensure_srs():
    """
    Docker Desktop kapalıysa açar, Engine gelene kadar bekler.
    SRS container'ını (ossrs/srs:5) 1935/8080 portlarıyla ayağa kaldırır.
    Durum metnini döndürür.
    """
    if not docker_available():
        return "Docker CLI bulunamadı (Docker Desktop kurulu mu?)"

    # Docker Desktop'ı başlat (varsayılan kurulum yolu)
    docker_desktop_paths = [
        r"C:\Program Files\Docker\Docker\Docker Desktop.exe",
        r"C:\Program Files\Docker\Docker\Docker Desktop.exe".replace("Program Files", "Program Files (x86)")
    ]
    for p in docker_desktop_paths:
        if os.path.isfile(p):
            try:
                subprocess.Popen([p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
            break

    # Engine hazır olana dek bekle
    for _ in range(60):  # ~60 sn
        try:
            subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, check=True)
            break
        except Exception:
            time.sleep(1)
    else:
        return "Docker Engine başlatılamadı!"

    # Container var mı?
    exists = subprocess.run(["docker", "inspect", SRS_NAME],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL).returncode == 0
    if exists:
        # Çalışıyor mu?
        try:
            status = subprocess.check_output(
                ["docker", "inspect", "-f", "{{.State.Running}}", SRS_NAME],
                encoding="utf-8"
            ).strip().lower()
        except subprocess.CalledProcessError:
            status = "false"

        if status == "true":
            return "SRS zaten çalışıyor"
        else:
            rc = subprocess.run(["docker", "start", SRS_NAME],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
            return "SRS başlatıldı" if rc == 0 else "SRS başlatılamadı"
    else:
        # Yeni container oluştur
        rc = subprocess.run([
            "docker", "run", "-d",
            "--name", SRS_NAME,
            "-p", "1935:1935", "-p", "8080:8080",
            "--restart", "unless-stopped",
            SRS_IMAGE
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
        return "SRS oluşturuldu" if rc == 0 else "SRS oluşturulamadı"


def open_mobile_hotspot():
    """Windows Mobil Etkin Nokta ayarlarını aç (kullanıcı elle açsın)."""
    try:
        subprocess.Popen("start ms-settings:network-mobilehotspot", shell=True)
    except Exception as e:
        messagebox.showerror("Hata", f"Mobil etkin nokta açılamadı:\n{e}")


def set_label(lbl, text):
    try:
        lbl.after(0, lbl.config, {"text": text})
    except Exception:
        pass


# ---- Yayını başlat (FFmpeg -> OpenCV) ----
def start_stream():
    if not os.path.isfile(FFMPEG_PATH):
        messagebox.showerror("Hata", f"FFmpeg bulunamadı:\n{FFMPEG_PATH}")
        return

    # FFmpeg: RTMP'den oku, RAW video olarak pipe'a ver, çıkış FPS'ini sabitle
    cmd = [
        FFMPEG_PATH,
        "-fflags", "+genpts",
        "-rtmp_buffer", str(RTMP_BUFFER_MS),
        "-i", RTMP_URL,
        "-max_delay", str(MAX_DELAY_US),
        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "-r", str(FPS),       # <<< OpenCV'ye sabit hızda kare ver
        "-"
    ]

    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=10**8)
    except Exception as e:
        messagebox.showerror("Hata", f"FFmpeg başlatılamadı:\n{e}")
        return

    set_label(lbl_conn, "Bağlantı: Bağlanıyor…")
    frame_bytes = WIDTH * HEIGHT * 3
    frame_count, t0 = 0, time.time()

    while True:
        raw = process.stdout.read(frame_bytes)
        if not raw:
            set_label(lbl_conn, "Bağlantı: HATA - Yayın yok")
            break

        frame = np.frombuffer(raw, dtype=np.uint8).reshape((HEIGHT, WIDTH, 3))

        # FPS ölçümü (gerçek gösterim hızı)
        frame_count += 1
        elapsed = time.time() - t0
        if elapsed >= 2.0:
            real_fps = frame_count / elapsed
            set_label(lbl_fps, f"FPS: {real_fps:.2f}")
            set_label(lbl_conn, "Bağlantı: Aktif")
            frame_count, t0 = 0, time.time()

        # Overlay bilgi yaz
        overlay = frame.copy()
        info = f"{RTMP_URL} | Buffer: {BUFFER_SECONDS}s | Target FPS: {FPS}"
        cv2.putText(overlay, info, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (255, 255, 255), 2, cv2.LINE_AA)

        cv2.imshow("DJI Live (Buffered)", overlay)

        # OpenCV pencere kontrolü
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

        # Pacing: OpenCV tarafında da hız sabitle (FFmpeg -r ile birlikte emniyet kemeri)
        time.sleep(max(0, 1.0/FPS - 0.001))

    try:
        process.terminate()
    except Exception:
        pass
    cv2.destroyAllWindows()
    set_label(lbl_conn, "Bağlantı: Kapalı")


# ---- UI olayları ----
def on_docker_start():
    def task():
        set_label(lbl_docker, "Docker: başlatılıyor…")
        status = ensure_srs()
        set_label(lbl_docker, f"Docker: {status}")
    threading.Thread(target=task, daemon=True).start()


def on_stream_start():
    threading.Thread(target=start_stream, daemon=True).start()


# ==================== UI ====================
root = tk.Tk()
root.title("DJI RTMP Viewer")
root.geometry("540x320")

tk.Label(root, text="DJI RTMP Görüntüleyici", font=("Segoe UI", 14, "bold")).pack(pady=10)

btn_frame = tk.Frame(root)
btn_frame.pack(pady=5)

tk.Button(btn_frame, text="Mobil Etkin Nokta Aç", command=open_mobile_hotspot,
          height=2, width=20).grid(row=0, column=0, padx=6, pady=4)

tk.Button(btn_frame, text="Docker Başlat (SRS)", command=on_docker_start,
          height=2, width=20).grid(row=0, column=1, padx=6, pady=4)

tk.Button(root, text="Bağlan ve Görüntüyü Aç", command=on_stream_start,
          height=2, width=25).pack(pady=8)

info = tk.Frame(root)
info.pack(pady=8, fill="x", padx=14)

tk.Label(info, text=f"RTMP URL: {RTMP_URL}", font=("Segoe UI", 11)).grid(row=0, column=0, sticky="w", pady=2)
tk.Label(info, text=f"Buffer: {BUFFER_SECONDS} sn", font=("Segoe UI", 11)).grid(row=1, column=0, sticky="w", pady=2)
tk.Label(info, text=f"Hedef FPS: {FPS}", font=("Segoe UI", 11)).grid(row=2, column=0, sticky="w", pady=2)

status = tk.Frame(root)
status.pack(pady=6, fill="x", padx=14)

lbl_docker = tk.Label(status, text="Docker: -", font=("Segoe UI", 11))
lbl_docker.grid(row=0, column=0, sticky="w", pady=2)

lbl_conn = tk.Label(status, text="Bağlantı: -", font=("Segoe UI", 11))
lbl_conn.grid(row=1, column=0, sticky="w", pady=2)

lbl_fps = tk.Label(status, text="FPS: -", font=("Segoe UI", 11))
lbl_fps.grid(row=2, column=0, sticky="w", pady=2)

tk.Label(root, text="OpenCV penceresinde çıkış: 'q'", font=("Segoe UI", 9), fg="#666").pack(pady=4)

root.mainloop()
