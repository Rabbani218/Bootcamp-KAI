'use client';

import { motion } from 'framer-motion';
import { WifiOff, RefreshCw } from 'lucide-react';

export default function ErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="min-h-screen dark:bg-[#050d1a] bg-slate-100 flex items-center justify-center p-8">
      <motion.div
        initial={{ opacity: 0, scale: 0.9 }}
        animate={{ opacity: 1, scale: 1 }}
        className="max-w-md w-full text-center space-y-6 rounded-2xl p-10
          border border-kci-red/30 bg-white dark:bg-[#0a1628] shadow-xl"
      >
        <div className="relative mx-auto w-20 h-20">
          <WifiOff className="w-20 h-20 text-kci-red mx-auto opacity-80" />
          <div className="absolute inset-0 rounded-full border-2 border-kci-red/30 animate-ping" />
        </div>

        <div>
          <h2 className="text-2xl font-black text-kci-red mb-2 tracking-tight">
            KONEKSI TERPUTUS
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">Menghubungkan Ulang ke Server...</p>
          {error?.message && (
            <p className="mt-2 text-[11px] font-mono text-slate-400 bg-slate-100 dark:bg-black/30 px-3 py-2 rounded-lg break-all">
              {error.message}
            </p>
          )}
        </div>

        <button
          onClick={reset}
          className="flex items-center gap-2 mx-auto px-6 py-2.5 rounded-xl
            bg-kci-red text-white font-bold hover:bg-kci-red/90 active:scale-95 transition-all"
        >
          <RefreshCw className="w-4 h-4" />
          Coba Lagi
        </button>
      </motion.div>
    </div>
  );
}
