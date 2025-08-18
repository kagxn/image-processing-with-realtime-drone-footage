import av
import cv2
import threading
import time
from collections import deque
import tkinter as tk
from tkinter import ttk

# ==================== KULLANICI AYARLARI ====================
RTMP_URL    = "rtmp://192.168.137.1/live/stream"
WIDTH, HEIGHT = 1280, 720
TARGET_FPS   = 30
# ===========================================================

# Global durumlar
running = False
frame_queue = deque()
queue_lock = threading.Lock()


# -------------------- Frame Reader (PyAV) --------------------
def start_reader():
    """PyAV ile RTMP yayını oku ve en güncel frame'i kuyruğa koy."""
    global running
    running = True

    def read_loop():
        try:
            container = av.open(RTMP_URL, options={
                "fflags": "nobuffer",
                "flags": "low_delay",
                "rtmp_live": "live"
            })
        except av.AVError as e:
            set_label(lbl_conn, f"Bağlantı hatası: {e}")
            return

        stream = container.streams.video[0]
        stream.thread_type = "AUTO"

        set_label(lbl_conn, "Bağlantı: Yayın alınıyor")
        for packet in container.demux(stream):
            if not running:
                break
            for frame in packet.decode():
                img = frame.to_ndarray(format="bgr24")

                if img.shape[1] != WIDTH or img.shape[0] != HEIGHT:
                    img = cv2.resize(img, (WIDTH, HEIGHT))

                with queue_lock:
                    frame_queue.clear()      # sadece en güncel kareyi tut
                    frame_queue.append(img)

        container.close()
        set_label(lbl_conn, "Bağlantı: Koptu / Yayın yok")

    t = threading.Thread(target=read_loop, daemon=True)
    t.start()


# -------------------- Frame Player --------------------
def start_player():
    global running
    frame_period = 1.0 / TARGET_FPS
    next_deadline = time.perf_counter()
    last_frame = None

    set_label(lbl_status, "Durum: Oynatılıyor")

    while running:
        with queue_lock:
            if frame_queue:
                frame = frame_queue.popleft()
                last_frame = frame
            else:
                frame = last_frame

        if frame is None:
            time.sleep(0.01)
            continue

        overlay = frame.copy()
        info = f"{RTMP_URL} | Low latency | {TARGET_FPS} FPS"
        cv2.putText(overlay, info, (10, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (255,255,255), 2, cv2.LINE_AA)
        cv2.imshow("DJI Live (PyAV)", overlay)

        next_deadline += frame_period
        sleep_time = next_deadline - time.perf_counter()
        if sleep_time > 0:
            time.sleep(sleep_time)
        else:
            next_deadline = time.perf_counter()

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cv2.destroyAllWindows()
    set_label(lbl_status, "Durum: Beklemede")


# -------------------- Tkinter Wrapper --------------------
def set_label(lbl, text):
    try:
        lbl.after(0, lbl.config, {"text": text})
    except tk.TclError:
        pass


def on_start():
    global running
    if running:
        return
    running = True
    set_label(lbl_status, "Durum: Başlatılıyor…")
    start_reader()
    threading.Thread(target=start_player, daemon=True).start()


def on_stop():
    global running
    running = False
    with queue_lock:
        frame_queue.clear()
    set_label(lbl_conn, "Bağlantı: Kapalı")
    set_label(lbl_status, "Durum: Beklemede")
    try:
        cv2.destroyAllWindows()
    except Exception:
        pass


# -------------------- UI --------------------
root = tk.Tk()
root.title("DJI RTMP Viewer — PyAV Low Latency")
root.geometry("620x300")

title = tk.Label(root, text="DJI RTMP Görüntüleyici (PyAV, Low Latency)",
                 font=("Segoe UI", 13, "bold"))
title.pack(pady=8)

status_frame = tk.Frame(root)
status_frame.pack(pady=6, fill="x", padx=14)
lbl_conn = tk.Label(status_frame, text="Bağlantı: -", font=("Segoe UI", 11))
lbl_conn.grid(row=0, column=0, sticky="w", pady=2)
lbl_status = tk.Label(status_frame, text="Durum: Beklemede", font=("Segoe UI", 11))
lbl_status.grid(row=1, column=0, sticky="w", pady=2)

btns = tk.Frame(root)
btns.pack(pady=10)
tk.Button(btns, text="Yayını Başlat", command=on_start,
          width=22, bg="#2e7d32", fg="white").grid(row=0, column=0, padx=6, pady=6)
tk.Button(btns, text="Durdur", command=on_stop,
          width=22, bg="#c62828", fg="white").grid(row=0, column=1, padx=6, pady=6)

tk.Label(root, text="Not: OpenCV penceresinde çıkış için 'q' tuşu.",
         font=("Segoe UI", 9), fg="#666").pack(pady=4)

def on_close():
    on_stop()
    root.destroy()

root.protocol("WM_DELETE_WINDOW", on_close)
root.mainloop()
