"use client";

import { useEffect, useRef, useState } from 'react';

interface VideoStreamProps {
  backendUrl: string;
  streamKey?: string;
  mode?: string;
  isUpdating?: boolean;
}

export default function VideoStream({ backendUrl, streamKey, mode, isUpdating }: VideoStreamProps) {
  const [error, setError] = useState(false);
  const [streamUrl, setStreamUrl] = useState(`${backendUrl}/api/stream`);
  const [retryCount, setRetryCount] = useState(0);
  const [isStreamLoading, setIsStreamLoading] = useState(true);
  const imgRef = useRef<HTMLImageElement>(null);

  useEffect(() => {
    // Reset saat base url atau streamKey (url youtube) diganti
    if (isUpdating) return; // Jangan restart kalau masih nunggu request POST URL selesai
    setError(false);
    setIsStreamLoading(true);
    // Tambahkan parameter unik agar cache tertembus
    setStreamUrl(`${backendUrl}/api/stream?k=${encodeURIComponent(streamKey || '')}&m=${mode || ''}&t=${Date.now()}`);
  }, [backendUrl, streamKey, mode, isUpdating]);

  const handleImageError = () => {
    console.warn("MJPEG stream error. Mencoba auto-reconnect...");
    setError(true);
    setIsStreamLoading(false);
    
    // Auto reconnect dengan interval bertingkat (Exponential backoff)
    const delay = Math.min(2000 + (retryCount * 1000), 10000); // max 10s
    setTimeout(() => {
      setRetryCount(prev => prev + 1);
      setIsStreamLoading(true); // Tampilkan spinner lagi selagi mencoba
      setStreamUrl(`${backendUrl}/api/stream?retry=${Date.now()}`);
      setError(false);
    }, delay);
  };

  const handleImageLoad = () => {
    setIsStreamLoading(false); // Frame berhasil diterima!
    if (retryCount > 0) {
      console.log("Stream berhasil terkoneksi kembali.");
      setRetryCount(0);
    }
  };

  return (
    <div className="relative w-full aspect-video bg-gray-900 rounded-lg overflow-hidden flex items-center justify-center border border-gray-800">
      
      {/* Loading Spinner overlay */}
      {isStreamLoading && !error && (
        <div className="absolute inset-0 bg-gray-900 flex flex-col items-center justify-center z-10">
          <div className="w-12 h-12 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mb-4"></div>
          <p className="text-blue-400 font-medium animate-pulse">Menghubungkan ke Kamera AI...</p>
        </div>
      )}

      {/* Strict Standard HTML Image */}
      {!error ? (
        <img
          ref={imgRef}
          src={streamUrl}
          alt="Live Stream"
          className={`w-full h-full object-contain transition-opacity duration-300 ${isStreamLoading ? 'opacity-0' : 'opacity-100'}`}
          onError={handleImageError}
          onLoad={handleImageLoad}
        />
      ) : (
        <div className="text-gray-400 flex flex-col items-center animate-pulse z-0">
          <svg className="w-12 h-12 mb-2 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
          </svg>
          <p>Koneksi stream terputus. Mencoba reconnect...</p>
        </div>
      )}

      <div className="absolute top-4 left-4 bg-black/60 px-3 py-1 rounded-md flex items-center gap-2 text-sm text-white backdrop-blur-sm z-20">
        <span className={`w-2 h-2 rounded-full ${error ? 'bg-yellow-500' : 'bg-red-500 animate-pulse'}`}></span>
        {error ? 'RECONNECTING' : (isStreamLoading ? 'CONNECTING...' : 'LIVE')}
      </div>
    </div>
  );
}
