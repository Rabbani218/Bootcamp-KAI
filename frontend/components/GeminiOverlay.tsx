"use client";

import { useEffect, useState, useRef } from 'react';

interface GeminiReport {
  status: string;
  lokasi: string;
  narasi: string;
  timestamp?: number;
}

interface GeminiOverlayProps {
  backendWsUrl: string;
  isBackendWakingUp?: boolean;
  onWsStatusChange?: (status: 'connected' | 'disconnected') => void;
  isDemoMode?: boolean;
  demoVideoDanger?: boolean;
}

export default function GeminiOverlay({ backendWsUrl, isBackendWakingUp, onWsStatusChange, isDemoMode, demoVideoDanger }: GeminiOverlayProps) {
  const [report, setReport] = useState<GeminiReport>({
    status: "MENGINISIALISASI",
    lokasi: "Menghubungkan ke AI...",
    narasi: "Sistem sedang menyambungkan ke server analisis.",
  });
  const [connected, setConnected] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<NodeJS.Timeout | null>(null);
  const retryCount = useRef(0);

  // LOGIKA SIMULASI MODE DEMO BERSINKRONISASI SEMPURNA DENGAN VIDEO
  useEffect(() => {
    if (!isDemoMode) {
      // BERSENJATA: Jika pengguna keluar dari mode Demo ke mode lain (Live/Upload),
      // kita harus segera MENGHAPUS jejak data kalibata dari layar sebelum data WS baru datang!
      setReport(prev => ({
        ...prev,
        status: "MENGINISIALISASI",
        lokasi: "Menunggu data AI...",
        narasi: "Menunggu stream terhubung..."
      }));
      return;
    }

    // Paksa status ke Connected untuk UI
    setConnected(true);
    if (onWsStatusChange) onWsStatusChange('connected');

    if (demoVideoDanger) {
      setReport({
        status: "DARURAT_KRITIS: KENDARAAN TERJEBAK",
        lokasi: "Stasiun Duren Kalibata (Jalur Bogor - Jakarta Kota)",
        narasi: "Jalur ini bahaya. Mengirimkan pesan peringatan ke DJKA untuk memberlakukan semboyan (sinyal merah terdekat) dan rem darurat pada rangkaian KRL untuk melakukan pengereman darurat.",
        timestamp: Math.floor(Date.now() / 1000)
      });
    } else {
      setReport({
        status: "AMAN",
        lokasi: "Stasiun Duren Kalibata (Jalur Bogor - Jakarta Kota)",
        narasi: "Jalur ini aman, tidak ada tanda bahaya di sini.",
        timestamp: Math.floor(Date.now() / 1000)
      });
    }
    setLastUpdate(new Date());

  }, [isDemoMode, demoVideoDanger]);

  useEffect(() => {
    const connect = () => {
      // Bersihkan koneksi lama jika ada
      if (wsRef.current) {
        wsRef.current.onclose = null; // Cegah auto-reconnect dari instance lama
        wsRef.current.close();
      }

      console.log(`[GeminiOverlay] Connecting to: ${backendWsUrl}`);
      const ws = new WebSocket(backendWsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log("[GeminiOverlay] WebSocket connected ✅");
        setConnected(true);
        retryCount.current = 0; // Reset
        if (onWsStatusChange) onWsStatusChange('connected');
        // Kirim ping ke server untuk meminta data terbaru
        try { ws.send("ping"); } catch {}
      };

      // ──────────────────────────────────────────────────────────
      // KUNCI: onmessage handler yang BENAR-BENAR memperbarui state
      // Data dari backend: {"status":"...", "lokasi":"...", "narasi":"...", "timestamp":...}
      // ──────────────────────────────────────────────────────────
      ws.onmessage = (event) => {
        if (isDemoMode) return; // Abaikan data asli dari server jika sedang dalam mode Simulasi Canned Demo
        try {
          const data = JSON.parse(event.data) as GeminiReport;
          console.log("[GeminiOverlay] Data diterima:", data);

          // Update SEMUA state dari data server secara langsung (Tanpa Override)
          setReport({
            status:    data.status    || "AMAN",
            lokasi:    data.lokasi    || "Tidak dikenali",
            narasi:    data.narasi    || "Tidak ada narasi.",
            timestamp: data.timestamp,
          });
          setLastUpdate(new Date());

        } catch (e) {
          console.error("[GeminiOverlay] Gagal parse JSON:", e, "Raw:", event.data);
        }
      };

      ws.onclose = (event) => {
        setConnected(false);
        if (onWsStatusChange) onWsStatusChange('disconnected');
        
        // CRITICAL FIX 11: Exponential Backoff (Maks 10s)
        retryCount.current += 1;
        const delay = retryCount.current >= 3 ? 10000 : Math.pow(2, retryCount.current) * 1000;
        
        console.log(`[GeminiOverlay] Disconnected (code=${event.code}). Reconnect attempt ${retryCount.current} in ${delay/1000}s...`);
        // Auto-reconnect
        reconnectTimer.current = setTimeout(connect, delay);
      };

      ws.onerror = (err) => {
        console.error("[GeminiOverlay] WebSocket error:", err);
        ws.close(); // Akan trigger onclose → reconnect
      };
    };

    connect();

    return () => {
      // Cleanup saat komponen unmount
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      if (wsRef.current) {
        wsRef.current.onclose = null; // Cegah reconnect saat unmount
        wsRef.current.close();
      }
    };
  }, [backendWsUrl]);

  // Deteksi tipe status untuk styling
  const isDanger      = report.status?.toUpperCase().includes("BAHAYA") || report.status?.toUpperCase().includes("DARURAT");
  const isStationary  = report.status?.includes("TERJEBAK");
  const isInitializing = report.status?.toUpperCase().includes("MENGINISIALISASI");

  // LOGIKA AUDIO WARNING
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    if (typeof window !== 'undefined' && !audioRef.current) {
      audioRef.current = new Audio('/Warning.mp3');
      audioRef.current.loop = true;
    }
  }, []);

  useEffect(() => {
    if (!audioRef.current) return;
    
    if (isDanger) {
      audioRef.current.play().catch(e => console.error("[Audio] Autoplay diblokir browser:", e));
    } else {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
    }

    return () => {
      // Hentikan audio saat komponen unmount
      if (audioRef.current) {
        audioRef.current.pause();
      }
    };
  }, [isDanger]);

  // Warna status badge
  const badgeClass = isDanger
    ? 'bg-red-600/90 text-white animate-pulse shadow-red-900/50 border border-red-500'
    : isInitializing
    ? 'bg-yellow-700/80 text-yellow-200 border border-yellow-600'
    : 'bg-emerald-600/90 text-white shadow-emerald-900/50 border border-emerald-500';

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-5 flex flex-col h-full shadow-xl">
      {/* Header */}
      <div className="flex items-center justify-between mb-4 pb-4 border-b border-gray-800">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <svg className="w-5 h-5 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
          </svg>
          AI Analytics Engine
        </h2>
        <div className={`px-2 py-1 rounded text-xs font-medium ${
          connected
            ? 'bg-green-900/50 text-green-400 border border-green-800/50'
            : 'bg-red-900/50 text-red-400 border border-red-800/50'
        }`}>
          {connected ? 'WS Connected' : 'WS Disconnected'}
        </div>
      </div>

      {/* CRITICAL FIX 11: Cold Start UI */}
      {isBackendWakingUp && (
        <div className="mb-4 bg-blue-900/40 border border-blue-700/50 p-3 rounded-lg shadow-inner">
          <p className="text-blue-300 text-xs font-mono font-semibold mb-2 flex items-center gap-2">
            <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            Menunggu Server Bangun (Cold Start)...
          </p>
          <div className="w-full bg-gray-800 rounded-full h-1.5 overflow-hidden relative">
            <div className="bg-blue-500 h-1.5 rounded-full w-full absolute animate-[progress_2s_ease-in-out_infinite] origin-left"></div>
          </div>
        </div>
      )}

      <div className="flex-1 overflow-y-auto pr-1 space-y-5">

        {/* Status Perlintasan */}
        <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700/50">
          <h3 className="text-xs text-gray-400 mb-2 uppercase font-semibold tracking-wider">
            Kondisi Perlintasan
          </h3>
          <div className={`inline-flex items-center px-4 py-2 rounded-md font-bold text-sm shadow-lg ${badgeClass}`}>
            {isDanger ? (
              <>
                <svg className="w-4 h-4 mr-2 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
                {report.status}
              </>
            ) : (
              <>
                <svg className="w-4 h-4 mr-2 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
                {report.status}
              </>
            )}
          </div>

          {/* Banner khusus kendaraan terjebak */}
          {isStationary && (
            <div className="mt-3 p-2 bg-red-900/40 border border-red-700 rounded text-xs text-red-300">
              🚨 Sistem deteksi kendaraan diam aktif. Petugas harap segera verifikasi ke lokasi.
            </div>
          )}
        </div>

        {/* Geo-Location */}
        <div>
          <h3 className="text-xs text-gray-400 mb-1 uppercase font-semibold tracking-wider">
            Geo-Location (AI Inference)
          </h3>
          <div className="flex items-start gap-2 mt-1">
            <svg className="w-4 h-4 text-gray-500 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
            <span className="text-sm font-medium text-gray-200">
              {report.lokasi}
            </span>
          </div>
        </div>

        {/* Insight Narasi */}
        <div>
          <h3 className="text-xs text-gray-400 mb-2 uppercase font-semibold tracking-wider">
            Insight Narasi (Gemini 2.0 Flash)
          </h3>
          <div className={`p-4 rounded-md text-sm leading-relaxed border shadow-inner transition-all duration-500 ${
            isDanger
              ? 'bg-red-950/40 border-red-800/50 text-red-200'
              : 'bg-gray-800 border-gray-700 text-gray-200'
          }`}>
            {report.narasi}
          </div>
        </div>

        {/* Timestamp & Update indicator */}
        <div className="flex justify-between items-center text-xs text-gray-500 pt-3 border-t border-gray-800">
          <span className="flex items-center gap-1.5">
            <span className={`w-2 h-2 rounded-full ${connected ? 'bg-green-500 animate-pulse' : 'bg-gray-600'}`} />
            {connected ? 'Live' : 'Offline'}
          </span>
          <span className="font-mono bg-gray-800 px-2 py-1 rounded text-gray-400">
            {lastUpdate
              ? `Update: ${lastUpdate.toLocaleTimeString('id-ID')}`
              : (report.timestamp
                  ? `Sync: ${new Date(report.timestamp * 1000).toLocaleTimeString('id-ID')}`
                  : 'Menunggu data...'
                )
            }
          </span>
        </div>
      </div>
    </div>
  );
}
