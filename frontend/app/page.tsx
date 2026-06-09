"use client";

import dynamic from 'next/dynamic';
import { useState, useEffect } from 'react';
import axios from 'axios';
import { Youtube, Video, Upload, Activity, Radio, BarChart3, Settings, MonitorPlay, Play } from 'lucide-react';

const VideoStream = dynamic(() => import('@/components/VideoStream'), { ssr: false });
const GeminiOverlay = dynamic(() => import('@/components/GeminiOverlay'), { ssr: false });
const AnalyticsDashboard = dynamic(() => import('@/components/AnalyticsDashboard'), { ssr: false });
const AdvancedSettings = dynamic(() => import('@/components/AdvancedSettings'), { ssr: false });

export default function Home() {
  let backendUrl = process.env.NEXT_PUBLIC_API_URL || process.env.NEXT_PUBLIC_BACKEND_URL || 'https://alex-universe11-bootcamp-ubsi-kai.hf.space';
  if (backendUrl.includes('localhost') && typeof window !== 'undefined' && window.location.hostname !== 'localhost') {
    backendUrl = 'https://alex-universe11-bootcamp-ubsi-kai.hf.space';
  }
  if (backendUrl.includes('hf.space') && backendUrl.startsWith('http://')) {
    backendUrl = backendUrl.replace('http://', 'https://');
  }
  const backendWsUrl = backendUrl.replace('http', 'ws') + '/ws/telemetry';
  
  const [mainTab, setMainTab] = useState<'monitoring' | 'analytics' | 'settings'>('monitoring');
  const [sourceTab, setSourceTab] = useState<'demo' | 'youtube' | 'rtsp' | 'upload'>('demo');
  
  const [youtubeUrl, setYoutubeUrl] = useState("https://www.youtube.com/watch?v=q7lvnYVuqNY");
  const [rtspUrl, setRtspUrl] = useState("");
  const [uploadProgress, setUploadProgress] = useState(0);
  const [isUpdating, setIsUpdating] = useState(false);
  const [healthInfo, setHealthInfo] = useState({ djka_connected: false, mqtt_connected: false });
  const [isDanger, setIsDanger] = useState(false);
  const [demoVideoDanger, setDemoVideoDanger] = useState(false);

  // CRITICAL FIX 11: Real-time Sync & Cold Start Resiliency
  const [wsStatus, setWsStatus] = useState<'connected' | 'disconnected'>('disconnected');
  const [isBackendWakingUp, setIsBackendWakingUp] = useState(false);
  const [streamActive, setStreamActive] = useState(false);

  useEffect(() => {
    const fetchHealthAndStatus = async () => {
      try {
        const [healthRes, statusRes] = await Promise.all([
          fetch(`${backendUrl}/health`).catch(() => null),
          fetch(`${backendUrl}/`).catch(() => null)
        ]);

        if (!healthRes && !statusRes) {
          setIsBackendWakingUp(true);
        } else {
          setIsBackendWakingUp(false);
        }

        if (healthRes) {
          const healthData = await healthRes.json();
          setHealthInfo({
            djka_connected: healthData.djka_connected || false,
            mqtt_connected: healthData.mqtt_connected || false
          });
        }

        if (statusRes) {
          const statusData = await statusRes.json();
          setIsDanger(statusData.danger || false);
          
          // CRITICAL FIX 11: Sinkronisasi UI dan Backend
          if (statusData.stream_active === false && streamActive === true) {
            console.log("[Sync] Backend idle, reseting UI streamActive state.");
            setStreamActive(false);
          } else if (statusData.stream_active === true && streamActive === false) {
            setStreamActive(true);
          }
        }
      } catch (err) {
        setIsBackendWakingUp(true);
      }
    };

    fetchHealthAndStatus();
    // CRITICAL FIX 11: Polling setiap 5 detik
    const iv = setInterval(fetchHealthAndStatus, 5000);
    return () => clearInterval(iv);
  }, [backendUrl]);

  const handleUpdateUrl = async (e: React.FormEvent, mode: 'youtube' | 'rtsp') => {
    e.preventDefault();
    setIsUpdating(true);
    try {
      let res;
      if (mode === 'youtube') {
        const formData = new URLSearchParams({ url: youtubeUrl });
        res = await fetch(`${backendUrl}/start/youtube`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
          body: formData
        });
      } else {
        res = { ok: true };
      }
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
    if (file.size > 50 * 1024 * 1024) {
      alert("File terlalu besar. Maksimal 50MB.");
      return;
    }
    const formData = new FormData();
    formData.append("file", file);
    setIsUpdating(true);
    setUploadProgress(0);
    try {
      // CRITICAL FIX 12: Large File Chunked Upload Support (Direct to HF, bypass Vercel)
      setUploadProgress(30);
      const response = await fetch(`${backendUrl}/start/upload`, {
        method: 'POST',
        body: formData
        // DILARANG SET Content-Type: multipart/form-data secara manual!
        // Browser akan membuatnya otomatis beserta boundary
      });
      if (!response.ok) throw new Error("Upload failed");
      setUploadProgress(100);
    } catch (err) {
      console.error("Upload error", err);
      alert("Gagal mengunggah video");
    }
    setIsUpdating(false);
  };

  return (
    <main className={`min-h-screen p-4 md:p-8 font-sans transition-colors duration-500 ${isDanger ? 'bg-red-950/80 animate-pulse' : 'bg-black text-gray-100'}`}>
      <div className="max-w-7xl mx-auto space-y-6">
        
        {/* Header */}
        <header className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-gray-800 pb-6">
          <div>
            <h1 className="text-3xl font-bold flex items-center gap-2">
              <Activity className={`w-8 h-8 ${isDanger ? 'text-red-500' : 'text-emerald-400'}`} /> 
              <span className={isDanger ? 'text-red-500' : 'bg-gradient-to-r from-blue-400 to-emerald-400 bg-clip-text text-transparent'}>
                NusaRail Sentinel
              </span>
            </h1>
            <p className="text-gray-400 mt-1">
              Enterprise-Grade Early Warning System (Phase 4 Tactical Control)
            </p>
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

        {/* Main Navigation */}
        <div className="flex gap-4 border-b border-gray-800 pb-2">
          <button onClick={() => setMainTab('monitoring')} className={`flex items-center gap-2 px-4 py-2 font-medium transition-colors border-b-2 ${mainTab === 'monitoring' ? 'border-blue-500 text-blue-400' : 'border-transparent text-gray-500 hover:text-gray-300'}`}>
            <MonitorPlay className="w-5 h-5" /> Live Monitoring
          </button>
          <button onClick={() => setMainTab('analytics')} className={`flex items-center gap-2 px-4 py-2 font-medium transition-colors border-b-2 ${mainTab === 'analytics' ? 'border-blue-500 text-blue-400' : 'border-transparent text-gray-500 hover:text-gray-300'}`}>
            <BarChart3 className="w-5 h-5" /> Analytics & Logs
          </button>
          <button onClick={() => setMainTab('settings')} className={`flex items-center gap-2 px-4 py-2 font-medium transition-colors border-b-2 ${mainTab === 'settings' ? 'border-blue-500 text-blue-400' : 'border-transparent text-gray-500 hover:text-gray-300'}`}>
            <Settings className="w-5 h-5" /> Advanced Settings
          </button>
        </div>

        {/* Tab Content: Analytics & Logs */}
        {mainTab === 'analytics' && <AnalyticsDashboard backendUrl={backendUrl} />}

        {/* Tab Content: Advanced Settings */}
        {mainTab === 'settings' && <AdvancedSettings backendUrl={backendUrl} />}

        {/* Tab Content: Live Monitoring */}
        {mainTab === 'monitoring' && (
          <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
            {/* Input Controls */}
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 shadow-xl">
              <div className="flex flex-wrap gap-4 border-b border-gray-700 pb-4 mb-4">
                <button onClick={() => setSourceTab('demo')} className={`flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition ${sourceTab === 'demo' ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-900/50' : 'text-gray-400 hover:text-white bg-gray-800'}`}>
                  <Play className="w-5 h-5 text-indigo-300" /> Mode Simulasi (Canned Demo)
                </button>
                {/* DEBUG LOCKDOWN: Matikan sementara YouTube & Local Video */}
                <button disabled onClick={() => {}} className="flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition opacity-50 cursor-not-allowed text-gray-500">
                  <Youtube className="w-5 h-5" /> YouTube Live <span className="text-[10px] text-red-400 ml-1">(Disabled for Testing)</span>
                </button>
                <button onClick={() => setSourceTab('rtsp')} className={`flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition ${sourceTab === 'rtsp' ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-white'}`}>
                  <Radio className="w-5 h-5" /> RTSP CCTV
                </button>
                {/* DEBUG LOCKDOWN: Matikan sementara YouTube & Local Video */}
                <button disabled onClick={() => {}} className="flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition opacity-50 cursor-not-allowed text-gray-500">
                  <Upload className="w-5 h-5" /> Local Video <span className="text-[10px] text-red-400 ml-1">(Disabled for Testing)</span>
                </button>
              </div>

              {sourceTab === 'demo' && (
                <div className="flex items-center justify-between bg-indigo-950/30 border border-indigo-900/50 rounded-lg p-4 mb-4">
                  <div>
                    <h3 className="text-indigo-300 font-medium flex items-center gap-2">
                      <Play className="w-4 h-4" /> Mode Pra-Render Aktif
                    </h3>
                    <p className="text-sm text-gray-400 mt-1">Video presentasi ini berjalan 100% secara lokal dengan Zero-Lag dan anotasi AI yang sudah terkalibrasi.</p>
                  </div>
                </div>
              )}

              {sourceTab === 'youtube' && (
                <form onSubmit={(e) => handleUpdateUrl(e, 'youtube')} className="flex gap-2">
                  <input type="url" value={youtubeUrl} onChange={(e) => setYoutubeUrl(e.target.value)} className="flex-1 bg-gray-800 border border-gray-700 text-white rounded-md px-4 py-2 focus:outline-none focus:border-blue-500" placeholder="https://www.youtube.com/watch?v=..." required />
                  <button type="submit" disabled={isUpdating} className="bg-blue-600 hover:bg-blue-700 text-white px-6 py-2 rounded-md font-medium transition disabled:opacity-50 min-w-[150px]">{isUpdating ? 'Loading...' : 'Stream YouTube'}</button>
                </form>
              )}

              {sourceTab === 'rtsp' && (
                <form onSubmit={(e) => handleUpdateUrl(e, 'rtsp')} className="flex gap-2">
                  <input type="text" value={rtspUrl} onChange={(e) => setRtspUrl(e.target.value)} className="flex-1 bg-gray-800 border border-gray-700 text-white rounded-md px-4 py-2 focus:outline-none focus:border-blue-500" placeholder="rtsp://username:pass@192.168.1.100:554/stream" required />
                  <button type="submit" disabled={isUpdating} className="bg-blue-600 hover:bg-blue-700 text-white px-6 py-2 rounded-md font-medium transition disabled:opacity-50 min-w-[150px]">{isUpdating ? 'Loading...' : 'Connect CCTV'}</button>
                </form>
              )}

              {sourceTab === 'upload' && (
                <div className="flex items-center gap-4">
                  {/* DEBUG LOCKDOWN: Matikan sementara Local Video */}
                  <input type="file" accept="video/mp4,video/x-m4v,video/*" onChange={handleFileUpload} disabled={true} className="block w-full text-sm text-gray-400 file:mr-4 file:py-2 file:px-4 file:rounded-md file:border-0 file:text-sm file:font-semibold file:bg-blue-600 file:text-white hover:file:bg-blue-700 opacity-50 cursor-not-allowed" />
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
                <div className="bg-gray-900 border border-gray-800 p-1 rounded-xl shadow-2xl overflow-hidden flex justify-center items-center relative aspect-video">
                  {sourceTab === 'demo' ? (
                    <video 
                      src="/demo_nusarail_final.mp4" 
                      controls 
                      autoPlay 
                      loop 
                      muted 
                      playsInline 
                      className="w-full h-full bg-black rounded-lg object-contain"
                      onTimeUpdate={(e) => {
                        const time = (e.target as HTMLVideoElement).currentTime;
                        setDemoVideoDanger(time > 5.0);
                      }}
                    />
                  ) : (
                    <VideoStream 
                      backendUrl={backendUrl} 
                      mode={sourceTab as 'youtube' | 'rtsp' | 'upload'} 
                      streamKey={sourceTab === 'youtube' ? youtubeUrl : (sourceTab === 'rtsp' ? rtspUrl : 'upload')} 
                      isUpdating={isUpdating}
                      wsStatus={wsStatus} 
                    />
                  )}
                </div>
              </div>
              <div className="lg:col-span-1">
                <GeminiOverlay 
                  backendWsUrl={backendWsUrl} 
                  isBackendWakingUp={isBackendWakingUp}
                  onWsStatusChange={(status) => setWsStatus(status)}
                  isDemoMode={sourceTab === 'demo'}
                  demoVideoDanger={demoVideoDanger}
                />
              </div>
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
