'use client';

import React, { useRef, useEffect, useState, useCallback } from 'react';
import { Upload, Square, Video, Wifi, WifiOff, Youtube, Loader2 } from 'lucide-react';
import { useVideoCapture } from '@/hooks/useVideoCapture';
import type { AnalyzeFrameResponse } from '@/lib/types';
import { CLASS_COLORS } from '@/lib/constants';
import { resolveYouTubeUrl } from '@/lib/api';

interface VideoCaptureProps {
  onFrameAnalyzed?: (response: AnalyzeFrameResponse) => void;
  onError?: (error: string) => void;
  threshold?: number;
}

/** Draw bounding-box overlays onto a canvas, matching displayed video size */
function drawOverlays(
  canvas: HTMLCanvasElement,
  video: HTMLVideoElement,
  detections: AnalyzeFrameResponse['detections']
) {
  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  // Match canvas to rendered video size
  const rect = video.getBoundingClientRect();
  canvas.width  = rect.width;
  canvas.height = rect.height;

  // Scale factors from native video resolution → displayed size
  const scaleX = rect.width  / (video.videoWidth  || 1);
  const scaleY = rect.height / (video.videoHeight || 1);

  ctx.clearRect(0, 0, canvas.width, canvas.height);

  detections.forEach((det) => {
    const x = det.bbox.x1 * scaleX;
    const y = det.bbox.y1 * scaleY;
    const w = (det.bbox.x2 - det.bbox.x1) * scaleX;
    const h = (det.bbox.y2 - det.bbox.y1) * scaleY;

    const color = det.is_stationary
      ? '#ff2d55'
      : (CLASS_COLORS[det.class_name] ?? '#00f5ff');

    // Box
    ctx.strokeStyle = color;
    ctx.lineWidth   = det.is_stationary ? 2.5 : 1.5;
    ctx.shadowColor = color;
    ctx.shadowBlur  = 8;
    ctx.strokeRect(x, y, w, h);

    // Label background
    const label = `${det.class_name} ${(det.confidence * 100).toFixed(0)}%`;
    ctx.font = 'bold 11px JetBrains Mono, monospace';
    const textW = ctx.measureText(label).width + 10;
    ctx.fillStyle = color + 'cc';
    ctx.fillRect(x, y - 20, textW, 20);

    // Label text
    ctx.fillStyle = '#fff';
    ctx.shadowBlur = 0;
    ctx.fillText(label, x + 5, y - 5);

    // Stationary duration badge
    if (det.is_stationary && det.stationary_duration_ms > 0) {
      const dur = `⏱ ${(det.stationary_duration_ms / 1000).toFixed(1)}s`;
      ctx.fillStyle = '#ff2d55cc';
      const dw = ctx.measureText(dur).width + 10;
      ctx.fillRect(x, y + h, dw, 18);
      ctx.fillStyle = '#fff';
      ctx.fillText(dur, x + 5, y + h + 13);
    }
  });
}

export const VideoCapture: React.FC<VideoCaptureProps> = ({
  onFrameAnalyzed,
  onError,
  threshold = 0.5,
}) => {
  const fileInputRef  = useRef<HTMLInputElement>(null);
  const overlayRef    = useRef<HTMLCanvasElement>(null);
  const containerRef  = useRef<HTMLDivElement>(null);
  const [lastAnalysis, setLastAnalysis] = useState<AnalyzeFrameResponse | null>(null);
  const [fps, setFps]   = useState(0);
  const [ytUrl, setYtUrl] = useState('');
  const [isResolving, setIsResolving] = useState(false);
  const fpsCountRef     = useRef(0);

  const handleAnalyzed = useCallback((response: AnalyzeFrameResponse) => {
    setLastAnalysis(response);
    fpsCountRef.current += 1;
    onFrameAnalyzed?.(response);
  }, [onFrameAnalyzed]);

  const { videoRef, canvasRef, isCapturing, loadVideoFile, loadVideoUrl, startCapture, stopCapture } =
    useVideoCapture({
      onFrameAnalyzed: handleAnalyzed,
      onError: (e) => onError?.(e.message),
      threshold,
    });

  // Draw overlays when analysis updates
  useEffect(() => {
    if (!lastAnalysis || !overlayRef.current || !videoRef.current) return;
    drawOverlays(overlayRef.current, videoRef.current, lastAnalysis.detections);
  }, [lastAnalysis]);

  // FPS counter
  useEffect(() => {
    const id = setInterval(() => {
      setFps(fpsCountRef.current);
      fpsCountRef.current = 0;
    }, 1000);
    return () => clearInterval(id);
  }, []);

  const handleFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.type.startsWith('video/')) { onError?.('File harus berupa video'); return; }
    loadVideoFile(file);
    setTimeout(startCapture, 600);
  };

  return (
    <div className="flex flex-col gap-4">
      {/* Upload & YouTube Actions */}
      <div className="flex flex-col gap-3">
        <div>
          <input ref={fileInputRef} type="file" accept="video/*" onChange={handleFile} className="hidden" id="video-file-input" />
          <button
            id="upload-video-btn"
            onClick={() => fileInputRef.current?.click()}
            className="w-full py-3 px-4 rounded-xl flex items-center justify-center gap-3
                       bg-white/5 hover:bg-cyan-500/10 border border-white/10 hover:border-cyan-500/40
                       text-slate-300 hover:text-cyan-300 transition-all duration-200 font-medium"
          >
            <Upload className="w-4 h-4" />
            Upload Video CCTV
          </button>
        </div>

        <div className="flex gap-2">
          <input 
            type="text" 
            value={ytUrl}
            onChange={(e) => setYtUrl(e.target.value)}
            placeholder="Tempelkan Link YouTube di sini..." 
            className="flex-1 px-4 py-3 rounded-xl bg-white/5 border border-white/10 text-slate-200 focus:outline-none focus:border-red-500/50"
          />
          <button
            onClick={async () => {
              if (!ytUrl) return;
              setIsResolving(true);
              try {
                const stream = await resolveYouTubeUrl(ytUrl);
                loadVideoUrl(stream);
                setTimeout(startCapture, 1500); // Give video time to load metadata
              } catch (e: any) {
                onError?.(e.message);
              } finally {
                setIsResolving(false);
              }
            }}
            disabled={isResolving}
            className="py-3 px-6 rounded-xl flex items-center justify-center gap-2 whitespace-nowrap
                       bg-red-500/10 hover:bg-red-500/20 border border-red-500/30
                       text-red-400 transition-all duration-200 font-medium disabled:opacity-50"
          >
            {isResolving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Youtube className="w-4 h-4" />}
            Analisis YouTube
          </button>
        </div>
      </div>

      {/* Video + overlay canvas */}
      <div ref={containerRef} className="relative rounded-xl overflow-hidden border border-white/10 bg-black aspect-video scanline-overlay">
        <video
          ref={videoRef}
          className="w-full h-full object-contain"
          playsInline
          muted
        />
        {/* Bounding-box overlay */}
        <canvas
          ref={overlayRef}
          className="absolute inset-0 w-full h-full pointer-events-none"
          style={{ mixBlendMode: 'screen' }}
        />
        {/* Idle placeholder */}
        {!isCapturing && (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-slate-600">
            <Video className="w-12 h-12 mb-3 opacity-30" />
            <span className="text-sm">Upload video untuk memulai analisis</span>
          </div>
        )}
        {/* Live badge */}
        {isCapturing && (
          <div className="absolute top-3 left-3 flex items-center gap-2 px-3 py-1.5
                          rounded-full bg-black/60 backdrop-blur border border-red-500/40">
            <div className="w-2 h-2 rounded-full bg-red-500 dot-pulse" />
            <span className="text-xs font-mono-jet text-red-400 font-semibold tracking-wider">LIVE</span>
          </div>
        )}
        {/* FPS counter */}
        {isCapturing && (
          <div className="absolute top-3 right-3 px-2 py-1 rounded bg-black/60 backdrop-blur
                          border border-white/10 text-xs font-mono-jet text-slate-400">
            {fps} fps
          </div>
        )}
      </div>

      {/* Hidden capture canvas */}
      <canvas ref={canvasRef} className="hidden" />

      {/* Controls row */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {isCapturing
            ? <><Wifi className="w-4 h-4 text-cyan-400" /><span className="text-xs text-cyan-400 font-mono-jet">Capturing</span></>
            : <><WifiOff className="w-4 h-4 text-slate-600" /><span className="text-xs text-slate-600">Standby</span></>
          }
        </div>
        {isCapturing && (
          <button
            id="stop-capture-btn"
            onClick={stopCapture}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg
                       bg-red-500/10 hover:bg-red-500/20 border border-red-500/30
                       text-red-400 text-xs font-medium transition-all"
          >
            <Square className="w-3.5 h-3.5" />
            Stop
          </button>
        )}
      </div>
    </div>
  );
};
