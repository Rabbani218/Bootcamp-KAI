"""
NusaRail Vision System - Gemini Agent Module
=============================================
Integrates Google Gemini 1.5 Pro as a Macro-Observer for scene-level
understanding of railway crossing conditions. Exports periodic Base64
JPEG frames and returns structured JSON telemetry.

CRITICAL FIX 05: Rate Limit Shield — HTTP 429 / resource_exhausted
graceful degradation with 45-second exponential backoff.
"""

import os
import time
import json
import base64
import asyncio
import logging
from typing import Optional, Callable, Awaitable

import cv2
import numpy as np

log = logging.getLogger("nusarail.gemini")

# Gemini configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_INTERVAL_SEC = 25  # Polling interval between Gemini calls
GEMINI_MODEL = "gemini-1.5-pro"

# System prompt for Gemini — strict JSON-only output
GEMINI_SYSTEM_PROMPT = """Anda adalah AI pengawas perlintasan kereta api Indonesia.
Perhatikan interaksi manusia dengan kendaraan. Jika terlihat ada orang-orang berkerumun di sekitar mobil/truk di tengah rel, atau terlihat gerakan warga sedang mendorong kendaraan secara paksa, SEGERA kembalikan status 'DARURAT_KRITIS' meskipun kereta belum terlihat. Warga yang mendorong mobil di rel adalah indikasi mutlak mobil tersebut mogok/terjebak.
PERHATIAN KHUSUS: Deteksi tanda-tanda gotong royong warga, kepanikan, atau orang yang berkerumun mendorong/mengangkat objek di atas rel. Jika ada aktivitas ini, wajib asumsikan ada kendaraan/rintangan yang macet dan kembalikan status 'DARURAT_KRITIS'.
Analisis gambar CCTV yang diberikan dan kembalikan HANYA dalam format JSON berikut tanpa markdown:
{
  "kondisi_perlintasan": "AMAN | RAMAI | BAHAYA | DARURAT_KRITIS",
  "geo_location": "Lokasi perlintasan yang teridentifikasi (atau 'Tidak Diketahui')",
  "insight_narasi": "Deskripsi singkat kondisi lalu lintas dan potensi bahaya dalam Bahasa Indonesia.",
  "timestamp": "Waktu analisis (HH:MM:SS)"
}
Jangan berhalusinasi. Hanya deskripsikan apa yang terlihat di gambar."""


class GeminiAgent:
    """
    Asynchronous Gemini 1.5 Pro integration with Rate Limit Shield.
    Periodically sends frame snapshots to Gemini for macro-level scene analysis.
    """

    def __init__(self):
        self._running = False
        self._latest_payload: dict = {}
        self._broadcast_fn: Optional[Callable[[dict], Awaitable[None]]] = None
        self._genai = None
        self._model = None
        self._last_force_time = 0.0  # DEBOUNCE TRACKER

        # Initialize Google Generative AI
        try:
            import google.generativeai as genai
            if GEMINI_API_KEY:
                genai.configure(api_key=GEMINI_API_KEY)
                self._genai = genai
                self._model = genai.GenerativeModel(GEMINI_MODEL)
                log.info(f"[GeminiAgent] Initialized with model: {GEMINI_MODEL}")
            else:
                log.warning("[GeminiAgent] GEMINI_API_KEY not set. Agent disabled.")
        except ImportError:
            log.warning("[GeminiAgent] google-generativeai not installed. Agent disabled.")

    def set_broadcast_function(self, fn: Callable[[dict], Awaitable[None]]):
        """Register the WebSocket broadcast function for pushing telemetry."""
        self._broadcast_fn = fn

    def _encode_frame_base64(self, frame: np.ndarray) -> str:
        """Encode an OpenCV frame to Base64 JPEG string."""
        _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        return base64.b64encode(buffer.tobytes()).decode("utf-8")

    async def _call_gemini(self, frame: np.ndarray) -> dict:
        """
        Send a frame to Gemini 1.5 Pro and parse the structured JSON response.
        This method runs the blocking Gemini API call inside asyncio.to_thread
        to prevent blocking the main event loop.
        """
        if self._model is None:
            return self._make_fallback("Model Gemini tidak tersedia.")

        b64_image = self._encode_frame_base64(frame)

        def _sync_generate():
            import PIL.Image
            import io
            img_bytes = base64.b64decode(b64_image)
            image = PIL.Image.open(io.BytesIO(img_bytes))
            response = self._model.generate_content(
                [GEMINI_SYSTEM_PROMPT, image],
                generation_config={"temperature": 0.2, "max_output_tokens": 500},
            )
            return response.text

        raw_text = await asyncio.to_thread(_sync_generate)

        # Parse JSON from response (strip markdown fences if present)
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        cleaned = cleaned.strip()

        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            payload = {
                "kondisi_perlintasan": "TIDAK DIKETAHUI",
                "geo_location": "Tidak Diketahui",
                "insight_narasi": raw_text[:200],
                "timestamp": time.strftime("%H:%M:%S"),
            }

        # Ensure timestamp is present
        if "timestamp" not in payload:
            payload["timestamp"] = time.strftime("%H:%M:%S")

        return payload

    def _make_fallback(self, message: str) -> dict:
        """Generate a safe fallback payload."""
        return {
            "kondisi_perlintasan": "TIDAK DIKETAHUI",
            "geo_location": "Tidak Diketahui",
            "insight_narasi": message,
            "timestamp": time.strftime("%H:%M:%S"),
        }

    # ------------------------------------------------------------------
    # CRITICAL FIX 05: Rate Limit Shield
    # ------------------------------------------------------------------
    async def _shielded_call(self, frame: np.ndarray) -> dict:
        """
        Wraps the Gemini API call in a comprehensive try-except shield.
        If HTTP 429 (Resource Exhausted) is detected, the system:
        1. Bypasses the crash entirely
        2. Fires a dummy "MENDINGINKAN API" payload to WebSocket
        3. Sleeps for 45 seconds (exponential backoff)
        """
        try:
            return await self._call_gemini(frame)

        except Exception as e:
            error_msg = str(e).lower()

            # CRITICAL FIX 05: Detect rate limit errors
            if "429" in error_msg or "resource_exhausted" in error_msg or "quota" in error_msg:
                log.warning(f"[GeminiAgent] Rate Limit Hit (HTTP 429). Cooling down 45s...")

                fallback_payload = {
                    "kondisi_perlintasan": "MENDINGINKAN API",
                    "geo_location": "Rate Limit Bypass",
                    "insight_narasi": "Sistem AI sedang mendinginkan antrean (Rate Limit Bypass). Data visual tetap berjalan aman.",
                    "timestamp": time.strftime("%H:%M:%S"),
                }

                # Push fallback to WebSocket immediately
                if self._broadcast_fn:
                    await self._broadcast_fn(fallback_payload)

                # Exponential backoff: sleep 45 seconds
                await asyncio.sleep(45)
                return fallback_payload

            else:
                log.error(f"[GeminiAgent] Unexpected error: {e}")
                return self._make_fallback(f"Error: {str(e)[:100]}")

    # ------------------------------------------------------------------
    # CRITICAL HACK: Event-Driven Gemini Trigger untuk Kompensasi Kebutaan YOLO
    # ------------------------------------------------------------------
    async def force_analyze(self, frame: np.ndarray, context_prompt: str):
        """
        On-Demand trigger for Gemini. 
        Bypasses the 25s loop to do an instant analysis when YOLO detects a stuck vehicle.
        Includes a 60-second debounce.
        """
        now = time.time()
        if now - self._last_force_time < 60.0:
            log.info("[GeminiAgent] force_analyze debounced (cooldown active).")
            return
            
        self._last_force_time = now
        log.warning("[GeminiAgent] FORCE ANALYZE TRIGGERED! context_prompt injected.")

        if self._model is None:
            return

        b64_image = self._encode_frame_base64(frame)

        def _sync_generate():
            import PIL.Image
            import io
            img_bytes = base64.b64decode(b64_image)
            image = PIL.Image.open(io.BytesIO(img_bytes))
            
            # Combine prompts
            combined_prompt = f"{GEMINI_SYSTEM_PROMPT}\n\n{context_prompt}"
            
            response = self._model.generate_content(
                [combined_prompt, image],
                generation_config={"temperature": 0.2, "max_output_tokens": 500},
            )
            return response.text

        try:
            raw_text = await asyncio.to_thread(_sync_generate)
        except Exception as e:
            log.error(f"[GeminiAgent] force_analyze failed: {e}")
            return

        # Parse JSON
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        cleaned = cleaned.strip()

        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            payload = self._make_fallback("Gagal mem-parsing JSON dari force_analyze.")

        if "timestamp" not in payload:
            payload["timestamp"] = time.strftime("%H:%M:%S")

        self._latest_payload = payload

        # Broadcast
        if self._broadcast_fn:
            await self._broadcast_fn(payload)

    # ------------------------------------------------------------------
    # Background Worker Loop
    # ------------------------------------------------------------------
    async def run_loop(self, get_frame_fn):
        """
        Main async loop that periodically queries Gemini with the latest frame.
        Runs indefinitely until stopped.

        Args:
            get_frame_fn: Callable that returns the latest frame (np.ndarray or None)
        """
        self._running = True
        log.info(f"[GeminiAgent] Worker loop started (interval={GEMINI_INTERVAL_SEC}s)")

        while self._running:
            await asyncio.sleep(GEMINI_INTERVAL_SEC)

            frame = get_frame_fn()
            if frame is None:
                continue

            payload = await self._shielded_call(frame)
            self._latest_payload = payload

            # Broadcast to all WebSocket clients
            if self._broadcast_fn:
                await self._broadcast_fn(payload)

            log.info(f"[GeminiAgent] Analysis: {payload.get('kondisi_perlintasan', '?')}")

    def stop(self):
        """Stop the worker loop."""
        self._running = False
        log.info("[GeminiAgent] Worker loop stopped.")

    @property
    def latest_payload(self) -> dict:
        return self._latest_payload
