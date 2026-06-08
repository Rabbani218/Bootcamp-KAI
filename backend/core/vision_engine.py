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
CRITICAL FIX 18: Drop-Frame Shared State Architecture (Zero-Lag Frontend).
"""

import time
import math
import logging
import asyncio
import threading
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
# CRITICAL FIX 15: Absolute Class Synchronization (Removed Hardcoded Dict)
# ---------------------------------------------------------------------------

# Threshold constants
STUCK_DISTANCE_PX = 50       # CRITICAL FIX 14: Increased to 50 for accurate bounding box jitter tolerance
STUCK_DURATION_SEC = 5.0      # Seconds before a stationary vehicle is flagged
DJKA_COOLDOWN_SEC = 60.0      # CRITICAL FIX 08: Debounce interval
CONFIDENCE_THRESHOLD = 0.15   # CRITICAL FIX 04: Low threshold for night recall
MIN_AREA_PX = 1500            # ANTI-TROLLING: Ignore tiny objects (toys)
MAX_AREA_PX = 250000          # ANTI-TROLLING: Ignore massive objects (close-up phone pictures)

# DJKA Webhook endpoint (configurable via environment)
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
        self.has_moved = False  # STATIC OBJECT FILTER: Must have moved once
        self.is_evacuating = False

    def update(self, cx: int, cy: int):
        """Update centroid position and recalculate stuck status."""
        self.last_cx = cx
        self.last_cy = cy
        self.last_seen = time.monotonic()

        # Check if vehicle has ever moved significantly
        if not getattr(self, 'has_moved', False):
            total_delta = math.sqrt((cx - self.initial_cx) ** 2 + (cy - self.initial_cy) ** 2)
            if total_delta > 10:
                self.has_moved = True

        # Euclidean distance from initial position
        delta = math.sqrt((cx - self.initial_cx) ** 2 + (cy - self.initial_cy) ** 2)

        if delta < STUCK_DISTANCE_PX:
            elapsed = self.last_seen - self.first_seen
            # STATIC OBJECT FILTER: Only consider stuck if it has moved at least once
            if elapsed > STUCK_DURATION_SEC and getattr(self, 'has_moved', False):
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
        # Initialize YOLOv8
        if YOLO is None:
            raise ImportError("ultralytics is not installed.")
        self._model = YOLO(model_path)
        # CRITICAL FIX 15: Ambil nama kelas dinamis langsung dari Custom Weights!
        self.class_names = self._model.names
        self._tracked_vehicles: Dict[int, TrackedVehicle] = {}
        self._evacuation_timers: Dict[int, float] = {}  # CRITICAL FIX 09: Human Evacuation & Occlusion Guard
        self._last_emergency_time: float = 0.0
        self._frame_count: int = 0
        
        # ------------------------------------------------------------------
        # CRITICAL FIX 18: Drop-Frame Shared State Architecture
        # ------------------------------------------------------------------
        self._shared_frame = None
        self._frame_lock = threading.Lock()
        
        self._latest_raw_detections = []
        self._latest_telemetry = {
            "frame": 0, "detections": [], "is_car_stuck": False,
            "is_evacuating": False, "evacuation_detected": False,
            "is_train_incoming": False, "emergency_status": "AMAN", "stuck_vehicle_ids": []
        }
        self._result_lock = threading.Lock()
        
        # Start the background AI consumer thread
        self._ai_thread = threading.Thread(target=self._ai_inference_loop, daemon=True)
        self._ai_thread.start()
        
        log.info(f"[VisionEngine] Model loaded & Drop-Frame AI Thread started: {model_path}")

    def process_frame(self, frame: np.ndarray) -> Tuple[np.ndarray, dict]:
        """
        Producer: Called by video stream loop at 30 FPS.
        OVERWRITES the shared buffer instantly without queues, ensuring the AI
        always reads the freshest frame. Returns the annotated frame immediately
        using the LATEST AVAILABLE AI results, guaranteeing zero-lag video output.
        """
        # 1. Update Drop-Frame Shared Buffer
        with self._frame_lock:
            self._shared_frame = frame.copy()
            
        frame_copy = frame.copy()
        
        # 2. Grab latest results (instant, no blocking)
        with self._result_lock:
            raw_detections = self._latest_raw_detections.copy()
            telemetry = self._latest_telemetry.copy()
            
        # 3. Render HUD and Overlays instantly
        emergency_status = telemetry.get("emergency_status", "AMAN")
        
        for det in raw_detections:
            x1, y1, x2, y2 = det["x1"], det["y1"], det["x2"], det["y2"]
            cls_name = det["cls_name"]
            conf = det["conf"]
            tid = det["track_id"]
            stuck = det.get("is_stuck", False)
            evacuating = det.get("is_evacuating", False)

            # Color coding (BGR)
            if evacuating:
                color = (255, 0, 255)    # PURPLE for manual evacuation
                thickness = 3
            elif stuck:
                color = (0, 0, 255)      # RED for stuck vehicles
                thickness = 3
            elif cls_name == "car":
                color = (255, 0, 0)      # BLUE
                thickness = 2
            elif cls_name == "train":
                color = (0, 165, 255)    # ORANGE
                thickness = 3
            elif cls_name == "motorcycle":
                color = (0, 255, 0)      # GREEN
                thickness = 2
            else:
                color = (0, 255, 0)
                thickness = 2

            cv2.rectangle(frame_copy, (x1, y1), (x2, y2), color, thickness)

            # Label
            id_str = f" ID:{tid}" if tid is not None else ""
            label = f"{cls_name}{id_str} {conf:.2f}"
            if det.get("is_ghost"):
                label = f"{cls_name}{id_str} OCCLUDED!"
            if evacuating:
                label += " EVAKUASI MANUAL!"
            elif stuck:
                label += " MOGOK!"

            label_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)[0]
            cv2.rectangle(frame_copy, (x1, y1 - label_size[1] - 10),
                          (x1 + label_size[0], y1), color, -1)
            cv2.putText(frame_copy, label, (x1, y1 - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)

        # 4. Emergency Alerts & DJKA Trigger
        # CRITICAL FIX 14: Dynamic HUD Overlay & Accurate Warning Logic
        if emergency_status in ["DARURAT_KRITIS", "BAHAYA"]:
            # Banner Peringatan Global (Solid Background HUD)
            banner_height = 80
            cv2.rectangle(frame_copy, (0, 0), (frame_copy.shape[1], banner_height), (0, 0, 255), -1)
            
            # Teks Peringatan
            if emergency_status == "DARURAT_KRITIS" and int(time.time() * 2) % 2 == 0:
                alert_text = "!!! AUTO-BRAKE SIGNAL SENT TO KRL !!!"
                text_color = (0, 255, 255) # Yellow to contrast with red
            else:
                alert_text = "AWAS! KENDARAAN TERJEBAK DI REL!"
                text_color = (255, 255, 255) # White

            text_size = cv2.getTextSize(alert_text, cv2.FONT_HERSHEY_SIMPLEX, 1.0, 3)[0]
            text_x = (frame_copy.shape[1] - text_size[0]) // 2
            text_y = (banner_height + text_size[1]) // 2
            
            cv2.putText(frame_copy, alert_text, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 1.0, text_color, 3)

            if emergency_status == "DARURAT_KRITIS":
                # CRITICAL FIX 08: Debounce — fire webhook max 1x per 60s
                # Use background task so we don't block the video stream
                asyncio.ensure_future(self._trigger_djka_webhook())

        # Indikator Status Dinamis
        status_text = f"Status: {emergency_status}"
        status_color = (0, 255, 0) if emergency_status == "AMAN" else (0, 0, 255)
        status_thickness = 1 if emergency_status == "AMAN" else 2
        
        info_text = f"NusaRail Vision | Frame #{telemetry.get('frame', 0)} | "
        cv2.putText(
            frame_copy,
            info_text,
            (10, frame_copy.shape[0] - 15),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1,
        )
        info_text_size = cv2.getTextSize(info_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]
        cv2.putText(
            frame_copy,
            status_text,
            (10 + info_text_size[0], frame_copy.shape[0] - 15),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, status_color, status_thickness,
        )

        return frame_copy, telemetry

    def _ai_inference_loop(self):
        """
        Consumer Thread: Mengambil frame terbaru HANYA saat siap.
        Jika AI lambat, frame lama otomatis terbuang (Drop-Frame).
        """
        log.info("[VisionEngine] Drop-Frame Consumer Thread started.")
        while True:
            frame = None
            with self._frame_lock:
                if self._shared_frame is not None:
                    frame = self._shared_frame.copy()
            
            if frame is None:
                time.sleep(0.01)
                continue

            self._frame_count += 1
            
            # CRITICAL FIX 15: Absolute Class Synchronization & Unfiltering
            # HAPUS filter classes=[...] agar custom model bisa melihat 100% objeknya
            results = self._model.track(
                source=frame,
                persist=True,
                tracker="bytetrack.yaml",
                conf=CONFIDENCE_THRESHOLD,
                iou=0.45,
                verbose=False,
            )
            
            is_car_stuck = False
            is_evacuation_active = False
            is_train_incoming = False
            stuck_vehicles: List[int] = []
            detections: List[dict] = []
            raw_detections = []
            
            def check_overlap(box1, box2) -> bool:
                x1_a, y1_a, x2_a, y2_a = box1
                x1_b, y1_b, x2_b, y2_b = box2
                return not (x2_a < x1_b or x2_b < x1_a or y2_a < y1_b or y2_b < y1_a)
                
            if results and len(results) > 0:
                boxes = results[0].boxes

                if boxes is not None and len(boxes) > 0:
                    for box in boxes:
                        x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                        conf = float(box.conf[0])
                        cls_id = int(box.cls[0])
                        # CRITICAL FIX 15: Ambil nama dari weights asli
                        cls_name = self.class_names.get(cls_id, f"class_{cls_id}")

                        # (Custom confidence filters removed to allow conf=0.15 for night recall)

                        cx = int((x1 + x2) / 2)
                        cy = int((y1 + y2) / 2)
                        area = (x2 - x1) * (y2 - y1)

                        if area < MIN_AREA_PX or area > MAX_AREA_PX:
                            continue

                        track_id = None
                        if box.id is not None:
                            track_id = int(box.id[0])

                        raw_detections.append({
                            "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                            "conf": conf, "cls_id": cls_id, "cls_name": cls_name,
                            "cx": cx, "cy": cy, "area": area, "track_id": track_id,
                        })

                    active_ids = set()
                    
                    person_detections = [d for d in raw_detections if d["cls_name"] == "person"]
                    vehicle_detections = [d for d in raw_detections if d["cls_name"] in ("car", "motorcycle", "bus", "truck")]

                    for v_det in vehicle_detections:
                        tid = v_det["track_id"]
                        if tid is None: continue
                        v_box = (v_det["x1"], v_det["y1"], v_det["x2"], v_det["y2"])
                        
                        is_pushed = False
                        for p_det in person_detections:
                            p_box = (p_det["x1"], p_det["y1"], p_det["x2"], p_det["y2"])
                            if check_overlap(v_box, p_box):
                                is_pushed = True
                                break
                                
                        if is_pushed:
                            if tid not in self._evacuation_timers:
                                self._evacuation_timers[tid] = time.monotonic()
                            elif time.monotonic() - self._evacuation_timers[tid] > 4.0:
                                v_det["is_evacuating"] = True
                        else:
                            if tid in self._evacuation_timers:
                                del self._evacuation_timers[tid]

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
                            
                            if det.get("is_evacuating", False):
                                tv.is_evacuating = True
                            else:
                                det["is_evacuating"] = getattr(tv, 'is_evacuating', False)

                            if tv.is_stuck and det["cls_name"] in ("car", "motorcycle", "bus", "truck"):
                                is_car_stuck = True
                                stuck_vehicles.append(tid)

                            if det.get("is_evacuating", False) and det["cls_name"] in ("car", "motorcycle", "bus", "truck"):
                                is_evacuation_active = True

                        if det["cls_name"] == "train":
                            is_train_incoming = True

                    now = time.monotonic()
                    stale_ids = []
                    for tid, tv in self._tracked_vehicles.items():
                        if tid not in active_ids:
                            time_unseen = now - tv.last_seen
                            is_critical = getattr(tv, 'is_stuck', False) or getattr(tv, 'is_evacuating', False)
                            
                            # CRITICAL FIX 13: Temporal Smoothing (Ghost Vehicle)
                            should_render_ghost = False
                            if is_critical and time_unseen <= 5.0:
                                should_render_ghost = True
                            elif not is_critical and time_unseen <= 3.0:
                                should_render_ghost = True
                            
                            if time_unseen > 10.0:
                                stale_ids.append(tid)
                            elif should_render_ghost:
                                if is_critical:
                                    is_car_stuck = is_car_stuck or getattr(tv, 'is_stuck', False)
                                    is_evacuation_active = is_evacuation_active or getattr(tv, 'is_evacuating', False)
                                    stuck_vehicles.append(tid)
                                
                                raw_detections.append({
                                    "x1": tv.last_cx - 50, "y1": tv.last_cy - 50, "x2": tv.last_cx + 50, "y2": tv.last_cy + 50,
                                    "conf": 0.0, "cls_id": tv.class_id, "cls_name": self.class_names.get(tv.class_id, "ghost"),
                                    "cx": tv.last_cx, "cy": tv.last_cy, "area": 10000, "track_id": tid,
                                    "is_stuck": getattr(tv, 'is_stuck', False), "is_evacuating": getattr(tv, 'is_evacuating', False),
                                    "is_ghost": True
                                })
                                
                    for tid in stale_ids:
                        del self._tracked_vehicles[tid]
                        if tid in self._evacuation_timers:
                            del self._evacuation_timers[tid]

                    raw_detections.sort(key=lambda d: d["area"], reverse=True)

                    for det in raw_detections:
                        detections.append({
                            "class": det["cls_name"], "track_id": det["track_id"],
                            "confidence": round(det["conf"], 3), "stuck": det.get("is_stuck", False),
                        })

            emergency_status = "AMAN"
            if (is_car_stuck or is_evacuation_active) and is_train_incoming:
                emergency_status = "DARURAT_KRITIS"
            elif is_car_stuck or is_evacuation_active:
                emergency_status = "BAHAYA"

            telemetry = {
                "frame": self._frame_count,
                "detections": detections,
                "is_car_stuck": is_car_stuck,
                "is_evacuating": is_evacuation_active,
                "evacuation_detected": is_evacuation_active,
                "is_train_incoming": is_train_incoming,
                "emergency_status": emergency_status,
                "stuck_vehicle_ids": stuck_vehicles,
            }
            
            # Export results to Shared State
            with self._result_lock:
                self._latest_raw_detections = raw_detections
                self._latest_telemetry = telemetry

    # ------------------------------------------------------------------
    # CRITICAL FIX 08: DJKA Webhook with Absolute Time Debounce
    # ------------------------------------------------------------------
    async def _trigger_djka_webhook(self):
        """
        Fires an asynchronous HTTP POST to the DJKA emergency brake endpoint.
        """
        now = time.time()
        if now - self._last_emergency_time < DJKA_COOLDOWN_SEC:
            return  # Debounce active

        self._last_emergency_time = now

        payload = {
            "system": "NusaRail Vision System",
            "event": "DARURAT_KRITIS",
            "description": "Kendaraan mogok terdeteksi di perlintasan saat KRL mendekat. Sinyal rem darurat otomatis diaktifkan.",
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
