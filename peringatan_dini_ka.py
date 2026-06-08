"""
╔══════════════════════════════════════════════════════════════════════════════╗
║    SISTEM PERINGATAN DINI PERLINTASAN KERETA API — NusaRail Sentinel       ║
║    Production-Ready v1.0                                                    ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Vision    : YOLOv8n (Ultralytics) — deteksi car, person, train            ║
║  Context   : Gemini 2.0 Flash API — analisis situasi setiap 5 detik        ║
║  Stream    : yt-dlp — ekstrak URL streaming YouTube secara dinamis         ║
║  Concurrency: threading + queue.Queue (3 thread terpisah)                   ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  CARA MENJALANKAN:                                                          ║
║    python peringatan_dini_ka.py --url "https://www.youtube.com/watch?v=..." ║
║    python peringatan_dini_ka.py --url video.mp4                             ║
║    python peringatan_dini_ka.py --url 0  (webcam)                           ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

# ─────────────────────────────────────────────────────────────────────────────
# STDLIB
# ─────────────────────────────────────────────────────────────────────────────
import argparse
import io
import json
import logging
import os
import subprocess
import sys
import threading
import time
import warnings
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Queue
from typing import Dict, List, Optional, Tuple

# ─────────────────────────────────────────────────────────────────────────────
# THIRD-PARTY
# ─────────────────────────────────────────────────────────────────────────────
import cv2
import numpy as np

# Matikan warning yang tidak relevan
warnings.filterwarnings("ignore", category=FutureWarning)
os.environ["YOLO_VERBOSE"] = "False"

# Muat .env jika ada
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

# ─────────────────────────────────────────────────────────────────────────────
# KONFIGURASI LOGGING
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("sentinel.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("Sentinel")


# ─────────────────────────────────────────────────────────────────────────────
# KONSTANTA
# ─────────────────────────────────────────────────────────────────────────────
GEMINI_API_KEY   = os.getenv("GEMINI_API_KEY", "AIzaSyCCNLkAMh6VmZuaoG1LuqkAa9O0cMA-hVA")
GEMINI_MODEL     = "models/gemini-2.5-flash"       # Model dengan quota paling besar
GEMINI_INTERVAL  = 5                               # kirim frame ke Gemini setiap N detik
YOLO_MODEL       = str(Path(__file__).parent / "Dataset" / "best_pytorch.pt")
YOLO_FALLBACK    = "yolov8n.pt"                   # fallback ke model publik jika tidak ada
CONF_THRESHOLD   = 0.35
QUEUE_SIZE       = 32
STALL_SECONDS    = 6.0
DISPLACEMENT_TOL = 18.0                            # piksel — kendaraan "diam"

# Warna BGR
C_GREEN   = (0,   210, 80)
C_RED     = (0,    30, 230)
C_ORANGE  = (0,   165, 255)
C_YELLOW  = (0,   220, 220)
C_WHITE   = (255, 255, 255)
C_DARK    = (15,   15,  15)
C_CYAN    = (230, 200,   0)

# ─────────────────────────────────────────────────────────────────────────────
# DATACLASS — Status kendaraan individual (untuk deteksi mogok)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class VehicleState:
    """Riwayat posisi satu kendaraan yang sedang dilacak ByteTrack."""
    track_id  : int
    cls_name  : str
    positions : deque = field(default_factory=lambda: deque(maxlen=120))
    is_stalled: bool  = False
    stalled_at: Optional[float] = None

    def push(self, cx: float, cy: float) -> None:
        self.positions.append((cx, cy, time.monotonic()))

    @property
    def stall_duration(self) -> float:
        return (time.monotonic() - self.stalled_at) if self.stalled_at else 0.0

    def max_displacement(self, window: float = 5.0) -> float:
        """Pergeseran maksimum dalam N detik terakhir (piksel)."""
        now = time.monotonic()
        pts = [(x, y) for x, y, t in self.positions if now - t <= window]
        if len(pts) < 2:
            return float("inf")
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return max(max(xs) - min(xs), max(ys) - min(ys))


# ─────────────────────────────────────────────────────────────────────────────
# DATACLASS — Hasil inferensi YOLO satu frame
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class YOLOResult:
    """Payload yang dikirim dari YOLO Worker ke Main Thread."""
    frame      : np.ndarray
    detections : List[Dict]          # [{cls, conf, xyxy, tid, is_stalled, dur}]
    fps        : float
    n_stall    : int
    n_train    : int
    timestamp  : float = field(default_factory=time.monotonic)


# ═════════════════════════════════════════════════════════════════════════════
# KOMPONEN 1 — StreamExtractor
# ═════════════════════════════════════════════════════════════════════════════
class StreamExtractor:
    """
    Mengekstrak direct-stream URL dari YouTube menggunakan yt-dlp.
    Menyertakan retry mechanism eksponensial.
    Mendukung file lokal dan webcam (index integer).
    """

    MAX_RETRIES = 5
    FORMATS = [
        "bestvideo[height<=720][ext=mp4]+bestaudio/best[height<=720][ext=mp4]",
        "bestvideo[height<=480][ext=mp4]+bestaudio/best[height<=480][ext=mp4]",
        "best[height<=720]/best[height<=480]/best",
    ]

    @classmethod
    def resolve(cls, source: str) -> any:
        """Tentukan jenis sumber dan kembalikan sumber yang siap dipakai."""
        src = str(source).strip()

        # Webcam
        if src.isdigit():
            log.info(f"[Stream] Webcam index={src}")
            return int(src)

        # YouTube
        if "youtube.com" in src or "youtu.be" in src:
            return cls._extract_youtube(src)

        # File lokal
        if Path(src).exists():
            log.info(f"[Stream] File lokal: {src}")
            return src

        raise FileNotFoundError(f"Sumber tidak dikenali: {src}")

    @classmethod
    def _extract_youtube(cls, url: str) -> str:
        """Ekstrak URL streaming YouTube. Retry eksponensial hingga MAX_RETRIES."""
        delay = 2
        for attempt in range(1, cls.MAX_RETRIES + 1):
            log.info(f"[Stream] yt-dlp percobaan {attempt}/{cls.MAX_RETRIES}…")
            for fmt in cls.FORMATS:
                try:
                    result = subprocess.run(
                        [
                            "yt-dlp", "--no-warnings", "--quiet",
                            "-f", fmt, "-g", "--no-playlist",
                            "--extractor-args", "youtube:player_client=android,web",
                            url,
                        ],
                        capture_output=True, text=True, timeout=30,
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        stream_url = result.stdout.strip().splitlines()[0]
                        log.info(f"[Stream] URL berhasil diekstrak ({fmt[:35]}…)")
                        return stream_url
                except subprocess.TimeoutExpired:
                    log.warning("[Stream] yt-dlp timeout — coba format lain…")
                except FileNotFoundError:
                    raise RuntimeError(
                        "yt-dlp tidak ditemukan! Jalankan: pip install yt-dlp"
                    )

            log.warning(f"[Stream] Semua format gagal — tunggu {delay}s…")
            time.sleep(delay)
            delay = min(delay * 2, 60)

        raise RuntimeError(
            f"Gagal mendapatkan URL YouTube setelah {cls.MAX_RETRIES}× percobaan."
        )


# ═════════════════════════════════════════════════════════════════════════════
# KOMPONEN 2 — FrameProducer (Thread 1)
# ═════════════════════════════════════════════════════════════════════════════
class FrameProducer(threading.Thread):
    """
    THREAD 1 — Pembaca frame dari VideoCapture.
    Menaruh frame ke dalam frame_queue secara kontinu.
    Auto-reconnect jika stream terputus.
    """

    RECONNECT_FAIL_LIMIT = 40   # frame kosong berturut-turut → reconnect
    RECONNECT_DELAY      = 5    # detik sebelum coba reconnect

    def __init__(
        self,
        source     : str,
        frame_queue: Queue,
        stop_evt   : threading.Event,
        raw_source : str,       # URL asli YouTube (untuk re-resolve jika putus)
    ) -> None:
        super().__init__(daemon=True, name="FrameProducer")
        self.source      = source
        self.frame_queue = frame_queue
        self.stop_evt    = stop_evt
        self.raw_source  = raw_source
        self.fps         = 25.0

    def _open(self, src) -> Optional[cv2.VideoCapture]:
        """Buka VideoCapture. Kembalikan None jika gagal."""
        cap = cv2.VideoCapture(src)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)
        if cap.isOpened():
            fps = cap.get(cv2.CAP_PROP_FPS)
            if fps > 0:
                self.fps = fps
            log.info(f"[Producer] VideoCapture terbuka (FPS={self.fps:.1f})")
            return cap
        log.error("[Producer] Gagal membuka VideoCapture.")
        return None

    def _re_resolve(self) -> Optional[str]:
        """Re-ekstrak URL YouTube jika stream terputus."""
        try:
            return StreamExtractor.resolve(self.raw_source)
        except Exception as exc:
            log.error(f"[Producer] Re-resolve gagal: {exc}")
            return None

    def run(self) -> None:
        cap   = self._open(self.source)
        fails = 0

        while not self.stop_evt.is_set():
            if cap is None:
                time.sleep(self.RECONNECT_DELAY)
                new_src = self._re_resolve()
                if new_src:
                    cap = self._open(new_src)
                continue

            ret, frame = cap.read()

            # ── Frame gagal dibaca (stream putus / buffer habis) ─────────
            if not ret or frame is None:
                fails += 1
                if fails >= self.RECONNECT_FAIL_LIMIT:
                    log.warning(
                        f"[Producer] {fails} frame kosong — reconnect…"
                    )
                    cap.release()
                    cap = None
                    fails = 0
                time.sleep(0.01)
                continue

            fails = 0

            # ── Kirim ke antrian (drop frame lama jika antrian penuh) ────
            if self.frame_queue.full():
                try:
                    self.frame_queue.get_nowait()
                except Empty:
                    pass
            self.frame_queue.put(frame)

        if cap:
            cap.release()
        log.info("[Producer] Thread selesai.")


# ═════════════════════════════════════════════════════════════════════════════
# KOMPONEN 3 — YOLOWorker (Thread 2)
# ═════════════════════════════════════════════════════════════════════════════
class YOLOWorker(threading.Thread):
    """
    THREAD 2 — Inferensi YOLO + ByteTrack.
    Mengambil frame dari frame_queue, mendeteksi objek,
    dan menyimpan hasilnya ke result_queue untuk ditampilkan Main Thread.
    Juga memperbarui shared_frame untuk diambil Gemini Worker.
    """

    VEHICLE_CLASSES = {"car", "motorcycle", "truck", "bus"}

    def __init__(
        self,
        frame_queue : Queue,
        result_queue: Queue,
        shared_frame: dict,          # {"frame": np.ndarray} — shared state
        frame_lock  : threading.Lock,
        stop_evt    : threading.Event,
        model_path  : str = YOLO_MODEL,
        device      : str = "cpu",
    ) -> None:
        super().__init__(daemon=True, name="YOLOWorker")
        self.frame_queue  = frame_queue
        self.result_queue = result_queue
        self.shared_frame = shared_frame
        self.frame_lock   = frame_lock
        self.stop_evt     = stop_evt
        self.model_path   = model_path
        self.device       = device
        self.model        = None
        self.class_names  : List[str] = []
        self._states      : Dict[int, VehicleState] = {}
        self._fps_cnt     = 0
        self._fps_t0      = time.monotonic()
        self.current_fps  = 0.0

    # ── Muat Model ─────────────────────────────────────────────────────────
    def _load_model(self) -> bool:
        """Muat model YOLOv8. Fallback ke yolov8n.pt jika model kustom tidak ada."""
        try:
            from ultralytics import YOLO
        except ImportError:
            log.critical("ultralytics tidak terinstall! pip install ultralytics")
            return False

        model_path = self.model_path
        if not Path(model_path).exists():
            log.warning(
                f"[YOLO] Model kustom tidak ditemukan: {model_path}\n"
                f"       Fallback ke {YOLO_FALLBACK} (model publik YOLOv8n)"
            )
            model_path = YOLO_FALLBACK

        try:
            log.info(f"[YOLO] Memuat model: {model_path}")
            self.model = YOLO(model_path)
            self.model.to(self.device)
            self.class_names = list(self.model.names.values())
            log.info(f"[YOLO] Model siap — {len(self.class_names)} kelas: {self.class_names}")
            return True
        except Exception as exc:
            log.critical(f"[YOLO] Gagal memuat model: {exc}")
            return False

    # ── Update State Kendaraan ─────────────────────────────────────────────
    def _update_vehicle(
        self, tid: int, cls: str, cx: float, cy: float
    ) -> VehicleState:
        """Perbarui posisi dan status mogok kendaraan berdasarkan track_id."""
        if tid not in self._states:
            self._states[tid] = VehicleState(track_id=tid, cls_name=cls)
        state = self._states[tid]
        state.push(cx, cy)

        disp = state.max_displacement(window=5.0)
        if disp < DISPLACEMENT_TOL:
            if state.stalled_at is None:
                state.stalled_at = time.monotonic()
            elif time.monotonic() - state.stalled_at >= STALL_SECONDS:
                if not state.is_stalled:
                    log.warning(
                        f"[YOLO] KENDARAAN MOGOK — ID={tid} ({cls}) "
                        f"diam selama {state.stall_duration:.1f}s"
                    )
                state.is_stalled = True
        else:
            state.is_stalled = False
            state.stalled_at = None

        return state

    # ── Hapus State Basi ───────────────────────────────────────────────────
    def _cleanup(self) -> None:
        now = time.monotonic()
        dead = [
            tid for tid, s in self._states.items()
            if s.positions and (now - s.positions[-1][2]) > 30.0
        ]
        for tid in dead:
            del self._states[tid]

    # ── Proses Frame ───────────────────────────────────────────────────────
    def _infer(self, frame: np.ndarray) -> YOLOResult:
        """Jalankan YOLO + ByteTrack, kembalikan YOLOResult."""
        results = self.model.track(
            source=frame,
            conf=CONF_THRESHOLD,
            iou=0.45,
            persist=True,
            tracker="bytetrack.yaml",
            verbose=False,
            device=self.device,
        )

        detections: List[Dict] = []
        n_stall = n_train = 0

        for r in results:
            if r.boxes is None:
                continue
            for box in r.boxes:
                xyxy    = box.xyxy[0].cpu().numpy().astype(int)
                conf    = float(box.conf[0])
                cls_id  = int(box.cls[0])
                cls_nm  = (
                    self.class_names[cls_id]
                    if cls_id < len(self.class_names)
                    else "unknown"
                )
                tid = int(box.id[0]) if box.id is not None else -1
                x1, y1, x2, y2 = xyxy
                cx, cy = (x1 + x2) / 2, (y1 + y2) / 2

                is_stalled  = False
                stall_dur   = 0.0

                if cls_nm == "train":
                    n_train += 1
                elif cls_nm in self.VEHICLE_CLASSES and tid >= 0:
                    state      = self._update_vehicle(tid, cls_nm, cx, cy)
                    is_stalled = state.is_stalled
                    stall_dur  = state.stall_duration
                    if is_stalled:
                        n_stall += 1

                detections.append({
                    "cls"      : cls_nm,
                    "conf"     : conf,
                    "xyxy"     : (x1, y1, x2, y2),
                    "tid"      : tid,
                    "stalled"  : is_stalled,
                    "dur"      : stall_dur,
                })

        # Hitung FPS inferensi
        self._fps_cnt += 1
        elapsed = time.monotonic() - self._fps_t0
        if elapsed >= 1.0:
            self.current_fps = self._fps_cnt / elapsed
            self._fps_cnt    = 0
            self._fps_t0     = time.monotonic()

        self._cleanup()

        return YOLOResult(
            frame=frame, detections=detections,
            fps=self.current_fps,
            n_stall=n_stall, n_train=n_train,
        )

    # ── Thread Utama ───────────────────────────────────────────────────────
    def run(self) -> None:
        if not self._load_model():
            return

        while not self.stop_evt.is_set():
            try:
                frame = self.frame_queue.get(timeout=2.0)
            except Empty:
                continue

            # Simpan frame terbaru untuk Gemini Worker
            with self.frame_lock:
                self.shared_frame["frame"] = frame.copy()
                self.shared_frame["ts"]    = time.monotonic()

            # Inference
            try:
                result = self._infer(frame)
            except Exception as exc:
                log.error(f"[YOLO] Error inferensi: {exc}")
                result = YOLOResult(
                    frame=frame, detections=[], fps=0.0, n_stall=0, n_train=0
                )

            # Kirim ke Main Thread
            if self.result_queue.full():
                try:
                    self.result_queue.get_nowait()
                except Empty:
                    pass
            self.result_queue.put(result)

        log.info("[YOLO] Thread selesai.")


# ═════════════════════════════════════════════════════════════════════════════
# KOMPONEN 4 — GeminiWorker (Thread 3)
# ═════════════════════════════════════════════════════════════════════════════
class GeminiWorker(threading.Thread):
    """
    THREAD 3 — Gemini API Worker (berjalan di latar belakang).
    Mengambil 1 frame setiap GEMINI_INTERVAL detik,
    mengirimnya ke Gemini API, dan memperbarui gemini_status (shared dict).
    Jika API gagal / rate-limit, tampilkan pesan fallback dan terus berjalan.
    """

    PROMPT = (
        "Kamu adalah sistem kecerdasan buatan untuk deteksi bahaya perlintasan kereta api. "
        "Analisis frame CCTV ini dan jawab secara singkat dalam bahasa Indonesia:\n"
        "1. Apakah ada kendaraan (mobil/motor/truk) yang berhenti atau mogok di tengah rel?\n"
        "2. Apakah ada kereta yang terlihat atau mendekati perlintasan?\n"
        "3. Apa status bahaya perlintasan saat ini? (AMAN / WASPADA / BAHAYA KRITIS)\n"
        "Format jawaban: STATUS: [status] | [penjelasan singkat maks 15 kata]"
    )

    def __init__(
        self,
        api_key     : str,
        shared_frame: dict,
        frame_lock  : threading.Lock,
        gemini_status: dict,          # {"text": str, "ts": float} — shared state
        status_lock : threading.Lock,
        stop_evt    : threading.Event,
        interval_sec: int = GEMINI_INTERVAL,
    ) -> None:
        super().__init__(daemon=True, name="GeminiWorker")
        self.api_key      = api_key
        self.shared_frame = shared_frame
        self.frame_lock   = frame_lock
        self.gemini_status = gemini_status
        self.status_lock  = status_lock
        self.stop_evt     = stop_evt
        self.interval     = interval_sec
        self._client      = None
        self._available   = False

    # ── Inisialisasi Gemini Client ─────────────────────────────────────────
    def _init_client(self) -> bool:
        if not self.api_key:
            log.warning("[Gemini] API key tidak diset — worker dinonaktifkan.")
            return False
        try:
            from google import genai
            self._client = genai.Client(api_key=self.api_key)
            log.info(f"[Gemini] Client siap (model: {GEMINI_MODEL})")
            return True
        except Exception as exc:
            log.error(f"[Gemini] Gagal inisialisasi: {exc}")
            return False

    # ── Kirim Frame ke Gemini ──────────────────────────────────────────────
    def _call_api(self, frame: np.ndarray) -> str:
        """
        Encode frame ke JPEG, kirim ke Gemini, kembalikan teks respons.
        Lempar exception jika gagal (akan ditangani caller).
        """
        from google.genai import types

        # Encode ke JPEG bytes (kualitas 80 untuk hemat bandwidth)
        success, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not success:
            raise ValueError("Gagal mengkode frame ke JPEG")
        img_bytes = buf.tobytes()

        response = self._client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
                self.PROMPT,
            ],
        )
        return response.text.strip()

    # ── Tulis Status ───────────────────────────────────────────────────────
    def _write_status(self, text: str) -> None:
        with self.status_lock:
            self.gemini_status["text"] = text
            self.gemini_status["ts"]   = time.monotonic()

    # ── Thread Utama ───────────────────────────────────────────────────────
    def run(self) -> None:
        self._available = self._init_client()
        if not self._available:
            self._write_status("Gemini API: Tidak dikonfigurasi")
            return

        self._write_status("Gemini API: Menginisialisasi…")

        while not self.stop_evt.is_set():
            # Ambil snapshot frame terbaru
            with self.frame_lock:
                frame = self.shared_frame.get("frame", None)
            
            if frame is not None:
                try:
                    self._write_status("Gemini API: Menganalisis…")
                    text = self._call_api(frame)
                    # Potong teks agar tidak terlalu panjang di overlay
                    short = text[:90] + ("…" if len(text) > 90 else "")
                    self._write_status(short)
                    log.info(f"[Gemini] → {short}")
                except Exception as exc:
                    err_msg = str(exc)
                    if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                        self._write_status("Gemini API: Rate limit — Reconnecting…")
                        log.warning("[Gemini] Rate limit — tunggu 60s…")
                        # Tunggu lebih lama saat rate limit
                        for _ in range(60):
                            if self.stop_evt.is_set():
                                break
                            time.sleep(1)
                        continue
                    elif "quota" in err_msg.lower():
                        self._write_status("Gemini API: Quota habis — mode lokal")
                        log.warning("[Gemini] Quota habis — beralih ke mode lokal YOLO saja")
                        # Nonaktifkan Gemini selama 5 menit
                        for _ in range(300):
                            if self.stop_evt.is_set():
                                break
                            time.sleep(1)
                        continue
                    else:
                        self._write_status(f"Gemini API: Reconnecting… ({err_msg[:30]})")
                        log.warning(f"[Gemini] Error: {exc}")

            # Tunggu interval berikutnya
            for _ in range(self.interval):
                if self.stop_evt.is_set():
                    break
                time.sleep(1)

        log.info("[Gemini] Thread selesai.")


# ═════════════════════════════════════════════════════════════════════════════
# KOMPONEN 5 — Visualizer (Utility kelas statis)
# ═════════════════════════════════════════════════════════════════════════════
class Visualizer:
    """
    Semua fungsi menggambar pada frame OpenCV.
    Dipanggil hanya dari Main Thread (untuk keamanan GUI).
    """

    @staticmethod
    def draw_box(frame: np.ndarray, det: Dict) -> None:
        """Gambar satu bounding box dengan label dan warna sesuai status."""
        x1, y1, x2, y2 = det["xyxy"]
        cls   = det["cls"]
        conf  = det["conf"]
        tid   = det["tid"]
        stall = det["stalled"]
        dur   = det["dur"]

        if cls == "train":
            color = C_ORANGE
            label = f"KERETA  {conf:.0%}"
            thick = 3
        elif stall:
            color = C_RED
            label = f"MOGOK  ID:{tid}  {dur:.0f}s"
            thick = 3
            # Overlay merah transparan pada kendaraan mogok
            overlay = frame.copy()
            cv2.rectangle(overlay, (x1, y1), (x2, y2), color, -1)
            cv2.addWeighted(overlay, 0.20, frame, 0.80, 0, frame)
        else:
            color = C_GREEN
            label = f"{cls}  ID:{tid}  {conf:.0%}" if tid >= 0 else f"{cls}  {conf:.0%}"
            thick = 2

        cv2.rectangle(frame, (x1, y1), (x2, y2), color, thick)

        # Label background
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.50, 1)
        bgy = max(0, y1 - th - 8)
        cv2.rectangle(frame, (x1, bgy), (x1 + tw + 8, y1), color, -1)
        cv2.putText(
            frame, label, (x1 + 4, y1 - 4),
            cv2.FONT_HERSHEY_SIMPLEX, 0.50, C_WHITE, 1, cv2.LINE_AA,
        )

    @staticmethod
    def draw_hud(
        frame        : np.ndarray,
        result       : YOLOResult,
        gemini_text  : str,
        gemini_lag   : float,
    ) -> np.ndarray:
        """
        Gambar HUD (Heads-Up Display) di atas frame:
        - Panel info YOLO (kiri atas)
        - Panel Gemini context (bawah)
        - Alert banner jika ada mogok/kereta
        """
        h, w = frame.shape[:2]

        # ── Panel info YOLO (kiri atas) ─────────────────────────────────
        panel_h = 115
        overlay = frame.copy()
        cv2.rectangle(overlay, (5, 5), (340, panel_h), C_DARK, -1)
        frame = cv2.addWeighted(overlay, 0.75, frame, 0.25, 0)

        info_lines = [
            (f"NusaRail Sentinel  |  FPS: {result.fps:.1f}", C_WHITE, 0.55),
            (f"Deteksi: {len(result.detections)}  |  Mogok: {result.n_stall}  |  Kereta: {result.n_train}",
             C_YELLOW, 0.50),
            ("─" * 46, (60, 60, 60), 0.40),
            (f"Gemini ({gemini_lag:.0f}s lalu): {gemini_text[:48]}",
             C_CYAN, 0.46),
        ]
        for i, (txt, col, sc) in enumerate(info_lines):
            cv2.putText(
                frame, txt, (12, 28 + i * 22),
                cv2.FONT_HERSHEY_SIMPLEX, sc, col, 1, cv2.LINE_AA,
            )

        # ── Alert Banner (atas tengah) jika kondisi darurat ──────────────
        if result.n_stall > 0 or result.n_train > 0:
            banner_txt = []
            if result.n_stall > 0:
                banner_txt.append(f"!  KENDARAAN MOGOK DI REL  !")
            if result.n_train > 0:
                banner_txt.append(f"!  KERETA TERDETEKSI  !")

            for i, btxt in enumerate(banner_txt):
                (bw, bh), _ = cv2.getTextSize(
                    btxt, cv2.FONT_HERSHEY_DUPLEX, 0.75, 2
                )
                bx = (w - bw) // 2
                by = 40 + i * 36

                # Kedip: tampilkan hanya di detik genap
                if int(time.monotonic()) % 2 == 0:
                    ov2 = frame.copy()
                    cv2.rectangle(ov2, (bx - 10, by - bh - 6), (bx + bw + 10, by + 6),
                                  (0, 0, 180), -1)
                    frame = cv2.addWeighted(ov2, 0.85, frame, 0.15, 0)
                    cv2.putText(
                        frame, btxt, (bx, by),
                        cv2.FONT_HERSHEY_DUPLEX, 0.75, C_WHITE, 2, cv2.LINE_AA,
                    )

        # ── Teks Gemini di bawah layar (full bar) ────────────────────────
        gem_display = f"[AI] {gemini_text}"[:100]
        ov3 = frame.copy()
        cv2.rectangle(ov3, (0, h - 32), (w, h), C_DARK, -1)
        frame = cv2.addWeighted(ov3, 0.80, frame, 0.20, 0)
        cv2.putText(
            frame, gem_display, (8, h - 10),
            cv2.FONT_HERSHEY_SIMPLEX, 0.46, C_CYAN, 1, cv2.LINE_AA,
        )

        # ── Waktu sekarang (pojok kanan atas) ────────────────────────────
        ts_text = time.strftime("%H:%M:%S")
        (tw, _), _ = cv2.getTextSize(ts_text, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
        cv2.putText(
            frame, ts_text, (w - tw - 10, 22),
            cv2.FONT_HERSHEY_SIMPLEX, 0.55, C_WHITE, 1, cv2.LINE_AA,
        )

        return frame


# ═════════════════════════════════════════════════════════════════════════════
# KOMPONEN 6 — SentinelApp (Orkestrator Utama)
# ═════════════════════════════════════════════════════════════════════════════
class SentinelApp:
    """
    Orkestrator Sistem Peringatan Dini Perlintasan KA.

    Mengikat semua komponen:
      StreamExtractor → FrameProducer (Thread 1)
                        → YOLOWorker (Thread 2) → [result_queue] → Main Thread
                        → GeminiWorker (Thread 3) → [shared_state]
    """

    WINDOW  = "NusaRail Sentinel — Tekan Q untuk keluar"
    LOG_FILE = "sentinel_detections.jsonl"

    def __init__(
        self,
        source     : str,
        model_path : str = YOLO_MODEL,
        device     : str = "cpu",
        api_key    : str = GEMINI_API_KEY,
        log_det    : bool = True,
    ) -> None:
        self.source     = source
        self.model_path = model_path
        self.device     = device
        self.api_key    = api_key
        self.log_det    = log_det

    # ── Cetak Header ke Terminal ───────────────────────────────────────────
    def _print_banner(self) -> None:
        print("\n" + "=" * 65)
        print("   NUSARAIL SENTINEL — Sistem Peringatan Dini Perlintasan KA")
        print("=" * 65)
        print(f"   Sumber  : {self.source}")
        print(f"   Model   : {self.model_path}")
        print(f"   Device  : {self.device}")
        print(f"   Gemini  : {'AKTIF' if self.api_key else 'NONAKTIF'}")
        print(f"   Log     : {self.LOG_FILE}")
        print("=" * 65)
        print("   Tekan Q di jendela video untuk keluar dengan aman.\n")

    # ── Simpan Log Deteksi ke JSONL ────────────────────────────────────────
    def _log_detection(self, result: YOLOResult, gemini_text: str) -> None:
        if not self.log_det:
            return
        if result.n_stall == 0 and result.n_train == 0:
            return
        entry = {
            "timestamp" : time.strftime("%Y-%m-%dT%H:%M:%S"),
            "n_stall"   : result.n_stall,
            "n_train"   : result.n_train,
            "gemini"    : gemini_text,
            "detections": [
                {k: (list(v) if isinstance(v, tuple) else v)
                 for k, v in d.items()}
                for d in result.detections
            ],
        }
        try:
            with open(self.LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as exc:
            log.debug(f"[App] Log write error: {exc}")

    # ── Loop Utama (Main Thread) ───────────────────────────────────────────
    def run(self) -> None:
        self._print_banner()

        # 1. Resolve sumber stream
        try:
            resolved = StreamExtractor.resolve(self.source)
        except Exception as exc:
            log.critical(f"[App] Gagal resolve sumber: {exc}")
            sys.exit(1)

        # 2. Siapkan antrian & event
        frame_queue   = Queue(maxsize=QUEUE_SIZE)
        result_queue  = Queue(maxsize=8)
        stop_evt      = threading.Event()
        frame_lock    = threading.Lock()
        status_lock   = threading.Lock()

        shared_frame  : Dict = {"frame": None, "ts": 0.0}
        gemini_status : Dict = {
            "text": "Gemini API: Menginisialisasi…",
            "ts"  : time.monotonic(),
        }

        # 3. Buat semua worker
        producer = FrameProducer(
            source=resolved, frame_queue=frame_queue,
            stop_evt=stop_evt, raw_source=self.source,
        )
        yolo_worker = YOLOWorker(
            frame_queue=frame_queue, result_queue=result_queue,
            shared_frame=shared_frame, frame_lock=frame_lock,
            stop_evt=stop_evt,
            model_path=self.model_path, device=self.device,
        )
        gemini_worker = GeminiWorker(
            api_key=self.api_key,
            shared_frame=shared_frame, frame_lock=frame_lock,
            gemini_status=gemini_status, status_lock=status_lock,
            stop_evt=stop_evt, interval_sec=GEMINI_INTERVAL,
        )

        # 4. Start semua thread
        producer.start()
        yolo_worker.start()
        gemini_worker.start()
        log.info("[App] Semua thread dimulai — menunggu frame…")

        # 5. Main Thread: tampilkan hasil di OpenCV
        cv2.namedWindow(self.WINDOW, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(self.WINDOW, 1280, 720)

        last_frame: Optional[np.ndarray] = None
        log.info("[App] Jendela OpenCV dibuka. Tekan Q untuk keluar.")

        try:
            while not stop_evt.is_set():
                # Ambil hasil inferensi YOLO
                try:
                    result: YOLOResult = result_queue.get(timeout=2.0)
                except Empty:
                    # Tampilkan frame terakhir jika antrian kosong sesaat
                    if last_frame is not None:
                        cv2.imshow(self.WINDOW, last_frame)
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord("q") or key == 27:
                        break
                    continue

                # Baca status Gemini (non-blocking)
                with status_lock:
                    g_text = gemini_status["text"]
                    g_ts   = gemini_status["ts"]
                g_lag = time.monotonic() - g_ts

                # Gambar bounding box
                frame = result.frame.copy()
                for det in result.detections:
                    Visualizer.draw_box(frame, det)

                # Gambar HUD
                frame = Visualizer.draw_hud(frame, result, g_text, g_lag)
                last_frame = frame

                # Simpan log deteksi berbahaya
                self._log_detection(result, g_text)

                # Tampilkan
                cv2.imshow(self.WINDOW, frame)

                # Cek tombol keluar
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q") or key == 27:
                    log.info("[App] Pengguna menekan Q — menghentikan sistem…")
                    break

        except KeyboardInterrupt:
            log.info("[App] Ctrl+C diterima — menghentikan sistem…")

        finally:
            # ── Graceful Shutdown ──────────────────────────────────────
            log.info("[App] Membersihkan sumber daya…")
            stop_evt.set()

            producer.join(timeout=5)
            yolo_worker.join(timeout=5)
            gemini_worker.join(timeout=5)

            cv2.destroyAllWindows()
            log.info("[App] ✅ Semua thread berhenti. Sistem dimatikan dengan bersih.")
            print(f"\n✅ Sistem selesai. Log deteksi tersimpan di: {self.LOG_FILE}\n")


# ═════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═════════════════════════════════════════════════════════════════════════════
def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="NusaRail Sentinel — Sistem Peringatan Dini Perlintasan KA",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Contoh:
  python peringatan_dini_ka.py --url "https://www.youtube.com/watch?v=q7lvnYVuqNY"
  python peringatan_dini_ka.py --url video_cctv.mp4 --device cuda
  python peringatan_dini_ka.py --url 0 --no-gemini
        """,
    )
    p.add_argument(
        "--url", required=True,
        help="URL YouTube / path file video / index webcam (0, 1, …)",
    )
    p.add_argument(
        "--model", default=YOLO_MODEL,
        help=f"Path model YOLOv8 .pt (default: {YOLO_MODEL})",
    )
    p.add_argument(
        "--device", default="cpu", choices=["cpu", "cuda", "0", "1"],
        help="Device inferensi (default: cpu)",
    )
    p.add_argument(
        "--api-key", default=None,
        help="Gemini API key (override environment variable)",
    )
    p.add_argument(
        "--no-gemini", action="store_true",
        help="Nonaktifkan Gemini API (mode YOLO saja)",
    )
    p.add_argument(
        "--no-log", action="store_true",
        help="Jangan simpan log deteksi ke file",
    )
    return p.parse_args()


if __name__ == "__main__":
    args   = _parse_args()
    api_key = "" if args.no_gemini else (args.api_key or GEMINI_API_KEY)

    SentinelApp(
        source     = args.url,
        model_path = args.model,
        device     = args.device,
        api_key    = api_key,
        log_det    = not args.no_log,
    ).run()
