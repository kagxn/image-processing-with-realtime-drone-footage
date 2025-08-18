import os 
import time
import cv2
import sys
import subprocess
import threading
from collections import deque
import numpy as np
import tkinter as tk
from tkinter import messagebox
from tkinter import ttk

# ==================== KULLANICI AYARLARI ====================
FFMPEG_PATH = r"C:\ffmpeg\bin\ffmpeg.exe"         # <-- kendi ffmpeg yolun
RTMP_URL    = "rtmp://192.168.137.1/live/stream"  # Mobile Hotspot varsayılan gateway
WIDTH, HEIGHT = 1280, 720
TARGET_FPS   = 30
BUFFER_SEC   = 2                                   # DÜŞÜRÜLDÜ (önce 20 idi)
SRS_IMAGE    = "ossrs/srs:5"
SRS_NAME     = "dji_live_srs"
# ===========================================================

# Global durumlar
producer_proc = None
producer_thread = None
player_thread = None
running = False
queue_lock = threading.Lock()
frame_queue = deque()
target_frames = TARGET_FPS * BUFFER_SEC

# -------------------- UI setter --------------------
def set_label(lbl, text):
    try:
        lbl.after(0, lbl.config, {"text": text})
    except tk.TclError:
        pass

def set_progress(pb, value):
    try:
        pb.after(0, pb.config, {"value": value})
    except tk.TclError:
        pass

# -------------------- Producer (FFmpeg->Queue) --------------------
def start_producer():
    """FFmpeg ile RTMP'yi al, düşük gecikmeli stream aç ve kuyruğa kare koy."""
    global producer_proc, running

    if not os.path.isfile(FFMPEG_PATH):
        messagebox.showerror("Hata", f"FFmpeg bulunamadı:\n{FFMPEG_PATH}")
        return False

    cmd = [
        FFMPEG_PATH,
        "-loglevel", "error",
        "-fflags", "nobuffer",
        "-flags", "low_delay",
        "-rtmp_live", "live",
        "-i", RTMP_URL,
        "-vf", f"fps={TARGET_FPS},scale={WIDTH}:{HEIGHT}",
        "-pix_fmt", "bgr24",
        "-f", "rawvideo",
        "-"
    ]

    try:
        producer_proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
    except Exception as e:
        messagebox.showerror("Hata", f"FFmpeg başlatılamadı:\n{e}")
        return False

    set_label(lbl_conn, "Bağlantı: Bağlanıyor…")
    set_label(lbl_status, "Durum: Buffer dolduruluyor…")
    set_progress(pb_buffer, 0)

    frame_bytes = WIDTH * HEIGHT * 3
    running = True

    def read_loop():
        nonlocal frame_bytes
        def drain_stderr(p):
            for _ in p.stderr:
                pass
        threading.Thread(target=drain_stderr, args=(producer_proc,), daemon=True).start()

        while running:
            try:
                raw = producer_proc.stdout.read(frame_bytes)
                if not raw:
                    break
                frame = np.frombuffer(raw, dtype=np.uint8)
                if frame.size != WIDTH * HEIGHT * 3:
                    continue
                frame = frame.reshape((HEIGHT, WIDTH, 3))

                # Kuyruğu sadece en güncel kareyle güncelle
                with queue_lock:
                    frame_queue.clear()
                    frame_queue.append(frame)

                with queue_lock:
                    fill = min(len(frame_queue), target_frames)
                set_progress(pb_buffer, int(fill / target_frames * 100))

                set_label(lbl_conn, "Bağlantı: Yayın alınıyor")
            except Exception:
                break

        set_label(lbl_conn, "Bağlantı: Koptu / Yayın yok")
        set_label(lbl_status, "Durum: Beklemede")

    t = threading.Thread(target=read_loop, daemon=True)
    t.start()
    return True

# -------------------- Player (Queue->OpenCV) --------------------
def start_player():
    global running

    def play_loop():
        set_label(lbl_status, "Durum: Buffer dolduruluyor…")
        while running:
            with queue_lock:
                filled = len(frame_queue)
            set_progress(pb_buffer, int(min(filled, target_frames) / target_frames * 100))
            if filled >= 1:  # artık tek kare yeterli, çünkü hep en günceli alıyoruz
                break
            time.sleep(0.05)

        if not running:
            return

        set_label(lbl_status, "Durum: Oynatılıyor (30 fps)")
        set_label(lbl_conn, "Bağlantı: Aktif")

        frame_period = 1.0 / TARGET_FPS
        next_deadline = time.perf_counter()
        last_frame = None

        while running:
            with queue_lock:
                if frame_queue:
                    frame = frame_queue.popleft()
                    last_frame = frame
                else:
                    frame = last_frame

            if frame is None:
                set_label(lbl_status, "Durum: Yeniden tamponlanıyor…")
                time.sleep(0.05)
                continue

            overlay = frame.copy()
            info = f"{RTMP_URL} | Buffer hedef: {BUFFER_SEC}s | Target FPS: {TARGET_FPS}"
            cv2.putText(overlay, info, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 2, cv2.LINE_AA)

            cv2.imshow("DJI Live (Buffered 30fps)", overlay)

            next_deadline += frame_period
            sleep_time = next_deadline - time.perf_counter()
            if sleep_time > 0:
                time.sleep(sleep_time)
            else:
                next_deadline = time.perf_counter()

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

        cv2.destroyAllWindows()
        set_label(lbl_conn, "Bağlantı: Kapalı")
        set_label(lbl_status, "Durum: Beklemede")

    t = threading.Thread(target=play_loop, daemon=True)
    t.start()

# -------------------- Kontrol düğmeleri --------------------
def on_start():
    global running, producer_thread, player_thread
    if running:
        return
    running = True
    ok = start_producer()
    if not ok:
        running = False
        return
    start_player()

def on_stop():
    global running, producer_proc
    running = False
    try:
        if producer_proc:
            producer_proc.terminate()
            producer_proc = None
    except Exception:
        pass
    with queue_lock:
        frame_queue.clear()
    set_progress(pb_buffer, 0)
    set_label(lbl_conn, "Bağlantı: Kapalı")
    set_label(lbl_status, "Durum: Beklemede")
    try:
        cv2.destroyAllWindows()
    except Exception:
        pass

# -------------------- UI --------------------
root = tk.Tk()
root.title("DJI RTMP Viewer — Akıcı 30fps (Low Latency)")
root.geometry("620x380")

title = tk.Label(root, text="DJI RTMP Görüntüleyici (Low Latency)", font=("Segoe UI", 13, "bold"))
title.pack(pady=8)

status_frame = tk.Frame(root)
status_frame.pack(pady=6, fill="x", padx=14)
lbl_conn = tk.Label(status_frame, text="Bağlantı: -", font=("Segoe UI", 11))
lbl_conn.grid(row=0, column=0, sticky="w", pady=2)
lbl_status = tk.Label(status_frame, text="Durum: Beklemede", font=("Segoe UI", 11))
lbl_status.grid(row=1, column=0, sticky="w", pady=2)

pb_buffer = ttk.Progressbar(root, orient="horizontal", length=560, mode="determinate", maximum=100)
pb_buffer.pack(pady=6)

btns = tk.Frame(root)
btns.pack(pady=10)
tk.Button(btns, text="Yayını Başlat", command=on_start, width=22, bg="#2e7d32", fg="white").grid(row=0, column=0, padx=6, pady=6)
tk.Button(btns, text="Durdur", command=on_stop, width=22, bg="#c62828", fg="white").grid(row=0, column=1, padx=6, pady=6)

tk.Label(root, text="Not: OpenCV penceresinde çıkış için 'q' tuşu.", font=("Segoe UI", 9), fg="#666").pack(pady=4)

def on_close():
    on_stop()
    root.destroy()

root.protocol("WM_DELETE_WINDOW", on_close)
root.mainloop()
