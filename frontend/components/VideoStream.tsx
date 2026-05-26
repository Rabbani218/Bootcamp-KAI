"use client";

import { useEffect, useRef, useState } from 'react';

interface VideoStreamProps {
  backendUrl: string;
}

export default function VideoStream({ backendUrl }: VideoStreamProps) {
  const [error, setError] = useState(false);
  const [streamUrl, setStreamUrl] = useState(`${backendUrl}/api/stream`);
  const [retryCount, setRetryCount] = useState(0);
  const imgRef = useRef<HTMLImageElement>(null);

  useEffect(() => {
    // Reset saat base url ganti
    setError(false);
    setStreamUrl(`${backendUrl}/api/stream?t=${Date.now()}`);
  }, [backendUrl]);

  const handleImageError = () => {
    console.warn("MJPEG stream error. Mencoba auto-reconnect...");
    setError(true);
    
    // Auto reconnect dengan interval bertingkat
    const delay = Math.min(2000 + (retryCount * 1000), 10000); // max 10s
    setTimeout(() => {
      setRetryCount(prev => prev + 1);
      setStreamUrl(`${backendUrl}/api/stream?retry=${Date.now()}`);
      setError(false);
    }, delay);
  };

  const handleImageLoad = () => {
    if (retryCount > 0) {
      console.log("Stream berhasil terkoneksi kembali.");
      setRetryCount(0);
    }
  };

  return (
    <div className="relative w-full aspect-video bg-gray-900 rounded-lg overflow-hidden flex items-center justify-center border border-gray-800">
      {!error ? (
        <img
          ref={imgRef}
          src={streamUrl}
          alt="Live Stream"
          className="w-full h-full object-contain"
          onError={handleImageError}
          onLoad={handleImageLoad}
        />
      ) : (
        <div className="text-gray-400 flex flex-col items-center animate-pulse">
          <svg className="w-12 h-12 mb-2 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
          </svg>
          <p>Koneksi stream terputus. Mencoba reconnect...</p>
        </div>
      )}
      <div className="absolute top-4 left-4 bg-black/60 px-3 py-1 rounded-md flex items-center gap-2 text-sm text-white backdrop-blur-sm">
        <span className={`w-2 h-2 rounded-full ${error ? 'bg-yellow-500' : 'bg-red-500 animate-pulse'}`}></span>
        {error ? 'RECONNECTING' : 'LIVE'}
      </div>
    </div>
  );
}
