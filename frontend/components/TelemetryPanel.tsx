"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";

interface GeminiPayload {
  kondisi_perlintasan?: string;
  geo_location?: string;
  insight_narasi?: string;
  timestamp?: string;
}

interface DetectionTelemetry {
  frame?: number;
  detections?: Array<{
    class: string;
    track_id: number | null;
    confidence: number;
    stuck: boolean;
  }>;
  is_car_stuck?: boolean;
  is_evacuating?: boolean;
  evacuation_detected?: boolean;
  is_train_incoming?: boolean;
  emergency_status?: string;
  stuck_vehicle_ids?: number[];
}

interface TelemetryPanelProps {
  backendUrl: string;
}

/**
 * TelemetryPanel Component
 * ========================
 * WebSocket listener that connects to FastAPI /ws/telemetry to receive
 * real-time JSON telemetry from both the YOLOv8 detection pipeline and
 * the Gemini 1.5 Pro Macro-Observer.
 *
 * CRITICAL FIX 01: Auto-Reconnect Polling
 * Implements exponential backoff reconnection to survive Hugging Face
 * cold starts (60-90s container spin-up) and TCP timeouts.
 */
const TelemetryPanel: React.FC<TelemetryPanelProps> = ({ backendUrl }) => {
  const [geminiData, setGeminiData] = useState<GeminiPayload>({});
  const [detectionData, setDetectionData] = useState<DetectionTelemetry>({});
  const [wsStatus, setWsStatus] = useState<"connecting" | "connected" | "disconnected">("connecting");
  const [reconnectAttempt, setReconnectAttempt] = useState(0);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<NodeJS.Timeout | null>(null);

  // ----------------------------------------------------------------
  // CRITICAL FIX 01: Auto-Reconnect with Exponential Backoff
  // ----------------------------------------------------------------
  const connectWebSocket = useCallback(() => {
    // CRITICAL FIX 10: Cross-Origin Unblocking & Cache Busting
    let cleanBackendUrl = backendUrl.replace(/\/$/, ""); // hapus trailing slash
    const wsUrl = cleanBackendUrl
      .replace("https://", "wss://")
      .replace("http://", "ws://")
      + "/ws/telemetry";

    setWsStatus("connecting");

    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setWsStatus("connected");
        setReconnectAttempt(0); // Reset backoff on successful connection
        console.log("[TelemetryPanel] WebSocket connected.");
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);

          // Route message to appropriate state based on payload shape
          if (data.kondisi_perlintasan) {
            setGeminiData(data);
          }
          if (data.emergency_status !== undefined || data.detections) {
            setDetectionData(data);
          }
        } catch (e) {
          console.warn("[TelemetryPanel] Failed to parse message:", e);
        }
      };

      ws.onclose = () => {
        setWsStatus("disconnected");
        console.log("[TelemetryPanel] WebSocket disconnected. Scheduling reconnect...");
        scheduleReconnect();
      };

      ws.onerror = (error) => {
        console.error("[TelemetryPanel] WebSocket error:", error);
        ws.close();
      };
    } catch (e) {
      console.error("[TelemetryPanel] Failed to create WebSocket:", e);
      scheduleReconnect();
    }
  }, [backendUrl]);

  const scheduleReconnect = useCallback(() => {
    // Exponential backoff: 2s, 4s, 8s, 16s, max 30s
    const delay = Math.min(2000 * Math.pow(2, reconnectAttempt), 30000);
    setReconnectAttempt((prev) => prev + 1);

    console.log(`[TelemetryPanel] Reconnecting in ${delay / 1000}s (attempt ${reconnectAttempt + 1})`);

    reconnectTimerRef.current = setTimeout(() => {
      connectWebSocket();
    }, delay);
  }, [reconnectAttempt, connectWebSocket]);

  useEffect(() => {
    connectWebSocket();

    return () => {
      if (wsRef.current) wsRef.current.close();
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
    };
  }, [connectWebSocket]);

  // ----------------------------------------------------------------
  // Helper: Status color and badge
  // ----------------------------------------------------------------
  const getStatusColor = (status?: string) => {
    switch (status) {
      case "DARURAT_KRITIS": return "bg-red-600 text-white animate-pulse";
      case "BAHAYA": return "bg-orange-500 text-white";
      case "RAMAI": return "bg-yellow-500 text-black";
      case "MENDINGINKAN API": return "bg-blue-500 text-white animate-pulse";
      case "AMAN": return "bg-green-500 text-white";
      default: return "bg-gray-600 text-gray-300";
    }
  };

  const getWsStatusBadge = () => {
    switch (wsStatus) {
      case "connected": return <span className="text-green-400">● Terhubung</span>;
      case "connecting": return <span className="text-yellow-400 animate-pulse">● Menghubungkan...</span>;
      case "disconnected": return <span className="text-red-400">● Terputus (Percobaan #{reconnectAttempt})</span>;
    }
  };

  return (
    <div className="space-y-4">
      {/* CRITICAL FIX 09: Evacuation Detected Alert Banner */}
      {detectionData.evacuation_detected && (
        <div className="animate-pulse bg-fuchsia-900 border-fuchsia-500 border-2 rounded-xl p-4 shadow-[0_0_15px_rgba(217,70,239,0.5)]">
          <p className="text-fuchsia-100 font-bold text-center tracking-wider text-lg">
            ⚠️ INTERVENSI WARGA: EVAKUASI KENDARAAN MANUAL!
          </p>
        </div>
      )}

      {/* Connection Status */}
      <div className="bg-gray-800/60 backdrop-blur-sm rounded-xl p-4 border border-gray-700/50">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-mono text-gray-400 uppercase tracking-wider">
            WebSocket Status
          </h3>
          <div className="text-xs font-mono">{getWsStatusBadge()}</div>
        </div>
      </div>

      {/* Model Meta-Information */}
      <div className="bg-gray-800/60 backdrop-blur-sm rounded-xl p-4 border border-gray-700/50">
        <h3 className="text-sm font-mono text-gray-400 uppercase tracking-wider mb-2">
          Model Meta-Information
        </h3>
        <ul className="text-xs text-gray-300 font-mono space-y-1">
          <li><span className="text-cyan-400">Model:</span> YOLOv8n-NusaRail (Custom Fine-tuned)</li>
          <li><span className="text-cyan-400">Dataset Volume:</span> 3,000 Annotated Frames (70% Train, 20% Val, 10% Test)</li>
          <li><span className="text-cyan-400">Active Classes:</span> Car, Motorcycle, Train (Strictly Filtered)</li>
        </ul>
      </div>

      {/* Emergency Status Panel */}
      <div className="bg-gray-800/60 backdrop-blur-sm rounded-xl p-5 border border-gray-700/50">
        <h3 className="text-sm font-mono text-gray-400 uppercase tracking-wider mb-3">
          Status Darurat DJKA
        </h3>
        <div className={`inline-block px-4 py-2 rounded-lg font-bold text-lg ${getStatusColor(detectionData.emergency_status)}`}>
          {detectionData.emergency_status || "MENUNGGU DATA"}
        </div>

        {detectionData.is_evacuating && (
          <div className="mt-3 p-3 bg-fuchsia-950/50 border border-fuchsia-500/30 rounded-lg">
            <p className="text-fuchsia-300 text-sm font-mono">
              ⚠️ DETEKSI INTERVENSI WARGA: EVAKUASI KENDARAAN MANUAL!
            </p>
          </div>
        )}

        {detectionData.is_car_stuck && (
          <div className="mt-3 p-3 bg-red-950/50 border border-red-500/30 rounded-lg">
            <p className="text-red-300 text-sm font-mono">
              ⚠️ KENDARAAN MOGOK TERDETEKSI
              {detectionData.stuck_vehicle_ids &&
                ` (ID: ${detectionData.stuck_vehicle_ids.join(", ")})`}
            </p>
          </div>
        )}

        {detectionData.is_train_incoming && (
          <div className="mt-2 p-3 bg-orange-950/50 border border-orange-500/30 rounded-lg">
            <p className="text-orange-300 text-sm font-mono">
              🚂 KRL MENDEKAT TERDETEKSI
            </p>
          </div>
        )}
      </div>

      {/* Gemini AI Analysis */}
      <div className="bg-gray-800/60 backdrop-blur-sm rounded-xl p-5 border border-gray-700/50">
        <h3 className="text-sm font-mono text-gray-400 uppercase tracking-wider mb-3">
          🧠 Analisis Gemini 1.5 Pro
        </h3>

        {geminiData.kondisi_perlintasan ? (
          <div className="space-y-3">
            <div className="flex items-center gap-3">
              <span className="text-gray-500 text-xs w-24">Kondisi:</span>
              <span className={`px-3 py-1 rounded-md text-sm font-bold ${getStatusColor(geminiData.kondisi_perlintasan)}`}>
                {geminiData.kondisi_perlintasan}
              </span>
            </div>
            <div className="flex items-start gap-3">
              <span className="text-gray-500 text-xs w-24 mt-0.5">Lokasi:</span>
              <span className="text-gray-200 text-sm">
                {geminiData.geo_location || "-"}
              </span>
            </div>
            <div className="flex items-start gap-3">
              <span className="text-gray-500 text-xs w-24 mt-0.5">Insight:</span>
              <span className="text-gray-300 text-sm leading-relaxed">
                {geminiData.insight_narasi || "-"}
              </span>
            </div>
            <div className="flex items-center gap-3">
              <span className="text-gray-500 text-xs w-24">Waktu:</span>
              <span className="text-cyan-400 text-xs font-mono">
                {geminiData.timestamp}
              </span>
            </div>
          </div>
        ) : (
          <p className="text-gray-500 text-sm italic">
            Menunggu analisis Gemini... (interval 25 detik)
          </p>
        )}
      </div>

      {/* Detection Summary */}
      <div className="bg-gray-800/60 backdrop-blur-sm rounded-xl p-5 border border-gray-700/50">
        <h3 className="text-sm font-mono text-gray-400 uppercase tracking-wider mb-3">
          📊 Deteksi YOLOv8 ByteTrack
        </h3>

        {detectionData.detections && detectionData.detections.length > 0 ? (
          <div className="space-y-1 max-h-48 overflow-y-auto">
            {detectionData.detections.map((det, i) => (
              <div
                key={i}
                className={`flex items-center justify-between px-3 py-1.5 rounded-md text-xs font-mono ${
                  det.stuck
                    ? "bg-red-950/50 text-red-300 border border-red-500/20"
                    : "bg-gray-700/30 text-gray-300"
                }`}
              >
                <span>
                  {det.class} {det.track_id !== null ? `(ID:${det.track_id})` : "(ID:?)"}
                </span>
                <span className="text-gray-500">
                  {(det.confidence * 100).toFixed(1)}%
                  {det.stuck && <span className="ml-2 text-red-400 font-bold">MOGOK</span>}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-gray-500 text-sm italic">
            Belum ada objek terdeteksi.
          </p>
        )}

        {detectionData.frame && (
          <p className="text-gray-600 text-xs mt-2 font-mono">
            Frame #{detectionData.frame}
          </p>
        )}
      </div>
    </div>
  );
};

export default TelemetryPanel;
