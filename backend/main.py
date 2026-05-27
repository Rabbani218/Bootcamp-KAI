import asyncio
import json
import logging
import os
import time
import math
import shutil
import threading
from pathlib import Path
from typing import Dict, List, Optional

import cv2
import numpy as np
import yt_dlp
import aiohttp
import paho.mqtt.client as mqtt
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import sqlite3

# ── DB Init ───────────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect("incidents.db")
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER,
            lokasi TEXT,
            jenis TEXT,
            snapshot_url TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("debug.log")]
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
GEMINI_API_KEY   = os.getenv("GEMINI_API_KEY", "AIzaSyCCNLkAMh6VmZuaoG1LuqkAa9O0cMA-hVA")
GEMINI_INTERVAL  = 10
FRONTEND_URL     = os.getenv("FRONTEND_URL", "*")
MQTT_BROKER      = os.getenv("MQTT_BROKER", "test.mosquitto.org")

# Kelas COCO yang kita pantau (Person, Car, Motorcycle, Bus, Train, Truck)
YOLO_CLASSES     = [0, 2, 3, 5, 6, 7]
YOLO_CONF        = 0.25   # Confidence threshold (cukup sensitif)
YOLO_IOU         = 0.45   # IoU NMS threshold

# Nama model: prioritas custom, fallback ke yolov8n.pt (auto-download dari Ultralytics)
YOLO_MODEL_PATH  = os.getenv("YOLO_MODEL", "best_web_optimized.onnx")

# ── AppState ──────────────────────────────────────────────────────────────────
class AppState:
    def __init__(self):
        self.source_mode: str      = "youtube"
        self.target_url: str       = "https://www.youtube.com/watch?v=q7lvnYVuqNY"
        self.stream_url            = None
        self.last_frame            = None      # Frame mentah (untuk Gemini)
        self.last_detections       = []
        self.gemini_report: Dict   = {
            "status":  "MENGINISIALISASI",
            "lokasi":  "Mencari data...",
            "narasi":  "Sistem sedang dijalankan."
        }
        self.clients: List[WebSocket] = []
        self.running: bool         = False
        self.yolo_model            = None      # Ultralytics YOLO object
        self.frame_lock            = asyncio.Lock()
        self.yolo_danger: bool     = False
        self.telegram_token: str   = ""
        self.telegram_chat_id: str = ""
        self.polygon_points        = []
        self.djka_webhook_url: str = os.getenv("DJKA_WEBHOOK_URL", "https://httpbin.org/post")
        self.mqtt_broker: str      = MQTT_BROKER
        self.start_time: float     = time.time()
        self.active_objects_count  = 0

app_state = AppState()

# ── FastAPI App ───────────────────────────────────────────────────────────────
app = FastAPI(title="NusaRail Sentinel Backend API v5 (Ultralytics Native)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Model Loader ──────────────────────────────────────────────────────────────
def load_yolo_model():
    """
    Muat model Ultralytics YOLO.
    Urutan prioritas:
      1. Custom model (best_web_optimized.onnx / .pt) jika ada
      2. yolov8s.pt - auto-download dari Ultralytics (COCO 80 kelas, lebih akurat)
      3. yolov8n.pt - fallback nano (paling kecil)
    """
    from ultralytics import YOLO

    # Lokasi pencarian custom model
    custom_paths = [
        Path(__file__).parent / YOLO_MODEL_PATH,
        Path(__file__).parent / "Dataset" / YOLO_MODEL_PATH,
        Path(__file__).parent / "yolov8s.onnx",
        Path(__file__).parent / "yolov8n.onnx",
    ]

    model_path = None
    for p in custom_paths:
        if p.exists():
            model_path = str(p)
            log.info(f"[ModelLoader] Ditemukan model lokal: {p.name}")
            break

    if model_path is None:
        # Auto-download yolov8n.pt dari Ultralytics (COCO 80 kelas, 6MB)
        model_path = "yolov8n.pt"
        log.warning(f"[ModelLoader] Tidak ada model lokal. Menggunakan '{model_path}' (auto-download).")

    try:
        log.info(f"[ModelLoader] Memuat: {model_path}")
        model = YOLO(model_path)

        # Verifikasi: apakah model mendukung kelas kendaraan?
        if hasattr(model, 'names'):
            cls_names = model.names
            has_car   = any('car'   in str(v).lower() for v in cls_names.values())
            has_train = any('train' in str(v).lower() for v in cls_names.values())
            log.info(f"[ModelLoader] Jumlah kelas: {len(cls_names)} | car={has_car} | train={has_train}")

            if not has_car:
                log.warning("[ModelLoader] Model tidak mengenali 'car'! Mengganti ke yolov8n.pt COCO...")
                model = YOLO("yolov8n.pt")
                log.info(f"[ModelLoader] Fallback yolov8n.pt dimuat. Kelas: {len(model.names)}")

        log.info(f"[ModelLoader] ✅ Model siap: {model_path}")
        return model

    except Exception as e:
        log.error(f"[ModelLoader] Gagal memuat {model_path}: {e}")
        try:
            log.warning("[ModelLoader] Mencoba fallback yolov8n.pt...")
            return YOLO("yolov8n.pt")
        except Exception as e2:
            log.error(f"[ModelLoader] Fallback gagal: {e2}")
            return None

# ── Utilities ─────────────────────────────────────────────────────────────────
def generate_text_frame(message: str, bg_color=(20, 20, 20), text_color=(255, 255, 255)) -> np.ndarray:
    frame = np.full((360, 640, 3), bg_color, dtype=np.uint8)
    y0, dy = 160, 35
    for i, line in enumerate(message.split('\n')):
        y = y0 + i * dy
        cv2.putText(frame, line.strip(), (30, y), cv2.FONT_HERSHEY_SIMPLEX, 0.65, text_color, 2, cv2.LINE_AA)
    return frame

async def extract_youtube_url_async(url: str) -> Optional[str]:
    def sync_extract():
        log.info(f"[yt-dlp] Mengekstrak: {url}")
        cookie_path = os.path.join(os.path.dirname(__file__), 'cookies.txt')
        ydl_opts = {
            'format': 'best[height<=480]/worst',
            'socket_timeout': 10,
            'force_ipv4': True,
            'geo_bypass': True,
            'nocheckcertificate': True,
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'extractor_args': {'youtube': {'player_client': ['android', 'web']}}
        }
        if os.path.exists(cookie_path):
            ydl_opts['cookiefile'] = cookie_path
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info and info.get('url'):
                    return info.get('url')
        except Exception as e:
            raise RuntimeError(str(e))
        return None

    try:
        return await asyncio.wait_for(asyncio.to_thread(sync_extract), timeout=20.0)
    except asyncio.TimeoutError:
        return "TIMEOUT"
    except Exception as e:
        log.error(f"[yt-dlp] Error: {e}")
        return "ERROR"

# ── Alert Dispatcher ──────────────────────────────────────────────────────────
class AlertDispatcher:
    def __init__(self):
        self.mqtt_client = mqtt.Client(client_id="NusaRail_Dispatcher")
        try:
            self.mqtt_client.connect(app_state.mqtt_broker, 1883, 60)
            self.mqtt_client.loop_start()
            log.info("[MQTT] Connected")
        except Exception as e:
            log.warning(f"[MQTT] Gagal terhubung: {e}")

    async def dispatch_alert(self, lokasi: str, bahaya: bool, frame: np.ndarray, jenis: str = "Kendaraan Mogok"):
        timestamp    = int(time.time())
        filename     = f"snapshot_{timestamp}.jpg"
        os.makedirs("temp_snapshots", exist_ok=True)
        filepath     = os.path.join("temp_snapshots", filename)
        cv2.imwrite(filepath, frame)

        # Cleanup snapshot lama
        try:
            files = sorted(Path("temp_snapshots").glob("*.jpg"), key=os.path.getmtime)
            if len(files) > 20:
                os.remove(files[0])
        except:
            pass

        snapshot_url = f"/snapshots/{filename}"
        try:
            conn = sqlite3.connect("incidents.db")
            c    = conn.cursor()
            c.execute("INSERT INTO incidents (timestamp, lokasi, jenis, snapshot_url) VALUES (?, ?, ?, ?)",
                      (timestamp, lokasi, jenis, snapshot_url))
            conn.commit()
            conn.close()
        except Exception as e:
            log.error(f"[DB] Gagal simpan: {e}")

        payload = {
            "timestamp":       timestamp,
            "lokasi":          lokasi,
            "tingkat_bahaya":  "KRITIS" if bahaya else "PERINGATAN",
            "snapshot_url":    snapshot_url,
            "jenis":           jenis
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(app_state.djka_webhook_url, json=payload, timeout=5) as resp:
                    pass
        except Exception as e:
            log.error(f"[Webhook] Error: {e}")

        try:
            self.mqtt_client.publish("nusarail/alerts/gate", json.dumps(payload))
        except Exception as e:
            log.error(f"[MQTT] Publish error: {e}")

        if app_state.telegram_token and app_state.telegram_chat_id:
            try:
                caption = f"🚨 PERINGATAN BAHAYA 🚨\nLokasi: {lokasi}\nJenis: {jenis}"
                url     = f"https://api.telegram.org/bot{app_state.telegram_token}/sendPhoto"
                with open(filepath, 'rb') as f:
                    form = aiohttp.FormData()
                    form.add_field('chat_id', app_state.telegram_chat_id)
                    form.add_field('caption', caption)
                    form.add_field('photo', f, filename=filename, content_type='image/jpeg')
                    async with aiohttp.ClientSession() as s:
                        async with s.post(url, data=form, timeout=10) as resp:
                            if resp.status != 200:
                                log.error(f"[Telegram] Error: {await resp.text()}")
            except Exception as e:
                log.error(f"[Telegram] Gagal kirim: {e}")

alert_dispatcher = AlertDispatcher()

# ── Broadcast Gemini ──────────────────────────────────────────────────────────
async def broadcast_gemini_report():
    if not app_state.clients:
        return
    report = app_state.gemini_report.copy()
    if app_state.yolo_danger and "BAHAYA" not in report["status"].upper():
        report["status"] = "BAHAYA KRITIS (Override Visi AI)"
        report["narasi"] = "[Sistem Visi Mendeteksi Konflik]: " + report["narasi"]

    msg = json.dumps(report)

    async def send_to(ws: WebSocket):
        try:
            await ws.send_text(msg)
        except:
            return ws
        return None

    results      = await asyncio.gather(*(send_to(ws) for ws in app_state.clients))
    disconnected = [ws for ws in results if ws is not None]
    for ws in disconnected:
        if ws in app_state.clients:
            app_state.clients.remove(ws)

# ═══════════════════════════════════════════════════════════════════════════════
# ARSITEKTUR SHARED STATE (NON-BLOCKING DROP PATTERN)
#
# Thread 1 - VideoReader : cap.read() + sleep(1/fps) → latest_frame
# Thread 2 - AIWorker    : YOLO.predict(latest_frame) + .plot() → latest_annotated_frame
# Async Generator        : ambil latest_annotated_frame → resize → JPEG 55% → yield
# ═══════════════════════════════════════════════════════════════════════════════
class VideoStreamer:
    """
    Mengelola 2 thread independen dengan shared state (bukan Queue).
    Thread Reader dan AI Worker TIDAK saling memblokir.
    """
    DISPLAY_W = 640
    DISPLAY_H = 360

    def __init__(self, target_url: str, mode: str, yolo_model):
        self.target_url  = target_url
        self.mode        = mode
        self.yolo_model  = yolo_model

        # ── Shared State ──────────────────────────────────────────
        self.latest_frame           = None  # Frame mentah dari Reader
        self.latest_annotated_frame = None  # Frame + bbox dari AI Worker
        self.latest_detections      = []    # List deteksi untuk geo-fencing
        self.original_fps           = 25.0
        self.running                = False

        # Thread-safe locks
        self._frame_lock  = threading.Lock()
        self._annot_lock  = threading.Lock()

        self._reader_thread = None
        self._ai_thread     = None

    # ──────────────────────────────────────────────────────────────
    # THREAD 1: VIDEO READER
    # Hanya membaca cap.read() dan update self.latest_frame.
    # sleep(1/fps) menjaga playback speed MP4 tetap natural.
    # ──────────────────────────────────────────────────────────────
    def _video_reader_thread(self):
        log.info(f"[VideoReader] Mulai: {self.mode} → {self.target_url[:70]}")
        cap = cv2.VideoCapture(self.target_url)

        if not cap.isOpened():
            log.error(f"[VideoReader] Gagal membuka: {self.target_url[:70]}")
            self.running = False
            return

        fps_raw = cap.get(cv2.CAP_PROP_FPS)
        if fps_raw and fps_raw > 0 and not math.isnan(fps_raw):
            self.original_fps = min(fps_raw, 30.0)  # Cap at 30 FPS
        log.info(f"[VideoReader] FPS: {self.original_fps}")

        frame_delay  = 1.0 / self.original_fps
        failed_reads = 0

        while self.running:
            t_start = time.monotonic()
            ret, frame = cap.read()

            if not ret:
                failed_reads += 1
                if self.mode == "upload":
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # Loop video
                    failed_reads = 0
                    continue
                if failed_reads > 20:
                    log.warning("[VideoReader] Stream putus.")
                    break
                time.sleep(0.05)
                continue

            failed_reads = 0

            # Drop pattern: timpa frame lama langsung (non-blocking)
            with self._frame_lock:
                self.latest_frame = frame

            # Sinkronisasi FPS hanya untuk video lokal
            if self.mode == "upload":
                elapsed    = time.monotonic() - t_start
                sleep_time = frame_delay - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)

        cap.release()
        log.info("[VideoReader] Thread selesai, cap.release() dipanggil.")

    # ──────────────────────────────────────────────────────────────
    # THREAD 2: AI WORKER (Ultralytics Native)
    # Menggunakan model.predict() + results[0].plot() secara langsung.
    # TIDAK ada sleep → secepat CPU mampu (3-5 FPS AI).
    # ──────────────────────────────────────────────────────────────
    def _ai_worker_thread(self):
        log.info("[AIWorker] Thread YOLO (Ultralytics Native) dimulai.")
        frame_count = 0

        while self.running:
            # Ambil salinan frame terbaru
            with self._frame_lock:
                if self.latest_frame is None:
                    time.sleep(0.03)
                    continue
                frame_copy = self.latest_frame.copy()

            if self.yolo_model is None:
                log.warning("[AIWorker] Model belum siap, menunggu...")
                time.sleep(1.0)
                continue

            try:
                frame_count += 1

                # ── INFERENSI ULTRALYTICS NATIVE ──────────────────────────
                # classes=[0,2,3,5,6,7]: Person, Car, Motorcycle, Bus, Train, Truck
                # conf=0.25: cukup sensitif untuk mendeteksi kendaraan
                # verbose=False: matikan print output per-frame
                results = self.yolo_model.predict(
                    frame_copy,
                    conf    = YOLO_CONF,
                    iou     = YOLO_IOU,
                    classes = YOLO_CLASSES,
                    verbose = False,
                    imgsz   = 640,
                )

                # ── PLOT NATIVE ULTRALYTICS ────────────────────────────────
                # .plot() menggambar SEMUA bounding box, label, confidence
                # secara otomatis dengan warna yang sudah disetel Ultralytics.
                # TIDAK perlu cv2.rectangle manual lagi!
                annotated_frame = results[0].plot(
                    line_width = 2,
                    font_size  = 0.5,
                )

                # Kumpulkan data deteksi untuk geo-fencing & alert
                detections = []
                if results[0].boxes is not None:
                    for box in results[0].boxes:
                        cls_id   = int(box.cls[0])
                        cls_name = self.yolo_model.names.get(cls_id, str(cls_id))
                        conf_val = float(box.conf[0])
                        xyxy     = box.xyxy[0].cpu().numpy().astype(int).tolist()
                        detections.append({
                            "cls":        cls_name,
                            "conf":       conf_val,
                            "xyxy":       xyxy,
                            "orig_shape": frame_copy.shape[:2],
                        })

                # Debug log setiap 30 frame
                if frame_count % 30 == 1 or len(detections) > 0:
                    log.info(f"[AIWorker] Frame #{frame_count}: {len(detections)} objek | "
                             + ", ".join(f"{d['cls']}({d['conf']:.0%})" for d in detections[:5]))

                # Simpan ke shared state
                with self._annot_lock:
                    self.latest_annotated_frame = annotated_frame
                    self.latest_detections      = detections

                # Sync ke app_state untuk danger detection
                app_state.last_detections       = detections
                app_state.active_objects_count  = len(detections)

            except Exception as e:
                log.error(f"[AIWorker] Error frame #{frame_count}: {e}")
                import traceback; traceback.print_exc()
                time.sleep(0.1)

        log.info(f"[AIWorker] Thread selesai. Total frame diproses: {frame_count}")

    # ── Lifecycle ─────────────────────────────────────────────────
    def start(self):
        self.running        = True
        self._reader_thread = threading.Thread(target=self._video_reader_thread, daemon=True)
        self._ai_thread     = threading.Thread(target=self._ai_worker_thread,    daemon=True)
        self._reader_thread.start()
        self._ai_thread.start()
        log.info("[VideoStreamer] Reader + AI Worker threads dimulai.")

    def stop(self):
        self.running = False
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=3.0)
        if self._ai_thread and self._ai_thread.is_alive():
            self._ai_thread.join(timeout=3.0)
        log.info("[VideoStreamer] Semua thread dihentikan.")

    def is_alive(self) -> bool:
        return self._reader_thread is not None and self._reader_thread.is_alive()

    def get_latest_frame(self):
        """Frame mentah (untuk Gemini analysis)."""
        with self._frame_lock:
            return None if self.latest_frame is None else self.latest_frame.copy()

    def get_latest_annotated_frame(self):
        """Frame dengan bounding box dari Ultralytics .plot()."""
        with self._annot_lock:
            return None if self.latest_annotated_frame is None else self.latest_annotated_frame.copy()

    def get_latest_detections(self):
        with self._annot_lock:
            return list(self.latest_detections)


# ── Singleton Streamer ────────────────────────────────────────────────────────
_current_streamer: Optional[VideoStreamer] = None
_streamer_lock    = threading.Lock()

def get_streamer() -> Optional[VideoStreamer]:
    global _current_streamer
    with _streamer_lock:
        return _current_streamer

def set_streamer(new_streamer: Optional[VideoStreamer]):
    global _current_streamer
    with _streamer_lock:
        if _current_streamer is not None:
            _current_streamer.stop()
        _current_streamer = new_streamer


# ── Management Loop ───────────────────────────────────────────────────────────
async def yolo_inference_loop():
    """Memantau perubahan source video dan mengelola lifecycle VideoStreamer."""
    log.info("[Manager] Memuat model YOLO (Ultralytics Native)...")
    app_state.yolo_model = load_yolo_model()

    if app_state.yolo_model is None:
        log.error("[Manager] Model gagal dimuat! Stream AI tidak akan berjalan.")
    else:
        log.info("[Manager] Model YOLO siap.")

    app_state.running  = True
    current_mode       = None
    current_target     = None

    while app_state.running:
        mode   = app_state.source_mode
        target = app_state.target_url

        if mode != current_mode or target != current_target:
            log.info(f"[Manager] Source berubah → {mode}: {target[:60]}")
            set_streamer(None)
            current_mode   = mode
            current_target = target
            resolved_url   = target

            if mode == "youtube":
                async with app_state.frame_lock:
                    app_state.last_frame = generate_text_frame(
                        "INITIALIZING...\nExtracting YouTube URL...")
                url_result = await extract_youtube_url_async(target)

                if url_result in ("TIMEOUT", "ERROR", None):
                    async with app_state.frame_lock:
                        app_state.last_frame = generate_text_frame(
                            "ERROR: YouTube Blocked / Invalid URL.\nGanti URL dan coba lagi.",
                            bg_color=(0, 0, 100))
                    await asyncio.sleep(5)
                    current_mode = None
                    continue
                resolved_url = url_result

            elif mode == "rtsp":
                async with app_state.frame_lock:
                    app_state.last_frame = generate_text_frame("Menghubungkan RTSP CCTV...")

            elif mode == "upload":
                async with app_state.frame_lock:
                    app_state.last_frame = generate_text_frame("Memuat video lokal...")

            new_streamer = VideoStreamer(resolved_url, mode, app_state.yolo_model)
            new_streamer.start()
            set_streamer(new_streamer)
            log.info(f"[Manager] VideoStreamer baru aktif: {mode}")

        # Monitor danger dari deteksi
        streamer = get_streamer()
        if streamer and streamer.is_alive():
            detections = streamer.get_latest_detections()
            H, W       = 360, 640
            frame_ref  = streamer.get_latest_frame()
            if frame_ref is not None:
                H, W = frame_ref.shape[:2]

            polygon_abs = []
            if len(app_state.polygon_points) >= 3:
                for pt in app_state.polygon_points:
                    polygon_abs.append([int(pt['x'] * W), int(pt['y'] * H)])
                polygon_abs = np.array(polygon_abs, np.int32)

            yolo_danger = False
            for det in detections:
                x1, y1, x2, y2 = det['xyxy']
                cx = (x1 + x2) / 2
                cy = (y1 + y2) / 2
                inside = True
                if len(polygon_abs) >= 3:
                    d = cv2.pointPolygonTest(polygon_abs, (float(cx), float(cy)), False)
                    if d < 0:
                        inside = False
                if inside and det['cls'] == 'train':
                    yolo_danger = True

            app_state.yolo_danger = yolo_danger

        await asyncio.sleep(1.0)

    set_streamer(None)


# ── MJPEG Async Generator ─────────────────────────────────────────────────────
async def generate_mjpeg_stream():
    """
    Async generator MJPEG.
    Tugas TUNGGAL:
      1. Ambil latest_annotated_frame dari VideoStreamer (sudah ada bbox dari .plot())
      2. Resize ke 640x360
      3. Encode JPEG 55%
      4. yield ke frontend ~30 FPS

    TIDAK ada manual cv2.rectangle di sini → semuanya sudah dilakukan .plot().
    """
    DISPLAY_W, DISPLAY_H = 640, 360

    # Frame inisialisasi
    init_f = generate_text_frame("NusaRail AI Engine\nMenginisialisasi sistem...", bg_color=(10, 15, 30))
    ret, buf = cv2.imencode('.jpg', init_f, [cv2.IMWRITE_JPEG_QUALITY, 55])
    if ret:
        yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buf.tobytes() + b'\r\n'

    while app_state.running:
        streamer = get_streamer()

        # ── Tidak ada streamer aktif ──────────────────────────────
        if streamer is None or not streamer.is_alive():
            wait_f = generate_text_frame("Menghubungkan ke sumber video...", bg_color=(15, 20, 40))
            ret, buf = cv2.imencode('.jpg', wait_f, [cv2.IMWRITE_JPEG_QUALITY, 55])
            if ret:
                yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buf.tobytes() + b'\r\n'
            await asyncio.sleep(0.5)
            continue

        # ── Ambil frame yang SUDAH dianotasi oleh .plot() ─────────
        frame = streamer.get_latest_annotated_frame()

        if frame is None:
            # AI Worker belum selesai inference pertama, tampilkan frame mentah
            frame = streamer.get_latest_frame()
            if frame is None:
                await asyncio.sleep(0.05)
                continue
            # Tambahkan overlay "AI Loading..."
            cv2.putText(frame, "AI Loading...", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2, cv2.LINE_AA)

        # ── Resize ke display 640x360 ─────────────────────────────
        frame = cv2.resize(frame, (DISPLAY_W, DISPLAY_H))
        H, W  = DISPLAY_H, DISPLAY_W

        # ── Geo-Fence Overlay (jika ada polygon) ──────────────────
        if len(app_state.polygon_points) >= 3:
            pts = [[int(pt['x'] * W), int(pt['y'] * H)] for pt in app_state.polygon_points]
            pts = np.array(pts, np.int32)
            cv2.polylines(frame, [pts], True, (0, 0, 255), 2)
            overlay = frame.copy()
            cv2.fillPoly(overlay, [pts], (0, 0, 255))
            cv2.addWeighted(overlay, 0.15, frame, 0.85, 0, frame)
            cv2.putText(frame, "DANGER ZONE", pts[0], cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, (0, 0, 255), 2, cv2.LINE_AA)

        # ── Overlay info ringkas ───────────────────────────────────
        det_count  = len(streamer.get_latest_detections())
        info_color = (0, 255, 100) if det_count > 0 else (180, 180, 180)
        ts         = time.strftime("%Y-%m-%d %H:%M:%S")

        cv2.putText(frame, f"AI: {det_count} objek", (8, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(frame, f"AI: {det_count} objek", (8, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, info_color, 1, cv2.LINE_AA)

        cv2.putText(frame, f"NusaRail | {ts}", (5, H - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(frame, f"NusaRail | {ts}", (5, H - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1, cv2.LINE_AA)

        # ── Encode JPEG 55% dan yield ─────────────────────────────
        ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 55])
        if ret:
            yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n'

        # ~30 FPS output
        await asyncio.sleep(0.033)


# ── Gemini Analysis Loop ──────────────────────────────────────────────────────
async def gemini_analysis_loop():
    log.info("[Gemini] Analysis Loop started")
    from google import genai
    from google.genai import types
    from pydantic import BaseModel as PM, Field

    class GeminiSchema(PM):
        status: str = Field(description="Aman atau BAHAYA")
        lokasi: str = Field(description="Nama lokasi perlintasan")
        narasi: str = Field(description="Laporan analisis situasi")
        rawan_injeksi: bool = Field(description="False")

    client  = None
    backoff = 10
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        log.error(f"[Gemini] Gagal init: {e}")

    prompt = (
        "Analisis gambar rekaman perlintasan kereta ini secara teliti. "
        "Deteksi kondisi bahaya: kendaraan mogok di rel, orang di jalur kereta. "
        "Kembalikan data sesuai skema JSON."
    )

    while app_state.running:
        streamer = get_streamer()
        frame_to_process = None
        if streamer and streamer.is_alive():
            frame_to_process = streamer.get_latest_frame()
        else:
            async with app_state.frame_lock:
                if app_state.last_frame is not None:
                    frame_to_process = app_state.last_frame.copy()

        if client and frame_to_process is not None:
            try:
                success, buf = cv2.imencode(".jpg", frame_to_process, [cv2.IMWRITE_JPEG_QUALITY, 70])
                if success:
                    def call_gemini():
                        return client.models.generate_content(
                            model="gemini-2.0-flash",
                            contents=[
                                types.Part.from_bytes(data=buf.tobytes(), mime_type="image/jpeg"),
                                prompt
                            ],
                            config=types.GenerateContentConfig(
                                response_mime_type="application/json",
                                response_schema=GeminiSchema,
                                temperature=0.1
                            )
                        )

                    response = await asyncio.wait_for(asyncio.to_thread(call_gemini), timeout=30.0)
                    text     = response.text.strip()
                    try:
                        parsed = json.loads(text)
                        app_state.gemini_report = {
                            "status":    parsed.get("status", "AMAN"),
                            "lokasi":    parsed.get("lokasi", "Unknown"),
                            "narasi":    parsed.get("narasi", ""),
                            "timestamp": time.time()
                        }
                    except json.JSONDecodeError:
                        app_state.gemini_report["narasi"] = "Error parsing JSON dari AI."

                    backoff = 10
                    await broadcast_gemini_report()

            except asyncio.TimeoutError:
                log.error("[Gemini] Timeout >30s")
                app_state.gemini_report["narasi"] = "Koneksi ke AI Cloud timeout."
            except Exception as e:
                err = str(e)
                log.error(f"[Gemini] Error: {e}")
                if "429" in err or "RESOURCE_EXHAUSTED" in err:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 120)

        await asyncio.sleep(GEMINI_INTERVAL)


# ── FastAPI Startup ───────────────────────────────────────────────────────────
os.makedirs("temp", exist_ok=True)
os.makedirs("temp_snapshots", exist_ok=True)

app.mount("/snapshots", StaticFiles(directory="temp_snapshots"), name="snapshots")

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(yolo_inference_loop())
    asyncio.create_task(gemini_analysis_loop())

@app.on_event("shutdown")
async def shutdown_event():
    app_state.running = False

# ── Endpoints ─────────────────────────────────────────────────────────────────
@app.get("/api/health")
def health_check():
    streamer = get_streamer()
    return {
        "status":         "ok",
        "running":        app_state.running,
        "model_loaded":   app_state.yolo_model is not None,
        "streamer_alive": streamer is not None and streamer.is_alive(),
        "djka_connected": True,
        "mqtt_connected": alert_dispatcher.mqtt_client.is_connected(),
    }

@app.get("/api/debug/model")
def debug_model():
    """Diagnosa model YOLO yang aktif."""
    model = app_state.yolo_model
    if model is None:
        return {"status": "ERROR", "message": "Model belum dimuat."}
    try:
        names = model.names if hasattr(model, 'names') else {}
        target_names = {str(i): names.get(i, "N/A") for i in YOLO_CLASSES}
        return {
            "status":           "OK",
            "model_type":       str(type(model).__name__),
            "total_classes":    len(names),
            "target_classes":   target_names,
            "conf_threshold":   YOLO_CONF,
            "iou_threshold":    YOLO_IOU,
            "classes_filter":   YOLO_CLASSES,
            "last_detections":  len(app_state.last_detections),
            "active_objects":   app_state.active_objects_count,
            "streamer_alive":   get_streamer() is not None and get_streamer().is_alive(),
            "class_check":      "✅ COCO 80 kelas" if len(names) >= 80 else f"⚠️ Hanya {len(names)} kelas",
        }
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}

class SetUrlRequest(BaseModel):
    youtube_url: str   = None
    rtsp_url: str      = None
    mode: str          = "youtube"

@app.post("/api/set_url")
def set_url(req: SetUrlRequest):
    if req.mode == "youtube" and req.youtube_url:
        url = req.youtube_url.strip()
        if not url.startswith("http"):
            url = "https://www.youtube.com/watch?v=q7lvnYVuqNY"
        app_state.target_url  = url
        app_state.source_mode = "youtube"
    elif req.mode == "rtsp" and req.rtsp_url:
        app_state.target_url  = req.rtsp_url
        app_state.source_mode = "rtsp"
    return {"status": "success", "mode": app_state.source_mode, "target_url": app_state.target_url}

@app.post("/api/upload")
async def upload_video(file: UploadFile = File(...)):
    for old in Path("temp").glob("*.*"):
        try:
            os.remove(old)
        except:
            pass
    file_path = f"temp/{file.filename}"
    with open(file_path, "wb") as buf:
        shutil.copyfileobj(file.file, buf)
    app_state.target_url  = file_path
    app_state.source_mode = "upload"
    return {"status": "success", "filename": file.filename}

class SetTelegramRequest(BaseModel):
    token: str
    chat_id: str

@app.post("/api/set_telegram")
def set_telegram(req: SetTelegramRequest):
    app_state.telegram_token   = req.token
    app_state.telegram_chat_id = req.chat_id
    return {"status": "success"}

class PolygonPointRequest(BaseModel):
    x: float
    y: float

class SetPolygonRequest(BaseModel):
    points: List[PolygonPointRequest]

@app.post("/api/set_polygon")
def set_polygon(req: SetPolygonRequest):
    app_state.polygon_points = [{"x": p.x, "y": p.y} for p in req.points]
    return {"status": "success", "points_count": len(app_state.polygon_points)}

class SetIntegrationRequest(BaseModel):
    djka_webhook: str
    mqtt_broker: str

@app.post("/api/set_integrations")
def set_integrations(req: SetIntegrationRequest):
    app_state.djka_webhook_url = req.djka_webhook
    app_state.mqtt_broker      = req.mqtt_broker
    try:
        alert_dispatcher.mqtt_client.disconnect()
        alert_dispatcher.mqtt_client.connect(app_state.mqtt_broker, 1883, 60)
    except Exception as e:
        log.error(f"[MQTT] Reconnect Error: {e}")
    return {"status": "success"}

@app.get("/api/incidents")
def get_incidents():
    try:
        conn = sqlite3.connect("incidents.db")
        conn.row_factory = sqlite3.Row
        c    = conn.cursor()
        c.execute("SELECT * FROM incidents ORDER BY timestamp DESC LIMIT 50")
        rows = c.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/status")
def get_status():
    return {
        "danger":          app_state.yolo_danger,
        "uptime":          int(time.time() - app_state.start_time),
        "active_objects":  app_state.active_objects_count,
    }

@app.get("/api/export_csv")
def export_csv():
    try:
        conn = sqlite3.connect("incidents.db")
        c    = conn.cursor()
        c.execute("SELECT timestamp, lokasi, jenis, snapshot_url FROM incidents ORDER BY timestamp DESC")
        rows = c.fetchall()
        conn.close()

        import io as _io, csv as _csv
        output = _io.StringIO()
        writer = _csv.writer(output)
        writer.writerow(["Timestamp", "Lokasi", "Jenis Insiden", "Snapshot URL"])
        for row in rows:
            ts_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(row[0]))
            writer.writerow([ts_str, row[1], row[2], row[3]])

        from fastapi.responses import Response
        return Response(
            content     = output.getvalue(),
            media_type  = "text/csv",
            headers     = {"Content-Disposition": "attachment; filename=nusarail_incidents.csv"}
        )
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/stream")
async def video_stream():
    return StreamingResponse(
        generate_mjpeg_stream(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

@app.websocket("/api/ws/gemini")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    app_state.clients.append(websocket)
    try:
        await websocket.send_text(json.dumps(app_state.gemini_report))
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in app_state.clients:
            app_state.clients.remove(websocket)
