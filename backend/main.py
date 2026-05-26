import asyncio
import io
import json
import logging
import os
import time
import math
import shutil
import queue
import threading
from pathlib import Path
from typing import Dict, List, Optional

import cv2
import numpy as np
import yt_dlp
import aiohttp
import paho.mqtt.client as mqtt
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import sqlite3

# Inisialisasi Database SQLite
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
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("debug.log")
    ]
)
log = logging.getLogger(__name__)

# ── Config & State ────────────────────────────────────────────────────────────
YOLO_MODEL = os.getenv("YOLO_MODEL", "best_web_optimized.onnx")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyCCNLkAMh6VmZuaoG1LuqkAa9O0cMA-hVA")
TARGET_FPS = 5
GEMINI_INTERVAL = 10
STATIONARY_TIME_THRESHOLD = 3.0  # detik kendaraan diam dianggap mogok
STATIONARY_PIXEL_THRESHOLD = 15.0 # jarak maksimum pixel (centroid) untuk dianggap diam

FRONTEND_URL = os.getenv("FRONTEND_URL", "*")
DJKA_WEBHOOK_URL = os.getenv("DJKA_WEBHOOK_URL", "https://httpbin.org/post")
MQTT_BROKER = os.getenv("MQTT_BROKER", "test.mosquitto.org")

class AppState:
    def __init__(self):
        self.source_mode: str = "youtube" # "youtube", "rtsp", "upload"
        self.target_url: str = "https://www.youtube.com/watch?v=q7lvnYVuqNY"
        self.stream_url: Optional[str] = None
        self.last_frame: Optional[np.ndarray] = None
        self.last_detections: List[Dict] = []
        self.gemini_report: Dict = {"status": "MENGINISIALISASI", "lokasi": "Mencari data...", "narasi": "Sistem sedang dijalankan."}
        self.clients: List[WebSocket] = []
        self.running: bool = False
        self.yolo_session = None
        self.frame_lock = asyncio.Lock()
        self.yolo_danger: bool = False
        
        # Advanced Features State
        self.telegram_token: str = ""
        self.telegram_chat_id: str = ""
        self.polygon_points: List[Dict[str, float]] = [] # [{x, y}] format (0.0-1.0)
        self.djka_webhook_url: str = os.getenv("DJKA_WEBHOOK_URL", "https://httpbin.org/post")
        self.mqtt_broker: str = os.getenv("MQTT_BROKER", "test.mosquitto.org")
        
        self.start_time: float = time.time()
        self.active_objects_count: int = 0

app_state = AppState()

app = FastAPI(title="NusaRail Sentinel Backend API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        FRONTEND_URL, 
        "http://localhost:3000", 
        "https://bootcamp-kai.vercel.app", 
        "*"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SetUrlRequest(BaseModel):
    youtube_url: str

# ── Utilities ─────────────────────────────────────────────────────────────────

def sanitize_url(url: str) -> str:
    # Basic URL sanitization
    url = url.strip()
    if not url.startswith("http"):
        return "https://www.youtube.com/watch?v=q7lvnYVuqNY"
    return url

def generate_text_frame(message: str, bg_color=(0, 0, 0), text_color=(255, 255, 255)) -> np.ndarray:
    frame = np.full((480, 640, 3), bg_color, dtype=np.uint8)
    y0, dy = 220, 35
    for i, line in enumerate(message.split('\n')):
        y = y0 + i*dy
        cv2.putText(frame, line.strip(), (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, text_color, 2)
    return frame

async def extract_youtube_url_async(url: str) -> Optional[str]:
    def sync_extract():
        log.info(f"Mengekstrak URL dari: {url}")
        
        cookie_path = os.path.join(os.path.dirname(__file__), 'cookies.txt')
        has_cookies = os.path.exists(cookie_path)
        
        ydl_opts = {
            'format': 'best[height<=480]/worst',
            'socket_timeout': 10,
            'source_address': '0.0.0.0',
            'force_ipv4': True,
            'geo_bypass': True,
            'nocheckcertificate': True,
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'extractor_args': {'youtube': {'player_client': ['android', 'web']}}
        }
        
        if has_cookies:
            ydl_opts['cookiefile'] = cookie_path
            log.info("Menggunakan cookies.txt untuk autentikasi yt-dlp.")
            
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info and info.get('url'):
                    return info.get('url')
        except Exception as e:
            raise RuntimeError(f"DownloadError: {e}")
        return None
            
    try:
        return await asyncio.wait_for(asyncio.to_thread(sync_extract), timeout=15.0)
    except asyncio.TimeoutError:
        log.error("Timeout 15s mengekstrak URL YouTube.")
        return "TIMEOUT"
    except Exception as e:
        log.error(str(e))
        return "ERROR"

def load_yolo_onnx():
    import onnxruntime as ort
    model_path = Path(__file__).parent / YOLO_MODEL
    if not model_path.exists():
        model_path = Path(__file__).parent / "Dataset" / YOLO_MODEL
        if not model_path.exists():
            log.warning(f"Model {YOLO_MODEL} tidak ditemukan, fallback.")
            return None
    try:
        log.info(f"Memuat model ONNX: {model_path}")
        providers = ['CPUExecutionProvider']
        return ort.InferenceSession(str(model_path), providers=providers)
    except Exception as e:
        log.error(f"Gagal memuat model ONNX: {e}")
        return None

def preprocess_image(img, input_size=(640, 640)):
    shape = img.shape[:2]
    r = min(input_size[0] / shape[0], input_size[1] / shape[1])
    new_unpad = int(round(shape[1] * r)), int(round(shape[0] * r))
    dw, dh = input_size[1] - new_unpad[0], input_size[0] - new_unpad[1]
    dw, dh = np.mod(dw, 32), np.mod(dh, 32)
    dw /= 2
    dh /= 2
    if shape[::-1] != new_unpad:
        img = cv2.resize(img, new_unpad, interpolation=cv2.INTER_LINEAR)
    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    img = cv2.copyMakeBorder(img, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(114, 114, 114))
    img = img.transpose((2, 0, 1))[::-1]
    img = np.ascontiguousarray(img)
    img = img.astype(np.float32) / 255.0
    if len(img.shape) == 3:
        img = img[None]
    return img, r, (dw, dh)

def postprocess(preds, orig_shape, ratio, pad):
    preds = preds[0]
    preds = preds.transpose()
    boxes = preds[:, :4]
    scores = preds[:, 4:]
    max_scores = np.max(scores, axis=1)
    class_ids = np.argmax(scores, axis=1)
    
    # Dual Thresholds
    classes = {0: 'person', 2: 'car', 3: 'motorcycle', 5: 'bus', 6: 'train', 7: 'truck'}
    
    mask = []
    for i, c_id in enumerate(class_ids):
        conf = max_scores[i]
        c_name = classes.get(int(c_id), 'unknown')
        if c_name == 'train' and conf > 0.6:
            mask.append(True)
        elif c_name in ['car', 'motorcycle', 'bus', 'truck'] and conf > 0.25:
            mask.append(True)
        elif c_name == 'person' and conf > 0.25:
            mask.append(True)
        else:
            mask.append(False)
            
    mask = np.array(mask)
    if not np.any(mask):
        return []
        
    boxes = boxes[mask]
    scores = max_scores[mask]
    class_ids = class_ids[mask]
    
    x1 = boxes[:, 0] - boxes[:, 2] / 2
    y1 = boxes[:, 1] - boxes[:, 3] / 2
    x2 = boxes[:, 0] + boxes[:, 2] / 2
    y2 = boxes[:, 1] + boxes[:, 3] / 2
    boxes = np.stack([x1, y1, x2, y2], axis=1)
    
    boxes[:, 0] -= pad[0]
    boxes[:, 1] -= pad[1]
    boxes[:, 2] -= pad[0]
    boxes[:, 3] -= pad[1]
    boxes /= ratio
    
    boxes[:, 0] = np.clip(boxes[:, 0], 0, orig_shape[1])
    boxes[:, 1] = np.clip(boxes[:, 1], 0, orig_shape[0])
    boxes[:, 2] = np.clip(boxes[:, 2], 0, orig_shape[1])
    boxes[:, 3] = np.clip(boxes[:, 3], 0, orig_shape[0])
    
    indices = cv2.dnn.NMSBoxes(boxes.tolist(), scores.tolist(), 0.5, 0.45)
    
    results = []
    if len(indices) > 0:
        for i in indices.flatten():
            cls_id = int(class_ids[i])
            results.append({
                "xyxy": boxes[i].astype(int).tolist(),
                "conf": float(scores[i]),
                "cls": classes[cls_id]
            })
    return results

def enhance_low_light(frame: np.ndarray) -> np.ndarray:
    """Implementasi CLAHE untuk preprocessing cahaya"""
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    cl = clahe.apply(l)
    limg = cv2.merge((cl, a, b))
    return cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)

# ── Alert Dispatcher (IoT & DJKA Webhook) ─────────────────────────────────────
class AlertDispatcher:
    def __init__(self):
        self.mqtt_client = mqtt.Client(client_id="NusaRail_Dispatcher")
        try:
            self.mqtt_client.connect(app_state.mqtt_broker, 1883, 60)
            self.mqtt_client.loop_start()
            log.info("MQTT Connected")
        except Exception as e:
            log.warning(f"MQTT gagal terhubung: {e}")
            
    async def dispatch_alert(self, lokasi: str, bahaya: bool, frame: np.ndarray, jenis: str = "Kendaraan Mogok"):
        timestamp = int(time.time())
        filename = f"snapshot_{timestamp}.jpg"
        filepath = os.path.join("temp_snapshots", filename)
        
        cv2.imwrite(filepath, frame)
        
        # Cleanup old snapshots > 20 files
        try:
            files = sorted(Path("temp_snapshots").glob("*.jpg"), key=os.path.getmtime)
            if len(files) > 20:
                os.remove(files[0])
        except:
            pass

        # Mock public URL based on HF space structure or just path
        snapshot_url = f"/snapshots/{filename}"
        
        # 1. Simpan ke Database SQLite
        try:
            conn = sqlite3.connect("incidents.db")
            c = conn.cursor()
            c.execute("INSERT INTO incidents (timestamp, lokasi, jenis, snapshot_url) VALUES (?, ?, ?, ?)",
                      (timestamp, lokasi, jenis, snapshot_url))
            conn.commit()
            conn.close()
        except Exception as e:
            log.error(f"Gagal simpan ke DB: {e}")
        
        payload = {
            "timestamp": timestamp,
            "lokasi": lokasi,
            "tingkat_bahaya": "KRITIS" if bahaya else "PERINGATAN",
            "snapshot_url": snapshot_url,
            "jenis": jenis
        }
        
        # 2. Webhook DJKA
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(app_state.djka_webhook_url, json=payload, timeout=5) as resp:
                    pass
        except Exception as e:
            log.error(f"Gagal kirim Webhook: {e}")
            
        # 3. MQTT Publish
        try:
            self.mqtt_client.publish("nusarail/alerts/gate", json.dumps(payload))
        except Exception as e:
            log.error(f"Gagal publish MQTT: {e}")
            
        # 4. Telegram Bot (Bila Dikonfigurasi)
        if app_state.telegram_token and app_state.telegram_chat_id:
            try:
                caption = f"🚨 PERINGATAN BAHAYA 🚨\nLokasi: {lokasi}\nJenis: {jenis}"
                url = f"https://api.telegram.org/bot{app_state.telegram_token}/sendPhoto"
                with open(filepath, 'rb') as f:
                    form = aiohttp.FormData()
                    form.add_field('chat_id', app_state.telegram_chat_id)
                    form.add_field('caption', caption)
                    form.add_field('photo', f, filename=filename, content_type='image/jpeg')
                    
                    async with aiohttp.ClientSession() as session:
                        async with session.post(url, data=form, timeout=10) as resp:
                            if resp.status != 200:
                                log.error(f"Telegram API Error: {await resp.text()}")
            except Exception as e:
                log.error(f"Gagal kirim Telegram: {e}")

alert_dispatcher = AlertDispatcher()

# ── Background Tasks ──────────────────────────────────────────────────────────
async def broadcast_gemini_report():
    if not app_state.clients: return
    # Override logic: Jika YOLO bahaya, override status AI
    report = app_state.gemini_report.copy()
    if app_state.yolo_danger and "BAHAYA" not in report["status"].upper():
        report["status"] = "BAHAYA KRITIS (Override Visi)"
        report["narasi"] = "[Sistem Visi Mendeteksi Konflik]: " + report["narasi"]

    msg = json.dumps(report)
    
    async def send_to_client(ws: WebSocket):
        try:
            await ws.send_text(msg)
        except Exception:
            return ws
        return None
        
    results = await asyncio.gather(*(send_to_client(ws) for ws in app_state.clients))
    disconnected = [ws for ws in results if ws is not None]
    
    for ws in disconnected:
        if ws in app_state.clients:
            app_state.clients.remove(ws)

# ── Producer-Consumer Architecture ────────────────────────────────────────────
class VideoProducer(threading.Thread):
    def __init__(self, target_url, mode):
        super().__init__()
        self.target_url = target_url
        self.mode = mode
        self.frame_queue = queue.Queue(maxsize=60)
        self.running = True
        self.cap = None
        self.original_fps = 25.0
        
    def run(self):
        self.cap = cv2.VideoCapture(self.target_url)
        if self.cap.isOpened():
            fps = self.cap.get(cv2.CAP_PROP_FPS)
            if fps > 0 and not math.isnan(fps):
                self.original_fps = fps
            log.info(f"Producer started for {self.mode}. FPS: {self.original_fps}")
        else:
            log.error(f"Producer failed to open: {self.target_url}")
            self.running = False
            return
            
        failed_reads = 0
        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                failed_reads += 1
                if self.mode == "upload":
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    failed_reads = 0
                    continue
                if failed_reads > 10:
                    break
                time.sleep(0.1)
                continue
                
            failed_reads = 0
            try:
                self.frame_queue.put(frame, timeout=1.0)
            except queue.Full:
                pass
                
        if self.cap:
            self.cap.release()
            
    def stop(self):
        self.running = False
        self.join(timeout=2.0)

async def yolo_inference_loop():
    log.info("YOLO Inference Loop started (Consumer Mode)")
    app_state.yolo_session = load_yolo_onnx()
    
    current_mode = None
    current_target = None
    producer = None
    
    trackers = {}
    next_id = 1
    
    frame_counter = 0
    
    app_state.running = True
    
    while app_state.running:
        
        if app_state.source_mode != current_mode or app_state.target_url != current_target:
            if producer is not None:
                producer.stop()
                producer = None
            
            current_mode = app_state.source_mode
            current_target = app_state.target_url
            
            if current_mode == "youtube":
                cookie_path = os.path.join(os.path.dirname(__file__), 'cookies.txt')
                if not os.path.exists(cookie_path):
                    warn_frame = generate_text_frame("WARNING: cookies.txt NOT FOUND.\nYOUTUBE MAY BLOCK THIS STREAM.", bg_color=(0, 128, 255))
                    async with app_state.frame_lock:
                        app_state.last_frame = warn_frame
                    await asyncio.sleep(3)
                else:
                    init_frame = generate_text_frame("INITIALIZING STREAM...\nExtracting YouTube URL (w/ Cookies)...", bg_color=(0, 150, 150))
                    async with app_state.frame_lock:
                        app_state.last_frame = init_frame
                
                log.info("Mencoba membuat koneksi stream YouTube...")
                url_result = await extract_youtube_url_async(current_target)
                
                if url_result == "TIMEOUT":
                    err_frame = generate_text_frame("ERROR: YOUTUBE BLOCKED HF IP (TIMEOUT).\nTRY ANOTHER URL.", bg_color=(0, 0, 200))
                    async with app_state.frame_lock:
                        app_state.last_frame = err_frame
                    await asyncio.sleep(5)
                    continue
                elif url_result == "ERROR" or not url_result:
                    err_frame = generate_text_frame("ERROR: VIDEO RESTRICTED OR INVALID.", bg_color=(0, 0, 200))
                    async with app_state.frame_lock:
                        app_state.last_frame = err_frame
                    await asyncio.sleep(5)
                    continue
                
                producer = VideoProducer(url_result, current_mode)
                producer.start()
            
            elif current_mode == "rtsp":
                init_frame = generate_text_frame("INITIALIZING RTSP CCTV...", bg_color=(150, 100, 0))
                async with app_state.frame_lock:
                    app_state.last_frame = init_frame
                producer = VideoProducer(current_target, current_mode)
                producer.start()
                
            elif current_mode == "upload":
                init_frame = generate_text_frame("INITIALIZING LOCAL VIDEO UPLOAD...", bg_color=(0, 100, 150))
                async with app_state.frame_lock:
                    app_state.last_frame = init_frame
                producer = VideoProducer(current_target, current_mode)
                producer.start()
                
            frame_counter = 0

        if producer is None or not producer.is_alive():
            err_frame = generate_text_frame("STREAM LOST OR CONNECTING...", bg_color=(0, 0, 200))
            async with app_state.frame_lock:
                app_state.last_frame = err_frame
            await asyncio.sleep(1)
            continue
            
        try:
            frame = producer.frame_queue.get_nowait()
        except queue.Empty:
            await asyncio.sleep(0.01)
            continue
            
        start_time_loop = time.time()
        frame_counter += 1
        H, W = frame.shape[:2]
        
        # Setup Absolute Polygon for Geo-Fencing Point-in-Polygon Test
        polygon_abs = []
        if len(app_state.polygon_points) >= 3:
            for pt in app_state.polygon_points:
                polygon_abs.append([int(pt['x'] * W), int(pt['y'] * H)])
            polygon_abs = np.array(polygon_abs, np.int32)
        
        try:
            # --- [2] Implementasi Algoritma AI Frame Skipping ---
            if frame_counter % 5 == 0 or len(app_state.last_detections) == 0:
                yolo_frame = enhance_low_light(frame)
                
                def run_yolo_sync(frame_np):
                    input_name = app_state.yolo_session.get_inputs()[0].name
                    img, ratio, pad = preprocess_image(frame_np)
                    preds = app_state.yolo_session.run(None, {input_name: img})[0]
                    return postprocess(preds, frame_np.shape[:2], ratio, pad)

                if app_state.yolo_session:
                    detections = await asyncio.to_thread(run_yolo_sync, yolo_frame)
                else:
                    detections = []
                    
                app_state.last_detections = detections
            else:
                # Gunakan cache detections
                detections = app_state.last_detections
                
            # --- Object Tracking & Stationary Logic ---
            current_centroids = []
            new_trackers = {}
            yolo_is_danger = False
            
            for det in detections:
                x1, y1, x2, y2 = det['xyxy']
                cx = (x1 + x2) / 2
                cy = (y1 + y2) / 2
                current_centroids.append((cx, cy, det))
            
            # Simple greedy match
            for cx, cy, det in current_centroids:
                matched_id = None
                min_dist = float('inf')
                for tid, tdata in trackers.items():
                    px, py = tdata['centroid']
                    dist = math.hypot(cx - px, cy - py)
                    if dist < STATIONARY_PIXEL_THRESHOLD and dist < min_dist:
                        min_dist = dist
                        matched_id = tid
                        
                is_mogok = False
                if matched_id is not None:
                    tdata = trackers[matched_id]
                    if start_time_loop - tdata['first_seen'] > STATIONARY_TIME_THRESHOLD:
                        is_mogok = True
                    new_trackers[matched_id] = {
                        "centroid": (cx, cy),
                        "first_seen": tdata['first_seen'],
                        "last_seen": start_time_loop,
                        "mogok": is_mogok,
                        "last_alert_time": tdata.get('last_alert_time', 0)
                    }
                else:
                    new_trackers[next_id] = {
                        "centroid": (cx, cy),
                        "first_seen": start_time_loop,
                        "last_seen": start_time_loop,
                        "mogok": False,
                        "last_alert_time": 0
                    }
                    matched_id = next_id
                    next_id += 1
                
                det['track_id'] = matched_id
                det['mogok'] = is_mogok
                
                # Cek danger dengan Geo-Fencing
                inside_polygon = True
                if len(polygon_abs) >= 3:
                    dist = cv2.pointPolygonTest(polygon_abs, (float(cx), float(cy)), False)
                    if dist < 0:
                        inside_polygon = False

                if inside_polygon:
                    if det['cls'] == 'train':
                        yolo_is_danger = True
                    elif is_mogok:
                        yolo_is_danger = True
                        if start_time_loop - new_trackers[matched_id]['last_alert_time'] > 30:
                            asyncio.create_task(alert_dispatcher.dispatch_alert(
                                lokasi=app_state.gemini_report.get("lokasi", "Unknown"),
                                bahaya=True,
                                frame=frame,
                                jenis=f"Mogok ({det['cls']})"
                            ))
                            new_trackers[matched_id]['last_alert_time'] = start_time_loop

            trackers = new_trackers
            app_state.yolo_danger = yolo_is_danger
            app_state.active_objects_count = len(trackers)
            
        except Exception as e:
            log.error(f"Error inferensi: {e}")

        # Render Bounding Boxes
        display_frame = frame.copy()
        
        if len(polygon_abs) >= 3:
            cv2.polylines(display_frame, [polygon_abs], True, (0, 0, 255), 2)
            overlay = display_frame.copy()
            cv2.fillPoly(overlay, [polygon_abs], (0, 0, 255))
            cv2.addWeighted(overlay, 0.15, display_frame, 0.85, 0, display_frame)
            cv2.putText(display_frame, "DANGER ZONE", polygon_abs[0], cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
        else:
            cv2.rectangle(display_frame, (int(W*0.1), int(H*0.2)), (int(W*0.9), int(H*0.9)), (255,255,0), 1, cv2.LINE_AA)
            cv2.putText(display_frame, "ROI Default (Seluruh Layar)", (int(W*0.1), int(H*0.2)-10), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255,255,0), 1)

        # Draw Timestamps
        timestamp_str = time.strftime("%Y-%m-%d %H:%M:%S")
        cv2.putText(display_frame, f"LIVE SYSTEM TIMESTAMP: {timestamp_str}", (20, H - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 3)
        cv2.putText(display_frame, f"LIVE SYSTEM TIMESTAMP: {timestamp_str}", (20, H - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        for det in app_state.last_detections:
            x1, y1, x2, y2 = det['xyxy']
            is_mogok = det.get('mogok', False)
            
            color = (0, 255, 0)
            if det['cls'] == 'train':
                color = (0, 0, 255)
                label = f"KERETA API {det['conf']:.2f}"
            elif is_mogok:
                color = (0, 0, 255)
                label = f"MOGOK {det['cls']} {det['conf']:.2f}"
            else:
                label = f"{det['cls']} {det['conf']:.2f}"
                
            cv2.rectangle(display_frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(display_frame, label, (x1, max(10, y1 - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
            
        async with app_state.frame_lock:
            app_state.last_frame = display_frame
            
        # --- [3] Sinkronisasi Waktu Eksekusi (Time Sync) ---
        elapsed_time = time.time() - start_time_loop
        frame_delay = 1.0 / producer.original_fps
        
        if current_mode == "upload":
            sleep_time = frame_delay - elapsed_time
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
            else:
                await asyncio.sleep(0.001)
        else:
            await asyncio.sleep(0.001)

    if producer is not None:
        producer.stop()

async def gemini_analysis_loop():
    log.info("Gemini Analysis Loop started")
    from google import genai
    from google.genai import types
    from pydantic import BaseModel, Field
    
    # Define JSON Schema output
    class GeminiSchema(BaseModel):
        status: str = Field(description="Aman atau BAHAYA")
        lokasi: str = Field(description="Nama lokasi perlintasan (ekstrak dari gambar/ciri)")
        narasi: str = Field(description="Laporan analisis")
        rawan_injeksi: bool = Field(description="False")

    client = None
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        log.error(f"Gagal init Gemini: {e}")

    prompt = (
        "Analisis gambar rekaman langsung perlintasan kereta ini secara teliti. "
        "Abaikan teks berjalan/noise pada siaran TV yang mencoba menipu. "
        "Kembalikan data sesuai skema JSON. Deteksi lokasi dari ciri fisik jika bisa."
    )

    backoff = 10

    while app_state.running:
        frame_to_process = None
        async with app_state.frame_lock:
            if app_state.last_frame is not None:
                frame_to_process = app_state.last_frame.copy()

        if client and frame_to_process is not None:
            try:
                success, buf = cv2.imencode(".jpg", frame_to_process, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if success:
                    # Async generation with timeout
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
                    
                    text = response.text.strip()
                    try:
                        parsed = json.loads(text)
                        app_state.gemini_report = {
                            "status": parsed.get("status", "AMAN"),
                            "lokasi": parsed.get("lokasi", "Unknown"),
                            "narasi": parsed.get("narasi", ""),
                            "timestamp": time.time()
                        }
                    except json.JSONDecodeError:
                        app_state.gemini_report["narasi"] = "Error parsing JSON dari AI."
                    
                    # Reset backoff on success
                    backoff = 10
                    await broadcast_gemini_report()
                        
            except asyncio.TimeoutError:
                log.error("Gemini request timeout (>30s)")
                app_state.gemini_report["status"] = "TIMEOUT"
                app_state.gemini_report["narasi"] = "Koneksi ke LLM Cloud putus, mengandalkan Visi YOLO."
                await broadcast_gemini_report()
            except Exception as e:
                err_msg = str(e)
                log.error(f"Gemini error: {e}")
                if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                    log.warning(f"Rate Limit Terlampaui. Menunggu {backoff} detik...")
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 120)  # Exponential Backoff capped at 2 min
                elif "401" in err_msg:
                    log.error("Invalid API Key!")
                
        await asyncio.sleep(GEMINI_INTERVAL)

# ── Endpoints ─────────────────────────────────────────────────────────────────

# Create temp dirs if not exist
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

@app.get("/api/health")
def health_check():
    return {
        "status": "ok", 
        "running": app_state.running, 
        "djka_connected": True, 
        "mqtt_connected": alert_dispatcher.mqtt_client.is_connected()
    }

class SetUrlRequest(BaseModel):
    youtube_url: Optional[str] = None
    rtsp_url: Optional[str] = None
    mode: str = "youtube"

@app.post("/api/set_url")
def set_url(req: SetUrlRequest):
    if req.mode == "youtube" and req.youtube_url:
        safe_url = sanitize_url(req.youtube_url)
        app_state.target_url = safe_url
        app_state.source_mode = "youtube"
    elif req.mode == "rtsp" and req.rtsp_url:
        app_state.target_url = req.rtsp_url
        app_state.source_mode = "rtsp"
        
    app_state.stream_url = None 
    return {"status": "success", "mode": app_state.source_mode, "target_url": app_state.target_url}

@app.post("/api/upload")
async def upload_video(file: UploadFile = File(...)):
    for old_file in Path("temp").glob("*.*"):
        try:
            os.remove(old_file)
        except: pass
        
    file_path = f"temp/{file.filename}"
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    app_state.target_url = file_path
    app_state.source_mode = "upload"
    return {"status": "success", "filename": file.filename}

class SetTelegramRequest(BaseModel):
    token: str
    chat_id: str

@app.post("/api/set_telegram")
def set_telegram(req: SetTelegramRequest):
    app_state.telegram_token = req.token
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
    app_state.mqtt_broker = req.mqtt_broker
    
    # Reconnect MQTT
    try:
        alert_dispatcher.mqtt_client.disconnect()
        alert_dispatcher.mqtt_client.connect(app_state.mqtt_broker, 1883, 60)
    except Exception as e:
        log.error(f"MQTT Reconnect Error: {e}")
        
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
    uptime_seconds = int(time.time() - app_state.start_time)
    return {
        "danger": app_state.yolo_danger,
        "uptime": uptime_seconds,
        "active_objects": app_state.active_objects_count
    }

async def generate_mjpeg_stream():
    # 1. Instant First-Frame Yielding (Pencegah Timeout Kritis)
    init_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.putText(init_frame, "INITIALIZING AI ENGINE & YOUTUBE STREAM...", (20, 220), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    cv2.putText(init_frame, "Please wait 10s", (240, 260), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    ret, buffer = cv2.imencode('.jpg', init_frame)
    if ret:
        frame_bytes = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

    # Boundary format standard
    while app_state.running:
        frame_to_stream = None
        async with app_state.frame_lock:
            if app_state.last_frame is not None:
                frame_to_stream = app_state.last_frame
                
        if frame_to_stream is not None:
            ret, buffer = cv2.imencode('.jpg', frame_to_stream)
            if ret:
                frame = buffer.tobytes()
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
        else:
            # Fallback frame abu-abu saat buffering awal atau jika gagal baca video
            buff_frame = np.full((480, 640, 3), 128, dtype=np.uint8)
            cv2.putText(buff_frame, "BUFFERING YOUTUBE / HF COLD START...", (40, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
            ret, buffer = cv2.imencode('.jpg', buff_frame)
            if ret:
                frame = buffer.tobytes()
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
        await asyncio.sleep(0.04)  # ~25 FPS emit rate

@app.get("/api/stream")
async def video_stream():
    return StreamingResponse(generate_mjpeg_stream(), media_type="multipart/x-mixed-replace; boundary=frame")

@app.websocket("/api/ws/gemini")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    app_state.clients.append(websocket)
    try:
        await websocket.send_text(json.dumps(app_state.gemini_report))
        while True:
            # Tetap terbuka dan menunggu ping dari frontend untuk cegah zombie process
            await websocket.receive_text() 
    except WebSocketDisconnect:
        if websocket in app_state.clients:
            app_state.clients.remove(websocket)
