"use client";

import { useEffect, useState } from 'react';

interface GeminiReport {
  status: string;
  lokasi: string;
  narasi: string;
  timestamp: number;
}

interface GeminiOverlayProps {
  backendWsUrl: string;
}

export default function GeminiOverlay({ backendWsUrl }: GeminiOverlayProps) {
  const [report, setReport] = useState<GeminiReport | null>(null);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    let ws: WebSocket;
    let reconnectTimer: NodeJS.Timeout;

    const connect = () => {
      ws = new WebSocket(backendWsUrl);

      ws.onopen = () => {
        setConnected(true);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          setReport(data);
        } catch (e) {
          console.error("Gagal parse data websocket", e);
        }
      };

      ws.onclose = () => {
        setConnected(false);
        reconnectTimer = setTimeout(connect, 5000);
      };

      ws.onerror = (err) => {
        console.error("WebSocket error:", err);
        ws.close();
      };
    };

    connect();

    return () => {
      clearTimeout(reconnectTimer);
      if (ws) {
        ws.close();
      }
    };
  }, [backendWsUrl]);

  const isDanger = report?.status?.toUpperCase().includes("BAHAYA");
  const isOverride = report?.status?.toUpperCase().includes("OVERRIDE VISI");

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-5 flex flex-col h-full shadow-xl">
      <div className="flex items-center justify-between mb-4 pb-4 border-b border-gray-800">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <svg className="w-5 h-5 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
          </svg>
          AI Analytics Engine
        </h2>
        <div className={`px-2 py-1 rounded text-xs font-medium ${connected ? 'bg-green-900/50 text-green-400 border border-green-800/50' : 'bg-red-900/50 text-red-400 border border-red-800/50'}`}>
          {connected ? 'WS Connected' : 'WS Disconnected'}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto pr-2 custom-scrollbar">
        <div className="space-y-5">
          {/* Status Keamanan */}
          <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700/50">
            <h3 className="text-xs text-gray-400 mb-2 uppercase font-semibold tracking-wider">Kondisi Perlintasan</h3>
            <div className={`inline-flex items-center px-4 py-2 rounded-md font-bold text-sm shadow-lg ${isDanger ? 'bg-red-600/90 text-white animate-pulse shadow-red-900/50 border border-red-500' : 'bg-emerald-600/90 text-white shadow-emerald-900/50 border border-emerald-500'}`}>
              {isDanger ? (
                <>
                  <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" /></svg>
                  {report?.status || 'BAHAYA'}
                </>
              ) : (
                <>
                  <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" /></svg>
                  {report?.status || 'AMAN'}
                </>
              )}
            </div>
            {isOverride && (
              <p className="text-xs text-red-400 mt-2 font-medium">
                Sistem YOLO mendeteksi bahaya (AI Gemini diblokir).
              </p>
            )}
          </div>

          {/* Lokasi Terdeteksi */}
          <div>
            <h3 className="text-xs text-gray-400 mb-1 uppercase font-semibold tracking-wider">Geo-Location (AI Inference)</h3>
            <div className="flex items-start gap-2 mt-1">
              <svg className="w-4 h-4 text-gray-500 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" /></svg>
              <span className="text-sm font-medium text-gray-200">
                {report?.lokasi || "Menunggu data lokasi..."}
              </span>
            </div>
          </div>

          {/* Narasi */}
          <div>
            <h3 className="text-xs text-gray-400 mb-2 uppercase font-semibold tracking-wider">Insight Narasi (Gemini 2.0 Flash)</h3>
            <div className="bg-gray-800 p-4 rounded-md text-gray-200 text-sm leading-relaxed border border-gray-700 shadow-inner">
              {report?.narasi || "Model AI sedang mengumpulkan konteks sekuensial dari streaming video..."}
            </div>
          </div>
          
          {report?.timestamp && (
            <div className="flex justify-between items-center text-xs text-gray-500 pt-4 border-t border-gray-800">
              <span>Sync Time:</span>
              <span className="font-mono bg-gray-800 px-2 py-1 rounded text-gray-400">
                {new Date(report.timestamp * 1000).toLocaleTimeString()}
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
