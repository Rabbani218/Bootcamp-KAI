import { motion } from 'framer-motion';

export default function Loading() {
  return (
    <div className="min-h-screen dark:bg-[#050d1a] bg-slate-100 flex flex-col items-center justify-center gap-6">
      {/* KCI branded spinner */}
      <div className="relative w-16 h-16">
        <div className="absolute inset-0 rounded-full border-4 border-kci-blue/20" />
        <div className="absolute inset-0 rounded-full border-4 border-transparent border-t-kci-red animate-spin" />
        <div className="absolute inset-2 rounded-full border-4 border-transparent border-t-kci-orange animate-spin" style={{ animationDuration: '0.8s', animationDirection: 'reverse' }} />
      </div>

      <div className="text-center space-y-1">
        <div className="text-sm font-bold text-kci-red tracking-widest uppercase">NusaRail Vision</div>
        <div className="text-[11px] text-slate-400 font-mono animate-pulse">Memuat sistem pemantauan...</div>
      </div>

      {/* Pulsing dots */}
      <div className="flex gap-1.5">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className="w-2 h-2 rounded-full bg-kci-red animate-dot-pulse"
            style={{ animationDelay: `${i * 0.3}s` }}
          />
        ))}
      </div>
    </div>
  );
}
