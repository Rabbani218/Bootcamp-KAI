'use client';

import { useRef, useEffect, useState } from 'react';
import type { AnalyzeFrameResponse } from '@/lib/types';
import { analyzeFrame } from '@/lib/api';

interface UseVideoCaptureProps {
  onFrameAnalyzed?: (response: AnalyzeFrameResponse) => void;
  onError?: (error: Error) => void;
  captureInterval?: number;
  enabled?: boolean;
  threshold?: number;  // dynamic confidence threshold (0–1)
}

export const useVideoCapture = ({
  onFrameAnalyzed,
  onError,
  captureInterval = 1000,
  enabled = true,
  threshold = 0.5,
}: UseVideoCaptureProps) => {
  const videoRef    = useRef<HTMLVideoElement>(null);
  const canvasRef   = useRef<HTMLCanvasElement>(null);
  const intervalRef = useRef<NodeJS.Timeout | null>(null);
  const threshRef   = useRef(threshold);   // keep latest threshold without re-creating interval
  const isProcessingRef = useRef(false);
  const [isCapturing, setIsCapturing] = useState(false);

  // Sync threshold ref when prop changes
  useEffect(() => { threshRef.current = threshold; }, [threshold]);

  const captureAndAnalyze = async () => {
    if (!videoRef.current || !canvasRef.current) return;
    if (videoRef.current.paused || videoRef.current.ended) return;
    if (isProcessingRef.current) return; // Prevent overlapping memory leaks

    isProcessingRef.current = true;
    try {
      const ctx = canvasRef.current.getContext('2d');
      if (!ctx) {
        isProcessingRef.current = false;
        return;
      }

      ctx.drawImage(
        videoRef.current, 0, 0,
        canvasRef.current.width,
        canvasRef.current.height
      );

      // quality 0.65 — ~40% smaller than 0.8, prevents RAM pressure
      canvasRef.current.toBlob(
        async (blob) => {
          if (!blob) {
            isProcessingRef.current = false;
            return;
          }
          try {
            const response = await analyzeFrame(blob, threshRef.current);
            onFrameAnalyzed?.(response);
          } catch (error) {
            onError?.(error instanceof Error ? error : new Error('Unknown error'));
          } finally {
            isProcessingRef.current = false;
          }
          // blob reference released here — eligible for GC
        },
        'image/jpeg',
        0.65
      );
    } catch (error) {
      isProcessingRef.current = false;
      onError?.(error instanceof Error ? error : new Error('Capture failed'));
    }
  };

  const loadVideoFile = (file: File) => {
    if (!videoRef.current) return;
    const url = URL.createObjectURL(file);
    videoRef.current.src = url;
    videoRef.current.onloadedmetadata = () => {
      if (canvasRef.current && videoRef.current) {
        canvasRef.current.width  = videoRef.current.videoWidth;
        canvasRef.current.height = videoRef.current.videoHeight;
      }
      videoRef.current!.loop = true;
      videoRef.current!.play().catch((err) => {
        console.error('Play error:', err);
        onError?.(new Error('Failed to play video'));
      });
    };
    return () => URL.revokeObjectURL(url);
  };

  const startCapture = () => {
    if (intervalRef.current) return;
    setIsCapturing(true);
    intervalRef.current = setInterval(captureAndAnalyze, captureInterval);
  };

  const stopCapture = () => {
    if (intervalRef.current) { clearInterval(intervalRef.current); intervalRef.current = null; }
    setIsCapturing(false);
  };

  useEffect(() => {
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
      if (videoRef.current?.src) URL.revokeObjectURL(videoRef.current.src);
    };
  }, []);

  useEffect(() => {
    if (!enabled) stopCapture();
    return () => stopCapture();
  }, [enabled]);

  return { videoRef, canvasRef, isCapturing, loadVideoFile, startCapture, stopCapture };
};
