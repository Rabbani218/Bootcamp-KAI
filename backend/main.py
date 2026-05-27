"""
NusaRail Vision System — Backend v6
====================================
Arsitektur:
  Thread 1 (VideoReader)   : cap.read() + sleep(1/fps) → latest_frame
  Thread 2 (AIWorker)      : model.track(persist=True) + .plot() → latest_annotated_frame
                             + Stationary Vehicle Detection (ByteTrack ID)
  Async Task (Manager)     : Memantau source, mengelola VideoStreamer lifecycle
  Async Task (Gemini)      : Setiap 10 detik, analisis frame via Gemini 2.0 Flash
                             → broadcast ke semua WebSocket clients
  Async Generator (MJPEG)  : 30 FPS strict-paced stream ke browser
"""
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
import httpx
import threading

last_emergency_time = 0

def trigger_djka_emergency_brake(snapshot_frame):
    global last_emergency_time
    now = time.time()
    
    # Anti-Spam (Cooldown): Hanya kirim HTTP Request 1 kali setiap 60 detik per insiden
    if now - last_emergency_time < 60:
        return
        
    last_emergency_time = now
    log.error("🚨 [DISPATCHER] BAHAYA KRITIS! MENGIRIM SINYAL REM DARURAT KE KRL!")
    
    payload = {
        "status": "HALT",
        "reason": "OBSTACLE_ON_TRACK",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "location": "Perlintasan JPL 18 Kalibata"
    }
    
    try:
        # Simulasi pengiriman Webhook sistem operasional DJKA / KAI
        response = httpx.post("https://webhook.site/nusarail-emergency", json=payload, timeout=5.0)
        log.info(f"[DISPATCHER] Respon DJKA: {response.status_code}")
    except Exception as e:
        log.error(f"[DISPATCHER] Gagal mengirim sinyal darurat ke server pusat: {e}")

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
GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY", "AIzaSyCCNLkAMh6VmZuaoG1LuqkAa9O0cMA-hVA")
GEMINI_INTERVAL = 10      # Detik antar analisis Gemini
MQTT_BROKER     = os.getenv("MQTT_BROKER", "test.mosquitto.org")

# YOLO Config
YOLO_CLASSES    = [0, 2, 3, 5, 6, 7]  # person, car, motorcycle, bus, train, truck
YOLO_CONF       = 0.15                 # Sensitif untuk malam/buram
YOLO_IOU        = 0.45

# Pre-scaling: lock resolusi sebelum inference agar bbox 100% presisi
INFER_W = 640
INFER_H = 480

# Stationary Vehicle Detection Config
STATIONARY_SECONDS   = 5.0   # Detik kendaraan diam = bahaya
STATIONARY_PX_DELTA  = 20    # Pixel centroid bergerak < ini = dianggap diam
VEHICLE_CLASSES      = {'car', 'truck', 'bus', 'motorcycle'}

# ── AppState ──────────────────────────────────────────────────────────────────
class AppState:
    def __init__(self):
        self.source_mode: str       = "youtube"
        self.target_url: str        = "https://www.youtube.com/watch?v=q7lvnYVuqNY"
        self.last_frame             = None
        self.last_detections        = []
        self.gemini_report: Dict    = {
            "status":  "MENGINISIALISASI",
            "lokasi":  "Mencari data...",
            "narasi":  "Sistem sedang dijalankan."
        }
        self.clients: List[WebSocket] = []
        self.running: bool          = False
        self.yolo_model             = None
        self.frame_lock             = asyncio.Lock()
        self.yolo_danger: bool      = False
        self.telegram_token: str    = ""
        self.telegram_chat_id: str  = ""
        self.polygon_points         = []
        self.djka_webhook_url: str  = os.getenv("DJKA_WEBHOOK_URL", "https://httpbin.org/post")
        self.mqtt_broker: str       = MQTT_BROKER
        self.start_time: float      = time.time()
        self.active_objects_count   = 0
        # Stationary tracking (thread-safe via threading.Lock)
        self.stationary_alert: bool = False

app_state = AppState()

# ── FastAPI ───────────────────────────────────────────────────────────────────
app = FastAPI(title="NusaRail Sentinel Backend v6")

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
    Load Ultralytics YOLO model.
    Prioritas: custom model lokal → yolov8n.pt (auto-download COCO 80 kelas).
    """
    from ultralytics import YOLO

    search_paths = [
        Path(__file__).parent / os.getenv("YOLO_MODEL", "best_web_optimized.onnx"),
        Path(__file__).parent / "Dataset" / os.getenv("YOLO_MODEL", "best_web_optimized.onnx"),
        Path(__file__).parent / "yolov8s.onnx",
        Path(__file__).parent / "yolov8n.onnx",
    ]

    model_path = None
    for p in search_paths:
        if p.exists():
            model_path = str(p)
            log.info(f"[ModelLoader] Model lokal ditemukan: {p.name}")
            break

    if model_path is None:
        model_path = "yolov8n.pt"
        log.warning(f"[ModelLoader] Tidak ada model lokal → auto-download {model_path}")

    try:
        model = YOLO(model_path)
        names = model.names if hasattr(model, 'names') else {}
        has_car   = any('car'   in str(v).lower() for v in names.values())
        has_train = any('train' in str(v).lower() for v in names.values())
        log.info(f"[ModelLoader] ✅ {model_path} | Kelas: {len(names)} | car={has_car} | train={has_train}")

        if not has_car:
            log.warning("[ModelLoader] Model tidak mengenali 'car', ganti ke yolov8n.pt COCO...")
            model = YOLO("yolov8n.pt")
            log.info(f"[ModelLoader] Fallback yolov8n.pt: {len(model.names)} kelas")

        return model
    except Exception as e:
        log.error(f"[ModelLoader] Gagal muat {model_path}: {e}")
        try:
            model = YOLO("yolov8n.pt")
            log.info("[ModelLoader] Fallback yolov8n.pt berhasil.")
            return model
        except Exception as e2:
            log.error(f"[ModelLoader] Fallback juga gagal: {e2}")
            return None

# ── Utility ───────────────────────────────────────────────────────────────────
def generate_text_frame(message: str, bg_color=(20, 20, 20), text_color=(255, 255, 255)) -> np.ndarray:
    frame = np.full((360, 640, 3), bg_color, dtype=np.uint8)
    for i, line in enumerate(message.split('\n')):
        y = 160 + i * 35
        cv2.putText(frame, line.strip(), (30, y), cv2.FONT_HERSHEY_SIMPLEX, 0.65, text_color, 2, cv2.LINE_AA)
    return frame

async def extract_youtube_url_async(url: str) -> Optional[str]:
    def sync_extract():
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
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get('url') if info else None

    try:
        return await asyncio.wait_for(asyncio.to_thread(sync_extract), timeout=20.0)
    except asyncio.TimeoutError:
        return "TIMEOUT"
    except Exception as e:
        log.error(f"[yt-dlp] Error: {e}")
        return "ERROR"

# ── WebSocket Broadcaster ─────────────────────────────────────────────────────
async def broadcast_ws(payload: dict):
    """
    Broadcast JSON ke semua WebSocket clients yang terhubung.
    Ini adalah fungsi KUNCI untuk menghidupkan Gemini Panel di frontend.
    """
    if not app_state.clients:
        return

    # Override status jika YOLO mendeteksi bahaya kendaraan terjebak
    if app_state.stationary_alert:
        payload = payload.copy()
        payload["status"] = "⚠️ BAHAYA: KENDARAAN TERJEBAK DI REL"

    msg = json.dumps(payload, ensure_ascii=False)
    log.info(f"[WS Broadcast] → {len(app_state.clients)} klien | status={payload.get('status')}")

    disconnected = []
    for ws in list(app_state.clients):
        try:
            await ws.send_text(msg)
        except Exception:
            disconnected.append(ws)

    for ws in disconnected:
        if ws in app_state.clients:
            app_state.clients.remove(ws)

# ── Alert Dispatcher ──────────────────────────────────────────────────────────
class AlertDispatcher:
    def __init__(self):
        self.mqtt_client = mqtt.Client(client_id="NusaRail_Dispatcher")
        try:
            self.mqtt_client.connect(app_state.mqtt_broker, 1883, 60)
            self.mqtt_client.loop_start()
        except Exception as e:
            log.warning(f"[MQTT] Gagal terhubung: {e}")

    async def dispatch_alert(self, lokasi: str, bahaya: bool, frame: np.ndarray, jenis: str = "Kendaraan Terjebak"):
        timestamp   = int(time.time())
        filename    = f"snapshot_{timestamp}.jpg"
        os.makedirs("temp_snapshots", exist_ok=True)
        filepath    = os.path.join("temp_snapshots", filename)
        cv2.imwrite(filepath, frame)

        try:
            files = sorted(Path("temp_snapshots").glob("*.jpg"), key=os.path.getmtime)
            if len(files) > 20:
                os.remove(files[0])
        except:
            pass

        snapshot_url = f"/snapshots/{filename}"
        try:
            conn = sqlite3.connect("incidents.db")
            c = conn.cursor()
            c.execute("INSERT INTO incidents (timestamp, lokasi, jenis, snapshot_url) VALUES (?, ?, ?, ?)",
                      (timestamp, lokasi, jenis, snapshot_url))
            conn.commit()
            conn.close()
        except Exception as e:
            log.error(f"[DB] {e}")

        payload = {"timestamp": timestamp, "lokasi": lokasi,
                   "tingkat_bahaya": "KRITIS" if bahaya else "PERINGATAN",
                   "snapshot_url": snapshot_url, "jenis": jenis}

        try:
            async with aiohttp.ClientSession() as s:
                await s.post(app_state.djka_webhook_url, json=payload, timeout=aiohttp.ClientTimeout(total=5))
        except:
            pass

        try:
            self.mqtt_client.publish("nusarail/alerts/gate", json.dumps(payload))
        except:
            pass

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
                        await s.post(url, data=form, timeout=aiohttp.ClientTimeout(total=10))
            except Exception as e:
                log.error(f"[Telegram] {e}")

alert_dispatcher = AlertDispatcher()

# ═══════════════════════════════════════════════════════════════════════════════
# ARSITEKTUR SHARED STATE (NON-BLOCKING DROP PATTERN)
#
# Thread 1 - VideoReader  : cap.read() + sleep(1/fps) → latest_frame
# Thread 2 - AI Worker    : model.track() + .plot() + Stationary Logic
#                         → latest_annotated_frame + latest_detections
# Async Generator (MJPEG) : ambil annotated_frame → resize → JPEG → yield
# Async Task (Gemini)     : setiap 10 detik, analisis frame → broadcast WS
# ═══════════════════════════════════════════════════════════════════════════════
class VideoStreamer:
    DISPLAY_W = 640
    DISPLAY_H = 360

    def __init__(self, target_url: str, mode: str, yolo_model):
        self.target_url  = target_url
        self.mode        = mode
        self.yolo_model  = yolo_model

        self.latest_frame           = None
        self.latest_annotated_frame = None
        self.latest_detections      = []
        self.original_fps           = 25.0
        self.running                = False

        self._frame_lock  = threading.Lock()
        self._annot_lock  = threading.Lock()

        self._reader_thread = None
        self._ai_thread     = None

        # ── Stationary Vehicle Tracker ────────────────────────────
        # Format: {track_id: {"centroid": (cx, cy), "first_seen": timestamp, "last_cx": cx, "last_cy": cy}}
        self._tracked_vehicles: Dict[int, dict] = {}
        self._track_lock = threading.Lock()

    # ──────────────────────────────────────────────────────────────
    # THREAD 1: VIDEO READER
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
            self.original_fps = min(fps_raw, 30.0)
        log.info(f"[VideoReader] FPS: {self.original_fps}")

        frame_delay  = 1.0 / self.original_fps
        failed_reads = 0

        while self.running:
            t_start = time.monotonic()
            ret, frame = cap.read()

            if not ret:
                failed_reads += 1
                if self.mode == "upload":
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    failed_reads = 0
                    continue
                if failed_reads > 20:
                    log.warning("[VideoReader] Stream putus.")
                    break
                time.sleep(0.05)
                continue

            failed_reads = 0

            with self._frame_lock:
                self.latest_frame = frame  # Non-blocking drop

            if self.mode == "upload":
                elapsed    = time.monotonic() - t_start
                sleep_time = frame_delay - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)

        cap.release()
        log.info("[VideoReader] Thread selesai.")

    # ──────────────────────────────────────────────────────────────
    # THREAD 2: AI WORKER (YOLO Tracking + Stationary Detection)
    # ──────────────────────────────────────────────────────────────
    def _ai_worker_thread(self):
        """
        Menggunakan model.track(persist=True, tracker='bytetrack.yaml') untuk
        melacak kendaraan lintas frame dengan Track ID stabil.

        Stationary Logic:
          - Simpan centroid setiap Track ID saat pertama terlihat
          - Jika centroid tidak bergerak > STATIONARY_PX_DELTA dalam STATIONARY_SECONDS
          - → tandai kendaraan sebagai "TERJEBAK", gambar kotak MERAH TEBAL
        """
        log.info("[AIWorker] Thread YOLO Tracking (ByteTrack) dimulai.")
        frame_count = 0

        while self.running:
            # Drop-Frame: selalu ambil frame TERBARU
            with self._frame_lock:
                if self.latest_frame is None:
                    time.sleep(0.03)
                    continue
                frame_copy = self.latest_frame.copy()

            if self.yolo_model is None:
                time.sleep(1.0)
                continue

            try:
                frame_count += 1

                # ── PRE-SCALING (kunci presisi bbox) ──────────────────────
                infer_frame = cv2.resize(frame_copy, (INFER_W, INFER_H))

                # ── YOLO TRACKING (ByteTrack, persist=True) ───────────────
                # model.track() mempertahankan Track ID lintas frame → KUNCI
                # untuk Stationary Detection yang akurat.
                # Jika tracker file tidak tersedia, fallback ke predict.
                try:
                    results = self.yolo_model.track(
                        source    = infer_frame,
                        conf      = YOLO_CONF,
                        iou       = YOLO_IOU,
                        classes   = YOLO_CLASSES,
                        verbose   = False,
                        imgsz     = 640,
                        persist   = True,      # Pertahankan ID lintas frame
                        tracker   = "bytetrack.yaml",
                    )
                except Exception as tracker_err:
                    # Fallback ke predict jika ByteTrack tidak tersedia
                    log.warning(f"[AIWorker] ByteTrack error ({tracker_err}), fallback ke predict")
                    results = self.yolo_model.predict(
                        source  = infer_frame,
                        conf    = YOLO_CONF,
                        iou     = YOLO_IOU,
                        classes = YOLO_CLASSES,
                        verbose = False,
                        imgsz   = 640,
                    )

                # ── STATIONARY VEHICLE DETECTION ──────────────────────────
                now         = time.time()
                detections  = []
                stationary_ids = set()
                is_car_stuck = False
                is_train_incoming = False

                if results[0].boxes is not None and len(results[0].boxes) > 0:
                    for box in results[0].boxes:
                        cls_id   = int(box.cls[0])
                        cls_name = self.yolo_model.names.get(cls_id, str(cls_id))
                        conf_val = float(box.conf[0])
                        xyxy     = [int(v) for v in box.xyxy[0].cpu().tolist()]

                        cx = int((xyxy[0] + xyxy[2]) / 2)
                        cy = int((xyxy[1] + xyxy[3]) / 2)

                        # 1. Deteksi Kereta Datang (Incoming Train)
                        if cls_name == 'train' and conf_val > 0.15:
                            is_train_incoming = True

                        # 2. Proteksi NoneType pada Track ID
                        track_id = None
                        if box.id is not None:
                            track_id = int(box.id[0])

                        mogok = False

                        # 3. Logika Kendaraan Terjebak (Hanya jika ID tersedia)
                        if cls_name in VEHICLE_CLASSES and track_id is not None:
                            with self._track_lock:
                                if track_id not in self._tracked_vehicles:
                                    self._tracked_vehicles[track_id] = {
                                        "cx": cx, "cy": cy,
                                        "first_seen": now, "last_moved": now
                                    }
                                else:
                                    vh = self._tracked_vehicles[track_id]
                                    dist = math.hypot(cx - vh["cx"], cy - vh["cy"])
                                    
                                    if dist > STATIONARY_PX_DELTA:
                                        vh["cx"] = cx
                                        vh["cy"] = cy
                                        vh["last_moved"] = now
                                    else:
                                        diam_durasi = now - vh["last_moved"]
                                        if diam_durasi >= STATIONARY_SECONDS:
                                            mogok = True
                                            is_car_stuck = True
                                            stationary_ids.add(track_id)
                                            log.warning(f"[Stationary] ⚠️ Track ID {track_id} ({cls_name}) TERJEBAK!")

                        # 4. Rendering Visual Bounding Box (Aman untuk objek tanpa ID)
                        color = (0, 0, 255) if mogok else (0, 255, 0)
                        label = f"{cls_name} {'TERJEBAK' if mogok else (track_id or '')}"
                        cv2.rectangle(frame_copy, (xyxy[0], xyxy[1]), (xyxy[2], xyxy[3]), color, 2)
                        cv2.putText(frame_copy, label, (xyxy[0], xyxy[1] - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
                        
                        detections.append({
                            "cls":        cls_name,
                            "conf":       conf_val,
                            "xyxy":       xyxy,
                            "track_id":   track_id,
                            "mogok":      mogok,
                            "orig_shape": (INFER_H, INFER_W),
                        })

                # Bersihkan track ID yang tidak terlihat lagi (>10 detik)
                with self._track_lock:
                    stale = [tid for tid, v in self._tracked_vehicles.items()
                             if now - v.get("last_moved", 0) > 30.0]
                    for tid in stale:
                        del self._tracked_vehicles[tid]

                # Update stationary alert global
                app_state.stationary_alert = len(stationary_ids) > 0

                # 5. Eksekusi Fatal Hazard (Kereta Datang + Mobil Mogok)
                if is_car_stuck and is_train_incoming:
                    app_state.stationary_alert = True
                    # Tembak fungsi dispatcher API menggunakan thread terpisah agar video tidak tersendat
                    threading.Thread(target=trigger_djka_emergency_brake, args=(frame_copy.copy(),), daemon=True).start()
                    
                    # Teks Merah Berkedip di OpenCV (Flash Effect)
                    if int(time.time() * 4) % 2 == 0:
                        cv2.putText(frame_copy, "AUTO-BRAKE SIGNAL SENT TO KRL!", (50, 100),
                                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 4, cv2.LINE_AA)

                # ── PLOT NATIVE + Overlay Kendaraan Terjebak ──────────────
                # .plot() menggambar semua bbox secara otomatis
                annotated_frame = results[0].plot(line_width=2, font_size=0.5)

                # Override: gambar kotak MERAH TEBAL untuk kendaraan terjebak
                for det in detections:
                    if det["mogok"]:
                        x1, y1, x2, y2 = det["xyxy"]
                        # Kotak merah tebal
                        cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), (0, 0, 255), 4)
                        # Label peringatan
                        label = f"⚠ TERJEBAK! {det['cls'].upper()}"
                        cv2.rectangle(annotated_frame, (x1, max(0, y1 - 30)), (x1 + 200, y1), (0, 0, 200), -1)
                        cv2.putText(annotated_frame, label, (x1 + 3, max(20, y1 - 8)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2, cv2.LINE_AA)

                # Debug log
                if frame_count % 30 == 1 or len(detections) > 0:
                    objs = ", ".join(
                        f"{d['cls']}(ID:{d['track_id']}{'⚠' if d['mogok'] else ''})"
                        for d in detections[:5]
                    )
                    log.info(f"[AIWorker] Frame #{frame_count} | {len(detections)} objek | {objs}")

                # ── Simpan ke Shared State ─────────────────────────────────
                with self._annot_lock:
                    self.latest_annotated_frame = annotated_frame
                    self.latest_detections      = detections

                app_state.last_detections      = detections
                app_state.active_objects_count = len(detections)

            except Exception as e:
                log.error(f"[AIWorker] Error frame #{frame_count}: {e}")
                import traceback; traceback.print_exc()
                time.sleep(0.1)

        log.info(f"[AIWorker] Thread selesai. Total frame: {frame_count}")

    # ── Lifecycle ─────────────────────────────────────────────────
    def start(self):
        self.running        = True
        self._reader_thread = threading.Thread(target=self._video_reader_thread, daemon=True)
        self._ai_thread     = threading.Thread(target=self._ai_worker_thread,    daemon=True)
        self._reader_thread.start()
        self._ai_thread.start()
        log.info("[VideoStreamer] Reader + AI Worker dimulai.")

    def stop(self):
        self.running = False
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=3.0)
        if self._ai_thread and self._ai_thread.is_alive():
            self._ai_thread.join(timeout=3.0)

    def is_alive(self) -> bool:
        return self._reader_thread is not None and self._reader_thread.is_alive()

    def get_latest_frame(self):
        with self._frame_lock:
            return None if self.latest_frame is None else self.latest_frame.copy()

    def get_latest_annotated_frame(self):
        with self._annot_lock:
            return None if self.latest_annotated_frame is None else self.latest_annotated_frame.copy()

    def get_latest_detections(self):
        with self._annot_lock:
            return list(self.latest_detections)


# ── Singleton Streamer ────────────────────────────────────────────────────────
_current_streamer: Optional[VideoStreamer] = None
_streamer_lock = threading.Lock()

def get_streamer() -> Optional[VideoStreamer]:
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
    """
    Async background task: Memuat model YOLO, memantau perubahan source video,
    dan mengelola lifecycle VideoStreamer.
    """
    log.info("[Manager] Memuat model YOLO...")
    app_state.yolo_model = load_yolo_model()
    app_state.running    = True

    current_mode   = None
    current_target = None

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
                url_result = await extract_youtube_url_async(target)
                if url_result in ("TIMEOUT", "ERROR", None):
                    log.error(f"[Manager] Gagal ekstrak YouTube URL: {url_result}")
                    await asyncio.sleep(5)
                    current_mode = None
                    continue
                resolved_url = url_result

            new_streamer = VideoStreamer(resolved_url, mode, app_state.yolo_model)
            new_streamer.start()
            set_streamer(new_streamer)
            log.info(f"[Manager] VideoStreamer aktif: {mode} ({resolved_url[:60]})")

        # Danger zone check
        streamer = get_streamer()
        if streamer and streamer.is_alive():
            dets = streamer.get_latest_detections()
            app_state.yolo_danger = app_state.stationary_alert or any(
                d['cls'] in ('train',) for d in dets
            )

        await asyncio.sleep(1.0)

    set_streamer(None)


# ── Gemini Background Task ────────────────────────────────────────────────────
async def gemini_analysis_loop():
    """
    Async Background Task — Independen dari loop video.
    Setiap GEMINI_INTERVAL detik:
      1. Ambil frame terbaru dari streamer
      2. Kirim ke Gemini 2.0 Flash untuk analisis
      3. BROADCAST hasil JSON ke SEMUA WebSocket clients → menghidupkan panel Gemini
    """
    log.info("[Gemini] Background Task dimulai (interval=10s)")

    # Import Gemini
    try:
        from google import genai
        from google.genai import types
        gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        log.info("[Gemini] Client berhasil diinisialisasi.")
    except Exception as e:
        log.error(f"[Gemini] Gagal init client: {e}")
        gemini_client = None

    PROMPT = (
        "Kamu adalah sistem AI analisis perlintasan kereta api di Indonesia. "
        "Analisis frame ini dari rekaman kamera CCTV perlintasan kereta. "
        "Berikan: (1) nama lokasi yang kamu tebak berdasarkan ciri visual, "
        "(2) status kondisi: AMAN atau BAHAYA, "
        "(3) narasi situasi lalu lintas dalam 2-3 kalimat Bahasa Indonesia. "
        "Kembalikan HANYA JSON dengan format: "
        '{"status":"AMAN|BAHAYA","lokasi":"nama lokasi","narasi":"deskripsi"}'
    )

    backoff = 10

    while app_state.running:
        # Interval dinaikkan ke 25 detik demi menjaga kelonggaran kuota Free Tier API
        await asyncio.sleep(25)

        # ── Ambil frame terbaru ───────────────────────────────────
        streamer    = get_streamer()
        frame_to_analyze = None

        if streamer and streamer.is_alive():
            frame_to_analyze = streamer.get_latest_frame()

        if frame_to_analyze is None:
            log.debug("[Gemini] Belum ada frame, skip siklus ini.")
            continue

        # ── Kirim ke Gemini API ───────────────────────────────────
        if gemini_client is None:
            log.warning("[Gemini] Client tidak tersedia, skip.")
            continue

        try:
            # Encode frame ke JPEG untuk dikirim ke Gemini
            success, buf = cv2.imencode(".jpg", frame_to_analyze, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if not success:
                continue

            def call_gemini_api():
                from google.genai import types as _types
                return gemini_client.models.generate_content(
                    model    = "gemini-2.0-flash",
                    contents = [
                        _types.Part.from_bytes(data=buf.tobytes(), mime_type="image/jpeg"),
                        PROMPT
                    ],
                    config   = _types.GenerateContentConfig(
                        response_mime_type = "application/json",
                        temperature        = 0.2,
                        max_output_tokens  = 256,
                    )
                )

            response = await asyncio.wait_for(
                asyncio.to_thread(call_gemini_api),
                timeout=25.0
            )

            raw_text = response.text.strip()
            log.info(f"[Gemini] Response: {raw_text[:120]}")

            # Parse JSON
            try:
                parsed = json.loads(raw_text)
            except json.JSONDecodeError:
                # Coba ekstrak JSON dari teks jika ada markdown
                import re
                match = re.search(r'\{.*\}', raw_text, re.DOTALL)
                if match:
                    parsed = json.loads(match.group())
                else:
                    raise ValueError("Response bukan JSON valid")

            report = {
                "status":    str(parsed.get("status", "AMAN")),
                "lokasi":    str(parsed.get("lokasi", "Tidak dikenali")),
                "narasi":    str(parsed.get("narasi", "Tidak ada narasi.")),
                "timestamp": time.time(),
            }

            # ── Override jika ada kendaraan terjebak ──────────────
            if app_state.stationary_alert:
                report["status"] = "⚠️ BAHAYA: KENDARAAN TERJEBAK"
                report["narasi"] = (
                    "AI mendeteksi kendaraan yang tidak bergerak di area perlintasan. "
                    + report["narasi"]
                )

            # Simpan laporan terbaru
            app_state.gemini_report = report

            # ── BROADCAST KE SEMUA WEBSOCKET CLIENTS ──────────────
            # Ini adalah kunci menghidupkan panel Gemini di frontend!
            await broadcast_ws(report)

            backoff = 10  # Reset backoff setelah sukses

        except asyncio.TimeoutError:
            log.error("[Gemini] Timeout >25s")
            app_state.gemini_report["narasi"] = "Koneksi ke Gemini AI timeout. Mencoba lagi..."
            await broadcast_ws(app_state.gemini_report)

        except Exception as e:
            err_msg = str(e)
            log.error(f"[Gemini] Error: {err_msg}")

            if "429" in err_msg or "resource_exhausted" in err_msg.lower() or "quota" in err_msg.lower():
                log.warning("⚠️ [Gemini] Rate Limit 429 tercapai. Mengaktifkan sistem pendinginan (Backoff).")
                
                # Payload darurat agar UI tidak macet di "Mencari data..."
                fallback_payload = {
                    "kondisi_perlintasan": "MENDINGINKAN API",
                    "geo_location": "Rate Limit Bypass",
                    "insight_narasi": "Sistem AI sedang mendinginkan antrean (Rate Limit Bypass). Data visual tetap berjalan aman.",
                    "timestamp": time.strftime("%H:%M:%S")
                }
                
                await broadcast_ws(fallback_payload)
                # Istirahatkan worker ekstra 45 detik
                await asyncio.sleep(45)
            elif "INVALID_API_KEY" in err_msg or "401" in err_msg:
                log.error("[Gemini] API Key tidak valid!")
                app_state.gemini_report["narasi"] = "Error: Gemini API Key tidak valid."
                await broadcast_ws(app_state.gemini_report)
            else:
                app_state.gemini_report["narasi"] = f"Error analisis AI: {err_msg[:60]}"
                await broadcast_ws(app_state.gemini_report)


# ── MJPEG Async Generator ─────────────────────────────────────────────────────
async def generate_mjpeg_stream():
    """
    Async MJPEG Generator — Strict 30 FPS Pacing.
    Mengambil annotated_frame (bbox dari .plot() + overlay terjebak) dari
    shared state dan melakukan yield ke browser.
    """
    DISPLAY_W        = 640
    DISPLAY_H        = 360
    TARGET_FPS_DELAY = 0.033  # 30 FPS

    init_f   = generate_text_frame("NusaRail Vision System v6\nMemuat AI Engine...", bg_color=(10, 15, 30))
    ret, buf = cv2.imencode('.jpg', init_f, [cv2.IMWRITE_JPEG_QUALITY, 60])
    if ret:
        yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buf.tobytes() + b'\r\n'

    while app_state.running:
        t_start  = asyncio.get_event_loop().time()
        streamer = get_streamer()

        if streamer is None or not streamer.is_alive():
            wait_f   = generate_text_frame("Menghubungkan ke sumber video...", bg_color=(15, 20, 40))
            ret, buf = cv2.imencode('.jpg', wait_f, [cv2.IMWRITE_JPEG_QUALITY, 60])
            if ret:
                yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buf.tobytes() + b'\r\n'
            await asyncio.sleep(TARGET_FPS_DELAY)
            continue

        # Prioritaskan annotated frame (dengan bbox + overlay terjebak)
        frame = streamer.get_latest_annotated_frame()

        if frame is None:
            frame = streamer.get_latest_frame()
            if frame is None:
                elapsed = asyncio.get_event_loop().time() - t_start
                await asyncio.sleep(max(0, TARGET_FPS_DELAY - elapsed))
                continue
            cv2.putText(frame, "AI warming up...", (10, 35),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 220, 255), 2, cv2.LINE_AA)

        # Resize ke display 640x360
        if frame.shape[:2] != (DISPLAY_H, DISPLAY_W):
            frame = cv2.resize(frame, (DISPLAY_W, DISPLAY_H))
        H, W = DISPLAY_H, DISPLAY_W

        # Geo-Fence Overlay
        if len(app_state.polygon_points) >= 3:
            pts = [[int(pt['x'] * W), int(pt['y'] * H)] for pt in app_state.polygon_points]
            pts = np.array(pts, np.int32)
            cv2.polylines(frame, [pts], True, (0, 0, 255), 2)
            overlay = frame.copy()
            cv2.fillPoly(overlay, [pts], (0, 0, 255))
            cv2.addWeighted(overlay, 0.15, frame, 0.85, 0, frame)
            cv2.putText(frame, "DANGER ZONE", tuple(pts[0]),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2, cv2.LINE_AA)

        # ── Info Overlay ──────────────────────────────────────────
        det_count  = len(streamer.get_latest_detections())
        ts         = time.strftime("%Y-%m-%d %H:%M:%S")

        # Banner merah jika ada kendaraan terjebak
        if app_state.stationary_alert:
            cv2.rectangle(frame, (0, 0), (DISPLAY_W, 36), (0, 0, 180), -1)
            cv2.putText(frame, "⚠ BAHAYA: KENDARAAN TERJEBAK DI REL!", (6, 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2, cv2.LINE_AA)
        else:
            cv2.rectangle(frame, (0, 0), (200, 32), (0, 0, 0), -1)
            info_color = (0, 255, 100) if det_count > 0 else (160, 160, 160)
            cv2.putText(frame, f"AI: {det_count} objek terdeteksi", (6, 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.52, info_color, 1, cv2.LINE_AA)

        cv2.putText(frame, f"NusaRail | {ts}", (5, H - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(frame, f"NusaRail | {ts}", (5, H - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1, cv2.LINE_AA)

        # Encode JPEG & yield
        ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
        if ret:
            yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n'

        # Strict 30 FPS pacing
        elapsed = asyncio.get_event_loop().time() - t_start
        await asyncio.sleep(max(0.001, TARGET_FPS_DELAY - elapsed))


# ── FastAPI Startup ───────────────────────────────────────────────────────────
os.makedirs("temp", exist_ok=True)
os.makedirs("temp_snapshots", exist_ok=True)
app.mount("/snapshots", StaticFiles(directory="temp_snapshots"), name="snapshots")

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(yolo_inference_loop())    # Task 1: Model + VideoStreamer
    asyncio.create_task(gemini_analysis_loop())   # Task 2: Gemini + WS Broadcast

@app.on_event("shutdown")
async def shutdown_event():
    app_state.running = False

# ── REST Endpoints ────────────────────────────────────────────────────────────
@app.get("/api/health")
def health_check():
    streamer = get_streamer()
    return {
        "status":          "ok",
        "running":         app_state.running,
        "model_loaded":    app_state.yolo_model is not None,
        "streamer_alive":  streamer is not None and streamer.is_alive(),
        "stationary_alert": app_state.stationary_alert,
        "djka_connected":  True,
        "mqtt_connected":  alert_dispatcher.mqtt_client.is_connected(),
    }

@app.get("/api/debug/model")
def debug_model():
    model = app_state.yolo_model
    if model is None:
        return {"status": "ERROR", "message": "Model belum dimuat."}
    names        = model.names if hasattr(model, 'names') else {}
    target_names = {str(i): names.get(i, "N/A") for i in YOLO_CLASSES}
    return {
        "status":           "OK",
        "total_classes":    len(names),
        "target_classes":   target_names,
        "conf_threshold":   YOLO_CONF,
        "tracking":         "ByteTrack (persist=True)",
        "stationary_secs":  STATIONARY_SECONDS,
        "stationary_px":    STATIONARY_PX_DELTA,
        "active_objects":   app_state.active_objects_count,
        "stationary_alert": app_state.stationary_alert,
        "ws_clients":       len(app_state.clients),
        "class_check":      "✅ COCO 80 kelas" if len(names) >= 80 else f"⚠️ {len(names)} kelas",
    }

class SetUrlRequest(BaseModel):
    youtube_url: str = None
    rtsp_url: str    = None
    mode: str        = "youtube"

@app.post("/api/set_url")
def set_url(req: SetUrlRequest):
    if req.mode == "youtube" and req.youtube_url:
        app_state.target_url  = req.youtube_url.strip()
        app_state.source_mode = "youtube"
    elif req.mode == "rtsp" and req.rtsp_url:
        app_state.target_url  = req.rtsp_url
        app_state.source_mode = "rtsp"
    return {"status": "success", "mode": app_state.source_mode}

@app.post("/api/upload")
async def upload_video(file: UploadFile = File(...)):
    for old in Path("temp").glob("*.*"):
        try: os.remove(old)
        except: pass
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
    points: list

@app.post("/api/set_polygon")
def set_polygon(req: SetPolygonRequest):
    app_state.polygon_points = req.points if isinstance(req.points[0], dict) else \
        [{"x": p.x, "y": p.y} for p in req.points]
    return {"status": "success"}

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
        log.error(f"[MQTT] {e}")
    return {"status": "success"}

@app.get("/api/incidents")
def get_incidents():
    try:
        conn = sqlite3.connect("incidents.db")
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
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
        "stationary_alert": app_state.stationary_alert,
        "uptime":          int(time.time() - app_state.start_time),
        "active_objects":  app_state.active_objects_count,
    }

@app.get("/api/export_csv")
def export_csv():
    import io as _io, csv as _csv
    from fastapi.responses import Response
    try:
        conn = sqlite3.connect("incidents.db")
        c    = conn.cursor()
        c.execute("SELECT timestamp, lokasi, jenis, snapshot_url FROM incidents ORDER BY timestamp DESC")
        rows = c.fetchall()
        conn.close()
        out = _io.StringIO()
        w   = _csv.writer(out)
        w.writerow(["Timestamp", "Lokasi", "Jenis", "Snapshot URL"])
        for r in rows:
            w.writerow([time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r[0])), r[1], r[2], r[3]])
        return Response(
            content    = out.getvalue(),
            media_type = "text/csv",
            headers    = {"Content-Disposition": "attachment; filename=nusarail_incidents.csv"}
        )
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/stream")
async def video_stream():
    return StreamingResponse(
        generate_mjpeg_stream(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

# ── WebSocket Endpoint ────────────────────────────────────────────────────────
@app.websocket("/api/ws/gemini")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint untuk push analisis Gemini ke frontend secara real-time.
    Saat client connect: langsung kirim laporan terakhir yang tersimpan.
    Setelah itu: gemini_analysis_loop() yang akan broadcast setiap 10 detik.
    """
    await websocket.accept()
    app_state.clients.append(websocket)
    log.info(f"[WS] Client terhubung. Total: {len(app_state.clients)}")

    # Kirim laporan terakhir langsung saat connect (bukan nunggu 10 detik)
    try:
        initial_report = app_state.gemini_report.copy()
        initial_report["timestamp"] = initial_report.get("timestamp", time.time())
        await websocket.send_text(json.dumps(initial_report, ensure_ascii=False))
    except:
        pass

    try:
        while True:
            # Keep-alive: terima ping dari client
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in app_state.clients:
            app_state.clients.remove(websocket)
        log.info(f"[WS] Client disconnect. Sisa: {len(app_state.clients)}")
