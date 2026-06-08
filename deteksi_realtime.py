"""
╔══════════════════════════════════════════════════════════════════════════════╗
║          NusaRail Vision — Real-Time Anomaly Detection Engine               ║
║          Deteksi Kendaraan Mogok & Kereta Api via YouTube / File Lokal      ║
╚══════════════════════════════════════════════════════════════════════════════╝

Dikembangkan oleh  : Rahman Hanif (Bootcamp UBSI–KAI)
Tech Stack         : YOLOv8 (Ultralytics) · yt-dlp · OpenCV · Multithreading
Deskripsi          : Script tunggal OOP untuk mendeteksi kendaraan mogok dan
                     kereta api dari stream YouTube live / video lokal secara
                     real-time dengan toleransi-kesalahan penuh (zero-crash).

Cara Menjalankan   :
  1. Dari YouTube   : python deteksi_realtime.py --url "https://youtu.be/VIDEO_ID"
  2. Dari file lokal: python deteksi_realtime.py --url "path/to/video.mp4"
  3. Dari webcam    : python deteksi_realtime.py --url 0
  4. Dengan threshold kustom: python deteksi_realtime.py --url "..." --threshold 0.45

Dependensi:
  pip install ultralytics yt-dlp opencv-python numpy
"""

import argparse
import logging
import os
import subprocess
import sys
import threading
import time
import warnings
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Queue
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

# Tekan warning yang tidak perlu
warnings.filterwarnings("ignore", category=FutureWarning)
os.environ["YOLO_VERBOSE"] = "False"

# ─────────────────────────────────────────────────────────────────────────────
# KONFIGURASI LOGGING
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("NusaRailVision")


# ─────────────────────────────────────────────────────────────────────────────
# DATACLASS: State satu kendaraan yang sedang dilacak
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class VehicleState:
    """Menyimpan riwayat posisi dan status satu kendaraan tertentu."""

    track_id: int
    class_name: str
    positions: deque = field(default_factory=lambda: deque(maxlen=60))
    first_seen: float = field(default_factory=time.time)
    is_stalled: bool = False
    stalled_since: Optional[float] = None

    def update_position(self, cx: float, cy: float) -> None:
        """Tambahkan posisi pusat bounding box terbaru."""
        self.positions.append((cx, cy, time.time()))

    @property
    def seconds_stalled(self) -> float:
        """Berapa detik kendaraan ini sudah diam."""
        if self.stalled_since is None:
            return 0.0
        return time.time() - self.stalled_since

    def calculate_displacement(self, window_seconds: float = 5.0) -> float:
        """
        Hitung jarak pergerakan dalam rentang waktu terakhir (detik).
        Semakin kecil nilainya, semakin diam kendaraan tersebut.
        """
        if len(self.positions) < 2:
            return float("inf")
        now = time.time()
        recent = [(x, y) for x, y, t in self.positions if now - t <= window_seconds]
        if len(recent) < 2:
            return float("inf")
        xs = [p[0] for p in recent]
        ys = [p[1] for p in recent]
        return max(max(xs) - min(xs), max(ys) - min(ys))


# ─────────────────────────────────────────────────────────────────────────────
# CLASS: Pengekstrak URL YouTube menggunakan yt-dlp
# ─────────────────────────────────────────────────────────────────────────────
class YouTubeExtractor:
    """
    Mengekstrak direct-stream URL dari tautan YouTube menggunakan yt-dlp.
    Dilengkapi retry mechanism 3× dengan exponential backoff.
    """

    MAX_RETRIES = 3
    RETRY_DELAY = 3  # detik

    # Prioritas format: 720p → 480p → terbaik yang tersedia (mp4)
    FORMAT_PREFERENCE = [
        "bestvideo[height<=720][ext=mp4]+bestaudio/best[height<=720][ext=mp4]",
        "bestvideo[height<=480][ext=mp4]+bestaudio/best[height<=480][ext=mp4]",
        "best[ext=mp4]/best",
    ]

    @classmethod
    def extract_url(cls, youtube_url: str) -> str:
        """
        Ekstrak URL streaming langsung dari tautan YouTube.
        Melempar RuntimeError jika semua percobaan gagal.
        """
        for attempt in range(1, cls.MAX_RETRIES + 1):
            log.info(f"[YouTube] Percobaan {attempt}/{cls.MAX_RETRIES} — {youtube_url}")
            for fmt in cls.FORMAT_PREFERENCE:
                try:
                    result = subprocess.run(
                        [
                            "yt-dlp",
                            "--no-warnings",
                            "--quiet",
                            "-f", fmt,
                            "-g",           # cetak URL saja, jangan download
                            "--no-playlist",
                            youtube_url,
                        ],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        urls = result.stdout.strip().splitlines()
                        # Ambil URL pertama (video stream)
                        stream_url = urls[0]
                        log.info(f"[YouTube] ✅ URL berhasil diekstrak (format: {fmt[:40]}...)")
                        return stream_url
                except subprocess.TimeoutExpired:
                    log.warning("[YouTube] yt-dlp timeout — mencoba format lain…")
                except FileNotFoundError:
                    raise RuntimeError(
                        "yt-dlp tidak ditemukan! Jalankan: pip install yt-dlp"
                    )
                except Exception as e:
                    log.warning(f"[YouTube] Error: {e}")

            if attempt < cls.MAX_RETRIES:
                wait = cls.RETRY_DELAY * attempt
                log.warning(f"[YouTube] Semua format gagal — menunggu {wait}s…")
                time.sleep(wait)

        raise RuntimeError(
            f"Gagal mengekstrak URL YouTube setelah {cls.MAX_RETRIES}× percobaan."
        )


# ─────────────────────────────────────────────────────────────────────────────
# CLASS: Thread pembaca frame (Producer)
# ─────────────────────────────────────────────────────────────────────────────
class FrameReader(threading.Thread):
    """
    Thread terpisah yang membaca frame dari sumber video dan menaruhnya
    ke dalam antrian (Queue). Memastikan thread inferensi tidak pernah
    menunggu I/O jaringan.
    """

    MAX_QUEUE_SIZE = 32
    RECONNECT_DELAY = 5  # detik

    def __init__(self, source: str, queue: Queue, stop_event: threading.Event):
        super().__init__(daemon=True, name="FrameReader")
        self.source = source
        self.queue = queue
        self.stop_event = stop_event
        self._cap: Optional[cv2.VideoCapture] = None
        self.fps: float = 25.0

    def _open_capture(self) -> bool:
        """Buka sumber video. Kembalikan True jika berhasil."""
        if self._cap:
            self._cap.release()

        log.info(f"[FrameReader] Membuka sumber: {str(self.source)[:80]}")
        self._cap = cv2.VideoCapture(self.source)

        # Optimalkan buffer untuk latency rendah pada stream jaringan
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)

        if self._cap.isOpened():
            fps = self._cap.get(cv2.CAP_PROP_FPS)
            if fps > 0:
                self.fps = fps
            log.info(f"[FrameReader] ✅ Sumber terbuka (FPS={self.fps:.1f})")
            return True
        else:
            log.error("[FrameReader] ❌ Gagal membuka sumber video.")
            return False

    def run(self) -> None:
        """Loop utama thread: baca frame tanpa henti hingga stop_event dikirim."""
        if not self._open_capture():
            return

        consecutive_fails = 0
        MAX_FAILS = 30  # maksimum frame kosong sebelum reconnect

        while not self.stop_event.is_set():
            ret, frame = self._cap.read()

            if not ret or frame is None:
                consecutive_fails += 1
                if consecutive_fails >= MAX_FAILS:
                    log.warning(
                        f"[FrameReader] {MAX_FAILS}× frame gagal dibaca — "
                        f"mencoba reconnect dalam {self.RECONNECT_DELAY}s…"
                    )
                    time.sleep(self.RECONNECT_DELAY)
                    if not self._open_capture():
                        continue
                    consecutive_fails = 0
                else:
                    time.sleep(0.01)
                continue

            consecutive_fails = 0

            # Jangan biarkan antrian penuh (drop frame lama)
            if self.queue.full():
                try:
                    self.queue.get_nowait()
                except Empty:
                    pass

            self.queue.put(frame)

        if self._cap:
            self._cap.release()
        log.info("[FrameReader] Thread berhenti.")


# ─────────────────────────────────────────────────────────────────────────────
# CLASS: Engine Deteksi & Pelacakan (Consumer + Visualizer)
# ─────────────────────────────────────────────────────────────────────────────
class DetectionEngine:
    """
    Mesin utama yang:
      1. Menarik frame dari antrian.
      2. Menjalankan YOLO inference + ByteTrack tracking.
      3. Mendeteksi kendaraan mogok (berdasarkan immobility > threshold).
      4. Menampilkan hasil di jendela OpenCV.
    """

    # Kelas kendaraan yang dilacak untuk deteksi mogok
    VEHICLE_CLASSES = {"car", "motorcycle", "truck", "bus"}

    # Warna BGR
    COLOR_NORMAL   = (0,   200, 100)   # Hijau
    COLOR_TRAIN    = (255, 150,   0)   # Biru muda
    COLOR_STALLED  = (0,     0, 255)   # Merah
    COLOR_OVERLAY  = (20,   20,  20)   # Overlay gelap semi-transparan

    def __init__(
        self,
        model_path: str,
        stall_threshold_sec: float = 8.0,
        displacement_tolerance: float = 25.0,
        conf_threshold: float = 0.40,
        device: str = "cpu",
    ):
        """
        Args:
            model_path          : Path ke file .pt model YOLOv8.
            stall_threshold_sec : Waktu diam (detik) sebelum dinyatakan mogok.
            displacement_tolerance: Toleransi piksel pergerakan (dianggap diam).
            conf_threshold      : Confidence minimum untuk deteksi diterima.
            device              : 'cpu', 'cuda', atau '0' (GPU ID).
        """
        self.model_path          = model_path
        self.stall_threshold_sec = stall_threshold_sec
        self.displacement_tol    = displacement_tolerance
        self.conf_threshold      = conf_threshold
        self.device              = device
        self.model               = None
        self.class_names: List[str] = []

        # State tracker: {track_id: VehicleState}
        self._vehicle_states: Dict[int, VehicleState] = {}
        self._stall_alert_log: deque = deque(maxlen=100)

        # Statistik tampilan
        self._frame_count        = 0
        self._fps_calc_time      = time.time()
        self._display_fps        = 0.0
        self._total_detections   = 0
        self._active_stalls      = 0

    # ── Inisialisasi Model ─────────────────────────────────────────────────
    def load_model(self) -> None:
        """Muat model YOLOv8 ke memori. Panggil sebelum run()."""
        try:
            from ultralytics import YOLO  # impor di sini agar error lebih jelas
        except ImportError:
            raise RuntimeError(
                "Ultralytics belum terinstall! Jalankan: pip install ultralytics"
            )

        log.info(f"[Model] Memuat model dari: {self.model_path}")
        self.model = YOLO(self.model_path)
        self.model.to(self.device)

        # Daftar nama kelas dari model
        self.class_names = list(self.model.names.values())
        log.info(f"[Model] ✅ Model dimuat — Kelas: {self.class_names}")

    # ── Update Status Kendaraan ────────────────────────────────────────────
    def _update_vehicle_state(
        self, track_id: int, class_name: str, cx: float, cy: float
    ) -> VehicleState:
        """Perbarui riwayat posisi kendaraan dan tentukan statusnya."""
        if track_id not in self._vehicle_states:
            self._vehicle_states[track_id] = VehicleState(
                track_id=track_id, class_name=class_name
            )

        state = self._vehicle_states[track_id]
        state.update_position(cx, cy)

        # Hitung perpindahan dalam 5 detik terakhir
        displacement = state.calculate_displacement(window_seconds=5.0)

        if displacement < self.displacement_tol:
            if not state.is_stalled:
                if state.stalled_since is None:
                    state.stalled_since = time.time()
                elif time.time() - state.stalled_since >= self.stall_threshold_sec:
                    state.is_stalled = True
                    msg = (
                        f"[ALERT] 🚨 ID={track_id} ({class_name}) "
                        f"MOGOK selama {state.seconds_stalled:.1f}s"
                    )
                    log.warning(msg)
                    self._stall_alert_log.appendleft(
                        (time.strftime("%H:%M:%S"), msg)
                    )
        else:
            # Kendaraan bergerak — reset status mogok
            state.is_stalled = False
            state.stalled_since = None

        return state

    # ── Gambar Overlay HUD ─────────────────────────────────────────────────
    def _draw_hud(self, frame: np.ndarray) -> np.ndarray:
        """Gambar panel informasi (HUD) di pojok kiri atas."""
        h, w = frame.shape[:2]
        overlay = frame.copy()

        # Panel background semi-transparan
        cv2.rectangle(overlay, (5, 5), (340, 120), (15, 15, 15), -1)
        frame = cv2.addWeighted(overlay, 0.65, frame, 0.35, 0)

        # Teks informasi
        lines = [
            f"NusaRail Vision  |  FPS: {self._display_fps:.1f}",
            f"Deteksi: {self._total_detections}   |  Mogok Aktif: {self._active_stalls}",
            f"Model: {Path(self.model_path).name}",
            f"Kelas: {' | '.join(self.class_names)}",
        ]
        for i, line in enumerate(lines):
            cv2.putText(
                frame, line, (12, 28 + i * 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.52,
                (220, 220, 220), 1, cv2.LINE_AA,
            )

        # Log alert terbaru (pojok kiri bawah)
        for i, (ts, msg) in enumerate(list(self._stall_alert_log)[:3]):
            alert_text = f"{ts} {msg[10:60]}"  # potong agar muat layar
            cv2.putText(
                frame, alert_text, (8, h - 15 - i * 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.44,
                (0, 80, 255), 1, cv2.LINE_AA,
            )

        return frame

    # ── Gambar Satu Bounding Box ───────────────────────────────────────────
    def _draw_box(
        self,
        frame: np.ndarray,
        box: Tuple[int, int, int, int],
        label: str,
        color: Tuple[int, int, int],
        conf: float,
    ) -> None:
        """Gambar bounding box dengan label dan confidence score."""
        x1, y1, x2, y2 = box
        thickness = 2

        # Kotak
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)

        # Label background
        text = f"{label}  {conf:.0%}"
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
        lx1, ly1 = x1, max(0, y1 - th - 10)
        cv2.rectangle(frame, (lx1, ly1), (lx1 + tw + 8, y1), color, -1)

        # Teks label
        cv2.putText(
            frame, text, (lx1 + 4, y1 - 5),
            cv2.FONT_HERSHEY_SIMPLEX, 0.55,
            (255, 255, 255), 1, cv2.LINE_AA,
        )

    # ── Proses Satu Frame ──────────────────────────────────────────────────
    def process_frame(self, frame: np.ndarray) -> np.ndarray:
        """
        Jalankan inference + tracking pada satu frame.
        Kembalikan frame yang sudah dianotasi.
        """
        h, w = frame.shape[:2]

        # ── YOLO Inference + ByteTrack ─────────────────────────────────────
        results = self.model.track(
            source=frame,
            conf=self.conf_threshold,
            iou=0.5,
            persist=True,               # pertahankan ID antar frame
            tracker="bytetrack.yaml",   # ByteTrack sudah ada di Ultralytics
            verbose=False,
            device=self.device,
        )

        detected_count = 0
        stall_count    = 0

        for result in results:
            if result.boxes is None:
                continue

            for box in result.boxes:
                # Ambil informasi kotak
                xyxy   = box.xyxy[0].cpu().numpy().astype(int)
                conf   = float(box.conf[0])
                cls_id = int(box.cls[0])
                cls_name = self.class_names[cls_id] if cls_id < len(self.class_names) else "unknown"

                # Track ID (bisa None jika tracking belum stabil)
                track_id = int(box.id[0]) if box.id is not None else -1

                x1, y1, x2, y2 = xyxy
                cx = (x1 + x2) / 2
                cy = (y1 + y2) / 2

                detected_count += 1

                # ── Tentukan warna dan label berdasarkan kelas ──────────────
                if cls_name == "train":
                    # Deteksi Kereta Api
                    color = self.COLOR_TRAIN
                    label = "🚂 KERETA API"

                    # Gambar kotak yang lebih tebal untuk kereta
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)
                    text = f"{label}  {conf:.0%}"
                    cv2.putText(
                        frame, text, (x1 + 4, y1 + 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                        color, 2, cv2.LINE_AA,
                    )
                    continue  # kereta tidak perlu tracking mogok

                elif cls_name in self.VEHICLE_CLASSES:
                    # ── Kendaraan bermotor — cek status mogok ──────────────
                    if track_id >= 0:
                        state = self._update_vehicle_state(
                            track_id, cls_name, cx, cy
                        )
                        if state.is_stalled:
                            color = self.COLOR_STALLED
                            label = f"🚨 MOGOK  ID:{track_id}"
                            # Overlay merah berkedip pada kotak mogok
                            overlay = frame.copy()
                            cv2.rectangle(
                                overlay, (x1, y1), (x2, y2), color, -1
                            )
                            frame = cv2.addWeighted(
                                overlay, 0.15, frame, 0.85, 0
                            )
                            stall_count += 1
                        else:
                            color = self.COLOR_NORMAL
                            label = f"{cls_name}  ID:{track_id}"
                    else:
                        color = self.COLOR_NORMAL
                        label = cls_name

                else:
                    color = (180, 180, 180)
                    label = cls_name

                self._draw_box(frame, (x1, y1, x2, y2), label, color, conf)

        self._total_detections = detected_count
        self._active_stalls    = stall_count

        # Hapus state kendaraan yang sudah lama tidak terdeteksi (> 30 detik)
        self._cleanup_old_states(max_age_sec=30.0)

        return frame

    # ── Hapus State Lama ───────────────────────────────────────────────────
    def _cleanup_old_states(self, max_age_sec: float) -> None:
        """Hapus state kendaraan yang tidak terdeteksi lagi agar memori tidak bocor."""
        now = time.time()
        stale_ids = [
            tid
            for tid, state in self._vehicle_states.items()
            if (
                len(state.positions) > 0
                and now - state.positions[-1][2] > max_age_sec
            )
        ]
        for tid in stale_ids:
            del self._vehicle_states[tid]

    # ── Loop Utama ─────────────────────────────────────────────────────────
    def run(self, frame_queue: Queue, stop_event: threading.Event) -> None:
        """
        Tarik frame dari antrian, proses, dan tampilkan di jendela OpenCV.
        Tekan 'q' untuk keluar.
        """
        window_name = "NusaRail Vision — Tekan Q untuk keluar"
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(window_name, 1280, 720)

        last_frame: Optional[np.ndarray] = None
        fps_frame_counter = 0
        fps_start = time.time()

        log.info("[Engine] 🚀 Memulai loop deteksi…")

        while not stop_event.is_set():
            # Ambil frame dari antrian (timeout 2 detik agar tidak freeze)
            try:
                frame = frame_queue.get(timeout=2.0)
            except Empty:
                # Tampilkan frame terakhir saat antrian kosong sesaat
                if last_frame is not None:
                    cv2.imshow(window_name, last_frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
                continue

            # Proses frame dengan YOLO
            try:
                annotated = self.process_frame(frame)
            except Exception as exc:
                log.error(f"[Engine] Error saat inference: {exc}")
                annotated = frame  # tampilkan frame asli jika error

            # Hitung FPS tampilan
            fps_frame_counter += 1
            elapsed = time.time() - fps_start
            if elapsed >= 1.0:
                self._display_fps = fps_frame_counter / elapsed
                fps_frame_counter = 0
                fps_start = time.time()

            # Tambahkan HUD
            annotated = self._draw_hud(annotated)
            last_frame = annotated

            cv2.imshow(window_name, annotated)

            # Tekan 'q' untuk keluar
            if cv2.waitKey(1) & 0xFF == ord("q"):
                log.info("[Engine] Pengguna menekan 'q' — menghentikan program…")
                stop_event.set()
                break

        cv2.destroyAllWindows()
        log.info("[Engine] Jendela ditutup, memori dibersihkan.")


# ─────────────────────────────────────────────────────────────────────────────
# CLASS: Orkestrator Utama
# ─────────────────────────────────────────────────────────────────────────────
class NusaRailVision:
    """
    Orkestrator yang mengikat semua komponen:
      YouTubeExtractor → FrameReader (Thread) → DetectionEngine
    """

    # Path default model (relatif terhadap lokasi script ini)
    DEFAULT_MODEL = str(
        Path(__file__).parent / "Dataset" / "best_pytorch.pt"
    )

    def __init__(
        self,
        source: str,
        model_path: Optional[str] = None,
        conf_threshold: float = 0.40,
        stall_seconds: float = 8.0,
        device: str = "cpu",
    ):
        """
        Args:
            source          : URL YouTube, path file video, atau index webcam.
            model_path      : Path ke model .pt (default: Dataset/best_pytorch.pt).
            conf_threshold  : Confidence minimum untuk deteksi.
            stall_seconds   : Waktu diam sebelum dinyatakan mogok (detik).
            device          : 'cpu' atau 'cuda' atau '0'.
        """
        self.source         = source
        self.model_path     = model_path or self.DEFAULT_MODEL
        self.conf_threshold = conf_threshold
        self.stall_seconds  = stall_seconds
        self.device         = device

    def _resolve_source(self) -> str:
        """Tentukan apakah sumber adalah YouTube, file lokal, atau webcam."""
        src = str(self.source).strip()

        # Webcam (angka)
        if src.isdigit():
            log.info(f"[Sumber] Menggunakan webcam index={src}")
            return int(src)

        # YouTube
        if "youtube.com" in src or "youtu.be" in src:
            log.info("[Sumber] Mendeteksi tautan YouTube — mengekstrak URL streaming…")
            return YouTubeExtractor.extract_url(src)

        # File lokal
        if Path(src).exists():
            log.info(f"[Sumber] File lokal: {src}")
            return src

        raise FileNotFoundError(
            f"Sumber tidak dikenali atau file tidak ditemukan: {src}"
        )

    def start(self) -> None:
        """Mulai pipeline deteksi end-to-end."""
        # 1. Resolve sumber
        try:
            resolved_source = self._resolve_source()
        except Exception as e:
            log.error(f"[Utama] ❌ {e}")
            sys.exit(1)

        # 2. Inisialisasi komponen
        frame_queue  = Queue(maxsize=FrameReader.MAX_QUEUE_SIZE)
        stop_event   = threading.Event()

        reader = FrameReader(
            source=resolved_source,
            queue=frame_queue,
            stop_event=stop_event,
        )

        engine = DetectionEngine(
            model_path=self.model_path,
            stall_threshold_sec=self.stall_seconds,
            conf_threshold=self.conf_threshold,
            device=self.device,
        )

        # 3. Muat model
        try:
            engine.load_model()
        except Exception as e:
            log.error(f"[Utama] ❌ Gagal memuat model: {e}")
            sys.exit(1)

        # 4. Jalankan thread pembaca frame
        reader.start()
        log.info("[Utama] Thread FrameReader dimulai.")

        # 5. Loop deteksi (berjalan di thread utama agar GUI responsif)
        try:
            engine.run(frame_queue=frame_queue, stop_event=stop_event)
        except KeyboardInterrupt:
            log.info("[Utama] Ctrl+C diterima — menghentikan…")
        finally:
            stop_event.set()
            reader.join(timeout=5)
            log.info("[Utama] ✅ Program selesai dengan bersih.")


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    """Parsing argumen command-line."""
    parser = argparse.ArgumentParser(
        description="NusaRail Vision — Deteksi Kendaraan Mogok & Kereta Api Real-Time",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Contoh penggunaan:
  python deteksi_realtime.py --url "https://youtu.be/LZr7jt3MmKM"
  python deteksi_realtime.py --url "video_cctv.mp4"
  python deteksi_realtime.py --url 0 --device cuda
  python deteksi_realtime.py --url "https://youtu.be/..." --stall 5 --conf 0.45
        """,
    )
    parser.add_argument(
        "--url",
        required=True,
        help="URL YouTube, path file video lokal, atau index webcam (misal: 0)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Path ke model .pt (default: Dataset/best_pytorch.pt)",
    )
    parser.add_argument(
        "--conf",
        type=float,
        default=0.40,
        help="Confidence threshold (0.0–1.0, default: 0.40)",
    )
    parser.add_argument(
        "--stall",
        type=float,
        default=8.0,
        help="Waktu diam (detik) sebelum dinyatakan MOGOK (default: 8)",
    )
    parser.add_argument(
        "--device",
        default="cpu",
        choices=["cpu", "cuda", "0", "1"],
        help="Device inferensi: 'cpu' atau 'cuda' (default: cpu)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    app = NusaRailVision(
        source=args.url,
        model_path=args.model,
        conf_threshold=args.conf,
        stall_seconds=args.stall,
        device=args.device,
    )
    app.start()
