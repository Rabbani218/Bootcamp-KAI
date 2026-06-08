"""
╔══════════════════════════════════════════════════════════════════════════════╗
║   NusaRail Intelligence — Multi-Agent Infrastructure Monitoring System     ║
║                                                                              ║
║   Arsitektur  : 3-Agent Pipeline (Streamer | YOLO | Gemini)                ║
║   Vision      : YOLOv8 + ByteTrack  (deteksi objek real-time)              ║
║   Context     : Gemini 1.5 Pro API  (geospatial & temporal reasoning)      ║
║   Stream      : yt-dlp + OpenCV     (YouTube / file lokal / webcam)        ║
║   Concurrency : asyncio + threading + queue.Queue                           ║
╚══════════════════════════════════════════════════════════════════════════════╝

PENGATURAN ENVIRONMENT (buat file .env di direktori ini):
    GEMINI_API_KEY="AIzaSy..."   ← Kunci API dari Google AI Studio
    YOLO_MODEL_PATH="Dataset/best_pytorch.pt"   ← opsional, ada default
    STALL_SECONDS=8              ← waktu diam sebelum dinyatakan mogok
    GEMINI_INTERVAL=20           ← seberapa sering Gemini menganalisis konteks

CARA MENJALANKAN:
    python multi_agent.py --url "https://youtu.be/VIDEO_ID"
    python multi_agent.py --url video.mp4 --stall 5
    python multi_agent.py --url 0          (webcam)

DEPENDENSI:
    pip install ultralytics opencv-python-headless yt-dlp \
                google-generativeai python-dotenv numpy pillow
"""

# ─────────────────────────────────────────────────────────────────────────────
# IMPORT STANDAR & PIHAK KETIGA
# ─────────────────────────────────────────────────────────────────────────────
from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
import warnings
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

# Tekan peringatan tidak penting
warnings.filterwarnings("ignore", category=FutureWarning)
os.environ["YOLO_VERBOSE"] = "False"

# Muat variabel lingkungan dari .env (opsional, tidak crash jika tidak ada)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass  # python-dotenv opsional

# ─────────────────────────────────────────────────────────────────────────────
# KONFIGURASI LOGGING
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("NusaRail")


# ─────────────────────────────────────────────────────────────────────────────
# KONSTANTA & KONFIGURASI GLOBAL
# ─────────────────────────────────────────────────────────────────────────────
QUEUE_MAX_SIZE   = 30           # maks frame di antrian (anti-memory-leak)
GEMINI_INTERVAL  = int(os.getenv("GEMINI_INTERVAL", 20))  # detik antar panggilan
STALL_SECONDS    = float(os.getenv("STALL_SECONDS", 8))
DISP_TOLERANCE   = 20.0        # piksel toleransi "diam"
CONF_THRESHOLD   = 0.40
ROI_TOP_FRAC     = 0.05        # 5% atas   → abaikan (header berita)
ROI_BOT_FRAC     = 0.12        # 12% bawah → abaikan (teks berjalan)
ROI_LEFT_FRAC    = 0.03        # 3% kiri   → abaikan (logo TV)
ROI_RIGHT_FRAC   = 0.03        # 3% kanan  → abaikan

DEFAULT_MODEL    = str(Path(__file__).parent / "Dataset" / "best_pytorch.pt")
GEMINI_API_KEY   = os.getenv("GEMINI_API_KEY", "")

# Warna BGR
CLR_NORMAL  = (0,   200, 100)
CLR_TRAIN   = (255, 165,   0)
CLR_STALLED = (0,     0, 255)
CLR_ROI     = (0,   255, 255)
CLR_HUD     = (220, 220, 220)
CLR_ALERT   = (50,   50, 255)


# ─────────────────────────────────────────────────────────────────────────────
# DATACLASS: State kendaraan individual
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class VehicleState:
    """Menyimpan riwayat posisi dan status mogok satu kendaraan."""

    track_id   : int
    class_name : str
    positions  : deque = field(default_factory=lambda: deque(maxlen=90))
    is_stalled : bool  = False
    stalled_at : Optional[float] = None

    def push(self, cx: float, cy: float) -> None:
        self.positions.append((cx, cy, time.monotonic()))

    @property
    def stall_duration(self) -> float:
        return (time.monotonic() - self.stalled_at) if self.stalled_at else 0.0

    def max_displacement(self, window: float = 5.0) -> float:
        """Pergerakan maksimum (piksel) dalam window detik terakhir."""
        now = time.monotonic()
        pts = [(x, y) for x, y, t in self.positions if now - t <= window]
        if len(pts) < 2:
            return float("inf")
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return max(max(xs) - min(xs), max(ys) - min(ys))


# ─────────────────────────────────────────────────────────────────────────────
# DATACLASS: Paket data lintas-thread
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class InferenceResult:
    """Hasil YOLO satu frame — dibagikan ke layer display."""

    timestamp     : float
    frame         : np.ndarray
    detections    : List[Dict[str, Any]]   # per objek: {cls, conf, xyxy, id, stalled}
    fps           : float = 0.0
    stall_count   : int   = 0
    train_count   : int   = 0


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 1 — YouTubeStreamer  (Thread pembaca frame)
# ─────────────────────────────────────────────────────────────────────────────
class YouTubeStreamer(threading.Thread):
    """
    THREAD 1 — Streamer
    ───────────────────
    • Mengekstrak direct-stream URL dari YouTube via yt-dlp (retry eksponensial).
    • Membaca frame dari VideoCapture dan menaruhnya ke frame_queue.
    • Jika stream terputus / buffering, reconnect otomatis tanpa crash.
    """

    MAX_RETRIES      = 5
    BASE_RETRY_DELAY = 2    # detik — dikalikan 2× setiap percobaan (eksponensial)
    RECONNECT_FAILS  = 40   # frame kosong berturut-turut sebelum reconnect

    FORMAT_LIST = [
        "bestvideo[height<=720][ext=mp4]+bestaudio/best",
        "bestvideo[height<=480][ext=mp4]+bestaudio/best",
        "best[height<=720]/best[height<=480]/best",
    ]

    def __init__(
        self,
        source    : str,
        out_queue : Queue,
        stop_evt  : threading.Event,
    ) -> None:
        super().__init__(daemon=True, name="Streamer")
        self.source    = source
        self.out_queue = out_queue
        self.stop_evt  = stop_evt
        self.fps       = 25.0

    # ── Ekstrak URL dari YouTube ───────────────────────────────────────────
    def _extract_yt_url(self, youtube_url: str) -> str:
        """Ekstrak direct-stream URL. Retry eksponensial hingga MAX_RETRIES kali."""
        delay = self.BASE_RETRY_DELAY
        for attempt in range(1, self.MAX_RETRIES + 1):
            log.info(f"[Streamer] Mengekstrak URL — percobaan {attempt}/{self.MAX_RETRIES}")
            for fmt in self.FORMAT_LIST:
                try:
                    result = subprocess.run(
                        ["yt-dlp", "--no-warnings", "--quiet",
                         "-f", fmt, "-g", "--no-playlist", youtube_url],
                        capture_output=True, text=True, timeout=30,
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        url = result.stdout.strip().splitlines()[0]
                        log.info(f"[Streamer] URL berhasil diekstrak (fmt={fmt[:30]}…)")
                        return url
                except subprocess.TimeoutExpired:
                    log.warning("[Streamer] yt-dlp timeout, mencoba format lain…")
                except FileNotFoundError:
                    raise RuntimeError("yt-dlp tidak ditemukan! pip install yt-dlp")
                except Exception as exc:
                    log.warning(f"[Streamer] {exc}")

            log.warning(f"[Streamer] Semua format gagal — menunggu {delay}s…")
            time.sleep(delay)
            delay = min(delay * 2, 60)  # cap 60 detik

        raise RuntimeError(
            f"Gagal mendapatkan URL setelah {self.MAX_RETRIES} percobaan."
        )

    # ── Tentukan sumber (YouTube / lokal / webcam) ─────────────────────────
    def _resolve_source(self) -> Any:
        src = str(self.source).strip()
        if src.isdigit():
            return int(src)
        if "youtube.com" in src or "youtu.be" in src:
            return self._extract_yt_url(src)
        if Path(src).exists():
            return src
        raise FileNotFoundError(f"Sumber tidak dikenali: {src}")

    # ── Buka VideoCapture ──────────────────────────────────────────────────
    def _open_cap(self, resolved: Any) -> Optional[cv2.VideoCapture]:
        cap = cv2.VideoCapture(resolved)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)
        if cap.isOpened():
            fps = cap.get(cv2.CAP_PROP_FPS)
            if fps > 0:
                self.fps = fps
            log.info(f"[Streamer] Sumber terbuka (FPS={self.fps:.1f})")
            return cap
        log.error("[Streamer] Gagal membuka sumber video.")
        return None

    # ── Thread utama ───────────────────────────────────────────────────────
    def run(self) -> None:
        try:
            resolved = self._resolve_source()
        except Exception as exc:
            log.critical(f"[Streamer] {exc}")
            return

        cap = self._open_cap(resolved)
        fails = 0

        while not self.stop_evt.is_set():
            if cap is None:
                time.sleep(self.BASE_RETRY_DELAY)
                cap = self._open_cap(resolved)
                continue

            ret, frame = cap.read()
            if not ret or frame is None:
                fails += 1
                if fails >= self.RECONNECT_FAILS:
                    log.warning("[Streamer] Reconnecting…")
                    cap.release()
                    cap = None
                    fails = 0
                time.sleep(0.01)
                continue

            fails = 0
            # Drop frame lama agar antrian tidak meluap
            if self.out_queue.full():
                try:
                    self.out_queue.get_nowait()
                except Empty:
                    pass
            self.out_queue.put(frame)

        if cap:
            cap.release()
        log.info("[Streamer] Thread selesai.")


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 2 — GeminiContextAgent  (Thread analisis konteks Gemini)
# ─────────────────────────────────────────────────────────────────────────────
class GeminiContextAgent(threading.Thread):
    """
    THREAD 3 — Gemini Context Agent
    ─────────────────────────────────
    Berjalan di latar belakang setiap GEMINI_INTERVAL detik.
    Mengambil satu sample frame, mengkodenya ke JPEG base64, dan mengirimnya
    ke Gemini 1.5 Pro untuk mengekstrak:
        • Lokasi geospatial (nama ruas jalan / perlintasan / stasiun)
        • Kondisi umum (sepi / padat / ada kedaruratan)
        • Teks yang terbaca di layar (judul berita, narator, plat)
    Hasilnya disimpan di shared_context (dict) — dibaca thread display.
    """

    PROMPT = (
        "Kamu adalah sistem analisis visual cerdas untuk infrastruktur perkeretaapian Indonesia.\n"
        "Analisis frame video berikut dan ekstrak informasi dalam format JSON:\n"
        "{\n"
        '  "lokasi": "<nama ruas, perlintasan, atau stasiun — tulis TIDAK DIKETAHUI jika tidak jelas>",\n'
        '  "kota": "<nama kota/kabupaten — atau TIDAK DIKETAHUI>",\n'
        '  "kondisi": "<satu kata: NORMAL / PADAT / DARURAT / SEPI>",\n'
        '  "teks_layar": "<teks/judul berita yang terbaca — atau TIDAK ADA>",\n'
        '  "catatan": "<observasi singkat — maks 60 karakter>"\n'
        "}\n"
        "Balas HANYA dengan JSON, tanpa penjelasan tambahan."
    )

    def __init__(
        self,
        api_key       : str,
        frame_source  : "FrameSnapshotter",
        shared_context: Dict[str, Any],
        context_lock  : threading.Lock,
        stop_evt      : threading.Event,
        interval_sec  : int = GEMINI_INTERVAL,
    ) -> None:
        super().__init__(daemon=True, name="GeminiAgent")
        self.api_key        = api_key
        self.frame_source   = frame_source
        self.shared_context = shared_context
        self.context_lock   = context_lock
        self.stop_evt       = stop_evt
        self.interval       = interval_sec
        self._model         = None
        self._available     = False

    # ── Inisialisasi Gemini SDK (google-genai terbaru) ────────────────────
    def _init_sdk(self) -> bool:
        if not self.api_key:
            log.warning("[Gemini] GEMINI_API_KEY tidak diset — agent dinonaktifkan.")
            return False
        try:
            from google import genai as _genai          # type: ignore
            from google.genai import types as _gtypes   # type: ignore
            self._genai   = _genai
            self._gtypes  = _gtypes
            self._client  = _genai.Client(api_key=self.api_key)
            self._model_name = "gemini-1.5-flash"
            log.info("[Gemini] Client Gemini 1.5 Flash siap (SDK google-genai).")
            return True
        except ImportError:
            # Fallback ke SDK lama jika google-genai belum terinstall
            try:
                import google.generativeai as genai  # type: ignore
                import warnings
                warnings.filterwarnings("ignore", category=FutureWarning)
                genai.configure(api_key=self.api_key)
                self._model = genai.GenerativeModel("gemini-1.5-flash")
                self._client = None
                log.info("[Gemini] SDK lama (google-generativeai) digunakan sebagai fallback.")
                return True
            except Exception as exc2:
                log.error(f"[Gemini] Gagal inisialisasi SDK: {exc2}")
                return False
        except Exception as exc:
            log.error(f"[Gemini] Gagal inisialisasi SDK: {exc}")
            return False

    # ── Kirim frame ke Gemini & parse JSON ────────────────────────────────
    def _analyze_frame(self, frame: np.ndarray) -> Optional[Dict[str, Any]]:
        try:
            from PIL import Image
            img_pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

            # Encode ke JPEG bytes
            buf = io.BytesIO()
            img_pil.save(buf, format="JPEG", quality=80)
            img_bytes = buf.getvalue()

            if hasattr(self, '_client') and self._client is not None:
                # ── SDK BARU (google-genai) ──────────────────────────────
                response = self._client.models.generate_content(
                    model=self._model_name,
                    contents=[
                        self._gtypes.Part.from_bytes(
                            data=img_bytes, mime_type="image/jpeg"
                        ),
                        self.PROMPT,
                    ],
                )
                text = response.text.strip()
            else:
                # ── SDK LAMA (google-generativeai) — fallback ────────────
                response = self._model.generate_content(
                    [self.PROMPT, img_pil],
                    request_options={"timeout": 15},
                )
                text = response.text.strip()

            # Bersihkan markdown code block jika ada
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text.strip())
        except json.JSONDecodeError:
            log.debug("[Gemini] Respons bukan JSON valid — diabaikan.")
            return None
        except Exception as exc:
            log.warning(f"[Gemini] Error saat analisis: {exc}")
            return None

    # ── Thread utama ───────────────────────────────────────────────────────
    def run(self) -> None:
        self._available = self._init_sdk()
        if not self._available:
            self._write_context({"status": "OFFLINE", "lokasi": "N/A"})
            return

        self._write_context({"status": "INISIALISASI", "lokasi": "Menganalisis…"})

        while not self.stop_evt.is_set():
            frame = self.frame_source.get_snapshot()
            if frame is not None:
                result = self._analyze_frame(frame)
                if result:
                    result["status"] = "AKTIF"
                    result["updated_at"] = time.strftime("%H:%M:%S")
                    self._write_context(result)
                    log.info(
                        f"[Gemini] Lokasi={result.get('lokasi','?')} | "
                        f"Kondisi={result.get('kondisi','?')}"
                    )

            # Tunggu interval berikutnya (dengan interupsi tiap 1 detik)
            for _ in range(self.interval):
                if self.stop_evt.is_set():
                    break
                time.sleep(1)

        log.info("[Gemini] Thread selesai.")

    def _write_context(self, data: Dict[str, Any]) -> None:
        with self.context_lock:
            self.shared_context.update(data)


# ─────────────────────────────────────────────────────────────────────────────
# HELPER — FrameSnapshotter  (shared state antar thread)
# ─────────────────────────────────────────────────────────────────────────────
class FrameSnapshotter:
    """Menyimpan frame terbaru secara thread-safe untuk dibaca Gemini agent."""

    def __init__(self) -> None:
        self._frame: Optional[np.ndarray] = None
        self._lock  = threading.Lock()

    def update(self, frame: np.ndarray) -> None:
        with self._lock:
            self._frame = frame.copy()

    def get_snapshot(self) -> Optional[np.ndarray]:
        with self._lock:
            return self._frame.copy() if self._frame is not None else None


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 2 — YOLOInferencer  (Thread deteksi & tracking)
# ─────────────────────────────────────────────────────────────────────────────
class YOLOInferencer(threading.Thread):
    """
    THREAD 2 — YOLO Inferencer
    ───────────────────────────
    • Menarik frame dari in_queue.
    • Terapkan ROI Mask untuk mengabaikan area template berita.
    • Jalankan YOLOv8 + ByteTrack.
    • Update VehicleState per track_id.
    • Taruh InferenceResult ke result_queue.
    """

    VEHICLE_CLASSES = {"car", "motorcycle", "truck", "bus"}

    def __init__(
        self,
        model_path    : str,
        in_queue      : Queue,
        result_queue  : Queue,
        snapshotter   : FrameSnapshotter,
        stop_evt      : threading.Event,
        device        : str = "cpu",
        stall_sec     : float = STALL_SECONDS,
    ) -> None:
        super().__init__(daemon=True, name="YOLOInferencer")
        self.model_path    = model_path
        self.in_queue      = in_queue
        self.result_queue  = result_queue
        self.snapshotter   = snapshotter
        self.stop_evt      = stop_evt
        self.device        = device
        self.stall_sec     = stall_sec
        self.model         = None
        self.class_names   : List[str] = []
        self._states       : Dict[int, VehicleState] = {}
        self._fps_counter  = 0
        self._fps_start    = time.monotonic()
        self._display_fps  = 0.0

    # ── Inisialisasi Model ─────────────────────────────────────────────────
    def _load_model(self) -> bool:
        try:
            from ultralytics import YOLO  # type: ignore
            log.info(f"[YOLO] Memuat model: {self.model_path}")
            self.model = YOLO(self.model_path)
            self.model.to(self.device)
            self.class_names = list(self.model.names.values())
            log.info(f"[YOLO] Model siap — Kelas: {self.class_names}")
            return True
        except Exception as exc:
            log.critical(f"[YOLO] Gagal memuat model: {exc}")
            return False

    # ── ROI Mask ───────────────────────────────────────────────────────────
    def _apply_roi_mask(self, frame: np.ndarray) -> Tuple[np.ndarray, tuple]:
        """
        Terapkan masker hitam pada area template berita (teks berjalan,
        logo TV, header) agar YOLO hanya memproses raw footage.
        Kembalikan frame termasked + koordinat ROI valid.
        """
        h, w = frame.shape[:2]
        y_top  = int(h * ROI_TOP_FRAC)
        y_bot  = int(h * (1 - ROI_BOT_FRAC))
        x_left = int(w * ROI_LEFT_FRAC)
        x_right= int(w * (1 - ROI_RIGHT_FRAC))

        masked = frame.copy()
        # Hitamkan luar ROI
        masked[:y_top,   :] = 0   # atas (header berita)
        masked[y_bot:,   :] = 0   # bawah (teks berjalan)
        masked[:, :x_left] = 0    # kiri  (logo TV)
        masked[:, x_right:]= 0    # kanan

        return masked, (x_left, y_top, x_right, y_bot)

    # ── Update state kendaraan ─────────────────────────────────────────────
    def _update_state(
        self, track_id: int, class_name: str, cx: float, cy: float
    ) -> VehicleState:
        if track_id not in self._states:
            self._states[track_id] = VehicleState(
                track_id=track_id, class_name=class_name
            )
        state = self._states[track_id]
        state.push(cx, cy)

        displacement = state.max_displacement(window=5.0)
        if displacement < DISP_TOLERANCE:
            if state.stalled_at is None:
                state.stalled_at = time.monotonic()
            elif time.monotonic() - state.stalled_at >= self.stall_sec:
                if not state.is_stalled:
                    log.warning(
                        f"[YOLO] MOGOK TERDETEKSI — ID={track_id} "
                        f"({class_name}) selama {state.stall_duration:.1f}s"
                    )
                state.is_stalled = True
        else:
            state.is_stalled = False
            state.stalled_at = None

        return state

    # ── Hapus state basi ───────────────────────────────────────────────────
    def _cleanup_states(self, max_age: float = 30.0) -> None:
        now = time.monotonic()
        stale = [
            tid for tid, s in self._states.items()
            if s.positions and (now - s.positions[-1][2]) > max_age
        ]
        for tid in stale:
            del self._states[tid]

    # ── Proses satu frame ──────────────────────────────────────────────────
    def _process(self, frame: np.ndarray) -> InferenceResult:
        masked, roi = self._apply_roi_mask(frame)

        results = self.model.track(
            source=masked,
            conf=CONF_THRESHOLD,
            iou=0.5,
            persist=True,
            tracker="bytetrack.yaml",
            verbose=False,
            device=self.device,
        )

        detections: List[Dict[str, Any]] = []
        stall_count = train_count = 0

        for r in results:
            if r.boxes is None:
                continue
            for box in r.boxes:
                xyxy     = box.xyxy[0].cpu().numpy().astype(int)
                conf     = float(box.conf[0])
                cls_id   = int(box.cls[0])
                cls_name = (
                    self.class_names[cls_id]
                    if cls_id < len(self.class_names)
                    else "unknown"
                )
                tid = int(box.id[0]) if box.id is not None else -1
                x1, y1, x2, y2 = xyxy
                cx, cy = (x1 + x2) / 2, (y1 + y2) / 2

                is_stalled   = False
                stall_seconds = 0.0

                if cls_name == "train":
                    train_count += 1
                elif cls_name in self.VEHICLE_CLASSES and tid >= 0:
                    state = self._update_state(tid, cls_name, cx, cy)
                    is_stalled    = state.is_stalled
                    stall_seconds = state.stall_duration
                    if is_stalled:
                        stall_count += 1

                detections.append({
                    "cls"          : cls_name,
                    "conf"         : conf,
                    "xyxy"         : (x1, y1, x2, y2),
                    "track_id"     : tid,
                    "is_stalled"   : is_stalled,
                    "stall_seconds": stall_seconds,
                })

        self._cleanup_states()

        # Hitung FPS
        self._fps_counter += 1
        elapsed = time.monotonic() - self._fps_start
        if elapsed >= 1.0:
            self._display_fps = self._fps_counter / elapsed
            self._fps_counter = 0
            self._fps_start   = time.monotonic()

        return InferenceResult(
            timestamp  = time.time(),
            frame      = frame,
            detections = detections,
            fps        = self._display_fps,
            stall_count= stall_count,
            train_count= train_count,
        )

    # ── Thread utama ───────────────────────────────────────────────────────
    def run(self) -> None:
        if not self._load_model():
            return

        while not self.stop_evt.is_set():
            try:
                frame = self.in_queue.get(timeout=2.0)
            except Empty:
                continue

            # Update snapshotter untuk Gemini agent
            self.snapshotter.update(frame)

            try:
                result = self._process(frame)
            except Exception as exc:
                log.error(f"[YOLO] Error saat inferensi: {exc}")
                result = InferenceResult(
                    timestamp=time.time(), frame=frame, detections=[]
                )

            # Taruh ke result queue (drop lama jika penuh)
            if self.result_queue.full():
                try:
                    self.result_queue.get_nowait()
                except Empty:
                    pass
            self.result_queue.put(result)

        log.info("[YOLO] Thread selesai.")


# ─────────────────────────────────────────────────────────────────────────────
# DISPLAY ENGINE  (berjalan di main thread, agar GUI responsif di Windows)
# ─────────────────────────────────────────────────────────────────────────────
class DisplayEngine:
    """
    Mengambil InferenceResult dari result_queue, menempelkan anotasi YOLO
    dan konteks Gemini dalam satu jendela OpenCV yang mulus dan real-time.
    """

    WINDOW = "NusaRail Intelligence — Tekan Q untuk keluar"

    def __init__(
        self,
        result_queue  : Queue,
        shared_context: Dict[str, Any],
        context_lock  : threading.Lock,
        stop_evt      : threading.Event,
    ) -> None:
        self.result_queue   = result_queue
        self.shared_context = shared_context
        self.context_lock   = context_lock
        self.stop_evt       = stop_evt

    # ── Gambar bounding box ────────────────────────────────────────────────
    def _draw_box(
        self,
        frame: np.ndarray,
        det  : Dict[str, Any],
    ) -> None:
        x1, y1, x2, y2 = det["xyxy"]
        cls   = det["cls"]
        conf  = det["conf"]
        tid   = det["track_id"]
        stall = det["is_stalled"]
        sdur  = det["stall_seconds"]

        if cls == "train":
            color = CLR_TRAIN
            label = f"KERETA  {conf:.0%}"
            thick = 3
        elif stall:
            color = CLR_STALLED
            label = f"MOGOK  ID:{tid}  {sdur:.0f}s"
            thick = 3
            # Overlay merah transparan
            ov = frame.copy()
            cv2.rectangle(ov, (x1, y1), (x2, y2), color, -1)
            cv2.addWeighted(ov, 0.18, frame, 0.82, 0, frame)
        else:
            color = CLR_NORMAL
            label = f"{cls}  ID:{tid}  {conf:.0%}"
            thick = 2

        cv2.rectangle(frame, (x1, y1), (x2, y2), color, thick)
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        lbg_y = max(0, y1 - th - 8)
        cv2.rectangle(frame, (x1, lbg_y), (x1 + tw + 8, y1), color, -1)
        cv2.putText(
            frame, label, (x1 + 4, y1 - 4),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA,
        )

    # ── Gambar panel HUD utama ─────────────────────────────────────────────
    def _draw_hud(
        self,
        frame  : np.ndarray,
        result : InferenceResult,
        ctx    : Dict[str, Any],
    ) -> np.ndarray:
        h, w = frame.shape[:2]
        panel_w = 330
        panel_h = 155

        # Background semi-transparan pojok kiri atas
        ov = frame.copy()
        cv2.rectangle(ov, (5, 5), (5 + panel_w, 5 + panel_h), (10, 10, 10), -1)
        frame = cv2.addWeighted(ov, 0.72, frame, 0.28, 0)

        # Isi teks HUD
        lines = [
            (f"NusaRail Intelligence  |  FPS: {result.fps:.1f}",
             CLR_HUD, 0.55),
            (f"Deteksi: {len(result.detections)}   "
             f"Mogok: {result.stall_count}   "
             f"Kereta: {result.train_count}",
             CLR_HUD, 0.50),
            ("─" * 42, (80, 80, 80), 0.45),
            (f"[GEMINI] Lokasi  : {ctx.get('lokasi','Menganalisis…')[:38]}",
             (0, 220, 255), 0.50),
            (f"[GEMINI] Kota    : {ctx.get('kota', '—')[:38]}",
             (0, 200, 200), 0.48),
            (f"[GEMINI] Kondisi : {ctx.get('kondisi', '—')}",
             _kondisi_color(ctx.get("kondisi", "")), 0.50),
            (f"[GEMINI] Teks    : {ctx.get('teks_layar','—')[:38]}",
             (150, 150, 220), 0.46),
        ]
        for i, (text, color, scale) in enumerate(lines):
            cv2.putText(
                frame, text, (12, 28 + i * 20),
                cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA,
            )

        # Waktu update Gemini (pojok kanan atas)
        upd = ctx.get("updated_at", "—")
        cv2.putText(
            frame, f"Gemini update: {upd}", (w - 220, 18),
            cv2.FONT_HERSHEY_SIMPLEX, 0.42, (120, 120, 120), 1, cv2.LINE_AA,
        )

        # Catatan Gemini (pojok kiri bawah)
        note = ctx.get("catatan", "")
        if note:
            cv2.putText(
                frame, f"Catatan: {note}", (8, h - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (140, 140, 200), 1, cv2.LINE_AA,
            )

        return frame

    # ── Gambar batas ROI ───────────────────────────────────────────────────
    def _draw_roi_border(self, frame: np.ndarray) -> None:
        h, w = frame.shape[:2]
        x1 = int(w * ROI_LEFT_FRAC)
        y1 = int(h * ROI_TOP_FRAC)
        x2 = int(w * (1 - ROI_RIGHT_FRAC))
        y2 = int(h * (1 - ROI_BOT_FRAC))
        cv2.rectangle(frame, (x1, y1), (x2, y2), CLR_ROI, 1)
        cv2.putText(
            frame, "ROI Aktif", (x1 + 4, y1 + 14),
            cv2.FONT_HERSHEY_SIMPLEX, 0.38, CLR_ROI, 1, cv2.LINE_AA,
        )

    # ── Loop utama display ─────────────────────────────────────────────────
    def run(self) -> None:
        cv2.namedWindow(self.WINDOW, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(self.WINDOW, 1280, 720)

        last_frame: Optional[np.ndarray] = None
        log.info("[Display] Jendela terbuka — tekan Q untuk keluar.")

        while not self.stop_evt.is_set():
            try:
                result: InferenceResult = self.result_queue.get(timeout=2.0)
            except Empty:
                if last_frame is not None:
                    cv2.imshow(self.WINDOW, last_frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
                continue

            frame = result.frame.copy()

            # 1. Gambar batas ROI
            self._draw_roi_border(frame)

            # 2. Gambar semua bounding box
            for det in result.detections:
                self._draw_box(frame, det)

            # 3. Gambar HUD + konteks Gemini
            with self.context_lock:
                ctx = dict(self.shared_context)

            frame = self._draw_hud(frame, result, ctx)
            last_frame = frame
            cv2.imshow(self.WINDOW, frame)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                log.info("[Display] Pengguna menekan Q — menghentikan sistem…")
                self.stop_evt.set()
                break

        cv2.destroyAllWindows()
        log.info("[Display] Jendela ditutup.")


# ─────────────────────────────────────────────────────────────────────────────
# UTILITAS
# ─────────────────────────────────────────────────────────────────────────────
def _kondisi_color(kondisi: str) -> Tuple[int, int, int]:
    """Pilih warna HUD sesuai kondisi dari Gemini."""
    return {
        "NORMAL"  : (0,   200, 100),
        "PADAT"   : (0,   190, 255),
        "DARURAT" : (0,     0, 255),
        "SEPI"    : (160, 160, 160),
    }.get(kondisi.upper(), CLR_HUD)


# ─────────────────────────────────────────────────────────────────────────────
# ORKESTRATOR UTAMA
# ─────────────────────────────────────────────────────────────────────────────
class NusaRailIntelligence:
    """
    Orkestrator yang mengikat seluruh agen:
      YouTubeStreamer → (frame_queue) → YOLOInferencer
                                        ↓ (result_queue)
                                    DisplayEngine
      GeminiContextAgent ─────────────────↑ (shared_context)
    """

    def __init__(
        self,
        source        : str,
        model_path    : str  = DEFAULT_MODEL,
        device        : str  = "cpu",
        stall_sec     : float = STALL_SECONDS,
        gemini_key    : str  = GEMINI_API_KEY,
        gemini_interval: int = GEMINI_INTERVAL,
    ) -> None:
        self.source          = source
        self.model_path      = model_path
        self.device          = device
        self.stall_sec       = stall_sec
        self.gemini_key      = gemini_key
        self.gemini_interval = gemini_interval

    def start(self) -> None:
        # ── Antrian & event bersama ────────────────────────────────────────
        frame_queue   = Queue(maxsize=QUEUE_MAX_SIZE)
        result_queue  = Queue(maxsize=8)
        stop_evt      = threading.Event()
        context_lock  = threading.Lock()
        shared_context: Dict[str, Any] = {
            "status"  : "INISIALISASI",
            "lokasi"  : "Menunggu analisis Gemini…",
            "kota"    : "—",
            "kondisi" : "—",
            "catatan" : "",
        }
        snapshotter = FrameSnapshotter()

        # ── Buat semua agen ────────────────────────────────────────────────
        streamer = YouTubeStreamer(
            source=self.source,
            out_queue=frame_queue,
            stop_evt=stop_evt,
        )
        inferencer = YOLOInferencer(
            model_path  =self.model_path,
            in_queue    =frame_queue,
            result_queue=result_queue,
            snapshotter =snapshotter,
            stop_evt    =stop_evt,
            device      =self.device,
            stall_sec   =self.stall_sec,
        )
        gemini_agent = GeminiContextAgent(
            api_key        =self.gemini_key,
            frame_source   =snapshotter,
            shared_context =shared_context,
            context_lock   =context_lock,
            stop_evt       =stop_evt,
            interval_sec   =self.gemini_interval,
        )
        display = DisplayEngine(
            result_queue  =result_queue,
            shared_context=shared_context,
            context_lock  =context_lock,
            stop_evt      =stop_evt,
        )

        # ── Jalankan semua thread ──────────────────────────────────────────
        log.info("=" * 65)
        log.info("  NusaRail Intelligence — SISTEM DIMULAI")
        log.info(f"  Sumber  : {self.source}")
        log.info(f"  Model   : {self.model_path}")
        log.info(f"  Device  : {self.device}")
        log.info(f"  Gemini  : {'AKTIF' if self.gemini_key else 'NONAKTIF'}")
        log.info("=" * 65)

        streamer.start()
        inferencer.start()
        gemini_agent.start()

        # Display di main thread (GUI OpenCV harus di main thread di Windows)
        try:
            display.run()
        except KeyboardInterrupt:
            log.info("Ctrl+C — menghentikan sistem…")
        finally:
            stop_evt.set()
            streamer.join(timeout=5)
            inferencer.join(timeout=5)
            gemini_agent.join(timeout=5)
            log.info("Semua thread berhenti. Program selesai.")


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────
def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="NusaRail Intelligence — Multi-Agent Real-Time Monitoring",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Contoh:
  python multi_agent.py --url "https://youtu.be/LZr7jt3MmKM"
  python multi_agent.py --url video_cctv.mp4 --stall 5
  python multi_agent.py --url 0 --device cuda --gemini-interval 30
        """,
    )
    p.add_argument("--url",    required=True,
                   help="URL YouTube / path file / index webcam")
    p.add_argument("--model",  default=None,
                   help=f"Path model .pt (default: {DEFAULT_MODEL})")
    p.add_argument("--device", default="cpu",
                   choices=["cpu", "cuda", "0", "1"],
                   help="Device inferensi")
    p.add_argument("--stall",  type=float, default=STALL_SECONDS,
                   help="Detik diam sebelum dinyatakan MOGOK")
    p.add_argument("--gemini-key", default=None,
                   help="Override GEMINI_API_KEY dari environment")
    p.add_argument("--gemini-interval", type=int, default=GEMINI_INTERVAL,
                   help="Interval analisis Gemini (detik, default=20)")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    NusaRailIntelligence(
        source          = args.url,
        model_path      = args.model or DEFAULT_MODEL,
        device          = args.device,
        stall_sec       = args.stall,
        gemini_key      = args.gemini_key or GEMINI_API_KEY,
        gemini_interval = args.gemini_interval,
    ).start()
