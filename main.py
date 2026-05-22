"""
Backend FastAPI untuk Sistem Peringatan Dini Anomali Lalu Lintas di Perlintasan Kereta Api
Mengintegrasikan YOLOv8 dengan Temporal Anomaly Tracking untuk deteksi real-time

Fitur Utama:
- Model YOLOv8 ONNX optimized untuk inferensi cepat
- Temporal tracking untuk mendeteksi objek yang diam di lokasi tertentu
- Alert CRITICAL_ALERT ketika objek terdeteksi >5 detik di area yang sama
- Error handling robust dengan logging
- CORS enabled untuk frontend Next.js
"""

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from io import BytesIO

import cv2
import numpy as np
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
from pydantic import BaseModel
from ultralytics import YOLO

# ============================================================================
# KONFIGURASI & SETUP LOGGING
# ============================================================================

# Setup logging untuk production
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('backend.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============================================================================
# PYDANTIC MODELS - Response Schemas
# ============================================================================

class BboxModel(BaseModel):
    """Model untuk bounding box koordinat"""
    x1: float
    y1: float
    x2: float
    y2: float
    center_x: float
    center_y: float


class DetectionModel(BaseModel):
    """Model untuk setiap deteksi objek"""
    class_name: str
    confidence: float
    bbox: BboxModel
    is_stationary: bool = False
    stationary_duration_ms: int = 0


class AnalyzeFrameResponse(BaseModel):
    """Model response untuk endpoint /api/v1/analyze-frame"""
    status: str
    timestamp: str
    alert_triggered: bool
    critical_alert_count: int
    detections: List[DetectionModel]
    inference_time_ms: float
    message: str


# ============================================================================
# TEMPORAL TRACKER - Logika Pelacakan Anomali
# ============================================================================

class TemporalAnomalyTracker:
    """
    Tracker untuk mendeteksi anomali temporal - objek yang tetap pada posisi yang sama
    selama periode waktu tertentu (threshold 5 detik untuk kasus ini).
    
    Logika:
    1. Setiap frame, deteksi objek dan catat koordinat pusatnya
    2. Bandingkan dengan frame sebelumnya dengan toleransi pergeseran (radius)
    3. Jika objek tetap di area yang sama >5 detik, trigger CRITICAL_ALERT
    """
    
    def __init__(self, 
                 stationary_threshold_ms: int = 5000,
                 position_tolerance_pixels: int = 20):
        """
        Args:
            stationary_threshold_ms: Threshold waktu dalam ms untuk menganggap objek diam
            position_tolerance_pixels: Toleransi pergeseran posisi (radius dalam pixel)
        """
        self.stationary_threshold_ms = stationary_threshold_ms
        self.position_tolerance_pixels = position_tolerance_pixels
        
        # Dictionary untuk tracking: {object_id: {center_x, center_y, class, first_detection_time}}
        self.tracked_objects: Dict[str, Dict] = {}
        self.critical_alerts: List[str] = []
        
        logger.info(
            f"TemporalAnomalyTracker initialized - "
            f"Threshold: {stationary_threshold_ms}ms, "
            f"Tolerance: {position_tolerance_pixels}px"
        )
    
    def _calculate_object_id(self, center_x: float, center_y: float, 
                            class_name: str) -> str:
        """
        Generate unique ID untuk object berdasarkan posisi & class
        ID format: "class_x_y" dengan rounded koordinat untuk grouping
        """
        rounded_x = round(center_x / self.position_tolerance_pixels) * self.position_tolerance_pixels
        rounded_y = round(center_y / self.position_tolerance_pixels) * self.position_tolerance_pixels
        return f"{class_name}_{rounded_x}_{rounded_y}"
    
    def _is_within_tolerance(self, pos1: Tuple[float, float], 
                            pos2: Tuple[float, float]) -> bool:
        """Check apakah dua posisi berada dalam tolerance radius"""
        distance = np.sqrt((pos1[0] - pos2[0])**2 + (pos1[1] - pos2[1])**2)
        return distance <= self.position_tolerance_pixels
    
    def update(self, detections: List[Dict]) -> Dict:
        """
        Update tracker dengan deteksi frame terbaru.
        
        Args:
            detections: List of {center_x, center_y, class_name, confidence, bbox}
            
        Returns:
            Dict berisi stationary_objects dan critical_alerts
        """
        current_time_ms = int(time.time() * 1000)
        stationary_objects = []
        newly_critical = []
        
        # Track objek yang terdeteksi di frame ini
        current_frame_ids = set()
        
        for detection in detections:
            center_x = detection['center_x']
            center_y = detection['center_y']
            class_name = detection['class_name']
            
            obj_id = self._calculate_object_id(center_x, center_y, class_name)
            current_frame_ids.add(obj_id)
            
            # Jika objek sudah di-track
            if obj_id in self.tracked_objects:
                tracked = self.tracked_objects[obj_id]
                
                # Cek apakah posisi masih dalam toleransi
                prev_pos = (tracked['center_x'], tracked['center_y'])
                curr_pos = (center_x, center_y)
                
                if self._is_within_tolerance(prev_pos, curr_pos):
                    # Objek masih diam, update waktu
                    duration_ms = current_time_ms - tracked['first_detection_time']
                    
                    # Update posisi (smooth tracking)
                    tracked['center_x'] = (tracked['center_x'] + center_x) / 2
                    tracked['center_y'] = (tracked['center_y'] + center_y) / 2
                    
                    detection['stationary_duration_ms'] = duration_ms
                    detection['is_stationary'] = True
                    stationary_objects.append(detection)
                    
                    # Jika melebihi threshold, trigger CRITICAL_ALERT
                    if duration_ms > self.stationary_threshold_ms:
                        if obj_id not in self.critical_alerts:
                            self.critical_alerts.append(obj_id)
                            newly_critical.append({
                                'object_id': obj_id,
                                'class': class_name,
                                'position': (center_x, center_y),
                                'duration_ms': duration_ms
                            })
                            logger.warning(
                                f"🚨 CRITICAL_ALERT TRIGGERED - {class_name} stationary for {duration_ms}ms "
                                f"at position ({center_x}, {center_y})"
                            )
                else:
                    # Objek bergerak, reset tracking
                    self.tracked_objects[obj_id] = {
                        'center_x': center_x,
                        'center_y': center_y,
                        'class_name': class_name,
                        'first_detection_time': current_time_ms
                    }
                    if obj_id in self.critical_alerts:
                        self.critical_alerts.remove(obj_id)
            else:
                # Objek baru, mulai track
                self.tracked_objects[obj_id] = {
                    'center_x': center_x,
                    'center_y': center_y,
                    'class_name': class_name,
                    'first_detection_time': current_time_ms
                }
        
        # Cleanup: Hapus objek yang tidak lagi terdeteksi di frame ini (untuk TTL management)
        # (Opsional: bisa ditambahkan cleanup logic jika perlu)
        
        return {
            'stationary_objects': stationary_objects,
            'critical_alerts': newly_critical,
            'total_tracked': len(self.tracked_objects)
        }


# ============================================================================
# SETUP FASTAPI APPLICATION
# ============================================================================

app = FastAPI(
    title="Traffic Anomaly Detection Backend",
    description="Backend sistem peringatan dini anomali lalu lintas di perlintasan kereta api",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc"
)

# Tambahkan CORS Middleware agar frontend Next.js dapat mengakses API
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

# ============================================================================
# MODEL LOADING & INITIALIZATION
# ============================================================================

class YOLODetector:
    """Wrapper untuk YOLOv8 model dengan error handling"""
    
    def __init__(self, model_path: str):
        """
        Initialize YOLOv8 model dari file
        
        Args:
            model_path: Path ke model file (ONNX recommended)
        """
        self.model_path = model_path
        self.model = None
        self._load_model()
    
    def _load_model(self) -> None:
        """Load model YOLOv8 dari disk"""
        try:
            # Cek keberadaan file
            model_file = Path(self.model_path)
            if not model_file.exists():
                raise FileNotFoundError(f"Model file tidak ditemukan: {self.model_path}")
            
            # Load model - ultralytics akan auto-detect format (ONNX/PyTorch)
            self.model = YOLO(self.model_path)
            logger.info(f"✅ Model YOLOv8 berhasil dimuat dari: {self.model_path}")
            
        except Exception as e:
            logger.error(f"❌ Gagal memuat model: {str(e)}")
            raise RuntimeError(f"Model initialization failed: {str(e)}")
    
    def predict(self, image_array: np.ndarray, 
                conf_threshold: float = 0.5,
                target_classes: Optional[List[str]] = None) -> List[Dict]:
        """
        Run inference pada image dan extract detections
        
        Args:
            image_array: Image array (BGR format dari OpenCV)
            conf_threshold: Confidence threshold untuk filter deteksi
            target_classes: List kelas yang ingin dideteksi (None = semua)
            
        Returns:
            List of detections dengan format:
            {
                'class_name': str,
                'confidence': float,
                'bbox': {x1, y1, x2, y2},
                'center_x': float,
                'center_y': float
            }
        """
        if self.model is None:
            raise RuntimeError("Model belum diload")
        
        # Default target classes jika tidak dispesifikasi
        if target_classes is None:
            target_classes = ['car', 'truck', 'motorcycle', 'bicycle', 'bus']
        
        try:
            # Run YOLOv8 inference
            results = self.model.predict(
                source=image_array,
                conf=conf_threshold,
                verbose=False,
                device=0  # GPU jika tersedia, CPU fallback
            )
            
            detections = []
            result = results[0]
            
            # Extract bounding boxes dan class names
            if result.boxes is not None:
                boxes = result.boxes.xyxy.cpu().numpy()  # (x1, y1, x2, y2)
                classes = result.boxes.cls.cpu().numpy()
                confidences = result.boxes.conf.cpu().numpy()
                class_names = result.names  # Dict mapping class_id ke class_name
                
                for box, class_id, confidence in zip(boxes, classes, confidences):
                    class_name = class_names[int(class_id)]
                    
                    # Filter hanya target classes
                    if class_name.lower() not in [c.lower() for c in target_classes]:
                        continue
                    
                    # Hitung center point
                    x1, y1, x2, y2 = box
                    center_x = (x1 + x2) / 2
                    center_y = (y1 + y2) / 2
                    
                    detections.append({
                        'class_name': class_name,
                        'confidence': float(confidence),
                        'bbox': {
                            'x1': float(x1),
                            'y1': float(y1),
                            'x2': float(x2),
                            'y2': float(y2)
                        },
                        'center_x': float(center_x),
                        'center_y': float(center_y)
                    })
            
            return detections
            
        except Exception as e:
            logger.error(f"Inference error: {str(e)}")
            raise RuntimeError(f"Model inference failed: {str(e)}")


# Initialize detector dan tracker secara global
MODEL_PATH = "./Dataset/best_web_optimized.onnx"
detector = None
tracker = None

@app.on_event("startup")
async def startup_event():
    """Load model dan initialize tracker saat startup aplikasi"""
    global detector, tracker
    try:
        detector = YOLODetector(MODEL_PATH)
        tracker = TemporalAnomalyTracker(
            stationary_threshold_ms=5000,  # 5 detik
            position_tolerance_pixels=20   # 20 pixel tolerance
        )
        logger.info("✅ Aplikasi startup berhasil - Model dan Tracker siap")
    except Exception as e:
        logger.error(f"❌ Startup error: {str(e)}")
        raise


# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.get("/api/health")
async def health_check():
    """Endpoint health check untuk monitoring"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "model_loaded": detector is not None and detector.model is not None,
        "tracker_ready": tracker is not None
    }


@app.post("/api/v1/analyze-frame", response_model=AnalyzeFrameResponse)
async def analyze_frame(file: UploadFile = File(...)):
    """
    Endpoint utama untuk analisis frame gambar.
    
    Menerima file gambar, menjalankan YOLOv8 inference, dan menerapkan
    temporal anomaly tracking untuk mendeteksi objek yang diam >5 detik.
    
    Args:
        file: File upload gambar (JPEG, PNG, etc)
        
    Returns:
        AnalyzeFrameResponse dengan deteksi dan alert status
    """
    
    if detector is None or tracker is None:
        raise HTTPException(
            status_code=503,
            detail="Model atau Tracker belum siap. Silakan coba beberapa saat lagi."
        )
    
    start_time = time.time()
    
    try:
        # ====== Validasi dan baca file gambar ======
        if not file.content_type.startswith('image/'):
            raise ValueError("File harus berupa gambar (image/*)")
        
        # Baca file ke bytes
        contents = await file.read()
        if not contents:
            raise ValueError("File gambar kosong")
        
        # Konversi bytes ke PIL Image
        image_pil = Image.open(BytesIO(contents))
        
        # Konversi PIL Image ke numpy array (BGR untuk OpenCV compatibility)
        image_array = cv2.cvtColor(np.array(image_pil), cv2.COLOR_RGB2BGR)
        
        logger.info(f"📷 Frame diterima - Ukuran: {image_array.shape}")
        
        # ====== Run YOLOv8 Inference ======
        detections = detector.predict(
            image_array,
            conf_threshold=0.5,
            target_classes=['car', 'truck', 'motorcycle', 'bicycle', 'bus']
        )
        
        logger.info(f"🔍 Deteksi selesai - {len(detections)} objek terdeteksi")
        
        # ====== Update Temporal Tracker ======
        tracking_result = tracker.update(detections)
        
        # ====== Prepare Response ======
        inference_time_ms = (time.time() - start_time) * 1000
        
        # Tandai deteksi dengan informasi temporal
        detection_responses = []
        for detection in detections:
            detection_responses.append(
                DetectionModel(
                    class_name=detection['class_name'],
                    confidence=detection['confidence'],
                    bbox=BboxModel(**detection['bbox'], 
                                   center_x=detection['center_x'],
                                   center_y=detection['center_y']),
                    is_stationary=detection.get('is_stationary', False),
                    stationary_duration_ms=detection.get('stationary_duration_ms', 0)
                )
            )
        
        # Check apakah ada CRITICAL_ALERT
        alert_triggered = len(tracking_result['critical_alerts']) > 0
        critical_count = len(tracker.critical_alerts)
        
        message = ""
        if alert_triggered:
            message = f"🚨 CRITICAL_ALERT: {len(tracking_result['critical_alerts'])} objek stationary terdeteksi"
        elif len(detections) > 0:
            message = f"✅ {len(detections)} objek terdeteksi - Normal"
        else:
            message = "✅ Tidak ada deteksi - Jalur aman"
        
        response = AnalyzeFrameResponse(
            status="success",
            timestamp=datetime.now().isoformat(),
            alert_triggered=alert_triggered,
            critical_alert_count=critical_count,
            detections=detection_responses,
            inference_time_ms=round(inference_time_ms, 2),
            message=message
        )
        
        logger.info(
            f"✅ Response siap - "
            f"Detections: {len(detections)}, "
            f"Critical Alerts: {critical_count}, "
            f"Inference Time: {inference_time_ms:.2f}ms"
        )
        
        return response
        
    except ValueError as ve:
        # Validation errors
        logger.warning(f"⚠️ Validation error: {str(ve)}")
        raise HTTPException(status_code=400, detail=f"Validation error: {str(ve)}")
    
    except Exception as e:
        # Unexpected errors
        logger.error(f"❌ Unexpected error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@app.get("/api/v1/status")
async def get_status():
    """Endpoint untuk mendapatkan status tracker dan statistik"""
    if tracker is None:
        raise HTTPException(status_code=503, detail="Tracker belum siap")
    
    return {
        "status": "operational",
        "timestamp": datetime.now().isoformat(),
        "tracked_objects": len(tracker.tracked_objects),
        "critical_alerts": tracker.critical_alerts,
        "configuration": {
            "stationary_threshold_ms": tracker.stationary_threshold_ms,
            "position_tolerance_pixels": tracker.position_tolerance_pixels
        }
    }


@app.post("/api/v1/reset-tracker")
async def reset_tracker():
    """Endpoint untuk mereset tracker (utility untuk testing/debugging)"""
    if tracker is None:
        raise HTTPException(status_code=503, detail="Tracker belum siap")
    
    tracker.tracked_objects.clear()
    tracker.critical_alerts.clear()
    
    logger.info("🔄 Tracker direset")
    
    return {
        "status": "success",
        "message": "Tracker berhasil direset",
        "timestamp": datetime.now().isoformat()
    }


# ============================================================================
# ROOT ENDPOINT
# ============================================================================

@app.get("/")
async def root():
    """Root endpoint - informasi API"""
    return {
        "name": "Traffic Anomaly Detection Backend",
        "version": "1.0.0",
        "status": "operational",
        "endpoints": {
            "health": "/api/health",
            "analyze_frame": "/api/v1/analyze-frame (POST)",
            "status": "/api/v1/status",
            "reset_tracker": "/api/v1/reset-tracker (POST)",
            "docs": "/api/docs",
            "redoc": "/api/redoc"
        }
    }


# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Custom handler untuk HTTP exceptions"""
    logger.warning(f"HTTP Exception: {exc.status_code} - {exc.detail}")
    return {
        "status": "error",
        "status_code": exc.status_code,
        "detail": exc.detail,
        "timestamp": datetime.now().isoformat()
    }


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    # Run dengan uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",  # Listen di semua interface
        port=8000,
        log_level="info",
        reload=False  # Set True hanya untuk development
    )
