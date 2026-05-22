"""
NusaRail Vision — FastAPI Backend v3.0
=========================================
New in v3:
  · SQLite auto-save on CRITICAL_ALERT  (GET /api/v1/history)
  · DVR evidence saver — frame buffer → .jpg + .mp4 on alert
  · gc.collect() + torch.cuda.empty_cache() after every inference
  · Async Ollama LLM integration  (POST /api/v1/ai-report)
  · Dynamic confidence threshold via Form param
"""

from __future__ import annotations

import gc
import io
import logging
import os
import sqlite3
import threading
import time
from collections import deque
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Deque, Dict, List, Optional, Tuple

import cv2
import geo_service
import httpx
import os

CAMERA_LAT = -6.4485
CAMERA_LON = 106.8016
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from PIL import Image
from pydantic import BaseModel
from ultralytics import YOLO

# ── Optional torch ────────────────────────────────────────────────────────────
try:
    import torch
    TORCH_AVAILABLE = torch.cuda.is_available()
except ImportError:
    TORCH_AVAILABLE = False

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("backend.log"), logging.StreamHandler()],
)
log = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR      = Path(__file__).parent.resolve()
EVIDENCE_DIR  = BASE_DIR / "evidence"
DB_PATH       = BASE_DIR / "nusarail.db"
MODEL_PATH    = str(BASE_DIR.parent / "Dataset" / "best_web_optimized.onnx")
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

# ── Ollama config ─────────────────────────────────────────────────────────────
OLLAMA_BASE = "http://localhost:11434"
OLLAMA_MODEL = "llama3"
OLLAMA_TIMEOUT = 30.0

# Frame ring-buffer for DVR (stores last N raw BGR frames as numpy arrays)
FRAME_BUFFER_SIZE = 90           # ~3 s at 30 fps
_frame_buffer: Deque[np.ndarray] = deque(maxlen=FRAME_BUFFER_SIZE)
_buffer_lock  = threading.Lock()

# ═══════════════════════════════════════════════════════════════════════════════
# PYDANTIC MODELS
# ═══════════════════════════════════════════════════════════════════════════════

class BboxModel(BaseModel):
    x1: float; y1: float; x2: float; y2: float
    center_x: float; center_y: float


class DetectionModel(BaseModel):
    class_name: str
    confidence: float
    bbox: BboxModel
    is_stationary: bool = False
    stationary_duration_ms: int = 0


class AnalyzeFrameResponse(BaseModel):
    status: str
    timestamp: str
    alert_triggered: bool
    critical_alert_count: int
    detections: List[DetectionModel]
    inference_time_ms: float
    message: str
    geo_location: Optional[dict] = None
    narrative_report: Optional[str] = None


class AiReportRequest(BaseModel):
    detections: List[DetectionModel]
    critical_alert_count: int
    timestamp: str


class AiReportResponse(BaseModel):
    report: str
    model: str
    generated_at: str


class AnomalyRecord(BaseModel):
    id: int
    timestamp: str
    vehicle_class: str
    duration_ms: int
    position_x: float
    position_y: float
    evidence_path: Optional[str]
    ai_report: Optional[str]


# ═══════════════════════════════════════════════════════════════════════════════
# SQLITE DATABASE
# ═══════════════════════════════════════════════════════════════════════════════

def _init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS anomaly_events (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp     TEXT    NOT NULL,
                vehicle_class TEXT    NOT NULL,
                duration_ms   INTEGER NOT NULL,
                position_x    REAL    NOT NULL,
                position_y    REAL    NOT NULL,
                evidence_path TEXT,
                ai_report     TEXT
            )
        """)
        conn.commit()
    log.info(f"✅ SQLite DB ready → {DB_PATH}")


@contextmanager
def _get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def db_save_anomaly(
    vehicle_class: str,
    duration_ms: int,
    position_x: float,
    position_y: float,
    evidence_path: Optional[str] = None,
    ai_report: Optional[str] = None,
) -> int:
    ts = datetime.now().isoformat()
    with _get_db() as conn:
        cur = conn.execute(
            """INSERT INTO anomaly_events
               (timestamp, vehicle_class, duration_ms, position_x, position_y,
                evidence_path, ai_report)
               VALUES (?,?,?,?,?,?,?)""",
            (ts, vehicle_class, duration_ms, position_x, position_y,
             evidence_path, ai_report),
        )
        conn.commit()
        row_id = cur.lastrowid
    log.info(f"💾 Anomaly saved → id={row_id}  class={vehicle_class}  dur={duration_ms}ms")
    return row_id


def db_get_history(limit: int = 100) -> List[Dict]:
    with _get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM anomaly_events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════════════════════
# DVR — Evidence Saver
# ═══════════════════════════════════════════════════════════════════════════════

def _save_evidence_snapshot(frame: np.ndarray, label: str = "") -> str:
    """Save a single JPEG snapshot and return its path."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = EVIDENCE_DIR / f"anomaly_{ts}.jpg"
    out = frame.copy()
    if label:
        cv2.putText(out, label, (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                    0.9, (0, 0, 255), 2, cv2.LINE_AA)
    cv2.imwrite(str(fname), out)
    log.info(f"📸 Evidence saved → {fname}")
    return str(fname)


def _save_evidence_clip(frames: List[np.ndarray], label: str = "") -> str:
    """Save a short MP4 clip from a list of BGR frames and return its path."""
    if not frames:
        return ""
    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = str(EVIDENCE_DIR / f"anomaly_{ts}.mp4")
    h, w = frames[0].shape[:2]
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(out_path, fourcc, 10.0, (w, h))
    for f in frames:
        if label:
            frm = f.copy()
            cv2.putText(frm, label, (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                        0.9, (0, 0, 255), 2, cv2.LINE_AA)
            writer.write(frm)
        else:
            writer.write(f)
    writer.release()
    log.info(f"🎬 Evidence clip saved → {out_path}  ({len(frames)} frames)")
    return out_path


def save_evidence_async(current_frame: np.ndarray, detections: List[Dict]) -> str:
    """
    Non-blocking evidence save:
    - Snapshot of current frame (JPEG)
    - Short MP4 clip from ring-buffer (last ~3 s)
    Returns the snapshot path immediately; clip saves in background thread.
    """
    label_parts = [
        f"{d['class_name']} {d.get('stationary_duration_ms',0)//1000}s"
        for d in detections if d.get("is_stationary")
    ]
    label = " | ".join(label_parts) if label_parts else "CRITICAL"

    snapshot_path = _save_evidence_snapshot(current_frame, label)

    with _buffer_lock:
        buffered = list(_frame_buffer)

    def _clip_worker():
        _save_evidence_clip(buffered, label)

    threading.Thread(target=_clip_worker, daemon=True).start()
    return snapshot_path


# ═══════════════════════════════════════════════════════════════════════════════
# TEMPORAL TRACKER
# ═══════════════════════════════════════════════════════════════════════════════

class TemporalAnomalyTracker:
    def __init__(self,
                 stationary_threshold_ms: int = 5000,
                 position_tolerance_pixels: int = 20):
        self.stationary_threshold_ms   = stationary_threshold_ms
        self.position_tolerance_pixels = position_tolerance_pixels
        self.tracked_objects: Dict[str, Dict] = {}
        self.critical_alerts: List[str]       = []
        log.info(
            f"Tracker init — threshold={stationary_threshold_ms}ms "
            f"tol={position_tolerance_pixels}px"
        )

    def _obj_id(self, cx: float, cy: float, cls: str) -> str:
        rx = round(cx / self.position_tolerance_pixels) * self.position_tolerance_pixels
        ry = round(cy / self.position_tolerance_pixels) * self.position_tolerance_pixels
        return f"{cls}_{rx}_{ry}"

    def _within(self, p1: Tuple[float, float], p2: Tuple[float, float]) -> bool:
        return np.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2) <= self.position_tolerance_pixels

    def update(self, detections: List[Dict]) -> Dict:
        now_ms = int(time.time() * 1000)
        newly_critical: List[Dict] = []

        for det in detections:
            cx, cy, cls = det["center_x"], det["center_y"], det["class_name"]
            oid = self._obj_id(cx, cy, cls)

            if oid in self.tracked_objects:
                tr = self.tracked_objects[oid]
                if self._within((tr["center_x"], tr["center_y"]), (cx, cy)):
                    dur = now_ms - tr["first_detection_time"]
                    tr["center_x"] = (tr["center_x"] + cx) / 2
                    tr["center_y"] = (tr["center_y"] + cy) / 2
                    det["stationary_duration_ms"] = dur
                    det["is_stationary"] = True

                    if dur > self.stationary_threshold_ms and oid not in self.critical_alerts:
                        self.critical_alerts.append(oid)
                        newly_critical.append({
                            "object_id": oid, "class": cls,
                            "position": (cx, cy), "duration_ms": dur,
                        })
                        log.warning(
                            f"🚨 CRITICAL_ALERT — {cls} static {dur}ms at ({cx:.0f},{cy:.0f})"
                        )
                else:
                    self.tracked_objects[oid] = {
                        "center_x": cx, "center_y": cy,
                        "class_name": cls, "first_detection_time": now_ms,
                    }
                    if oid in self.critical_alerts:
                        self.critical_alerts.remove(oid)
            else:
                self.tracked_objects[oid] = {
                    "center_x": cx, "center_y": cy,
                    "class_name": cls, "first_detection_time": now_ms,
                }

        return {"critical_alerts": newly_critical, "total_tracked": len(self.tracked_objects)}


# ═══════════════════════════════════════════════════════════════════════════════
# YOLO DETECTOR
# ═══════════════════════════════════════════════════════════════════════════════

class YOLODetector:
    def __init__(self, model_path: str):
        self.model_path = model_path
        self.model: Optional[YOLO] = None
        self._load()

    def _load(self):
        mp = Path(self.model_path)
        if not mp.exists():
            raise FileNotFoundError(f"Model not found: {self.model_path}")
        self.model = YOLO(self.model_path)
        log.info(f"✅ YOLO model loaded: {self.model_path}")

    def predict(
        self,
        image: np.ndarray,
        conf_threshold: float = 0.5,
        target_classes: Optional[List[str]] = None,
    ) -> List[Dict]:
        if self.model is None:
            raise RuntimeError("Model not loaded")
        if target_classes is None:
            target_classes = ["car", "truck", "motorcycle", "bicycle", "bus"]

        results = self.model.predict(source=image, conf=conf_threshold, verbose=False)
        detections: List[Dict] = []
        r = results[0]
        if r.boxes is not None:
            for box, cls_id, conf in zip(
                r.boxes.xyxy.cpu().numpy(),
                r.boxes.cls.cpu().numpy(),
                r.boxes.conf.cpu().numpy(),
            ):
                cls_name = r.names[int(cls_id)]
                if cls_name.lower() not in [c.lower() for c in target_classes]:
                    continue
                x1, y1, x2, y2 = box
                detections.append({
                    "class_name": cls_name,
                    "confidence": float(conf),
                    "bbox": {
                        "x1": float(x1), "y1": float(y1),
                        "x2": float(x2), "y2": float(y2),
                    },
                    "center_x": float((x1 + x2) / 2),
                    "center_y": float((y1 + y2) / 2),
                })
        return detections


# ═══════════════════════════════════════════════════════════════════════════════
# FASTAPI APP
# ═══════════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="NusaRail Vision API",
    description="YOLOv8 + Temporal Tracking + SQLite + DVR + Ollama LLM",
    version="3.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

detector: Optional[YOLODetector]       = None
tracker:  Optional[TemporalAnomalyTracker] = None


@app.on_event("startup")
async def startup_event():
    global detector, tracker
    _init_db()
    try:
        detector = YOLODetector(MODEL_PATH)
        tracker  = TemporalAnomalyTracker(
            stationary_threshold_ms=5000,
            position_tolerance_pixels=20,
        )
        log.info("✅ Backend startup complete")
    except Exception as e:
        log.error(f"❌ Startup error: {e}")
        # Degraded mode — health endpoint will report model_loaded=False


# ═══════════════════════════════════════════════════════════════════════════════
# OLLAMA
# ═══════════════════════════════════════════════════════════════════════════════

async def generate_emergency_report(
    detections: List[DetectionModel],
    critical_count: int,
    timestamp: str,
) -> str:
    det_summary = "; ".join(
        f"{d.class_name} (durasi {d.stationary_duration_ms/1000:.1f}s)"
        for d in detections
        if d.is_stationary
    ) or "tidak ada detail"

    prompt = (
        f"Kamu adalah sistem peringatan dini perlintasan kereta api. "
        f"Terdeteksi {critical_count} kendaraan berhenti di perlintasan pada {timestamp}. "
        f"Detail: {det_summary}. "
        f"Tulis LAPORAN TINDAKAN DARURAT singkat (3 kalimat) dalam bahasa Indonesia yang tegas "
        f"dan operasional, tanpa salam atau header."
    )
    try:
        async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
            resp = await client.post(
                f"{OLLAMA_BASE}/api/generate",
                json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            )
            resp.raise_for_status()
            return resp.json().get("response", "").strip()
    except httpx.ConnectError:
        log.warning("Ollama not reachable at localhost:11434")
        return (
            f"[LLM Offline] Peringatan: {critical_count} kendaraan berhenti di perlintasan. "
            "Segera aktifkan prosedur darurat dan hubungi petugas lapangan."
        )
    except Exception as e:
        log.error(f"Ollama error: {e}")
        return f"[LLM Error] {e}"


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/")
async def root():
    return {
        "name": "NusaRail Vision API",
        "version": "3.0.0",
        "docs": "/api/docs",
        "evidence_dir": str(EVIDENCE_DIR),
        "db": str(DB_PATH),
    }


@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "model_loaded": detector is not None and detector.model is not None,
        "tracker_ready": tracker is not None,
        "torch_cuda": TORCH_AVAILABLE,
        "ollama_url": OLLAMA_BASE,
        "db_path": str(DB_PATH),
        "evidence_dir": str(EVIDENCE_DIR),
    }


@app.post("/api/v1/analyze-frame", response_model=AnalyzeFrameResponse)
async def analyze_frame(
    file: UploadFile = File(...),
    threshold: float = Form(default=0.5),
):
    if detector is None or tracker is None:
        raise HTTPException(503, "Model atau Tracker belum siap.")

    threshold = max(0.1, min(0.99, threshold))
    t0 = time.time()

    try:
        # ── Decode image ───────────────────────────────────────────────────
        if not (file.content_type or "").startswith("image/"):
            raise ValueError("File harus berupa gambar (image/*)")
        raw = await file.read()
        if not raw:
            raise ValueError("File gambar kosong")

        img_pil   = Image.open(io.BytesIO(raw)).convert("RGB")
        img_array = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)
        log.info(f"📷 Frame {img_array.shape}  thr={threshold:.2f}")

        # ── Push to DVR ring buffer ────────────────────────────────────────
        with _buffer_lock:
            _frame_buffer.append(img_array.copy())

        # ── YOLO inference ─────────────────────────────────────────────────
        detections = detector.predict(
            img_array,
            conf_threshold=threshold,
            target_classes=["car", "truck", "motorcycle", "bicycle", "bus"],
        )
        log.info(f"🔍 {len(detections)} detection(s)")

        # ── Free image memory ──────────────────────────────────────────────
        saved_frame = img_array.copy()   # keep for evidence BEFORE del
        del img_array, img_pil, raw
        gc.collect()
        if TORCH_AVAILABLE:
            torch.cuda.empty_cache()

        # ── Temporal tracking ──────────────────────────────────────────────
        tracking = tracker.update(detections)

        # ── CRITICAL ALERT — save evidence + DB ───────────────────────────
        newly_critical = tracking["critical_alerts"]
        alert_triggered = len(newly_critical) > 0
        
        geo_location = None
        narrative_report = geo_service.latest_gemini_report

        if alert_triggered:
            # Cari rel terdekat dari database SQLite
            geo_location = geo_service.find_nearest_railway(CAMERA_LAT, CAMERA_LON)
            
            # Simpan frame terbaru sebagai evidence/alert_latest.jpg
            os.makedirs("evidence", exist_ok=True)
            latest_img_path = "evidence/alert_latest.jpg"
            cv2.imwrite(latest_img_path, saved_frame)
            
            # Panggil Gemini API di thread terpisah (agar tidak freeze)
            threading.Thread(
                target=geo_service.analyze_anomaly_with_gemini,
                args=(latest_img_path, geo_location),
                daemon=True
            ).start()
            
            narrative_report = "Memulai analisis AI darurat..."

            for alert in newly_critical:
                evidence_path = save_evidence_async(saved_frame, detections)
                
                threading.Thread(
                    target=db_save_anomaly,
                    args=(
                        alert["class"],
                        alert["duration_ms"],
                        alert["position"][0],
                        alert["position"][1],
                        evidence_path,
                        None,    # ai_report filled later via /api/v1/ai-report
                    ),
                    daemon=True,
                ).start()

        del saved_frame

        # ── Build response ─────────────────────────────────────────────────
        ms = (time.time() - t0) * 1000
        critical_count = len(tracker.critical_alerts)

        det_models = [
            DetectionModel(
                class_name=d["class_name"],
                confidence=d["confidence"],
                bbox=BboxModel(
                    **d["bbox"],
                    center_x=d["center_x"],
                    center_y=d["center_y"],
                ),
                is_stationary=d.get("is_stationary", False),
                stationary_duration_ms=d.get("stationary_duration_ms", 0),
            )
            for d in detections
        ]

        if alert_triggered:
            msg = f"🚨 CRITICAL_ALERT: {len(newly_critical)} objek stationary — bukti disimpan"
        elif detections:
            msg = f"✅ {len(detections)} objek terdeteksi — Normal"
        else:
            msg = "✅ Tidak ada deteksi — Jalur aman"
        log.info(f"✅ Done — alerts={critical_count}  time={ms:.1f}ms")
        
        return AnalyzeFrameResponse(
            status="success",
            timestamp=datetime.now().isoformat(),
            alert_triggered=alert_triggered,
            critical_alert_count=len(newly_critical),
            detections=det_models,
            inference_time_ms=round(ms, 2),
            message=msg,
            geo_location=geo_location,
            narrative_report=narrative_report
        )

    except ValueError as ve:
        raise HTTPException(400, f"Validation error: {ve}")
    except Exception as e:
        log.error(f"❌ analyze_frame error: {e}", exc_info=True)
        raise HTTPException(500, f"Internal error: {e}")


@app.post("/api/v1/ai-report", response_model=AiReportResponse)
async def ai_report(request: AiReportRequest):
    """Generate AI emergency report via local Ollama LLM."""
    report = await generate_emergency_report(
        request.detections,
        request.critical_alert_count,
        request.timestamp,
    )
    return AiReportResponse(
        report=report,
        model=OLLAMA_MODEL,
        generated_at=datetime.now().isoformat(),
    )


@app.get("/api/v1/history")
async def get_history(limit: int = 100):
    """Return historical anomaly events from SQLite, newest first."""
    try:
        records = db_get_history(limit=min(limit, 500))
        return {
            "status": "success",
            "count": len(records),
            "records": records,
        }
    except Exception as e:
        raise HTTPException(500, f"DB error: {e}")


@app.get("/api/v1/status")
async def get_status():
    if tracker is None:
        raise HTTPException(503, "Tracker belum siap")
    return {
        "status": "operational",
        "timestamp": datetime.now().isoformat(),
        "tracked_objects": len(tracker.tracked_objects),
        "critical_alerts": tracker.critical_alerts,
        "buffer_frames": len(_frame_buffer),
        "configuration": {
            "stationary_threshold_ms": tracker.stationary_threshold_ms,
            "position_tolerance_pixels": tracker.position_tolerance_pixels,
        },
    }


@app.post("/api/v1/reset-tracker")
async def reset_tracker():
    if tracker is None:
        raise HTTPException(503, "Tracker belum siap")
    tracker.tracked_objects.clear()
    tracker.critical_alerts.clear()
    with _buffer_lock:
        _frame_buffer.clear()
    gc.collect()
    log.info("🔄 Tracker + buffer reset")
    return {
        "status": "success",
        "message": "Tracker dan buffer direset",
        "timestamp": datetime.now().isoformat(),
    }


@app.exception_handler(HTTPException)
async def http_exc_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": "error",
            "detail": exc.detail,
            "timestamp": datetime.now().isoformat(),
        },
    )


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
