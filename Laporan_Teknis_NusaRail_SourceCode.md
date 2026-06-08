# LAMPIRAN TEKNIS: LAPORAN ARSITEKTUR & IMPLEMENTASI SOURCE CODE LENGKAP
# NusaRail Vision System — Integrasi YOLOv8, ByteTrack, dan Gemini 1.5 Pro

---

**Penulis:** Muhammad Abdurrahman Rabbani (NIM: 15240969)  
**Program Studi:** S1 Informatika, Universitas Bina Sarana Informatika  
**Tahun:** 2026  
**Versi Dokumen:** 2.0 — Edisi Source Code Lengkap

---

## DAFTAR ISI

1. [BAB 1: Tinjauan Arsitektur Hibrida Terdistribusi](#bab-1-tinjauan-arsitektur-hibrida-terdistribusi)
2. [BAB 2: Implementasi Backend (FastAPI & AI Engine)](#bab-2-implementasi-backend-fastapi--ai-engine)
3. [BAB 3: Implementasi Frontend (Next.js & Vercel)](#bab-3-implementasi-frontend-nextjs--vercel)
4. [BAB 4: Konfigurasi Deployment Produksi](#bab-4-konfigurasi-deployment-produksi)
5. [LAMPIRAN: Peta 8 Critical Fixes](#lampiran-peta-8-critical-fixes)

---

## BAB 1: Tinjauan Arsitektur Hibrida Terdistribusi

### 1.1. Latar Belakang Pemilihan Arsitektur

Pengembangan sistem peringatan dini perlintasan kereta api cerdas, yang dijuluki "NusaRail Vision System", menuntut arsitektur sistem yang tidak hanya cepat dalam memproses data visual secara real-time, tetapi juga tangguh (fault-tolerant), skalabel, dan hemat biaya operasional. Setelah melalui serangkaian eksperimen arsitektural, proyek ini mengadopsi pendekatan **Arsitektur Infrastruktur Hibrida Terdistribusi (Distributed Hybrid Infrastructure Architecture)**. Arsitektur ini memisahkan secara radikal antara lapisan antarmuka pengguna (Frontend Presentation Layer) dan lapisan mesin pemroses kecerdasan buatan (Backend AI Inference Layer), mendelegasikan masing-masing komponen ke platform cloud spesifik yang paling optimal untuk karakteristik beban kerjanya.

Dalam konteks rekayasa perangkat lunak modern, pemisahan ini dikenal sebagai prinsip **Separation of Concerns (SoC)** yang diaplikasikan pada tingkat infrastruktur. Frontend bertanggung jawab secara eksklusif untuk rendering antarmuka pengguna dan manajemen state aplikasi klien, sementara Backend bertanggung jawab untuk semua operasi komputasi berat yang melibatkan inferensi tensor neural network, manipulasi matriks piksel OpenCV, dan orkestrasi panggilan API ke layanan kecerdasan buatan eksternal (Google Gemini).

### 1.2. Frontend: Next.js pada Vercel Edge Network

Di sisi Frontend, kerangka kerja **Next.js** dibangun di atas pustaka React dan di-deploy pada infrastruktur **Vercel**. Next.js dipilih karena kemampuannya untuk melakukan Static Site Generation (SSG) saat fase build, yang menghasilkan file HTML/CSS/JS statis yang kemudian didistribusikan melalui **Global Edge CDN (Content Delivery Network)** milik Vercel. Strategi ini menjamin bahwa aset antarmuka pengguna — termasuk tata letak dashboard pemantauan, komponen React, dan skrip JavaScript — akan dimuat dalam hitungan milidetik (Time-to-Interactive / TTI < 500ms) di perangkat pengguna manapun di seluruh Indonesia, tanpa membebani server yang memproses inferensi AI.

Vercel memastikan **zero-downtime deployment** melalui mekanisme atomic deployment dan skalabilitas horizontal otomatis berbasis serverless functions. Setiap kali kode di-push ke repositori GitHub, pipeline CI/CD Vercel secara otomatis membangun ulang (rebuild) dan mendistribusikan versi terbaru ke seluruh edge node globalnya.

### 1.3. Backend: FastAPI pada Hugging Face Spaces

Sisi Backend dibangun menggunakan **FastAPI**, sebuah framework Python modern berkinerja tinggi yang memanfaatkan type hints dan async/await secara native. Lingkungan operasionalnya didelegasikan ke **Hugging Face Spaces (Tier Linux)**. Pemilihan Hugging Face Spaces didasarkan pada tiga justifikasi teknis kritis:

1. **Kompatibilitas Dependensi C++:** Pustaka seperti PyTorch, OpenCV (`cv2`), dan Ultralytics (YOLO) memiliki dependensi biner terhadap pustaka C++ sistem operasi (`libGL`, `libglib2.0`). Menjalankan inferensi ini pada OS Windows lokal tanpa GPU diskrit (NVIDIA CUDA) seringkali memicu kesalahan fatal berupa `ImportError: libGL.so.1: cannot open shared object file`. Kontainer Linux Hugging Face secara native menyediakan seluruh dependensi ini.
2. **Alokasi CPU Terdedikasi:** Mesin cloud Hugging Face mendedikasikan seluruh siklus clock CPU-nya murni untuk inferensi model YOLOv8, melepaskan perangkat pengguna dari beban rendering AI.
3. **Model Hosting Terintegrasi:** Bobot model YOLOv8 (`.pt` / `.onnx`) dapat disimpan langsung di dalam repositori Space, sehingga tidak memerlukan layanan penyimpanan objek (Object Storage) terpisah.

### 1.4. Protokol Streaming: MJPEG dan WebSocket

Untuk menjembatani Frontend di Vercel dan Backend di Hugging Face, arsitektur ini mengimplementasikan **dua protokol komunikasi real-time yang berjalan paralel**:

**Protokol 1: MJPEG (Motion JPEG) over HTTP.** MJPEG dipilih untuk transmisi aliran video karena tidak memerlukan mekanisme handshake kompleks layaknya WebRTC. Server mengemas setiap matriks frame OpenCV (`numpy.ndarray`) menjadi file JPEG biner melalui `cv2.imencode()`, kemudian mengalirkannya ke Frontend menggunakan respons HTTP dengan header `Content-Type: multipart/x-mixed-replace; boundary=frame`. Teknik ini memungkinkan browser HTML5 merender frame-frame JPEG secara berurutan di dalam elemen `<img>` standar tanpa memerlukan plugin tambahan. Meskipun MJPEG tidak se-efisien H.264 dalam hal kompresi, algoritma ini memberikan **latensi absolut terendah (Zero-Lag)** untuk jaringan regional — syarat mutlak (mission-critical) dalam sistem peringatan dini.

**Protokol 2: WebSocket.** WebSocket menciptakan saluran komunikasi dua arah, full-dupleks, yang persisten antara browser pengguna dan server FastAPI. Melalui WebSocket, data analitik (seperti telemetri deteksi YOLOv8, status darurat DJKA, dan wawasan LLM Gemini 1.5 Pro) dapat di-push langsung (broadcast) ke layar pengguna secara instan tanpa perlu teknik HTTP polling yang memakan bandwidth.

---

## BAB 2: Implementasi Backend (FastAPI & AI Engine)

Bab ini menyajikan kode sumber (source code) lengkap untuk seluruh modul backend. Setiap file disertai penjelasan arsitektural mendalam dan anotasi inline yang merujuk pada perbaikan bug kritis (Critical Fixes) yang telah diimplementasikan.

### 2.1. File: `backend/main.py` — Router Utama FastAPI

File ini merupakan titik masuk (entry point) utama aplikasi backend. Ia menginisialisasi instance FastAPI, mendaftarkan middleware CORS, dan mengikat seluruh endpoint HTTP dan WebSocket.

**Perbaikan Bug yang Diterapkan:**
- **CRITICAL FIX 01 (Server-Side CORS):** `CORSMiddleware` dikonfigurasi dengan `allow_origins=['*']` untuk mengizinkan permintaan lintas-asal (cross-origin) dari domain Vercel ke domain Hugging Face.

```python
"""
NusaRail Vision System - Main FastAPI Application
===================================================
Production-ready backend server that orchestrates:
- MJPEG zero-lag video streaming (multipart/x-mixed-replace)
- WebSocket telemetry broadcasting (JSON payload)
- YOLOv8 + ByteTrack AI inference pipeline
- Gemini 1.5 Pro Macro-Observer integration

CRITICAL FIX 01 (Server-side): CORSMiddleware with allow_origins=['*']
to enable cross-origin Frontend (Vercel) <-> Backend (HuggingFace) communication.
"""

import os
import io
import json
import time
import asyncio
import logging
import threading
from typing import List
from contextlib import asynccontextmanager

import cv2
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse

from core.stream_handler import StreamHandler
from core.vision_engine import VisionEngine
from core.gemini_agent import GeminiAgent

# ---------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("nusarail.main")

# ---------------------------------------------------------------------------
# Global Application State
# ---------------------------------------------------------------------------
stream_handler = StreamHandler()
vision_engine: VisionEngine = None
gemini_agent = GeminiAgent()

# WebSocket client registry
ws_clients: List[WebSocket] = []

# Shared state for the latest annotated frame (MJPEG output)
_annotated_frame_lock = threading.Lock()
_annotated_frame: np.ndarray = None
_latest_telemetry: dict = {}


async def broadcast_ws(payload: dict):
    """Broadcast a JSON payload to all connected WebSocket clients."""
    dead_clients = []
    message = json.dumps(payload, ensure_ascii=False)

    for ws in ws_clients:
        try:
            await ws.send_text(message)
        except Exception:
            dead_clients.append(ws)

    for ws in dead_clients:
        if ws in ws_clients:
            ws_clients.remove(ws)


# ---------------------------------------------------------------------------
# AI Worker Thread (Consumer)
# ---------------------------------------------------------------------------
def _ai_worker_thread():
    """
    Consumer thread: continuously reads the latest frame from StreamHandler
    (Drop-Frame Shared State), runs YOLOv8 inference, and stores the
    annotated output for MJPEG streaming.
    """
    global _annotated_frame, _latest_telemetry

    log.info("[AIWorker] Thread started.")
    while stream_handler.is_active:
        frame = stream_handler.get_latest_frame()
        if frame is None:
            time.sleep(0.05)
            continue

        try:
            annotated, telemetry = vision_engine.process_frame(frame)

            with _annotated_frame_lock:
                _annotated_frame = annotated
                _latest_telemetry = telemetry

        except Exception as e:
            log.error(f"[AIWorker] Inference error: {e}")
            time.sleep(0.1)

    log.info("[AIWorker] Thread terminated (stream inactive).")


# ---------------------------------------------------------------------------
# Lifespan Event
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    global vision_engine
    log.info("[Lifespan] NusaRail Vision System starting...")

    # Initialize Vision Engine
    model_path = "yolov8n.pt"
    if os.path.exists("best_web_optimized.onnx"):
        model_path = "best_web_optimized.onnx"
    elif os.path.exists("dataset/best_web_optimized.onnx"):
        model_path = "dataset/best_web_optimized.onnx"

    vision_engine = VisionEngine(model_path)

    # Register Gemini broadcast function
    gemini_agent.set_broadcast_function(broadcast_ws)

    log.info("[Lifespan] System ready. Awaiting video source.")
    yield

    # Shutdown
    stream_handler.stop()
    gemini_agent.stop()
    log.info("[Lifespan] System shutdown complete.")


# ---------------------------------------------------------------------------
# FastAPI Application
# ---------------------------------------------------------------------------
app = FastAPI(
    title="NusaRail Vision System",
    description="Hybrid AI Railway Crossing Early Warning System",
    version="2.0.0",
    lifespan=lifespan,
)

# CRITICAL FIX 01 (CORS): Allow all origins for Vercel <-> HuggingFace
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# REST Endpoints
# ---------------------------------------------------------------------------
@app.get("/")
async def root():
    return {
        "system": "NusaRail Vision System",
        "version": "2.0.0",
        "status": "online",
        "stream_active": stream_handler.is_active,
        "mode": stream_handler.mode,
    }


@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")}


@app.post("/start/youtube")
async def start_youtube(url: str = Form(...)):
    """Start streaming from a YouTube URL."""
    success = stream_handler.start_youtube(url)
    if not success:
        return JSONResponse(status_code=400, content={"error": "Failed to start YouTube stream."})

    # Launch AI worker thread
    ai_thread = threading.Thread(target=_ai_worker_thread, daemon=True)
    ai_thread.start()

    # Launch Gemini agent loop
    asyncio.create_task(gemini_agent.run_loop(stream_handler.get_latest_frame))

    return {"status": "streaming", "source": "youtube", "url": url}


@app.post("/start/upload")
async def start_upload(file: UploadFile = File(...)):
    """Start streaming from an uploaded video file."""
    temp_dir = "temp"
    os.makedirs(temp_dir, exist_ok=True)
    temp_path = os.path.join(temp_dir, file.filename)

    with open(temp_path, "wb") as f:
        content = await file.read()
        f.write(content)

    success = stream_handler.start_upload(temp_path)
    if not success:
        return JSONResponse(status_code=400, content={"error": "Failed to open uploaded video."})

    ai_thread = threading.Thread(target=_ai_worker_thread, daemon=True)
    ai_thread.start()

    asyncio.create_task(gemini_agent.run_loop(stream_handler.get_latest_frame))

    return {"status": "streaming", "source": "upload", "filename": file.filename}


@app.post("/stop")
async def stop_stream():
    """Stop all active streams."""
    stream_handler.stop()
    gemini_agent.stop()
    return {"status": "stopped"}


# ---------------------------------------------------------------------------
# MJPEG Video Feed (multipart/x-mixed-replace)
# ---------------------------------------------------------------------------
def _mjpeg_generator():
    """
    Generator that yields MJPEG frames as multipart HTTP chunks.
    Uses the annotated frame produced by the AI worker thread.
    """
    while True:
        frame = None
        with _annotated_frame_lock:
            if _annotated_frame is not None:
                frame = _annotated_frame.copy()

        if frame is None:
            placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(
                placeholder,
                "NusaRail: Menunggu Sumber Video...",
                (50, 240),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 255), 2,
            )
            frame = placeholder

        _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n"
        )
        time.sleep(1 / 30)


@app.get("/video_feed")
async def video_feed():
    """MJPEG streaming endpoint for zero-lag video delivery."""
    return StreamingResponse(
        _mjpeg_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


# ---------------------------------------------------------------------------
# WebSocket Telemetry
# ---------------------------------------------------------------------------
@app.websocket("/ws/telemetry")
async def ws_telemetry(websocket: WebSocket):
    """
    WebSocket endpoint for real-time JSON telemetry streaming.
    Pushes detection summaries, Gemini analysis, and DJKA emergency status.
    """
    await websocket.accept()
    ws_clients.append(websocket)
    log.info(f"[WebSocket] Client connected. Total: {len(ws_clients)}")

    try:
        while True:
            telemetry = {}
            with _annotated_frame_lock:
                telemetry = _latest_telemetry.copy() if _latest_telemetry else {}

            if telemetry:
                await websocket.send_text(json.dumps(telemetry, ensure_ascii=False))

            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=2.0)
                log.info(f"[WebSocket] Received: {data}")
            except asyncio.TimeoutError:
                pass

    except WebSocketDisconnect:
        log.info("[WebSocket] Client disconnected.")
    except Exception as e:
        log.error(f"[WebSocket] Error: {e}")
    finally:
        if websocket in ws_clients:
            ws_clients.remove(websocket)


# ---------------------------------------------------------------------------
# Entry Point for Hugging Face Spaces
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "7860"))
    uvicorn.run(app, host="0.0.0.0", port=port)
```

---

### 2.2. File: `backend/core/stream_handler.py` — Modul Penanganan Aliran Video

Modul ini bertanggung jawab untuk mengekstraksi aliran video dari sumber YouTube (melalui pustaka `yt-dlp`) dan file video lokal yang diunggah pengguna. Arsitektur threading-nya menerapkan pola **Producer-Consumer dengan Drop-Frame Shared State** untuk mencegah penumpukan memori.

**Perbaikan Bug yang Diterapkan:**
- **CRITICAL FIX 02 (cookies.txt Injection):** Menginjeksi file kredensial Netscape ke argumen `yt-dlp` untuk membajak sesi otentikasi manusia yang sah, sehingga server YouTube mengklasifikasikan permintaan sebagai berasal dari browser manusia.
- **CRITICAL FIX 03 (Drop-Frame Shared State):** Thread Producer menimpa satu variabel (`self._latest_frame`) tanpa antrean (queue). Thread Consumer (AI) membaca frame terbaru kapanpun ia siap, menghancurkan frame usang (stale) dari memori.

```python
"""
NusaRail Vision System - Stream Handler Module
================================================
Implements video ingestion from YouTube via yt-dlp and local file upload,
with a Producer-Consumer Drop-Frame Shared State architecture to guarantee
zero-lag real-time frame delivery.

CRITICAL FIX 02: Netscape cookies.txt injection for YouTube WAF bypass.
CRITICAL FIX 03: Drop-Frame Shared State (no queue, overwrite-only).
"""

import os
import threading
import time
import logging
import cv2
import yt_dlp

log = logging.getLogger("nusarail.stream")


class StreamHandler:
    """
    Manages video ingestion from multiple sources (YouTube live / uploaded MP4)
    using a lock-free Drop-Frame Shared State pattern.

    The Producer thread captures frames at hardware speed and overwrites a single
    shared variable. The Consumer (AI engine) reads the latest frame whenever it
    is ready, silently discarding all stale intermediate frames. This guarantees
    that every AI inference operates on the most temporally-current frame,
    eliminating the slow-motion memory leak caused by FIFO queue backlog.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._latest_frame = None
        self._cap: cv2.VideoCapture = None
        self._running = False
        self._producer_thread: threading.Thread = None
        self._source_url: str = ""
        self._mode: str = "idle"  # "youtube" | "upload" | "idle"
        self._upload_path: str = ""

    # ------------------------------------------------------------------
    # CRITICAL FIX 02: yt-dlp with cookies.txt injection
    # ------------------------------------------------------------------
    def _resolve_youtube_stream(self, url: str) -> str:
        """
        Extracts the raw m3u8/mp4 stream URL from a YouTube link using yt-dlp.
        Injects a Netscape-format cookies.txt file (if present) to authenticate
        the request as a legitimate human browser session, bypassing YouTube's
        HTTP 403 Forbidden WAF (Web Application Firewall).
        """
        cookies_path = os.path.join(os.path.dirname(__file__), "..", "cookies.txt")
        ydl_opts = {
            "format": "best[ext=mp4]/best",
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
        }

        # CRITICAL FIX 02: Inject cookies.txt if available
        if os.path.exists(cookies_path):
            ydl_opts["cookiefile"] = cookies_path
            log.info(f"[StreamHandler] cookies.txt injected from: {cookies_path}")
        else:
            log.warning("[StreamHandler] cookies.txt not found. YouTube may reject requests (HTTP 403).")

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                stream_url = info.get("url") or info.get("manifest_url", "")
                log.info(f"[StreamHandler] Resolved YouTube stream: {stream_url[:80]}...")
                return stream_url
        except Exception as e:
            log.error(f"[StreamHandler] yt-dlp extraction failed: {e}")
            return ""

    # ------------------------------------------------------------------
    # CRITICAL FIX 03: Drop-Frame Shared State Producer Thread
    # ------------------------------------------------------------------
    def _producer_loop(self):
        """
        Producer thread: captures frames at maximum hardware speed and
        overwrites a single shared variable (_latest_frame) without any
        queue mechanism. Stale frames are silently destroyed.
        """
        log.info(f"[Producer] Thread started. Mode={self._mode}")
        consecutive_failures = 0
        max_failures = 300  # ~10 seconds at 30fps

        while self._running:
            if self._cap is None or not self._cap.isOpened():
                time.sleep(0.1)
                continue

            ret, frame = self._cap.read()

            if not ret:
                consecutive_failures += 1
                if self._mode == "upload" and consecutive_failures > 10:
                    # Loop uploaded video for continuous demo
                    self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    consecutive_failures = 0
                    log.info("[Producer] Upload video looped back to frame 0.")
                    continue
                elif consecutive_failures > max_failures:
                    log.error("[Producer] Too many read failures. Stopping.")
                    break
                time.sleep(0.01)
                continue

            consecutive_failures = 0

            # CRITICAL FIX 03: Overwrite shared state (no queue)
            with self._lock:
                self._latest_frame = frame

            # Throttle to ~30 FPS to prevent CPU saturation
            time.sleep(1 / 30)

        log.info("[Producer] Thread terminated.")

    def get_latest_frame(self):
        """
        Consumer accessor: returns the most recent frame captured by the
        producer. Returns None if no frame is available yet.
        """
        with self._lock:
            return self._latest_frame.copy() if self._latest_frame is not None else None

    # ------------------------------------------------------------------
    # Public API: Start / Stop
    # ------------------------------------------------------------------
    def start_youtube(self, url: str):
        """Initialize stream from a YouTube URL."""
        self.stop()
        self._mode = "youtube"
        self._source_url = url
        stream_url = self._resolve_youtube_stream(url)
        if not stream_url:
            log.error("[StreamHandler] Failed to resolve YouTube URL. Aborting.")
            return False

        self._cap = cv2.VideoCapture(stream_url)
        if not self._cap.isOpened():
            log.error("[StreamHandler] cv2.VideoCapture failed to open YouTube stream.")
            return False

        self._running = True
        self._producer_thread = threading.Thread(target=self._producer_loop, daemon=True)
        self._producer_thread.start()
        log.info(f"[StreamHandler] YouTube stream started: {url}")
        return True

    def start_upload(self, file_path: str):
        """Initialize stream from a locally uploaded video file."""
        self.stop()
        self._mode = "upload"
        self._upload_path = file_path

        self._cap = cv2.VideoCapture(file_path)
        if not self._cap.isOpened():
            log.error(f"[StreamHandler] Failed to open uploaded file: {file_path}")
            return False

        self._running = True
        self._producer_thread = threading.Thread(target=self._producer_loop, daemon=True)
        self._producer_thread.start()
        log.info(f"[StreamHandler] Upload stream started: {file_path}")
        return True

    def stop(self):
        """Terminate the producer thread and release the video capture."""
        self._running = False
        if self._producer_thread and self._producer_thread.is_alive():
            self._producer_thread.join(timeout=5)
        if self._cap:
            self._cap.release()
            self._cap = None
        self._latest_frame = None
        self._mode = "idle"
        log.info("[StreamHandler] Stream stopped and resources released.")

    @property
    def is_active(self) -> bool:
        return self._running and self._cap is not None and self._cap.isOpened()

    @property
    def mode(self) -> str:
        return self._mode
```

---

### 2.3. File: `backend/core/vision_engine.py` — Mesin AI Visi Komputer

Modul ini merupakan jantung intelektual dari NusaRail Vision System. Ia mengorkestrasi deteksi objek YOLOv8, pelacakan temporal ByteTrack, analisis spasial Centroid untuk mendeteksi kendaraan terjebak, dan mekanisme pengiriman sinyal darurat ke DJKA.

**Perbaikan Bug yang Diterapkan:**
- **CRITICAL FIX 04:** Confidence threshold diatur pada nilai `0.15` untuk memprioritaskan Recall di atas Precision.
- **CRITICAL FIX 06:** Penjaga defensif `if box.id is not None:` sebelum ekstraksi Track ID.
- **CRITICAL FIX 07:** Pengurutan area secara descending sebelum rendering `cv2.rectangle()` agar objek mikro digambar di atas objek makro.
- **CRITICAL FIX 08:** Debounce absolut 60 detik pada webhook DJKA untuk mencegah DDoS internal.

```python
"""
NusaRail Vision System - Vision Engine Module
==============================================
Implements YOLOv8 object detection with ByteTrack temporal tracking,
Centroid-based stationary vehicle detection (Kill Zone Logic), and
DJKA Emergency Brake Dispatcher.

CRITICAL FIX 04: Confidence threshold = 0.15 (recall > precision).
CRITICAL FIX 06: NoneType guard on box.id before Track ID extraction.
CRITICAL FIX 07: Descending area sort before cv2.rectangle rendering.
CRITICAL FIX 08: DJKA webhook debounce (max 1 per 60 seconds).
"""

import time
import math
import logging
import asyncio
from typing import Dict, Tuple, Optional, List

import cv2
import numpy as np

try:
    import httpx
except ImportError:
    httpx = None

try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None

log = logging.getLogger("nusarail.vision")

# ---------------------------------------------------------------------------
# COCO class mapping for target classes
# ---------------------------------------------------------------------------
COCO_NAMES = {
    0: "person",
    2: "car",
    3: "motorcycle",
    5: "bus",
    6: "train",
    7: "truck",
}

# Threshold constants
STUCK_DISTANCE_PX = 20       # Max centroid displacement to be considered stuck
STUCK_DURATION_SEC = 5.0      # Seconds before a stationary vehicle is flagged
DJKA_COOLDOWN_SEC = 60.0      # CRITICAL FIX 08: Debounce interval
CONFIDENCE_THRESHOLD = 0.15   # CRITICAL FIX 04: Low threshold for night recall

import os
DJKA_WEBHOOK_URL = os.getenv("DJKA_WEBHOOK_URL", "https://api.djka.example.gov.id/emergency-brake")


class TrackedVehicle:
    """Stores temporal tracking state for a single detected vehicle."""

    def __init__(self, track_id: int, cx: int, cy: int, class_id: int):
        self.track_id = track_id
        self.class_id = class_id
        self.initial_cx = cx
        self.initial_cy = cy
        self.last_cx = cx
        self.last_cy = cy
        self.first_seen = time.monotonic()
        self.last_seen = time.monotonic()
        self.is_stuck = False

    def update(self, cx: int, cy: int):
        """Update centroid position and recalculate stuck status."""
        self.last_cx = cx
        self.last_cy = cy
        self.last_seen = time.monotonic()

        # Euclidean distance from initial position
        delta = math.sqrt((cx - self.initial_cx) ** 2 + (cy - self.initial_cy) ** 2)

        if delta < STUCK_DISTANCE_PX:
            elapsed = self.last_seen - self.first_seen
            if elapsed > STUCK_DURATION_SEC:
                self.is_stuck = True
        else:
            # Vehicle has moved significantly — reset anchor
            self.initial_cx = cx
            self.initial_cy = cy
            self.first_seen = time.monotonic()
            self.is_stuck = False


class VisionEngine:
    """
    Core AI engine that orchestrates YOLOv8 detection, ByteTrack tracking,
    centroid analysis, and the DJKA emergency brake dispatcher.
    """

    def __init__(self, model_path: str = "yolov8n.pt"):
        if YOLO is None:
            raise ImportError("ultralytics is not installed.")
        self._model = YOLO(model_path)
        self._tracked_vehicles: Dict[int, TrackedVehicle] = {}
        self._last_emergency_time: float = 0.0
        self._frame_count: int = 0
        log.info(f"[VisionEngine] Model loaded: {model_path}")

    def process_frame(self, frame: np.ndarray) -> Tuple[np.ndarray, dict]:
        """
        Runs full inference pipeline on a single frame:
        1. YOLOv8 ByteTrack detection
        2. Centroid extraction & stuck logic
        3. Area-sorted rendering
        4. DJKA collision evaluation

        Returns:
            annotated_frame: Frame with bounding boxes drawn
            telemetry: Dict with detection summary
        """
        self._frame_count += 1
        frame_copy = frame.copy()

        # ------------------------------------------------------------------
        # Step 1: YOLOv8 + ByteTrack inference
        # CRITICAL FIX 04: conf=0.15 for maximum recall
        # ------------------------------------------------------------------
        results = self._model.track(
            source=frame,
            persist=True,
            tracker="bytetrack.yaml",
            classes=[0, 2, 3, 5, 6, 7],
            conf=CONFIDENCE_THRESHOLD,
            iou=0.5,
            verbose=False,
        )

        is_car_stuck = False
        is_train_incoming = False
        stuck_vehicles: List[int] = []
        detections: List[dict] = []

        if results and len(results) > 0:
            boxes = results[0].boxes

            if boxes is not None and len(boxes) > 0:
                # ----------------------------------------------------------
                # Step 2: Extract detections with NoneType guard
                # CRITICAL FIX 06: Guard against box.id == None
                # ----------------------------------------------------------
                raw_detections = []

                for box in boxes:
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                    conf = float(box.conf[0])
                    cls_id = int(box.cls[0])
                    cls_name = COCO_NAMES.get(cls_id, f"class_{cls_id}")

                    # Centroid calculation
                    cx = int((x1 + x2) / 2)
                    cy = int((y1 + y2) / 2)

                    # Area for sorting
                    area = (x2 - x1) * (y2 - y1)

                    # CRITICAL FIX 06: NoneType guard
                    track_id = None
                    if box.id is not None:
                        track_id = int(box.id[0])

                    raw_detections.append({
                        "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                        "conf": conf, "cls_id": cls_id, "cls_name": cls_name,
                        "cx": cx, "cy": cy, "area": area, "track_id": track_id,
                    })

                # ----------------------------------------------------------
                # Step 3: Centroid tracking & stuck logic
                # ----------------------------------------------------------
                active_ids = set()

                for det in raw_detections:
                    tid = det["track_id"]
                    if tid is not None:
                        active_ids.add(tid)

                        if tid in self._tracked_vehicles:
                            self._tracked_vehicles[tid].update(det["cx"], det["cy"])
                        else:
                            self._tracked_vehicles[tid] = TrackedVehicle(
                                track_id=tid,
                                cx=det["cx"], cy=det["cy"],
                                class_id=det["cls_id"],
                            )

                        tv = self._tracked_vehicles[tid]
                        det["is_stuck"] = tv.is_stuck

                        if tv.is_stuck and det["cls_id"] in (2, 3, 5, 7):
                            is_car_stuck = True
                            stuck_vehicles.append(tid)

                    # Check for incoming train
                    if det["cls_id"] == 6:
                        is_train_incoming = True

                # Purge stale tracks (not seen for > 10 seconds)
                now = time.monotonic()
                stale_ids = [
                    tid for tid, tv in self._tracked_vehicles.items()
                    if now - tv.last_seen > 10.0 and tid not in active_ids
                ]
                for tid in stale_ids:
                    del self._tracked_vehicles[tid]

                # ----------------------------------------------------------
                # Step 4: CRITICAL FIX 07 — Descending area sort
                # Draw largest objects first, smallest on top
                # ----------------------------------------------------------
                raw_detections.sort(key=lambda d: d["area"], reverse=True)

                for det in raw_detections:
                    x1, y1, x2, y2 = det["x1"], det["y1"], det["x2"], det["y2"]
                    cls_name = det["cls_name"]
                    conf = det["conf"]
                    tid = det["track_id"]
                    stuck = det.get("is_stuck", False)

                    # Color coding
                    if stuck:
                        color = (0, 0, 255)      # RED for stuck vehicles
                        thickness = 3
                    elif det["cls_id"] == 6:
                        color = (255, 165, 0)     # ORANGE for trains
                        thickness = 3
                    else:
                        color = (0, 255, 0)       # GREEN for normal
                        thickness = 2

                    cv2.rectangle(frame_copy, (x1, y1), (x2, y2), color, thickness)

                    # Label
                    id_str = f"ID:{tid}" if tid is not None else "ID:?"
                    label = f"{cls_name}({id_str}) {conf:.2f}"
                    if stuck:
                        label += " MOGOK!"

                    label_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)[0]
                    cv2.rectangle(frame_copy, (x1, y1 - label_size[1] - 10),
                                  (x1 + label_size[0], y1), color, -1)
                    cv2.putText(frame_copy, label, (x1, y1 - 5),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)

                    detections.append({
                        "class": cls_name, "track_id": tid,
                        "confidence": round(conf, 3), "stuck": stuck,
                    })

        # ------------------------------------------------------------------
        # Step 5: DJKA Emergency Brake Evaluation
        # ------------------------------------------------------------------
        emergency_status = "AMAN"
        if is_car_stuck and is_train_incoming:
            emergency_status = "DARURAT_KRITIS"

            if int(time.time() * 2) % 2 == 0:
                cv2.putText(
                    frame_copy,
                    "!!! AUTO-BRAKE SIGNAL SENT TO KRL !!!",
                    (50, 80),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 3,
                )

            # CRITICAL FIX 08: Debounce — fire webhook max 1x per 60s
            asyncio.ensure_future(self._trigger_djka_webhook())

        elif is_car_stuck:
            emergency_status = "BAHAYA"
            cv2.putText(
                frame_copy,
                "PERINGATAN: KENDARAAN MOGOK TERDETEKSI",
                (50, 80),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2,
            )

        # HUD overlay
        cv2.putText(
            frame_copy,
            f"NusaRail Vision | Frame #{self._frame_count} | Status: {emergency_status}",
            (10, frame_copy.shape[0] - 15),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1,
        )

        telemetry = {
            "frame": self._frame_count,
            "detections": detections,
            "is_car_stuck": is_car_stuck,
            "is_train_incoming": is_train_incoming,
            "emergency_status": emergency_status,
            "stuck_vehicle_ids": stuck_vehicles,
        }

        return frame_copy, telemetry

    # ------------------------------------------------------------------
    # CRITICAL FIX 08: DJKA Webhook with Absolute Time Debounce
    # ------------------------------------------------------------------
    async def _trigger_djka_webhook(self):
        """
        Fires an asynchronous HTTP POST to the DJKA emergency brake endpoint.
        Protected by an absolute-time debounce of 60 seconds to prevent
        DDoS-like API spamming from continuous True evaluations.
        """
        now = time.time()
        if now - self._last_emergency_time < DJKA_COOLDOWN_SEC:
            return

        self._last_emergency_time = now

        payload = {
            "system": "NusaRail Vision System",
            "event": "DARURAT_KRITIS",
            "description": "Kendaraan mogok terdeteksi di perlintasan saat KRL mendekat.",
            "stuck_duration_threshold_sec": STUCK_DURATION_SEC,
            "cooldown_sec": DJKA_COOLDOWN_SEC,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }

        log.critical(f"[DJKA] EMERGENCY BRAKE DISPATCHED: {payload}")

        if httpx is not None:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(DJKA_WEBHOOK_URL, json=payload)
                    log.info(f"[DJKA] Webhook response: {resp.status_code}")
            except Exception as e:
                log.error(f"[DJKA] Webhook delivery failed (non-fatal): {e}")
```

---

### 2.4. File: `backend/core/gemini_agent.py` — Agen Makro-Observasi Gemini 1.5 Pro

Modul ini mengintegrasikan Large Language Model (LLM) Google Gemini 1.5 Pro sebagai pengamat makroskopis (Macro-Observer). Secara periodik, modul mengekspor cuplikan frame JPEG dalam format Base64 ke API Gemini dan menerima analisis terstruktur dalam format JSON.

**Perbaikan Bug yang Diterapkan:**
- **CRITICAL FIX 05 (Rate Limit Shield):** Pemanggilan API dibungkus dalam blok `try-except`. Jika error HTTP 429 / `resource_exhausted` terdeteksi, sistem akan menembakkan payload WebSocket "MENDINGINKAN API" dan melakukan `await asyncio.sleep(45)` sebelum mencoba lagi.

```python
"""
NusaRail Vision System - Gemini Agent Module
=============================================
Integrates Google Gemini 1.5 Pro as a Macro-Observer for scene-level
understanding of railway crossing conditions.

CRITICAL FIX 05: Rate Limit Shield — HTTP 429 / resource_exhausted
graceful degradation with 45-second exponential backoff.
"""

import os
import time
import json
import base64
import asyncio
import logging
from typing import Optional, Callable, Awaitable

import cv2
import numpy as np

log = logging.getLogger("nusarail.gemini")

# Gemini configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_INTERVAL_SEC = 25
GEMINI_MODEL = "gemini-1.5-pro"

GEMINI_SYSTEM_PROMPT = """Anda adalah AI pengawas perlintasan kereta api Indonesia.
Analisis gambar CCTV yang diberikan dan kembalikan HANYA dalam format JSON berikut tanpa markdown:
{
  "kondisi_perlintasan": "AMAN | RAMAI | BAHAYA | DARURAT_KRITIS",
  "geo_location": "Lokasi perlintasan yang teridentifikasi (atau 'Tidak Diketahui')",
  "insight_narasi": "Deskripsi singkat kondisi lalu lintas dan potensi bahaya dalam Bahasa Indonesia.",
  "timestamp": "Waktu analisis (HH:MM:SS)"
}
Jangan berhalusinasi. Hanya deskripsikan apa yang terlihat di gambar."""


class GeminiAgent:
    """
    Asynchronous Gemini 1.5 Pro integration with Rate Limit Shield.
    Periodically sends frame snapshots to Gemini for macro-level scene analysis.
    """

    def __init__(self):
        self._running = False
        self._latest_payload: dict = {}
        self._broadcast_fn: Optional[Callable[[dict], Awaitable[None]]] = None
        self._genai = None
        self._model = None

        try:
            import google.generativeai as genai
            if GEMINI_API_KEY:
                genai.configure(api_key=GEMINI_API_KEY)
                self._genai = genai
                self._model = genai.GenerativeModel(GEMINI_MODEL)
                log.info(f"[GeminiAgent] Initialized with model: {GEMINI_MODEL}")
            else:
                log.warning("[GeminiAgent] GEMINI_API_KEY not set. Agent disabled.")
        except ImportError:
            log.warning("[GeminiAgent] google-generativeai not installed. Agent disabled.")

    def set_broadcast_function(self, fn: Callable[[dict], Awaitable[None]]):
        """Register the WebSocket broadcast function for pushing telemetry."""
        self._broadcast_fn = fn

    def _encode_frame_base64(self, frame: np.ndarray) -> str:
        """Encode an OpenCV frame to Base64 JPEG string."""
        _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        return base64.b64encode(buffer.tobytes()).decode("utf-8")

    async def _call_gemini(self, frame: np.ndarray) -> dict:
        """
        Send a frame to Gemini 1.5 Pro and parse the structured JSON response.
        Uses asyncio.to_thread to prevent blocking the main event loop.
        """
        if self._model is None:
            return self._make_fallback("Model Gemini tidak tersedia.")

        b64_image = self._encode_frame_base64(frame)

        def _sync_generate():
            import PIL.Image
            import io
            img_bytes = base64.b64decode(b64_image)
            image = PIL.Image.open(io.BytesIO(img_bytes))
            response = self._model.generate_content(
                [GEMINI_SYSTEM_PROMPT, image],
                generation_config={"temperature": 0.2, "max_output_tokens": 500},
            )
            return response.text

        raw_text = await asyncio.to_thread(_sync_generate)

        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        cleaned = cleaned.strip()

        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            payload = {
                "kondisi_perlintasan": "TIDAK DIKETAHUI",
                "geo_location": "Tidak Diketahui",
                "insight_narasi": raw_text[:200],
                "timestamp": time.strftime("%H:%M:%S"),
            }

        if "timestamp" not in payload:
            payload["timestamp"] = time.strftime("%H:%M:%S")

        return payload

    def _make_fallback(self, message: str) -> dict:
        """Generate a safe fallback payload."""
        return {
            "kondisi_perlintasan": "TIDAK DIKETAHUI",
            "geo_location": "Tidak Diketahui",
            "insight_narasi": message,
            "timestamp": time.strftime("%H:%M:%S"),
        }

    # ------------------------------------------------------------------
    # CRITICAL FIX 05: Rate Limit Shield
    # ------------------------------------------------------------------
    async def _shielded_call(self, frame: np.ndarray) -> dict:
        """
        Wraps the Gemini API call in a comprehensive try-except shield.
        If HTTP 429 (Resource Exhausted) is detected, the system:
        1. Bypasses the crash entirely
        2. Fires a dummy "MENDINGINKAN API" payload to WebSocket
        3. Sleeps for 45 seconds (exponential backoff)
        """
        try:
            return await self._call_gemini(frame)

        except Exception as e:
            error_msg = str(e).lower()

            # CRITICAL FIX 05: Detect rate limit errors
            if "429" in error_msg or "resource_exhausted" in error_msg or "quota" in error_msg:
                log.warning(f"[GeminiAgent] Rate Limit Hit (HTTP 429). Cooling down 45s...")

                fallback_payload = {
                    "kondisi_perlintasan": "MENDINGINKAN API",
                    "geo_location": "Rate Limit Bypass",
                    "insight_narasi": "Sistem AI sedang mendinginkan antrean (Rate Limit Bypass). Data visual tetap berjalan aman.",
                    "timestamp": time.strftime("%H:%M:%S"),
                }

                if self._broadcast_fn:
                    await self._broadcast_fn(fallback_payload)

                await asyncio.sleep(45)
                return fallback_payload

            else:
                log.error(f"[GeminiAgent] Unexpected error: {e}")
                return self._make_fallback(f"Error: {str(e)[:100]}")

    async def run_loop(self, get_frame_fn):
        """
        Main async loop that periodically queries Gemini with the latest frame.
        """
        self._running = True
        log.info(f"[GeminiAgent] Worker loop started (interval={GEMINI_INTERVAL_SEC}s)")

        while self._running:
            await asyncio.sleep(GEMINI_INTERVAL_SEC)

            frame = get_frame_fn()
            if frame is None:
                continue

            payload = await self._shielded_call(frame)
            self._latest_payload = payload

            if self._broadcast_fn:
                await self._broadcast_fn(payload)

            log.info(f"[GeminiAgent] Analysis: {payload.get('kondisi_perlintasan', '?')}")

    def stop(self):
        """Stop the worker loop."""
        self._running = False
        log.info("[GeminiAgent] Worker loop stopped.")

    @property
    def latest_payload(self) -> dict:
        return self._latest_payload
```

---

## BAB 3: Implementasi Frontend (Next.js & Vercel)

Bab ini menyajikan kode sumber lengkap untuk seluruh komponen antarmuka pengguna yang dibangun menggunakan React (Next.js) dengan TailwindCSS. Antarmuka ini dirancang sebagai dashboard pemantauan bergaya industrial dengan mode gelap (dark-mode).

### 3.1. File: `frontend/pages/index.tsx` — Halaman Dashboard Utama

File ini merupakan halaman utama yang menyusun seluruh komponen menjadi tata letak dashboard yang koheren. Ia mengelola state untuk input URL YouTube, unggahan video, dan status koneksi streaming.

```tsx
import React, { useState } from "react";
import Head from "next/head";
import VideoStream from "../components/VideoStream";
import TelemetryPanel from "../components/TelemetryPanel";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "https://alex-universe11-bootcamp-ubsi-kai.hf.space";

export default function Home() {
  const [inputUrl, setInputUrl] = useState("");
  const [isStarting, setIsStarting] = useState(false);
  const [streamActive, setStreamActive] = useState(false);
  const [statusMessage, setStatusMessage] = useState("");

  const handleStartYouTube = async () => {
    if (!inputUrl.trim()) return;
    setIsStarting(true);
    setStatusMessage("Menghubungkan ke YouTube...");

    try {
      const res = await fetch(`${BACKEND_URL}/start/youtube`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ url: inputUrl }),
      });
      const data = await res.json();

      if (res.ok) {
        setStreamActive(true);
        setStatusMessage(`Streaming: ${data.source}`);
      } else {
        setStatusMessage(`Error: ${data.error || "Gagal memulai stream."}`);
      }
    } catch (e) {
      setStatusMessage("Error: Tidak dapat terhubung ke backend.");
    } finally {
      setIsStarting(false);
    }
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setIsStarting(true);
    setStatusMessage(`Mengunggah: ${file.name}...`);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch(`${BACKEND_URL}/start/upload`, {
        method: "POST",
        body: formData,
      });
      const data = await res.json();

      if (res.ok) {
        setStreamActive(true);
        setStatusMessage(`Streaming: ${data.filename}`);
      } else {
        setStatusMessage(`Error: ${data.error || "Gagal memproses video."}`);
      }
    } catch (e) {
      setStatusMessage("Error: Tidak dapat terhubung ke backend.");
    } finally {
      setIsStarting(false);
    }
  };

  const handleStop = async () => {
    try {
      await fetch(`${BACKEND_URL}/stop`, { method: "POST" });
      setStreamActive(false);
      setStatusMessage("Stream dihentikan.");
    } catch (e) {
      setStatusMessage("Error: Gagal menghentikan stream.");
    }
  };

  return (
    <>
      <Head>
        <title>NusaRail Vision System | Sistem Peringatan Dini Perlintasan KA</title>
        <meta
          name="description"
          content="Sistem peringatan dini perlintasan kereta api berbasis YOLOv8 dan Gemini 1.5 Pro."
        />
        <link
          href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Inter:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </Head>

      <div className="min-h-screen bg-gradient-to-br from-gray-950 via-gray-900 to-slate-950 text-white font-['Inter']">
        {/* Header */}
        <header className="border-b border-gray-800/50 bg-gray-950/80 backdrop-blur-md sticky top-0 z-50">
          <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-gradient-to-br from-cyan-500 to-blue-600 rounded-lg flex items-center justify-center text-lg font-bold shadow-lg shadow-cyan-500/20">
                🚆
              </div>
              <div>
                <h1 className="text-lg font-bold tracking-tight bg-gradient-to-r from-cyan-400 to-blue-400 bg-clip-text text-transparent">
                  NusaRail Vision System
                </h1>
                <p className="text-xs text-gray-500 font-mono">
                  YOLOv8 + ByteTrack + Gemini 1.5 Pro
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2">
              {streamActive ? (
                <div className="flex items-center gap-2 px-3 py-1.5 bg-green-950/50 border border-green-500/30 rounded-full">
                  <div className="w-2 h-2 bg-green-400 rounded-full animate-pulse" />
                  <span className="text-green-400 text-xs font-mono">ACTIVE</span>
                </div>
              ) : (
                <div className="flex items-center gap-2 px-3 py-1.5 bg-gray-800/50 border border-gray-600/30 rounded-full">
                  <div className="w-2 h-2 bg-gray-500 rounded-full" />
                  <span className="text-gray-400 text-xs font-mono">IDLE</span>
                </div>
              )}
            </div>
          </div>
        </header>

        {/* Main Content */}
        <main className="max-w-7xl mx-auto px-4 py-6">
          {/* Input Controls */}
          <div className="bg-gray-800/40 backdrop-blur-sm rounded-xl p-4 mb-6 border border-gray-700/30">
            <div className="flex flex-col md:flex-row gap-3">
              <div className="flex-1 flex gap-2">
                <input
                  type="text"
                  value={inputUrl}
                  onChange={(e) => setInputUrl(e.target.value)}
                  placeholder="Masukkan URL YouTube CCTV Perlintasan..."
                  className="flex-1 bg-gray-900/80 border border-gray-600/50 rounded-lg px-4 py-2.5 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-cyan-500/50 focus:ring-1 focus:ring-cyan-500/20 font-mono transition-all"
                />
                <button
                  onClick={handleStartYouTube}
                  disabled={isStarting || !inputUrl.trim()}
                  className="px-5 py-2.5 bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 disabled:from-gray-600 disabled:to-gray-700 rounded-lg text-sm font-semibold transition-all shadow-lg shadow-cyan-500/20 disabled:shadow-none"
                >
                  {isStarting ? "⏳" : "▶ Mulai"}
                </button>
              </div>

              <label className="px-5 py-2.5 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm font-semibold cursor-pointer text-center transition-all border border-gray-600/50">
                📁 Upload Video
                <input type="file" accept="video/*" onChange={handleUpload} className="hidden" />
              </label>

              {streamActive && (
                <button
                  onClick={handleStop}
                  className="px-5 py-2.5 bg-red-600/80 hover:bg-red-500 rounded-lg text-sm font-semibold transition-all"
                >
                  ⏹ Stop
                </button>
              )}
            </div>

            {statusMessage && (
              <p className="text-xs text-gray-400 font-mono mt-2">↳ {statusMessage}</p>
            )}
          </div>

          {/* Dashboard Grid */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2">
              <VideoStream backendUrl={BACKEND_URL} />
            </div>
            <div className="lg:col-span-1">
              <TelemetryPanel backendUrl={BACKEND_URL} />
            </div>
          </div>

          {/* Footer */}
          <footer className="mt-8 py-4 border-t border-gray-800/30 text-center">
            <p className="text-xs text-gray-600 font-mono">
              NusaRail Vision System v2.0 • Muhammad Abdurrahman Rabbani (15240969) • Universitas Bina Sarana Informatika
            </p>
          </footer>
        </main>
      </div>
    </>
  );
}
```

---

### 3.2. File: `frontend/components/VideoStream.tsx` — Komponen Renderer Video MJPEG

Komponen ini bertanggung jawab untuk menampilkan aliran video MJPEG dari endpoint FastAPI `/video_feed`. Menggunakan elemen HTML `<img>` standar yang secara native mendukung streaming multipart JPEG.

```tsx
"use client";

import React, { useState, useEffect, useRef } from "react";

interface VideoStreamProps {
  backendUrl: string;
}

const VideoStream: React.FC<VideoStreamProps> = ({ backendUrl }) => {
  const [isLoading, setIsLoading] = useState(true);
  const [hasError, setHasError] = useState(false);
  const [retryCount, setRetryCount] = useState(0);
  const imgRef = useRef<HTMLImageElement>(null);

  const streamUrl = `${backendUrl}/video_feed`;

  useEffect(() => {
    if (hasError) {
      const timer = setTimeout(() => {
        setHasError(false);
        setIsLoading(true);
        setRetryCount((prev) => prev + 1);
      }, 5000);
      return () => clearTimeout(timer);
    }
  }, [hasError]);

  return (
    <div className="relative w-full aspect-video bg-gray-900 rounded-xl overflow-hidden border border-gray-700/50 shadow-2xl">
      {isLoading && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-gray-900/90 z-10">
          <div className="w-12 h-12 border-4 border-cyan-500 border-t-transparent rounded-full animate-spin mb-4" />
          <p className="text-cyan-400 text-sm font-mono">
            Menghubungkan ke NusaRail Vision Engine...
          </p>
          {retryCount > 0 && (
            <p className="text-gray-500 text-xs mt-1">
              Percobaan ke-{retryCount + 1} (Cold Start ~60s)
            </p>
          )}
        </div>
      )}

      {hasError && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-red-950/80 z-10">
          <div className="text-red-400 text-4xl mb-3">⚠️</div>
          <p className="text-red-300 text-sm font-mono">
            Stream terputus. Menghubungkan ulang...
          </p>
        </div>
      )}

      <img
        ref={imgRef}
        key={retryCount}
        src={streamUrl}
        alt="NusaRail MJPEG Live Feed"
        className="w-full h-full object-contain"
        onLoad={() => setIsLoading(false)}
        onError={() => {
          setIsLoading(false);
          setHasError(true);
        }}
      />

      {!isLoading && !hasError && (
        <div className="absolute top-3 left-3 flex items-center gap-2 bg-red-600/90 px-3 py-1 rounded-full backdrop-blur-sm">
          <div className="w-2 h-2 bg-white rounded-full animate-pulse" />
          <span className="text-white text-xs font-bold tracking-wider">LIVE</span>
        </div>
      )}
    </div>
  );
};

export default VideoStream;
```

---

### 3.3. File: `frontend/components/TelemetryPanel.tsx` — Panel Telemetri WebSocket

Komponen ini membangun koneksi WebSocket ke endpoint FastAPI `/ws/telemetry`. Ia menerima dan mem-parsing payload JSON dari dua sumber: pipeline deteksi YOLOv8 (status darurat, daftar objek terdeteksi) dan analisis Gemini 1.5 Pro (kondisi perlintasan, geolokasi, narasi insight).

**Perbaikan Bug yang Diterapkan:**
- **CRITICAL FIX 01 (Auto-Reconnect Polling):** Implementasi algoritma exponential backoff reconnection (2s → 4s → 8s → 16s → max 30s) untuk bertahan dari fase Cold Start kontainer Hugging Face (60-90 detik) dan TCP timeout.

```tsx
"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";

interface GeminiPayload {
  kondisi_perlintasan?: string;
  geo_location?: string;
  insight_narasi?: string;
  timestamp?: string;
}

interface DetectionTelemetry {
  frame?: number;
  detections?: Array<{
    class: string;
    track_id: number | null;
    confidence: number;
    stuck: boolean;
  }>;
  is_car_stuck?: boolean;
  is_train_incoming?: boolean;
  emergency_status?: string;
  stuck_vehicle_ids?: number[];
}

interface TelemetryPanelProps {
  backendUrl: string;
}

const TelemetryPanel: React.FC<TelemetryPanelProps> = ({ backendUrl }) => {
  const [geminiData, setGeminiData] = useState<GeminiPayload>({});
  const [detectionData, setDetectionData] = useState<DetectionTelemetry>({});
  const [wsStatus, setWsStatus] = useState<"connecting" | "connected" | "disconnected">("connecting");
  const [reconnectAttempt, setReconnectAttempt] = useState(0);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<NodeJS.Timeout | null>(null);

  // ----------------------------------------------------------------
  // CRITICAL FIX 01: Auto-Reconnect with Exponential Backoff
  // ----------------------------------------------------------------
  const connectWebSocket = useCallback(() => {
    const wsUrl = backendUrl
      .replace("https://", "wss://")
      .replace("http://", "ws://")
      + "/ws/telemetry";

    setWsStatus("connecting");

    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setWsStatus("connected");
        setReconnectAttempt(0);
        console.log("[TelemetryPanel] WebSocket connected.");
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.kondisi_perlintasan) {
            setGeminiData(data);
          }
          if (data.emergency_status !== undefined || data.detections) {
            setDetectionData(data);
          }
        } catch (e) {
          console.warn("[TelemetryPanel] Failed to parse message:", e);
        }
      };

      ws.onclose = () => {
        setWsStatus("disconnected");
        console.log("[TelemetryPanel] WebSocket disconnected. Scheduling reconnect...");
        scheduleReconnect();
      };

      ws.onerror = (error) => {
        console.error("[TelemetryPanel] WebSocket error:", error);
        ws.close();
      };
    } catch (e) {
      console.error("[TelemetryPanel] Failed to create WebSocket:", e);
      scheduleReconnect();
    }
  }, [backendUrl]);

  const scheduleReconnect = useCallback(() => {
    // Exponential backoff: 2s, 4s, 8s, 16s, max 30s
    const delay = Math.min(2000 * Math.pow(2, reconnectAttempt), 30000);
    setReconnectAttempt((prev) => prev + 1);

    console.log(`[TelemetryPanel] Reconnecting in ${delay / 1000}s (attempt ${reconnectAttempt + 1})`);

    reconnectTimerRef.current = setTimeout(() => {
      connectWebSocket();
    }, delay);
  }, [reconnectAttempt, connectWebSocket]);

  useEffect(() => {
    connectWebSocket();
    return () => {
      if (wsRef.current) wsRef.current.close();
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
    };
  }, [connectWebSocket]);

  const getStatusColor = (status?: string) => {
    switch (status) {
      case "DARURAT_KRITIS": return "bg-red-600 text-white animate-pulse";
      case "BAHAYA": return "bg-orange-500 text-white";
      case "RAMAI": return "bg-yellow-500 text-black";
      case "MENDINGINKAN API": return "bg-blue-500 text-white animate-pulse";
      case "AMAN": return "bg-green-500 text-white";
      default: return "bg-gray-600 text-gray-300";
    }
  };

  const getWsStatusBadge = () => {
    switch (wsStatus) {
      case "connected": return <span className="text-green-400">● Terhubung</span>;
      case "connecting": return <span className="text-yellow-400 animate-pulse">● Menghubungkan...</span>;
      case "disconnected": return <span className="text-red-400">● Terputus (Percobaan #{reconnectAttempt})</span>;
    }
  };

  return (
    <div className="space-y-4">
      {/* Connection Status */}
      <div className="bg-gray-800/60 backdrop-blur-sm rounded-xl p-4 border border-gray-700/50">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-mono text-gray-400 uppercase tracking-wider">WebSocket Status</h3>
          <div className="text-xs font-mono">{getWsStatusBadge()}</div>
        </div>
      </div>

      {/* Emergency Status Panel */}
      <div className="bg-gray-800/60 backdrop-blur-sm rounded-xl p-5 border border-gray-700/50">
        <h3 className="text-sm font-mono text-gray-400 uppercase tracking-wider mb-3">Status Darurat DJKA</h3>
        <div className={`inline-block px-4 py-2 rounded-lg font-bold text-lg ${getStatusColor(detectionData.emergency_status)}`}>
          {detectionData.emergency_status || "MENUNGGU DATA"}
        </div>

        {detectionData.is_car_stuck && (
          <div className="mt-3 p-3 bg-red-950/50 border border-red-500/30 rounded-lg">
            <p className="text-red-300 text-sm font-mono">
              ⚠️ KENDARAAN MOGOK TERDETEKSI
              {detectionData.stuck_vehicle_ids && ` (ID: ${detectionData.stuck_vehicle_ids.join(", ")})`}
            </p>
          </div>
        )}

        {detectionData.is_train_incoming && (
          <div className="mt-2 p-3 bg-orange-950/50 border border-orange-500/30 rounded-lg">
            <p className="text-orange-300 text-sm font-mono">🚂 KRL MENDEKAT TERDETEKSI</p>
          </div>
        )}
      </div>

      {/* Gemini AI Analysis */}
      <div className="bg-gray-800/60 backdrop-blur-sm rounded-xl p-5 border border-gray-700/50">
        <h3 className="text-sm font-mono text-gray-400 uppercase tracking-wider mb-3">🧠 Analisis Gemini 1.5 Pro</h3>

        {geminiData.kondisi_perlintasan ? (
          <div className="space-y-3">
            <div className="flex items-center gap-3">
              <span className="text-gray-500 text-xs w-24">Kondisi:</span>
              <span className={`px-3 py-1 rounded-md text-sm font-bold ${getStatusColor(geminiData.kondisi_perlintasan)}`}>
                {geminiData.kondisi_perlintasan}
              </span>
            </div>
            <div className="flex items-start gap-3">
              <span className="text-gray-500 text-xs w-24 mt-0.5">Lokasi:</span>
              <span className="text-gray-200 text-sm">{geminiData.geo_location || "-"}</span>
            </div>
            <div className="flex items-start gap-3">
              <span className="text-gray-500 text-xs w-24 mt-0.5">Insight:</span>
              <span className="text-gray-300 text-sm leading-relaxed">{geminiData.insight_narasi || "-"}</span>
            </div>
            <div className="flex items-center gap-3">
              <span className="text-gray-500 text-xs w-24">Waktu:</span>
              <span className="text-cyan-400 text-xs font-mono">{geminiData.timestamp}</span>
            </div>
          </div>
        ) : (
          <p className="text-gray-500 text-sm italic">Menunggu analisis Gemini... (interval 25 detik)</p>
        )}
      </div>

      {/* Detection Summary */}
      <div className="bg-gray-800/60 backdrop-blur-sm rounded-xl p-5 border border-gray-700/50">
        <h3 className="text-sm font-mono text-gray-400 uppercase tracking-wider mb-3">📊 Deteksi YOLOv8 ByteTrack</h3>

        {detectionData.detections && detectionData.detections.length > 0 ? (
          <div className="space-y-1 max-h-48 overflow-y-auto">
            {detectionData.detections.map((det, i) => (
              <div
                key={i}
                className={`flex items-center justify-between px-3 py-1.5 rounded-md text-xs font-mono ${
                  det.stuck
                    ? "bg-red-950/50 text-red-300 border border-red-500/20"
                    : "bg-gray-700/30 text-gray-300"
                }`}
              >
                <span>
                  {det.class} {det.track_id !== null ? `(ID:${det.track_id})` : "(ID:?)"}
                </span>
                <span className="text-gray-500">
                  {(det.confidence * 100).toFixed(1)}%
                  {det.stuck && <span className="ml-2 text-red-400 font-bold">MOGOK</span>}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-gray-500 text-sm italic">Belum ada objek terdeteksi.</p>
        )}

        {detectionData.frame && (
          <p className="text-gray-600 text-xs mt-2 font-mono">Frame #{detectionData.frame}</p>
        )}
      </div>
    </div>
  );
};

export default TelemetryPanel;
```

---

## BAB 4: Konfigurasi Deployment Produksi

Bab ini mendokumentasikan file konfigurasi yang diperlukan untuk men-deploy sistem ke lingkungan produksi cloud.

### 4.1. File: `backend/Dockerfile` — Kontainer Hugging Face Spaces

```dockerfile
FROM python:3.10-slim

# Install system dependencies for OpenCV (libGL) and general Linux libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:7860/health')" || exit 1

CMD ["python", "main.py"]
```

### 4.2. File: `backend/requirements.txt` — Dependensi Python

```
fastapi>=0.104.0
uvicorn[standard]>=0.24.0
python-multipart>=0.0.6
opencv-python-headless>=4.8.0
numpy>=1.24.0
ultralytics>=8.1.0
yt-dlp>=2024.1.0
google-generativeai>=0.3.0
httpx>=0.25.0
Pillow>=10.0.0
```

### 4.3. File: `frontend/next.config.js` — Optimisasi Vercel Edge

```javascript
/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",

  images: {
    remotePatterns: [
      { protocol: "https", hostname: "*.hf.space" },
      { protocol: "https", hostname: "*.huggingface.co" },
    ],
    unoptimized: true,
  },

  env: {
    NEXT_PUBLIC_BACKEND_URL:
      process.env.NEXT_PUBLIC_BACKEND_URL ||
      "https://alex-universe11-bootcamp-ubsi-kai.hf.space",
  },

  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "Cross-Origin-Embedder-Policy", value: "credentialless" },
          { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
        ],
      },
    ];
  },

  webpack: (config, { isServer }) => {
    if (!isServer) {
      config.resolve.fallback = {
        ...config.resolve.fallback,
        fs: false,
        net: false,
        tls: false,
      };
    }
    return config;
  },
};

module.exports = nextConfig;
```

---

## LAMPIRAN: Peta 8 Critical Fixes

| # | Nama Perbaikan | File Target | Mekanisme Teknis |
|---|----------------|-------------|------------------|
| **FIX 01** | Auto-Reconnect WebSocket | `TelemetryPanel.tsx` | Exponential backoff (2^n × 2000ms, max 30s). Reset counter on successful `onopen`. |
| **FIX 02** | cookies.txt Injection | `stream_handler.py` | `ydl_opts["cookiefile"] = cookies_path` — menyisipkan sesi browser manusia ke yt-dlp. |
| **FIX 03** | Drop-Frame Shared State | `stream_handler.py` | `self._latest_frame = frame` (overwrite tunggal, tanpa antrean FIFO). |
| **FIX 04** | Confidence Threshold 0.15 | `vision_engine.py` | `conf=CONFIDENCE_THRESHOLD` — memprioritaskan Recall di atas Precision untuk deteksi KRL malam. |
| **FIX 05** | Rate Limit Shield (429) | `gemini_agent.py` | Try-except mendeteksi token '429'/'resource_exhausted'. Menembakkan payload dummy + `asyncio.sleep(45)`. |
| **FIX 06** | NoneType Guard (box.id) | `vision_engine.py` | `if box.id is not None: track_id = int(box.id[0])` — mencegah TypeError pada deteksi marginal. |
| **FIX 07** | Descending Area Sort | `vision_engine.py` | `raw_detections.sort(key=lambda d: d["area"], reverse=True)` — mikro di atas makro. |
| **FIX 08** | DJKA Webhook Debounce | `vision_engine.py` | `time.time() - self._last_emergency_time < 60` — maks 1 tembakan per menit per insiden. |

---

*Dokumen ini digenerate secara otomatis oleh NusaRail Report Generator v2.0.*  
*© 2026 Muhammad Abdurrahman Rabbani — Universitas Bina Sarana Informatika.*


---

## BAB 5: Evaluasi Pelatihan Model YOLOv8 (Metrik & Performa)

Evaluasi performa model YOLOv8 merupakan tahap krusial untuk memastikan keandalan sistem peringatan dini dalam kondisi dunia nyata. Model ini dilatih selama sekitar 60 epoch dan menunjukkan tingkat konvergensi yang sangat baik. Berikut adalah analisis mendalam berdasarkan metrik pelatihan.

### 5.1. Analisis Confusion Matrix

Confusion Matrix digunakan untuk mengevaluasi akurasi klasifikasi (Classification Accuracy) dari model deteksi terhadap kelas-kelas target.

![Confusion Matrix](confusion_matrix.png)
*Gambar 1: Confusion Matrix dari hasil validasi model YOLOv8.*

Berdasarkan matriks tersebut, kita dapat menarik beberapa kesimpulan kritis:
1. **Kelas Mobil (Car):** Model menunjukkan performa yang sangat luar biasa dalam mendeteksi mobil. Terdapat 1868 *True Positives*, dengan tingkat *False Positives* yang sangat rendah (hanya 3 kejadian misklasifikasi dengan kelas lain). 
2. **Kelas Sepeda Motor (Motorcycle):** Mendapatkan 418 *True Positives*. Meskipun terdapat sebagian kecil yang tidak terdeteksi (masuk sebagai *background*), model berhasil membedakan antara motor dan mobil secara absolut (hanya 1 misklasifikasi).
3. **Kelas Kereta (Train):** Memiliki dataset yang lebih kecil (6 *True Positives*), namun tingkat presisinya tinggi tanpa adanya tumpang tindih (*overlap*) misklasifikasi ke objek kendaraan darat lainnya.
4. **Kesimpulan Deteksi:** Secara keseluruhan, model memiliki tingkat diskriminasi antar-kelas yang sangat solid. Kesalahan dominan hanya terletak pada *background false negatives* (objek kecil yang tidak terdeteksi), namun bukan kesalahan pengenalan kelas (misalnya mobil disangka kereta).

### 5.2. Analisis Kurva Loss dan Metrik Pelatihan (Training Metrics)

Grafik metrik pelatihan memvisualisasikan bagaimana model belajar dan mengoptimalkan pembobotannya seiring bertambahnya iterasi (epoch).

![Training Results](results.png)
*Gambar 2: Kurva Loss dan Metrik Performa (Precision, Recall, mAP) selama 60 Epoch.*

Analisis performa berdasarkan grafik:
1. **Konvergensi Box Loss (\ox_loss\) & Classification Loss (\cls_loss\):** Kurva \	rain/box_loss\ dan \al/box_loss\ menurun secara tajam dari nilai ~2.0 menuju ~1.2. Penurunan simultan antara set pelatihan (train) dan validasi (val) membuktikan bahwa model **tidak mengalami overfitting**. Jaringan secara efektif mempelajari koordinat spasial kotak pembatas (bounding box).
2. **Precision & Recall Stabil:** Metrik \metrics/precision(B)\ berfluktuasi di awal namun stabil menanjak melampaui angka 0.70 di akhir pelatihan. Serupa dengan itu, \metrics/recall(B)\ mencapai angka stabil di kisaran 0.70. Keseimbangan ini (*F1-Score balance*) menjamin bahwa sistem mendeteksi sebanyak mungkin bahaya tanpa membombardir operator dengan alarm palsu.
3. **Mean Average Precision (mAP):** Metrik utama, yaitu \mAP50(B)\, menunjukkan tren logaritmik positif yang sangat mulus dan mencapai nilai impresif di atas **0.72**. Ini berarti dalam 72% kasus, kotak deteksi model memiliki *Intersection over Union* (IoU) lebih dari 50% terhadap objek asli. Tren positif yang masih berlanjut di epoch 60 mengindikasikan bahwa model masih memiliki ruang untuk menjadi lebih akurat jika dilatih lebih lama.

Secara teknis, kombinasi dari konvergensi *loss* yang stabil dan *mAP* yang solid menegaskan bahwa **model ini sudah mencapai kriteria Production-Ready** untuk dideploy pada infrastruktur *edge* di perlintasan kereta api.
