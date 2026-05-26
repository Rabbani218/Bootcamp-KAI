"use client";

import dynamic from 'next/dynamic';
import { useState, useEffect } from 'react';
import axios from 'axios';
import { Youtube, Video, Upload, Activity, Radio } from 'lucide-react';

const VideoStream = dynamic(() => import('@/components/VideoStream'), { ssr: false });
const GeminiOverlay = dynamic(() => import('@/components/GeminiOverlay'), { ssr: false });

export default function Home() {
  let backendUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
  if (backendUrl.includes('hf.space') && backendUrl.startsWith('http://')) {
    backendUrl = backendUrl.replace('http://', 'https://');
  }
  const backendWsUrl = backendUrl.replace('http', 'ws') + '/api/ws/gemini';
  
  const [activeTab, setActiveTab] = useState<'youtube' | 'rtsp' | 'upload'>('youtube');
  const [youtubeUrl, setYoutubeUrl] = useState("https://www.youtube.com/watch?v=q7lvnYVuqNY");
  const [rtspUrl, setRtspUrl] = useState("");
  const [uploadProgress, setUploadProgress] = useState(0);
  const [isUpdating, setIsUpdating] = useState(false);
  const [healthInfo, setHealthInfo] = useState({ djka_connected: false, mqtt_connected: false });

  useEffect(() => {
    const fetchHealth = async () => {
      try {
        const res = await fetch(`${backendUrl}/api/health`);
        const data = await res.json();
        setHealthInfo({
          djka_connected: data.djka_connected || false,
          mqtt_connected: data.mqtt_connected || false
        });
      } catch (err) {}
    };
    fetchHealth();
    const iv = setInterval(fetchHealth, 10000);
    return () => clearInterval(iv);
  }, [backendUrl]);

  const handleUpdateUrl = async (e: React.FormEvent, mode: 'youtube' | 'rtsp') => {
    e.preventDefault();
    setIsUpdating(true);
    try {
      const payload = mode === 'youtube' 
        ? { mode, youtube_url: youtubeUrl } 
        : { mode, rtsp_url: rtspUrl };
        
      const res = await fetch(`${backendUrl}/api/set_url`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error("Gagal update URL");
    } catch (err) {
      console.error(err);
      alert("Gagal menyambungkan ke Backend.");
    }
    setIsUpdating(false);
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files || e.target.files.length === 0) return;
    const file = e.target.files[0];
    
    // Validasi < 50MB
    if (file.size > 50 * 1024 * 1024) {
      alert("File terlalu besar. Maksimal 50MB.");
      return;
    }

    const formData = new FormData();
    formData.append("file", file);

    setIsUpdating(true);
    setUploadProgress(0);

    try {
      await axios.post(`${backendUrl}/api/upload`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        onUploadProgress: (progressEvent) => {
          if (progressEvent.total) {
            const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total);
            setUploadProgress(percentCompleted);
          }
        }
      });
    } catch (err) {
      console.error("Upload error", err);
      alert("Gagal mengunggah video");
    }
    setIsUpdating(false);
  };

  return (
    <main className="min-h-screen bg-black text-gray-100 p-4 md:p-8 font-sans">
      <div className="max-w-7xl mx-auto space-y-6">
        
        {/* Header */}
        <header className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-gray-800 pb-6">
          <div>
            <h1 className="text-3xl font-bold bg-gradient-to-r from-blue-400 to-emerald-400 bg-clip-text text-transparent flex items-center gap-2">
              <Activity className="w-8 h-8 text-emerald-400" /> NusaRail Sentinel
            </h1>
            <p className="text-gray-400 mt-1">Enterprise-Grade Early Warning System (Multi-Source Input)</p>
          </div>
          
          <div className="flex flex-col sm:flex-row gap-4">
            <div className="flex items-center gap-3 bg-gray-900 border border-gray-800 rounded-lg px-4 py-2">
              <span className="relative flex h-3 w-3">
                <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${healthInfo.djka_connected ? 'bg-emerald-400' : 'bg-red-400'}`}></span>
                <span className={`relative inline-flex rounded-full h-3 w-3 ${healthInfo.djka_connected ? 'bg-emerald-500' : 'bg-red-500'}`}></span>
              </span>
              <span className="text-sm font-medium text-gray-300">DJKA Webhook: {healthInfo.djka_connected ? 'Connected' : 'Offline'}</span>
            </div>
            
            <div className="flex items-center gap-3 bg-gray-900 border border-gray-800 rounded-lg px-4 py-2">
              <span className="relative flex h-3 w-3">
                <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${healthInfo.mqtt_connected ? 'bg-emerald-400' : 'bg-red-400'}`}></span>
                <span className={`relative inline-flex rounded-full h-3 w-3 ${healthInfo.mqtt_connected ? 'bg-emerald-500' : 'bg-red-500'}`}></span>
              </span>
              <span className="text-sm font-medium text-gray-300">MQTT Signaling: {healthInfo.mqtt_connected ? 'Active' : 'Offline'}</span>
            </div>
          </div>
        </header>

        {/* Input Controls */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 shadow-xl">
          <div className="flex gap-4 border-b border-gray-700 pb-4 mb-4">
            <button 
              onClick={() => setActiveTab('youtube')}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition ${activeTab === 'youtube' ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-white'}`}
            >
              <Youtube className="w-5 h-5" /> YouTube Live
            </button>
            <button 
              onClick={() => setActiveTab('rtsp')}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition ${activeTab === 'rtsp' ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-white'}`}
            >
              <Radio className="w-5 h-5" /> RTSP CCTV
            </button>
            <button 
              onClick={() => setActiveTab('upload')}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition ${activeTab === 'upload' ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-white'}`}
            >
              <Upload className="w-5 h-5" /> Local Video
            </button>
          </div>

          {activeTab === 'youtube' && (
            <form onSubmit={(e) => handleUpdateUrl(e, 'youtube')} className="flex gap-2">
              <input 
                type="url" value={youtubeUrl} onChange={(e) => setYoutubeUrl(e.target.value)}
                className="flex-1 bg-gray-800 border border-gray-700 text-white rounded-md px-4 py-2 focus:outline-none focus:border-blue-500"
                placeholder="https://www.youtube.com/watch?v=..." required
              />
              <button type="submit" disabled={isUpdating} className="bg-blue-600 hover:bg-blue-700 text-white px-6 py-2 rounded-md font-medium transition disabled:opacity-50 min-w-[150px]">
                {isUpdating ? 'Loading...' : 'Stream YouTube'}
              </button>
            </form>
          )}

          {activeTab === 'rtsp' && (
            <form onSubmit={(e) => handleUpdateUrl(e, 'rtsp')} className="flex gap-2">
              <input 
                type="text" value={rtspUrl} onChange={(e) => setRtspUrl(e.target.value)}
                className="flex-1 bg-gray-800 border border-gray-700 text-white rounded-md px-4 py-2 focus:outline-none focus:border-blue-500"
                placeholder="rtsp://username:pass@192.168.1.100:554/stream" required
              />
              <button type="submit" disabled={isUpdating} className="bg-blue-600 hover:bg-blue-700 text-white px-6 py-2 rounded-md font-medium transition disabled:opacity-50 min-w-[150px]">
                {isUpdating ? 'Loading...' : 'Connect CCTV'}
              </button>
            </form>
          )}

          {activeTab === 'upload' && (
            <div className="flex items-center gap-4">
              <input 
                type="file" 
                accept="video/mp4,video/x-m4v,video/*"
                onChange={handleFileUpload}
                disabled={isUpdating}
                className="block w-full text-sm text-gray-400 file:mr-4 file:py-2 file:px-4 file:rounded-md file:border-0 file:text-sm file:font-semibold file:bg-blue-600 file:text-white hover:file:bg-blue-700 disabled:opacity-50"
              />
              {isUpdating && uploadProgress > 0 && (
                <div className="flex-1">
                  <div className="w-full bg-gray-700 rounded-full h-2.5">
                    <div className="bg-blue-600 h-2.5 rounded-full transition-all duration-300" style={{ width: `${uploadProgress}%` }}></div>
                  </div>
                  <p className="text-xs text-gray-400 mt-1">Uploading... {uploadProgress}%</p>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Main Content Area */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-4">
            <div className="bg-gray-900 border border-gray-800 p-1 rounded-xl shadow-2xl">
              <VideoStream backendUrl={backendUrl} mode={activeTab} streamKey={activeTab === 'youtube' ? youtubeUrl : (activeTab === 'rtsp' ? rtspUrl : 'upload')} isUpdating={isUpdating} />
            </div>
          </div>
          <div className="lg:col-span-1">
            <GeminiOverlay backendWsUrl={backendWsUrl} />
          </div>
        </div>
      </div>
    </main>
  );
}
