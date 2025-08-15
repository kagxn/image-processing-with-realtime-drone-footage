import subprocess

import cv2

import numpy as np

import os

import sys


# ffmpeg tam yolu

ffmpeg_path = r"C:\ffmpeg\bin\ffmpeg.exe"


# ffmpeg mevcut mu kontrol et

if not os.path.isfile(ffmpeg_path):

    print(f"HATA: ffmpeg yolu bulunamadı: {ffmpeg_path}")

    sys.exit(1)


# RTMP yayını (DJI IP veya localhost)

rtmp_url = "rtmp://127.0.0.1/live/stream"  # veya cihazın IP'si


# FFmpeg komutu (15 sn buffer ile OpenCV'ye kare gönderir)

cmd = [

    ffmpeg_path,

    "-fflags", "+genpts",

    "-rtmp_buffer", "15000",

    "-i", rtmp_url,

    "-max_delay", "15000000",

    "-f", "image2pipe",

    "-pix_fmt", "bgr24",

    "-vcodec", "rawvideo",

    "-"

]


# DJI yayının çözünürlüğü (gerekiyorsa değiştir)

width = 1280

height = 720


# FFmpeg sürecini başlat

process = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=10**8)


while True:

    # Kare boyutunu hesapla ve oku

    raw_image = process.stdout.read(width * height * 3)

    if not raw_image:

        break


    # Numpy array'e çevir

    frame = np.frombuffer(raw_image, dtype=np.uint8).reshape((height, width, 3))


    # Görüntüyü göster

    cv2.imshow("DJI Live (15s Buffer)", frame)


    # Çıkış için 'q' tuşu

    if cv2.waitKey(1) & 0xFF == ord('q'):

        break


# Temizlik

process.terminate()

cv2.destroyAllWindows()
