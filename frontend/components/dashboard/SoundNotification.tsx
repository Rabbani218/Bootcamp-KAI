'use client';

import React, { useEffect, useState } from 'react';
import { Volume2, VolumeX, AlertCircle } from 'lucide-react';

interface SoundNotificationProps {
  trigger?: boolean;
  soundUrl?: string;
  enabled?: boolean;
  onPlay?: () => void;
}

export function SoundNotification({ 
  trigger = false,
  soundUrl = '/Warning.mp3',
  enabled = true,
  onPlay 
}: SoundNotificationProps) {
  const [isPlaying, setIsPlaying] = useState(false);
  const [audioError, setAudioError] = useState<string | null>(null);

  useEffect(() => {
    if (!trigger || !enabled) return;

    const playAlert = async () => {
      try {
        setAudioError(null);
        setIsPlaying(true);
        const audio = new Audio(soundUrl);
        audio.volume = 0.8;
        
        audio.onerror = () => {
          setAudioError('Failed to load audio');
          setIsPlaying(false);
        };

        audio.onended = () => {
          setIsPlaying(false);
          onPlay?.();
        };

        await audio.play().catch((e) => {
          setAudioError(`Play failed: ${e.message}`);
          setIsPlaying(false);
        });
      } catch (error) {
        setAudioError('Audio system error');
        setIsPlaying(false);
      }
    };

    playAlert();
  }, [trigger, enabled, soundUrl, onPlay]);

  return (
    <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-500/30">
      {isPlaying ? (
        <>
          <Volume2 className="w-4 h-4 text-amber-400 animate-pulse" />
          <span className="text-xs text-amber-300 font-semibold">Alert sounding...</span>
        </>
      ) : audioError ? (
        <>
          <AlertCircle className="w-4 h-4 text-red-400" />
          <span className="text-xs text-red-300">{audioError}</span>
        </>
      ) : (
        <>
          <VolumeX className="w-4 h-4 text-slate-500" />
          <span className="text-xs text-slate-500">Ready</span>
        </>
      )}
    </div>
  );
}
