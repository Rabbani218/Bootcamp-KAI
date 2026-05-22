'use client';

import React, { useState, useEffect } from 'react';
import { AlertTriangle, CheckCircle, Shield, Zap, Clock } from 'lucide-react';
import type { AnalyzeFrameResponse } from '@/lib/types';

interface StatusIndicatorProps {
  analysis?: AnalyzeFrameResponse | null;
}

export const StatusIndicator: React.FC<StatusIndicatorProps> = ({ analysis }) => {
  const [flashActive, setFlashActive] = useState(false);

  useEffect(() => {
    if (analysis?.alert_triggered) {
      setFlashActive(true);
      const t = setTimeout(() => setFlashActive(false), 4000);
      return () => clearTimeout(t);
    }
  }, [analysis?.alert_triggered, analysis?.timestamp]);

  const isAlert = analysis?.alert_triggered ?? false;

  return (
    <div className="space-y-4">
      {/* Main status card */}
      <div
        id="status-indicator-box"
        className={`relative rounded-xl p-4 border-2 transition-all duration-500 overflow-hidden ${
          isAlert
            ? 'border-[#ff2d55] glass-panel-red animate-alert-flash'
            : 'border-[#00ff88]/40 glass-panel-green'
        }`}
      >
        {/* Corner accent */}
        <div className={`absolute top-0 right-0 w-16 h-16 opacity-20 ${isAlert ? 'bg-red-500' : 'bg-green-400'}`}
          style={{ clipPath: 'polygon(100% 0, 0 0, 100% 100%)' }} />

        <div className="flex items-center gap-3">
          <div className={`p-2 rounded-lg ${isAlert ? 'bg-red-500/20' : 'bg-green-400/20'}`}>
            {isAlert
              ? <AlertTriangle className="w-6 h-6 text-[#ff2d55]" />
              : <Shield className="w-6 h-6 text-[#00ff88]" />
            }
          </div>
          <div>
            <div className="text-[10px] text-slate-500 uppercase tracking-widest font-semibold">System Status</div>
            <div className={`text-base font-black tracking-wide ${isAlert ? 'text-neon-red' : 'text-neon-green'}`}>
              {isAlert ? '🚨 CRITICAL ALERT' : '✅ JALUR AMAN'}
            </div>
          </div>
        </div>

        {isAlert && (
          <div className="mt-3 p-2.5 rounded-lg bg-red-500/10 border border-red-500/20 text-xs text-red-300">
            ⚠ {analysis?.critical_alert_count} kendaraan stationary terdeteksi di perlintasan
          </div>
        )}
      </div>

      {/* Metrics grid */}
      <div className="grid grid-cols-2 gap-2">
        <div className="stat-card">
          <div className="flex items-center gap-1.5 text-[10px] text-slate-500 uppercase tracking-wider">
            <Zap className="w-3 h-3" /> Inference
          </div>
          <div className="font-mono-jet text-xl font-bold text-slate-200">
            {analysis?.inference_time_ms?.toFixed(0) ?? '—'}
            <span className="text-xs text-slate-500 ml-1">ms</span>
          </div>
        </div>

        <div className="stat-card">
          <div className="flex items-center gap-1.5 text-[10px] text-slate-500 uppercase tracking-wider">
            <CheckCircle className="w-3 h-3" /> Detections
          </div>
          <div className="font-mono-jet text-xl font-bold text-slate-200">
            {analysis?.detections.length ?? 0}
          </div>
        </div>
      </div>

      {/* Timestamp */}
      {analysis?.timestamp && (
        <div className="flex items-center gap-2 text-[11px] text-slate-500 font-mono-jet">
          <Clock className="w-3 h-3" />
          {new Date(analysis.timestamp).toLocaleTimeString('id-ID', { hour12: false })}
        </div>
      )}
    </div>
  );
};
