import os
import cv2
import math
from tqdm import tqdm
from ultralytics import YOLO

# CRITICAL FEATURE: Offline Video Renderer for Pre-calculated Demo
# Script ini digunakan untuk merender video MP4 berkualitas tinggi secara offline tanpa lag, 
# yang akan digunakan khusus untuk kebutuhan presentasi (Canned Demo).

# Konfigurasi
VIDEO_INPUT = "../Tester/Mobil macet di tengah rel disaat kereta mau Lewat di Kalibata Jaksel.mp4"
VIDEO_OUTPUT = "demo_nusarail_final.mp4"
MODEL_PATH = "best_web_optimized.onnx"

if not os.path.exists(MODEL_PATH) and os.path.exists("dataset/best_web_optimized.onnx"):
    MODEL_PATH = "dataset/best_web_optimized.onnx"

# Threshold constants dari Vision Engine
STUCK_DISTANCE_PX = 50
STUCK_DURATION_SEC = 5.0
CONFIDENCE_THRESHOLD = 0.40
MIN_AREA_PX = 1500
MAX_AREA_PX = 250000

class OfflineTrackedVehicle:
    """Modifikasi TrackedVehicle untuk menggunakan video_time bukan time.monotonic()"""
    def __init__(self, track_id: int, cx: int, cy: int, class_id: int, start_time: float):
        self.track_id = track_id
        self.class_id = class_id
        self.initial_cx = cx
        self.initial_cy = cy
        self.last_cx = cx
        self.last_cy = cy
        self.first_seen = start_time
        self.last_seen = start_time
        self.last_box = (0, 0, 0, 0)
        self.is_stuck = False
        self.has_moved = False
        self.is_evacuating = False

    def update(self, cx: int, cy: int, current_time: float, box: tuple = None):
        self.last_cx = cx
        self.last_cy = cy
        self.last_seen = current_time
        if box is not None:
            self.last_box = box

        if not self.has_moved:
            total_delta = math.sqrt((cx - self.initial_cx) ** 2 + (cy - self.initial_cy) ** 2)
            if total_delta > 10:
                self.has_moved = True

        delta = math.sqrt((cx - self.initial_cx) ** 2 + (cy - self.initial_cy) ** 2)

        if delta < STUCK_DISTANCE_PX:
            elapsed = current_time - self.first_seen
            if elapsed > STUCK_DURATION_SEC and self.has_moved:
                self.is_stuck = True
        else:
            self.initial_cx = cx
            self.initial_cy = cy
            self.first_seen = current_time
            self.is_stuck = False

def check_overlap(box1, box2) -> bool:
    x1_a, y1_a, x2_a, y2_a = box1
    x1_b, y1_b, x2_b, y2_b = box2
    return not (x2_a < x1_b or x2_b < x1_a or y2_a < y1_b or y2_b < y1_a)

def main():
    print(f"Loading model: {MODEL_PATH}")
    model = YOLO(MODEL_PATH)
    class_names = model.names

    cap = cv2.VideoCapture(VIDEO_INPUT)
    if not cap.isOpened():
        print(f"ERROR: Cannot open {VIDEO_INPUT}. Pastikan file berada di direktori yang sama.")
        return

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    if fps <= 0 or math.isnan(fps):
        fps = 30.0

    fourcc = cv2.VideoWriter_fourcc(*'avc1')
    out = cv2.VideoWriter(VIDEO_OUTPUT, fourcc, fps, (width, height))

    tracked_vehicles = {}
    evacuation_timers = {}

    print(f"Rendering {total_frames} frames at {fps:.1f} FPS to {VIDEO_OUTPUT}...")
    
    for frame_idx in tqdm(range(total_frames)):
        ret, frame = cap.read()
        if not ret:
            break

        # Waktu video simulasi (akurat tanpa terpengaruh lag hardware CPU)
        current_time = frame_idx / fps

        # --- YOLOv8 Inference ---
        results = model.track(
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
        raw_detections = []

        if results and len(results) > 0:
            boxes = results[0].boxes
            if boxes is not None and len(boxes) > 0:
                for box in boxes:
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                    conf = float(box.conf[0])
                    cls_id = int(box.cls[0])
                    cls_name = class_names.get(cls_id, f"class_{cls_id}")

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
                        if tid not in evacuation_timers:
                            evacuation_timers[tid] = current_time
                        elif current_time - evacuation_timers[tid] > 4.0:
                            v_det["is_evacuating"] = True
                    else:
                        if tid in evacuation_timers:
                            del evacuation_timers[tid]

                for det in raw_detections:
                    tid = det["track_id"]
                    if tid is not None:
                        active_ids.add(tid)

                        box_tuple = (det["x1"], det["y1"], det["x2"], det["y2"])
                        if tid in tracked_vehicles:
                            tracked_vehicles[tid].update(det["cx"], det["cy"], current_time, box_tuple)
                        else:
                            tv_new = OfflineTrackedVehicle(
                                track_id=tid,
                                cx=det["cx"], cy=det["cy"],
                                class_id=det["cls_id"],
                                start_time=current_time
                            )
                            tv_new.last_box = box_tuple
                            tracked_vehicles[tid] = tv_new

                        tv = tracked_vehicles[tid]
                        det["is_stuck"] = tv.is_stuck
                        
                        if det.get("is_evacuating", False):
                            tv.is_evacuating = True
                        else:
                            det["is_evacuating"] = tv.is_evacuating

                        if tv.is_stuck and det["cls_name"] in ("car", "motorcycle", "bus", "truck"):
                            is_car_stuck = True
                        if det.get("is_evacuating", False) and det["cls_name"] in ("car", "motorcycle", "bus", "truck"):
                            is_evacuation_active = True

                    if det["cls_name"] == "train":
                        is_train_incoming = True

                stale_ids = []
                for tid, tv in tracked_vehicles.items():
                    if tid not in active_ids:
                        time_unseen = current_time - tv.last_seen
                        is_critical = tv.is_stuck or tv.is_evacuating
                        
                        # Latch danger state: keep critical vehicles alive for 300s
                        max_unseen = 300.0 if is_critical else 1.5
                        
                        if time_unseen > max_unseen:
                            stale_ids.append(tid)
                        else:
                            if is_critical:
                                is_car_stuck = is_car_stuck or tv.is_stuck
                                is_evacuation_active = is_evacuation_active or tv.is_evacuating
                                
                                # Redraw EXACT last known box so it looks completely stable
                                raw_detections.append({
                                    "x1": tv.last_box[0], "y1": tv.last_box[1], "x2": tv.last_box[2], "y2": tv.last_box[3],
                                    "conf": 0.0, "cls_id": tv.class_id, "cls_name": class_names.get(tv.class_id, "car"),
                                    "cx": tv.last_cx, "cy": tv.last_cy, "area": 10000, "track_id": tid,
                                    "is_stuck": tv.is_stuck, "is_evacuating": tv.is_evacuating,
                                    "is_ghost": False # No OCCLUDED text
                                })
                            
                for tid in stale_ids:
                    del tracked_vehicles[tid]
                    if tid in evacuation_timers:
                        del evacuation_timers[tid]

                raw_detections.sort(key=lambda d: d["area"], reverse=True)

        emergency_status = "AMAN"
        if (is_car_stuck or is_evacuation_active) and is_train_incoming:
            emergency_status = "DARURAT_KRITIS"
        elif is_car_stuck or is_evacuation_active:
            emergency_status = "BAHAYA"

        # --- DRAWING ON FRAME ---
        for det in raw_detections:
            x1, y1, x2, y2 = det["x1"], det["y1"], det["x2"], det["y2"]
            cls_name = det["cls_name"]
            conf = det["conf"]
            tid = det["track_id"]
            stuck = det.get("is_stuck", False)
            evacuating = det.get("is_evacuating", False)

            if evacuating:
                color = (255, 0, 255)
                thickness = 2
            elif stuck:
                color = (0, 0, 255)
                thickness = 2
            elif cls_name == "car":
                color = (255, 0, 0)
                thickness = 2
            elif cls_name == "train":
                color = (0, 165, 255)
                thickness = 2
            elif cls_name == "motorcycle":
                color = (0, 255, 0)
                thickness = 2
            else:
                color = (0, 255, 0)
                thickness = 2

            cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)

            id_str = f" ID:{tid}" if tid is not None else ""
            label = f"{cls_name} {conf:.2f}"
            
            if evacuating:
                label += " EVAKUASI!"
            elif stuck:
                label += " MOGOK!"

            label_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]
            cv2.rectangle(frame, (x1, y1 - label_size[1] - 10),
                          (x1 + label_size[0], y1), color, -1)
            cv2.putText(frame, label, (x1, y1 - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        # CRITICAL FIX 14: Dynamic HUD Overlay
        if emergency_status in ["DARURAT_KRITIS", "BAHAYA"]:
            banner_height = 80
            cv2.rectangle(frame, (0, 0), (frame.shape[1], banner_height), (0, 0, 255), -1)
            
            if emergency_status == "DARURAT_KRITIS" and int(current_time * 2) % 2 == 0:
                alert_text = "!!! AUTO-BRAKE SIGNAL SENT TO KRL !!!"
                text_color = (0, 255, 255)
            else:
                alert_text = "AWAS! KENDARAAN TERJEBAK DI REL!"
                text_color = (255, 255, 255)

            text_size = cv2.getTextSize(alert_text, cv2.FONT_HERSHEY_SIMPLEX, 1.0, 3)[0]
            text_x = (frame.shape[1] - text_size[0]) // 2
            text_y = (banner_height + text_size[1]) // 2
            
            cv2.putText(frame, alert_text, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 1.0, text_color, 3)

        status_text = f"Status: {emergency_status}"
        status_color = (0, 255, 0) if emergency_status == "AMAN" else (0, 0, 255)
        status_thickness = 1 if emergency_status == "AMAN" else 2
        
        info_text = f"NusaRail Vision | Frame #{frame_idx} | "
        cv2.putText(
            frame, info_text, (10, frame.shape[0] - 15),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1,
        )
        info_text_size = cv2.getTextSize(info_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]
        cv2.putText(
            frame, status_text, (10 + info_text_size[0], frame.shape[0] - 15),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, status_color, status_thickness,
        )

        out.write(frame)

    cap.release()
    out.release()
    print(f"\nRendering complete! Output saved to: {VIDEO_OUTPUT}")

if __name__ == "__main__":
    main()
