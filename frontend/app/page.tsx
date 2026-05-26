"use client";

import dynamic from 'next/dynamic';
import { useState } from 'react';

const VideoStream = dynamic(() => import('@/components/VideoStream'), { ssr: false });
const GeminiOverlay = dynamic(() => import('@/components/GeminiOverlay'), { ssr: false });

export default function Home() {
  let backendUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
  if (backendUrl.includes('hf.space') && backendUrl.startsWith('http://')) {
    backendUrl = backendUrl.replace('http://', 'https://');
  }
  const backendWsUrl = backendUrl.replace('http', 'ws') + '/api/ws/gemini';
  
  const [targetUrl, setTargetUrl] = useState("https://www.youtube.com/watch?v=q7lvnYVuqNY");
  const [isUpdating, setIsUpdating] = useState(false);

  const handleUpdateUrl = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsUpdating(true);
    try {
      const res = await fetch(`${backendUrl}/api/set_url`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ youtube_url: targetUrl })
      });
      if (!res.ok) throw new Error("Gagal update URL");
    } catch (err) {
      console.error(err);
      alert("Gagal memperbarui URL Stream ke Backend.");
    }
    setIsUpdating(false);
  };

  return (
    <main className="min-h-screen bg-black text-gray-100 p-4 md:p-8 font-sans">
      <div className="max-w-7xl mx-auto space-y-6">
        
        {/* Header */}
        <header className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-gray-800 pb-6">
          <div>
            <h1 className="text-3xl font-bold bg-gradient-to-r from-blue-400 to-emerald-400 bg-clip-text text-transparent">
              NusaRail Sentinel
            </h1>
            <p className="text-gray-400 mt-1">Sistem Peringatan Dini Perlintasan Kereta Api Real-time (Enterprise Hardened)</p>
          </div>
          
          <div className="flex items-center gap-3 bg-gray-900 border border-gray-800 rounded-lg px-4 py-2">
            <span className="relative flex h-3 w-3">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-3 w-3 bg-emerald-500"></span>
            </span>
            <span className="text-sm font-medium text-gray-300">Sistem Aktif (Zero-Lag)</span>
          </div>
        </header>

        {/* Input Form URL */}
        <form onSubmit={handleUpdateUrl} className="flex gap-2">
          <input 
            type="url" 
            value={targetUrl}
            onChange={(e) => setTargetUrl(e.target.value)}
            className="flex-1 bg-gray-900 border border-gray-700 text-white rounded-md px-4 py-2 focus:outline-none focus:border-blue-500"
            placeholder="Masukkan URL YouTube Live Stream..."
            required
          />
          <button 
            type="submit" 
            disabled={isUpdating}
            className="bg-blue-600 hover:bg-blue-700 text-white px-6 py-2 rounded-md font-medium transition disabled:opacity-50"
          >
            {isUpdating ? 'Menyambungkan...' : 'Pantau Stream'}
          </button>
        </form>

        {/* Main Content Area */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          
          {/* Video Stream Column */}
          <div className="lg:col-span-2 space-y-4">
            <div className="bg-gray-900 border border-gray-800 p-1 rounded-xl shadow-2xl">
              <VideoStream backendUrl={backendUrl} streamKey={targetUrl} isUpdating={isUpdating} />
            </div>
            
            <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 flex items-start gap-4">
              <div className="bg-blue-900/30 p-2 rounded-lg text-blue-400">
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
              <div>
                <h3 className="font-medium text-gray-200">Hardware & AI Engine</h3>
                <p className="text-sm text-gray-400 mt-1">
                  YOLOv8 ONNX (CPU) with Stationary Object Tracking + Gemini 2.0 Flash (JSON Fallback) + MJPEG Auto-Reconnect.
                </p>
              </div>
            </div>
          </div>

          {/* Sidebar / Gemini AI Column */}
          <div className="lg:col-span-1">
            <GeminiOverlay backendWsUrl={backendWsUrl} />
          </div>
          
        </div>
        
      </div>
    </main>
  );
}
