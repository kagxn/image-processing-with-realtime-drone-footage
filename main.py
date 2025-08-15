import cv2

# RTMP yayını buradan alınacak
rtmp_url = "rtmp://127.0.0.1/live/stream"  # veya IP'li hali: rtmp://192.168.1.x/live/stream

cap = cv2.VideoCapture(rtmp_url)

if not cap.isOpened():
    print("Yayına bağlanılamadı.")
    exit()

while True:
    ret, frame = cap.read()
    if not ret:
        print("Görüntü alınamadı.")
        break

    cv2.imshow("DJI Live", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
