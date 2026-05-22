'use client';

import { motion, AnimatePresence } from 'framer-motion';
import { X, Volume2, VolumeX, Map, MapPin, SlidersHorizontal } from 'lucide-react';
import { useEffect, useState } from 'react';

interface SettingsModalProps {
  threshold: number;
  onThresholdChange: (v: number) => void;
  soundOn: boolean;
  onSoundToggle: () => void;
  showMap: boolean;
  onMapToggle: () => void;
  onClose: () => void;
}

const STORAGE_KEY = 'nusarail_settings';

export function SettingsModal({
  threshold, onThresholdChange,
  soundOn, onSoundToggle,
  showMap, onMapToggle,
  onClose,
}: SettingsModalProps) {
  const [localThreshold, setLocalThreshold] = useState(threshold);

  // Sync to localStorage
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ threshold: localThreshold, soundOn, showMap }));
    } catch {}
  }, [localThreshold, soundOn, showMap]);

  const handleApply = () => {
    onThresholdChange(localThreshold);
    onClose();
  };

  return (
    <motion.div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
    >
      {/* Backdrop */}
      <motion.div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
      />

      {/* Modal */}
      <motion.div
        className="relative w-full max-w-sm rounded-2xl border z-10
          bg-white/90 dark:bg-[#0a1628]/90 backdrop-blur-xl
          border-kci-blue/20 dark:border-white/10
          shadow-2xl shadow-kci-blue/10"
        initial={{ opacity: 0, scale: 0.92, y: 20 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.92, y: 20 }}
        transition={{ type: 'spring', stiffness: 300, damping: 28 }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-kci-blue/10 dark:border-white/10">
          <div className="flex items-center gap-2">
            <SlidersHorizontal className="w-4 h-4 text-kci-blue dark:text-kci-orange" />
            <h3 className="font-bold text-slate-800 dark:text-slate-100 text-sm">Pengaturan Sistem</h3>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-white/10 transition-colors">
            <X className="w-4 h-4 text-slate-400" />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-5 space-y-6">

          {/* Sensitivity slider */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                Sensitivitas Deteksi
              </label>
              <span className="text-sm font-black font-mono text-kci-blue dark:text-kci-orange">
                {Math.round(localThreshold * 100)}%
              </span>
            </div>
            <input
              type="range" min={10} max={90} step={5}
              value={Math.round(localThreshold * 100)}
              onChange={(e) => setLocalThreshold(Number(e.target.value) / 100)}
              className="w-full h-2 rounded-full appearance-none cursor-pointer
                bg-slate-200 dark:bg-slate-700
                [&::-webkit-slider-thumb]:appearance-none
                [&::-webkit-slider-thumb]:w-4
                [&::-webkit-slider-thumb]:h-4
                [&::-webkit-slider-thumb]:rounded-full
                [&::-webkit-slider-thumb]:bg-kci-red
                [&::-webkit-slider-thumb]:cursor-pointer"
            />
            <div className="flex justify-between text-[9px] text-slate-400 font-mono">
              <span>Sensitif</span><span>Konservatif</span>
            </div>
          </div>

          {/* Sound toggle */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              {soundOn ? <Volume2 className="w-4 h-4 text-kci-blue" /> : <VolumeX className="w-4 h-4 text-slate-400" />}
              <div>
                <div className="text-sm font-semibold text-slate-700 dark:text-slate-200">Suara Notifikasi</div>
                <div className="text-[10px] text-slate-400">{soundOn ? 'Aktif — Warning.mp3' : 'Dimatikan'}</div>
              </div>
            </div>
            <button
              onClick={onSoundToggle}
              className={`relative w-12 h-6 rounded-full transition-colors duration-200 ${soundOn ? 'bg-kci-red' : 'bg-slate-200 dark:bg-slate-700'}`}
            >
              <span className={`absolute top-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform duration-200 ${soundOn ? 'translate-x-6' : 'translate-x-0.5'}`} />
            </button>
          </div>

          {/* Map toggle */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              {showMap ? <Map className="w-4 h-4 text-kci-blue" /> : <MapPin className="w-4 h-4 text-slate-400" />}
              <div>
                <div className="text-sm font-semibold text-slate-700 dark:text-slate-200">Peta Jalur Rel</div>
                <div className="text-[10px] text-slate-400">{showMap ? 'Ditampilkan' : 'Disembunyikan'}</div>
              </div>
            </div>
            <button
              onClick={onMapToggle}
              className={`relative w-12 h-6 rounded-full transition-colors duration-200 ${showMap ? 'bg-kci-blue' : 'bg-slate-200 dark:bg-slate-700'}`}
            >
              <span className={`absolute top-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform duration-200 ${showMap ? 'translate-x-6' : 'translate-x-0.5'}`} />
            </button>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 pb-5 flex gap-3">
          <button
            onClick={onClose}
            className="flex-1 py-2 rounded-xl text-sm font-semibold border
              border-slate-200 dark:border-white/10
              text-slate-600 dark:text-slate-400
              hover:bg-slate-50 dark:hover:bg-white/5 transition-all"
          >
            Batal
          </button>
          <button
            onClick={handleApply}
            className="flex-1 py-2 rounded-xl text-sm font-bold
              bg-kci-red text-white
              hover:bg-kci-red/90 active:scale-95 transition-all"
          >
            Terapkan
          </button>
        </div>
      </motion.div>
    </motion.div>
  );
}
