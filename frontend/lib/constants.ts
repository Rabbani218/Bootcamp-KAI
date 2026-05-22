export const FRAME_CAPTURE_INTERVAL = parseInt(
  process.env.NEXT_PUBLIC_FRAME_CAPTURE_INTERVAL || '1000',
  10
); // 1 detik

export const MAX_LOG_ENTRIES = parseInt(
  process.env.NEXT_PUBLIC_LOG_MAX_ENTRIES || '100',
  10
);

export const ALERT_TIMEOUT = 3000; // 3 detik untuk alert display

// Warna tema Command Center
export const THEME_COLORS = {
  SAFE: '#10b981',      // Hijau (aman)
  DANGER: '#ef4444',    // Merah (bahaya)
  WARNING: '#f59e0b',   // Kuning (warning)
  DARK_BG: '#0f172a',   // Background gelap
  DARK_SECONDARY: '#1e293b',
  TEXT_PRIMARY: '#e2e8f0',
  TEXT_SECONDARY: '#94a3b8',
};

// Vehicle class colors untuk stats
export const CLASS_COLORS: Record<string, string> = {
  car: '#3b82f6',         // Biru
  truck: '#f97316',       // Orange
  motorcycle: '#ec4899',  // Pink
  bicycle: '#8b5cf6',     // Purple
  bus: '#06b6d4',         // Cyan
};
