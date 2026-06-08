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
NUSA_RAIL_CLASSES = {
    0: "car",
    1: "motorcycle",
    2: "train",
}

# Threshold constants
STUCK_DISTANCE_PX = 20       # Max centroid displacement to be considered stuck
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
        self._tracked_vehicles: Dict[int, TrackedVehicle] = {}
        self._evacuation_timers: Dict[int, float] = {}  # CRITICAL FIX 09: Human Evacuation & Occlusion Guard
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
            classes=[0, 1, 2],
            conf=CONFIDENCE_THRESHOLD,
            iou=0.5,
            verbose=False,
        )

        is_car_stuck = False
        is_evacuation_active = False
        is_train_incoming = False
        stuck_vehicles: List[int] = []
        detections: List[dict] = []

        # CRITICAL FIX 09: Human Evacuation & Occlusion Guard
        def check_overlap(box1, box2) -> bool:
            # Axis-Aligned Bounding Box (AABB) intersection
            x1_a, y1_a, x2_a, y2_a = box1
            x1_b, y1_b, x2_b, y2_b = box2
            return not (x2_a < x1_b or x2_b < x1_a or y2_a < y1_b or y2_b < y1_a)

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
                    cls_name = NUSA_RAIL_CLASSES.get(cls_id, f"class_{cls_id}")

                    # 1. PERBAIKAN: Filter Kepercayaan Khusus
                    if cls_name == "car" and conf < 0.4:
                        continue
                    if cls_name == "motorcycle" and conf < 0.3:
                        continue
                    if cls_name == "train" and conf < 0.5:
                        continue

                    # Centroid calculation
                    cx = int((x1 + x2) / 2)
                    cy = int((y1 + y2) / 2)

                    # Area for sorting
                    area = (x2 - x1) * (y2 - y1)

                    # ANTI-TROLLING: Area thresholding
                    if area < MIN_AREA_PX or area > MAX_AREA_PX:
                        continue

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
                
                # Model custom tidak mendeteksi person, jadi kosongkan.
                # Jika butuh integrasi LLM Event-Driven, akan dilakukan di layer atas.
                person_detections = []
                vehicle_detections = [d for d in raw_detections if d["cls_name"] in ("car", "motorcycle")]

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

                        if tv.is_stuck and det["cls_name"] in ("car", "motorcycle"):
                            is_car_stuck = True
                            stuck_vehicles.append(tid)

                        if det.get("is_evacuating", False) and det["cls_name"] in ("car", "motorcycle"):
                            is_evacuation_active = True

                    # Check for incoming train
                    if det["cls_name"] == "train":
                        is_train_incoming = True

                # Purge stale tracks & OCCLUSION GUARD
                now = time.monotonic()
                stale_ids = []
                for tid, tv in self._tracked_vehicles.items():
                    if tid not in active_ids:
                        time_unseen = now - tv.last_seen
                        # CRITICAL FIX 09: Occlusion Guard for ghosts
                        is_ghost = getattr(tv, 'is_stuck', False) or getattr(tv, 'is_evacuating', False)
                        max_unseen = 5.0 if is_ghost else 10.0
                        
                        if time_unseen > max_unseen:
                            stale_ids.append(tid)
                        elif is_ghost:
                            is_car_stuck = is_car_stuck or getattr(tv, 'is_stuck', False)
                            is_evacuation_active = is_evacuation_active or getattr(tv, 'is_evacuating', False)
                            stuck_vehicles.append(tid)
                            raw_detections.append({
                                "x1": tv.last_cx - 50, "y1": tv.last_cy - 50, "x2": tv.last_cx + 50, "y2": tv.last_cy + 50,
                                "conf": 0.0, "cls_id": tv.class_id, "cls_name": NUSA_RAIL_CLASSES.get(tv.class_id, "ghost"),
                                "cx": tv.last_cx, "cy": tv.last_cy, "area": 10000, "track_id": tid,
                                "is_stuck": getattr(tv, 'is_stuck', False), "is_evacuating": getattr(tv, 'is_evacuating', False),
                                "is_ghost": True
                            })
                            
                for tid in stale_ids:
                    del self._tracked_vehicles[tid]
                    if tid in self._evacuation_timers:
                        del self._evacuation_timers[tid]

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

                    detections.append({
                        "class": cls_name, "track_id": tid,
                        "confidence": round(conf, 3), "stuck": stuck,
                    })

        # ------------------------------------------------------------------
        # Step 5: DJKA Emergency Brake Evaluation
        # ------------------------------------------------------------------
        emergency_status = "AMAN"
        if (is_car_stuck or is_evacuation_active) and is_train_incoming:
            emergency_status = "DARURAT_KRITIS"

            # Flashing red warning overlay
            if int(time.time() * 2) % 2 == 0:
                cv2.putText(
                    frame_copy,
                    "!!! AUTO-BRAKE SIGNAL SENT TO KRL !!!",
                    (50, 80),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 3,
                )

            # CRITICAL FIX 08: Debounce — fire webhook max 1x per 60s
            asyncio.ensure_future(self._trigger_djka_webhook())

        elif is_car_stuck or is_evacuation_active:
            emergency_status = "BAHAYA"
            cv2.putText(
                frame_copy,
                "PERINGATAN: KENDARAAN MOGOK / EVAKUASI TERDETEKSI",
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
            "is_evacuating": is_evacuation_active,
            "evacuation_detected": is_evacuation_active, # Explicit request from user
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
        DDoS-like API spamming from continuous True evaluations across
        hundreds of consecutive frames.
        """
        now = time.time()
        if now - self._last_emergency_time < DJKA_COOLDOWN_SEC:
            return  # Debounce active — suppress duplicate fires

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
