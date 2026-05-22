"""
NusaRail Vision — Desktop Control Center
=========================================
GUI Launcher menggunakan CustomTkinter (dark mode modern).
Jalankan: python app.py
Install: pip install customtkinter
"""

import atexit
import os
import queue
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

import customtkinter as ctk
from pyngrok import ngrok

# ── Theme ──────────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

ROOT        = Path(__file__).parent.resolve()
BACKEND_DIR = ROOT / "backend"
FRONTEND_DIR= ROOT / "frontend"

NEON_CYAN   = "#00f5ff"
NEON_RED    = "#ff2d55"
NEON_GREEN  = "#00ff88"
NEON_AMBER  = "#ffb800"
DARK_900    = "#050d1a"
DARK_800    = "#0a1628"
DARK_700    = "#0f2040"
DARK_600    = "#1a2f55"

# ═══════════════════════════════════════════════════════════════════════════════
class NusaRailApp(ctk.CTk):

    def __init__(self):
        super().__init__()

        self.title("NusaRail Vision — Control Center")
        self.geometry("900x680")
        self.minsize(800, 600)
        self.configure(fg_color=DARK_900)
        try:
            self.iconbitmap("Assets/Logo.ico")
        except Exception:
            pass # fallback if icon doesn't exist on some OS
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._procs: list[subprocess.Popen] = []
        self._log_queue: queue.Queue[str]    = queue.Queue()
        self._running = False

        atexit.register(self._kill_all)

        self._build_ui()
        self._poll_log_queue()

    # ── UI Builder ─────────────────────────────────────────────────────────────
    def _build_ui(self):
        # ── Header ──────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color=DARK_800, corner_radius=0, height=70)
        hdr.pack(fill="x", side="top")
        hdr.pack_propagate(False)

        ctk.CTkLabel(
            hdr, text="⬡  NusaRail Vision",
            font=ctk.CTkFont("Segoe UI", 22, "bold"),
            text_color=NEON_CYAN,
        ).pack(side="left", padx=24, pady=16)

        ctk.CTkLabel(
            hdr, text="Traffic Anomaly Detection · Control Center",
            font=ctk.CTkFont("Segoe UI", 11),
            text_color="#4a7090",
        ).pack(side="left", padx=0, pady=16)

        # ── Status bar (right of header) ─────────────────────────────────────
        status_frame = ctk.CTkFrame(hdr, fg_color="transparent")
        status_frame.pack(side="right", padx=24)

        # Backend indicator
        self._be_dot = ctk.CTkLabel(status_frame, text="●", font=ctk.CTkFont(size=18),
                                     text_color="#333")
        self._be_dot.grid(row=0, column=0, padx=(0, 4))
        self._be_lbl = ctk.CTkLabel(status_frame, text="Backend",
                                     font=ctk.CTkFont("Segoe UI", 11),
                                     text_color="#555")
        self._be_lbl.grid(row=0, column=1, padx=(0, 20))

        # Frontend indicator
        self._fe_dot = ctk.CTkLabel(status_frame, text="●", font=ctk.CTkFont(size=18),
                                     text_color="#333")
        self._fe_dot.grid(row=0, column=2, padx=(0, 4))
        self._fe_lbl = ctk.CTkLabel(status_frame, text="Frontend",
                                     font=ctk.CTkFont("Segoe UI", 11),
                                     text_color="#555")
        self._fe_lbl.grid(row=0, column=3)

        # ── Main content ─────────────────────────────────────────────────────
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=20, pady=(10, 0))

        # Left sidebar: controls
        sidebar = ctk.CTkFrame(content, fg_color=DARK_800, corner_radius=16, width=230)
        sidebar.pack(side="left", fill="y", padx=(0, 14), pady=4)
        sidebar.pack_propagate(False)

        ctk.CTkLabel(sidebar, text="SERVER CONTROLS",
                     font=ctk.CTkFont("Segoe UI", 10, "bold"),
                     text_color="#3a5a7a").pack(pady=(20, 10))

        self._btn_start = ctk.CTkButton(
            sidebar, text="▶  Start Servers",
            font=ctk.CTkFont("Segoe UI", 13, "bold"),
            fg_color=NEON_GREEN, hover_color="#00cc66",
            text_color=DARK_900, corner_radius=10, height=44,
            command=self._start_servers,
        )
        self._btn_start.pack(fill="x", padx=16, pady=(0, 8))

        self._btn_stop = ctk.CTkButton(
            sidebar, text="■  Stop Servers",
            font=ctk.CTkFont("Segoe UI", 13, "bold"),
            fg_color=NEON_RED, hover_color="#cc2244",
            text_color="white", corner_radius=10, height=44,
            command=self._stop_servers, state="disabled",
        )
        self._btn_stop.pack(fill="x", padx=16, pady=(0, 16))

        ctk.CTkFrame(sidebar, fg_color=DARK_600, height=1).pack(fill="x", padx=16, pady=4)

        self._btn_web = ctk.CTkButton(
            sidebar, text="🌐  Open Web Dashboard",
            font=ctk.CTkFont("Segoe UI", 12),
            fg_color=DARK_700, hover_color=DARK_600,
            text_color=NEON_CYAN, corner_radius=10, height=40,
            command=lambda: webbrowser.open("http://localhost:3000"),
        )
        self._btn_web.pack(fill="x", padx=16, pady=(12, 4))

        self._btn_docs = ctk.CTkButton(
            sidebar, text="📄  API Docs",
            font=ctk.CTkFont("Segoe UI", 12),
            fg_color=DARK_700, hover_color=DARK_600,
            text_color="#a0c0d0", corner_radius=10, height=36,
            command=lambda: webbrowser.open("http://localhost:8000/api/docs"),
        )
        self._btn_docs.pack(fill="x", padx=16, pady=4)

        self._btn_clear = ctk.CTkButton(
            sidebar, text="🗑  Clear Log",
            font=ctk.CTkFont("Segoe UI", 11),
            fg_color=DARK_700, hover_color=DARK_600,
            text_color="#567080", corner_radius=10, height=32,
            command=self._clear_log,
        )
        self._btn_clear.pack(fill="x", padx=16, pady=(16, 4))

        # Info box at bottom of sidebar
        info = ctk.CTkFrame(sidebar, fg_color=DARK_700, corner_radius=10)
        info.pack(fill="x", side="bottom", padx=16, pady=16)

        for label, val, col in [
            ("Backend",  "localhost:8000", "#a0c0d0"),
            ("Frontend", "localhost:3000", "#a0c0d0"),
            ("Ollama",   "localhost:11434", "#7090a0"),
        ]:
            row = ctk.CTkFrame(info, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=3)
            ctk.CTkLabel(row, text=label + ":", font=ctk.CTkFont("Segoe UI", 10),
                         text_color="#3a5a7a").pack(side="left")
            ctk.CTkLabel(row, text=val, font=ctk.CTkFont("Consolas", 10),
                         text_color=col).pack(side="right")

        # ── Right: terminal log ───────────────────────────────────────────────
        log_frame = ctk.CTkFrame(content, fg_color=DARK_800, corner_radius=16)
        log_frame.pack(side="right", fill="both", expand=True, pady=4)

        # Title bar
        tb = ctk.CTkFrame(log_frame, fg_color=DARK_700, corner_radius=0,
                           height=36)
        tb.pack(fill="x")
        tb.pack_propagate(False)
        for c, col in [("●", NEON_RED), ("●", NEON_AMBER), ("●", NEON_GREEN)]:
            ctk.CTkLabel(tb, text=c, text_color=col,
                         font=ctk.CTkFont(size=12)).pack(side="left", padx=6, pady=8)
        ctk.CTkLabel(tb, text="nusarail-console.log",
                     font=ctk.CTkFont("Consolas", 10),
                     text_color="#2a4560").pack(side="left", padx=4)

        # Text widget (terminal)
        self._log_text = ctk.CTkTextbox(
            log_frame,
            font=ctk.CTkFont("Consolas", 11),
            fg_color="#010a14",
            text_color="#7ec8d8",
            activate_scrollbars=True,
            corner_radius=0,
        )
        self._log_text.pack(fill="both", expand=True, padx=2, pady=(0, 2))
        self._log_text.configure(state="disabled")

        # ── Footer ───────────────────────────────────────────────────────────
        ft = ctk.CTkFrame(self, fg_color=DARK_800, corner_radius=0, height=32)
        ft.pack(fill="x", side="bottom")
        ft.pack_propagate(False)
        ctk.CTkLabel(ft, text="NusaRail Vision v2.0.0  ·  YOLOv8 + SQLite + Ollama",
                     font=ctk.CTkFont("Segoe UI", 9),
                     text_color="#2a4560").pack(side="left", padx=16, pady=7)
        self._clock_lbl = ctk.CTkLabel(ft, text="",
                                        font=ctk.CTkFont("Consolas", 9),
                                        text_color="#2a4560")
        self._clock_lbl.pack(side="right", padx=16)
        self._update_clock()

    # ── Helpers ────────────────────────────────────────────────────────────────
    def _update_clock(self):
        self._clock_lbl.configure(text=time.strftime("%Y-%m-%d  %H:%M:%S"))
        self.after(1000, self._update_clock)

    def _log(self, msg: str, color: str = "default"):
        self._log_queue.put((msg, color))

    def _poll_log_queue(self):
        try:
            while True:
                item = self._log_queue.get_nowait()
                msg, color = item if isinstance(item, tuple) else (item, "default")
                self._append_log(msg, color)
        except queue.Empty:
            pass
        self.after(80, self._poll_log_queue)

    def _append_log(self, text: str, color: str = "default"):
        self._log_text.configure(state="normal")
        ts = time.strftime("%H:%M:%S")
        prefix_color_map = {
            "backend":  ("[BACKEND]  ", "#b060ff"),
            "frontend": ("[FRONTEND] ", "#00c8ff"),
            "system":   ("[SYSTEM]   ", "#00ff88"),
            "error":    ("[ERROR]    ", "#ff2d55"),
            "warn":     ("[WARN]     ", "#ffb800"),
        }
        prefix, tcol = prefix_color_map.get(color, ("[INFO]     ", "#4a8a9a"))
        line = f"{ts}  {prefix}{text}\n"
        self._log_text.insert("end", line)
        self._log_text.see("end")
        self._log_text.configure(state="disabled")

    def _clear_log(self):
        self._log_text.configure(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.configure(state="disabled")

    def _set_status(self, who: str, online: bool):
        dot  = self._be_dot  if who == "backend"  else self._fe_dot
        lbl  = self._be_lbl  if who == "backend"  else self._fe_lbl
        dot.configure(text_color=NEON_GREEN if online else NEON_RED)
        lbl.configure(text_color="#cce8f0"  if online else "#664455")

    # ── Server lifecycle ────────────────────────────────────────────────────────
    def _start_servers(self):
        if self._running:
            return
        self._running = True
        self._btn_start.configure(state="disabled")
        self._btn_stop.configure(state="normal")
        self._log("Memulai semua server...", "system")
        threading.Thread(target=self._run_backend,  daemon=True).start()
        threading.Thread(target=self._run_frontend, daemon=True).start()
        threading.Thread(target=self._health_probe, daemon=True).start()

    def _stop_servers(self):
        self._log("Menghentikan server...", "warn")
        self._kill_all()
        self._running = False
        self._btn_start.configure(state="normal")
        self._btn_stop.configure(state="disabled")
        self._set_status("backend",  False)
        self._set_status("frontend", False)
        self._log("Semua server dihentikan.", "system")

    def _run_backend(self):
        cmd = [sys.executable, "-m", "uvicorn", "main:app",
               "--host", "0.0.0.0", "--port", "8000", "--reload"]
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        try:
            p = subprocess.Popen(
                cmd, cwd=str(BACKEND_DIR),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                env=env,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform=="win32" else 0,
            )
            self._procs.append(p)
            threading.Thread(target=self._setup_ngrok_tunnel, daemon=True).start()
            for line in iter(p.stdout.readline, b""):
                txt = line.decode("utf-8", errors="replace").rstrip()
                if txt:
                    self._log(txt, "backend")
        except Exception as e:
            self._log(f"Backend error: {e}", "error")

    def _run_frontend(self):
        npm = "npm.cmd" if sys.platform == "win32" else "npm"
        try:
            p = subprocess.Popen(
                [npm, "run", "dev"], cwd=str(FRONTEND_DIR),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform=="win32" else 0,
            )
            self._procs.append(p)
            for line in iter(p.stdout.readline, b""):
                txt = line.decode("utf-8", errors="replace").rstrip()
                if txt:
                    self._log(txt, "frontend")
        except Exception as e:
            self._log(f"Frontend error: {e}", "error")

    def _health_probe(self):
        import socket
        def wait_port(port, timeout=60):
            dl = time.time() + timeout
            while time.time() < dl:
                try:
                    with socket.create_connection(("127.0.0.1", port), 1):
                        return True
                except OSError:
                    time.sleep(0.8)
            return False

        if wait_port(8000):
            self._log("Backend ONLINE → http://localhost:8000", "system")
            self.after(0, lambda: self._set_status("backend", True))
        else:
            self._log("Backend TIMEOUT — cek log di atas", "error")

        if wait_port(3000):
            self._log("Frontend ONLINE → http://localhost:3000", "system")
            self.after(0, lambda: self._set_status("frontend", True))
        else:
            self._log("Frontend TIMEOUT — jalankan: cd frontend && npm install", "warn")

    def _setup_ngrok_tunnel(self):
        time.sleep(3)
        try:
            public_url = ngrok.connect(8000)
            self._log(f"🟢 BACKEND PUBLIC URL: {public_url} [Copy ke NEXT_PUBLIC_API_URL di Vercel]", "system")
        except Exception as e:
            self._log(f"Ngrok tunnel error: {e}", "warn")

    def _kill_all(self):
        for p in self._procs:
            if p.poll() is None:
                try:
                    if sys.platform == "win32":
                        subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
                    else:
                        p.terminate()
                        p.wait(timeout=5)
                except Exception:
                    try:
                        p.kill()
                    except Exception:
                        pass
        self._procs.clear()

    def _on_close(self):
        self._log("Menutup aplikasi — menghentikan server...", "warn")
        self._kill_all()
        self.destroy()


# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    app = NusaRailApp()
    app.mainloop()
