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

        # CRITICAL FIX 13: Accurate Video Playback Speed (Anti-Lag)
        fps = 30.0
        if self._mode == "upload" and self._cap is not None:
            fps = self._cap.get(cv2.CAP_PROP_FPS)
            if fps <= 0 or fps > 120:
                fps = 30.0
        frame_delay = 1.0 / fps

        while self._running:
            if self._cap is None or not self._cap.isOpened():
                time.sleep(0.1)
                continue

            start_time = time.time()
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

            # CRITICAL FIX 13: Throttle ONLY for upload mode to maintain original FPS
            # Live streams (youtube/rtsp) will block naturally at cv2.read(), so NO sleep!
            if self._mode == "upload":
                elapsed = time.time() - start_time
                sleep_time = frame_delay - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)

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
