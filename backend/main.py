"""
NusaRail Vision System - Main FastAPI Application
===================================================
Production-ready backend server that orchestrates:
- MJPEG zero-lag video streaming (multipart/x-mixed-replace)
- WebSocket telemetry broadcasting (JSON payload)
- YOLOv8 + ByteTrack AI inference pipeline
- Gemini 1.5 Pro Macro-Observer integration

CRITICAL FIX 01 (Server-side): CORSMiddleware with allow_origins=['*']
to enable cross-origin Frontend (Vercel) ↔ Backend (HuggingFace) communication.
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

import aiofiles
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

            # CRITICAL HACK: Event-Driven Gemini Trigger untuk Kompensasi Kebutaan YOLO
            if telemetry.get("is_car_stuck"):
                context_prompt = "PERHATIAN DARURAT: Sistem YOLO baru saja mendeteksi kendaraan yang berhenti di tengah rel. Fokuskan penglihatan Anda ke sekitar kendaraan tersebut. Apakah terlihat ada kerumunan orang, kepanikan, atau warga yang sedang berusaha mendorong kendaraan tersebut? Jika YA, ubah kondisi_perlintasan menjadi 'DARURAT_KRITIS'."
                # Run the async force_analyze in a new event loop since this is a separate thread
                try:
                    asyncio.run(gemini_agent.force_analyze(frame, context_prompt))
                except Exception as e:
                    log.error(f"[AIWorker] Failed to trigger force_analyze: {e}")

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

# CRITICAL FIX 01 (CORS): Allow all origins for Vercel ↔ HuggingFace
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
    # Save uploaded file temporarily
    temp_dir = "temp"
    os.makedirs(temp_dir, exist_ok=True)
    temp_path = os.path.join(temp_dir, file.filename)

    # CRITICAL FIX 12: Large File Chunked Upload Support
    async with aiofiles.open(temp_path, "wb") as f:
        while content := await file.read(1024 * 1024):  # Chunk 1MB
            await f.write(content)

    success = stream_handler.start_upload(temp_path)
    if not success:
        return JSONResponse(status_code=400, content={"error": "Failed to open uploaded video."})

    # Launch AI worker thread
    ai_thread = threading.Thread(target=_ai_worker_thread, daemon=True)
    ai_thread.start()

    # Launch Gemini agent loop
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
            # Generate a "waiting" placeholder
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
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Accel-Buffering": "no",  # CRITICAL: Prevent Hugging Face Nginx from buffering the MJPEG stream
        }
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
            # Push latest telemetry periodically
            telemetry = {}
            with _annotated_frame_lock:
                telemetry = _latest_telemetry.copy() if _latest_telemetry else {}

            if telemetry:
                await websocket.send_text(json.dumps(telemetry, ensure_ascii=False))
            else:
                # CRITICAL FIX 11: Prevent HF Nginx from dropping idle WebSocket connection
                await websocket.send_text(json.dumps({"type": "ping", "status": "idle"}))

            # Also listen for incoming messages (keep-alive / commands)
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=2.0)
                log.info(f"[WebSocket] Received: {data}")
            except asyncio.TimeoutError:
                pass  # Normal timeout — no incoming message

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
