import React, { useState } from "react";
import Head from "next/head";
import VideoStream from "../components/VideoStream";
import TelemetryPanel from "../components/TelemetryPanel";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "https://alex-universe11-bootcamp-ubsi-kai.hf.space";

/**
 * NusaRail Vision System - Main Dashboard
 * =========================================
 * Dark-mode industrial dashboard optimized for Vercel Edge Network.
 * Displays MJPEG video feed alongside real-time AI telemetry panels.
 */
export default function Home() {
  const [inputUrl, setInputUrl] = useState("");
  const [isStarting, setIsStarting] = useState(false);
  const [streamActive, setStreamActive] = useState(false);
  const [statusMessage, setStatusMessage] = useState("");

  const handleStartYouTube = async () => {
    if (!inputUrl.trim()) return;
    setIsStarting(true);
    setStatusMessage("Menghubungkan ke YouTube...");

    try {
      const res = await fetch(`${BACKEND_URL}/start/youtube`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ url: inputUrl }),
      });
      const data = await res.json();

      if (res.ok) {
        setStreamActive(true);
        setStatusMessage(`Streaming: ${data.source}`);
      } else {
        setStatusMessage(`Error: ${data.error || "Gagal memulai stream."}`);
      }
    } catch (e) {
      setStatusMessage("Error: Tidak dapat terhubung ke backend.");
    } finally {
      setIsStarting(false);
    }
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setIsStarting(true);
    setStatusMessage(`Mengunggah: ${file.name}...`);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch(`${BACKEND_URL}/start/upload`, {
        method: "POST",
        body: formData,
      });
      const data = await res.json();

      if (res.ok) {
        setStreamActive(true);
        setStatusMessage(`Streaming: ${data.filename}`);
      } else {
        setStatusMessage(`Error: ${data.error || "Gagal memproses video."}`);
      }
    } catch (e) {
      setStatusMessage("Error: Tidak dapat terhubung ke backend.");
    } finally {
      setIsStarting(false);
    }
  };

  const handleStop = async () => {
    try {
      await fetch(`${BACKEND_URL}/stop`, { method: "POST" });
      setStreamActive(false);
      setStatusMessage("Stream dihentikan.");
    } catch (e) {
      setStatusMessage("Error: Gagal menghentikan stream.");
    }
  };

  return (
    <>
      <Head>
        <title>NusaRail Vision System | Sistem Peringatan Dini Perlintasan KA</title>
        <meta
          name="description"
          content="Sistem peringatan dini perlintasan kereta api berbasis YOLOv8 dan Gemini 1.5 Pro untuk deteksi kendaraan mogok secara real-time."
        />
        <link
          href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Inter:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </Head>

      <div className="min-h-screen bg-gradient-to-br from-gray-950 via-gray-900 to-slate-950 text-white font-['Inter']">
        {/* Header */}
        <header className="border-b border-gray-800/50 bg-gray-950/80 backdrop-blur-md sticky top-0 z-50">
          <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-gradient-to-br from-cyan-500 to-blue-600 rounded-lg flex items-center justify-center text-lg font-bold shadow-lg shadow-cyan-500/20">
                🚆
              </div>
              <div>
                <h1 className="text-lg font-bold tracking-tight bg-gradient-to-r from-cyan-400 to-blue-400 bg-clip-text text-transparent">
                  NusaRail Vision System
                </h1>
                <p className="text-xs text-gray-500 font-mono">
                  YOLOv8 + ByteTrack + Gemini 1.5 Pro
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2">
              {streamActive ? (
                <div className="flex items-center gap-2 px-3 py-1.5 bg-green-950/50 border border-green-500/30 rounded-full">
                  <div className="w-2 h-2 bg-green-400 rounded-full animate-pulse" />
                  <span className="text-green-400 text-xs font-mono">ACTIVE</span>
                </div>
              ) : (
                <div className="flex items-center gap-2 px-3 py-1.5 bg-gray-800/50 border border-gray-600/30 rounded-full">
                  <div className="w-2 h-2 bg-gray-500 rounded-full" />
                  <span className="text-gray-400 text-xs font-mono">IDLE</span>
                </div>
              )}
            </div>
          </div>
        </header>

        {/* Main Content */}
        <main className="max-w-7xl mx-auto px-4 py-6">
          {/* Input Controls */}
          <div className="bg-gray-800/40 backdrop-blur-sm rounded-xl p-4 mb-6 border border-gray-700/30">
            <div className="flex flex-col md:flex-row gap-3">
              {/* YouTube URL Input */}
              <div className="flex-1 flex gap-2">
                <input
                  type="text"
                  value={inputUrl}
                  onChange={(e) => setInputUrl(e.target.value)}
                  placeholder="Masukkan URL YouTube CCTV Perlintasan..."
                  className="flex-1 bg-gray-900/80 border border-gray-600/50 rounded-lg px-4 py-2.5 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-cyan-500/50 focus:ring-1 focus:ring-cyan-500/20 font-mono transition-all"
                />
                <button
                  onClick={handleStartYouTube}
                  disabled={isStarting || !inputUrl.trim()}
                  className="px-5 py-2.5 bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 disabled:from-gray-600 disabled:to-gray-700 rounded-lg text-sm font-semibold transition-all shadow-lg shadow-cyan-500/20 disabled:shadow-none"
                >
                  {isStarting ? "⏳" : "▶ Mulai"}
                </button>
              </div>

              {/* File Upload */}
              <label className="px-5 py-2.5 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm font-semibold cursor-pointer text-center transition-all border border-gray-600/50">
                📁 Upload Video
                <input
                  type="file"
                  accept="video/*"
                  onChange={handleUpload}
                  className="hidden"
                />
              </label>

              {/* Stop Button */}
              {streamActive && (
                <button
                  onClick={handleStop}
                  className="px-5 py-2.5 bg-red-600/80 hover:bg-red-500 rounded-lg text-sm font-semibold transition-all"
                >
                  ⏹ Stop
                </button>
              )}
            </div>

            {statusMessage && (
              <p className="text-xs text-gray-400 font-mono mt-2">
                ↳ {statusMessage}
              </p>
            )}
          </div>

          {/* Dashboard Grid */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Video Feed - 2 columns */}
            <div className="lg:col-span-2">
              <VideoStream backendUrl={BACKEND_URL} />
            </div>

            {/* Telemetry Sidebar - 1 column */}
            <div className="lg:col-span-1">
              <TelemetryPanel backendUrl={BACKEND_URL} />
            </div>
          </div>

          {/* Footer */}
          <footer className="mt-8 py-4 border-t border-gray-800/30 text-center">
            <p className="text-xs text-gray-600 font-mono">
              NusaRail Vision System v2.0 • Muhammad Abdurrahman Rabbani (15240969) • Universitas Bina Sarana Informatika
            </p>
          </footer>
        </main>
      </div>
    </>
  );
}
