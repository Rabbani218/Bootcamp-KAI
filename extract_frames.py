"""
Script analisis video: ekstrak frame-frame kunci dari video Kalibata
dan simpan sebagai gambar untuk inspeksi visual zero-halusinasi.
"""
import cv2
import os
import numpy as np

VIDEO_URL = "https://rr2---sn-npoe7nlz.googlevideo.com/videoplayback?expire=1779784771&ei=4wcVapnQIZjP1_oP64DZwAQ&ip=103.52.69.21&id=o-AObmQRDGuSJVu00IVOhR_xUkzqwFnqo6oP_iJg3fB9kJ&itag=18&source=youtube&requiressl=yes&xpc=EgVo2aDSNQ%3D%3D&cps=155&met=1779763171%2C&mh=Rw&mm=31%2C29&mn=sn-npoe7nlz%2Csn-npoldn7z&ms=au%2Crdu&mv=m&mvi=2&pl=24&rms=au%2Cau&initcwndbps=3472500&bui=AbKmrwoSZS23ohc4kfULmG3r19xik0GIR-HmRA8sqjfriHClQHLIR3bp_t4RWMwINxEEfkSyf-TV3nvs&spc=96XrvwpS_UkSpMm6H9oG5GhZTzq4IFOTzJfuxJEwuXDjcSFJ6WyqdJJM9hw6eQ3ZiPeTgKPE&vprv=1&svpuc=1&mime=video%2Fmp4&ns=_0GLrMBVeAxZdsPm77lybs4V&rqh=1&cnr=14&ratebypass=yes&dur=60.093&lmt=1704854821720988&mt=1779762774&fvip=3&fexp=51565116%2C51565681&c=WEB&sefc=1&txp=6218224&n=vtvj6YMTxC1Trvgss9U&sparams=expire%2Cei%2Cip%2Cid%2Citag%2Csource%2Crequiressl%2Cxpc%2Cbui%2Cspc%2Cvprv%2Csvpuc%2Cmime%2Cns%2Crqh%2Ccnr%2Cratebypass%2Cdur%2Clmt&sig=AHEqNM4wRQIgGsJvT3d2xYfBGiP3tBguFEnESQLMzpo9GnWAHhSnbyECIQDx3jSMdKzftKEzxRZyY8ddCI0cMe8EsS7zr0IvxkYGkA%3D%3D&lsparams=cps%2Cmet%2Cmh%2Cmm%2Cmn%2Cms%2Cmv%2Cmvi%2Cpl%2Crms%2Cinitcwndbps&lsig=APaTxxMwRQIgdYGsAh7rCAqTcLer-Dl2IXZp5rDtOnwPex0QV6YQEhsCIQC0Frck2ykoSmP-M5Oi6Xr9w6Mzxz8K9JwKuwFQCM8dlw%3D%3D"

OUT_DIR = "frame_analisis_kalibata"
os.makedirs(OUT_DIR, exist_ok=True)

cap = cv2.VideoCapture(VIDEO_URL)
if not cap.isOpened():
    print("ERROR: Tidak bisa membuka stream video")
    exit(1)

fps    = cap.get(cv2.CAP_PROP_FPS)
total  = cap.get(cv2.CAP_PROP_FRAME_COUNT)
dur    = total / fps if fps > 0 else 60.0

print(f"FPS       : {fps:.2f}")
print(f"Total fr  : {total:.0f}")
print(f"Durasi    : {dur:.1f} detik")

# Ambil frame setiap 1 detik (0, 1, 2, ... hingga akhir video)
saved = []
for target_sec in range(0, int(dur) + 1):
    target_frame = int(target_sec * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
    ret, frame = cap.read()
    if not ret or frame is None:
        continue
    
    fname = os.path.join(OUT_DIR, f"t{target_sec:03d}s.jpg")
    # Tambahkan timestamp overlay pada frame
    h, w = frame.shape[:2]
    cv2.putText(frame, f"T={target_sec}s", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2)
    cv2.imwrite(fname, frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    saved.append(fname)
    print(f"  Saved: {fname}")

cap.release()
print(f"\nTotal {len(saved)} frame disimpan ke folder '{OUT_DIR}/'")
