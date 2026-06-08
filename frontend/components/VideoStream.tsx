"use client";

import React, { useState, useEffect, useRef } from "react";

interface VideoStreamProps {
  backendUrl: string;
  mode?: string;
  streamKey?: string;
  isUpdating?: boolean;
}

/**
 * VideoStream Component
 * =====================
 * Renders the MJPEG video feed from the FastAPI backend using a standard
 * HTML <img> tag. MJPEG streams are natively supported by all modern browsers
 * via the 'multipart/x-mixed-replace' content type, requiring zero JavaScript
 * decoding overhead.
 */
const VideoStream: React.FC<VideoStreamProps> = ({ backendUrl, mode, streamKey, isUpdating }) => {
  const [isLoading, setIsLoading] = useState(true);
  const [hasError, setHasError] = useState(false);
  const [retryCount, setRetryCount] = useState(0);
  const imgRef = useRef<HTMLImageElement>(null);

  // CRITICAL FIX 10: Cross-Origin Unblocking & Cache Busting
  const streamUrl = `${backendUrl}/video_feed?t=${Date.now()}`;

  useEffect(() => {
    // Auto-retry on error (handles Hugging Face cold starts)
    if (hasError) {
      const timer = setTimeout(() => {
        setHasError(false);
        setIsLoading(true);
        setRetryCount((prev) => prev + 1);
      }, 5000);
      return () => clearTimeout(timer);
    }
  }, [hasError]);

  return (
    <div className="relative w-full aspect-video bg-gray-900 rounded-xl overflow-hidden border border-gray-700/50 shadow-2xl">
      {/* Loading Overlay */}
      {isLoading && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-gray-900/90 z-10">
          <div className="w-12 h-12 border-4 border-cyan-500 border-t-transparent rounded-full animate-spin mb-4" />
          <p className="text-cyan-400 text-sm font-mono">
            Menghubungkan ke NusaRail Vision Engine...
          </p>
          {retryCount > 0 && (
            <p className="text-gray-500 text-xs mt-1">
              Percobaan ke-{retryCount + 1} (Cold Start ~60s)
            </p>
          )}
        </div>
      )}

      {/* Error Overlay */}
      {hasError && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-red-950/80 z-10">
          <div className="text-red-400 text-4xl mb-3">⚠️</div>
          <p className="text-red-300 text-sm font-mono">
            Stream terputus. Menghubungkan ulang...
          </p>
        </div>
      )}

      {/* MJPEG Stream via <img> tag */}
      <img
        ref={imgRef}
        key={`${streamKey}-${retryCount}`} // Force remount on retry or URL change
        src={streamUrl}
        alt="NusaRail MJPEG Live Feed"
        className="w-full h-full object-contain"
        onLoad={() => setIsLoading(false)}
        onError={() => {
          setIsLoading(false);
          setHasError(true);
        }}
      />

      {/* Live Badge */}
      {!isLoading && !hasError && (
        <div className="absolute top-3 left-3 flex items-center gap-2 bg-red-600/90 px-3 py-1 rounded-full backdrop-blur-sm">
          <div className="w-2 h-2 bg-white rounded-full animate-pulse" />
          <span className="text-white text-xs font-bold tracking-wider">
            LIVE
          </span>
        </div>
      )}
    </div>
  );
};

export default VideoStream;
