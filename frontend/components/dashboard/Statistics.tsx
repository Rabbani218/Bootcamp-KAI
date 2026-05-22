'use client';

import React, { useMemo } from 'react';
import { Car, Truck, Bike, Bus, AlertTriangle, Eye, Zap, CheckCircle } from 'lucide-react';
import type { Detection } from '@/lib/types';
import { CLASS_COLORS } from '@/lib/constants';

interface StatisticsProps {
  detections: Detection[];
  criticalCount: number;
}

const CLASS_ICONS: Record<string, React.ReactNode> = {
  car:        <Car className="w-3.5 h-3.5" />,
  truck:      <Truck className="w-3.5 h-3.5" />,
  motorcycle: <Bike className="w-3.5 h-3.5" />,
  bicycle:    <Bike className="w-3.5 h-3.5" />,
  bus:        <Bus className="w-3.5 h-3.5" />,
};

export const Statistics: React.FC<StatisticsProps> = ({ detections, criticalCount }) => {
  const stats = useMemo(() => {
    const classCount: Record<string, number> = {};
    const stationaryCount: Record<string, number> = {};

    detections.forEach((det) => {
      classCount[det.class_name] = (classCount[det.class_name] || 0) + 1;
      if (det.is_stationary) stationaryCount[det.class_name] = (stationaryCount[det.class_name] || 0) + 1;
    });

    return {
      total: detections.length,
      totalStationary: detections.filter((d) => d.is_stationary).length,
      byClass: Object.entries(classCount).map(([className, count]) => ({
        className,
        count,
        stationary: stationaryCount[className] || 0,
        pct: Math.round((count / detections.length) * 100),
      })),
    };
  }, [detections]);

  return (
    <div className="space-y-4">
      {/* Summary stats with icons */}
      <div className="grid grid-cols-2 gap-2">
        <div className="bg-gradient-to-br from-cyan-500/20 to-blue-500/20 border border-cyan-500/30 rounded-lg p-3">
          <div className="flex items-center gap-2 mb-1">
            <Eye className="w-3.5 h-3.5 text-cyan-400" />
            <span className="text-[10px] text-slate-400">Total</span>
          </div>
          <div className="font-mono-jet text-2xl font-bold text-cyan-400">{stats.total}</div>
        </div>
        <div className={`bg-gradient-to-br border rounded-lg p-3 ${
          stats.totalStationary > 0
            ? 'from-red-500/20 to-orange-500/20 border-red-500/30'
            : 'from-green-500/20 to-emerald-500/20 border-green-500/30'
        }`}>
          <div className="flex items-center gap-2 mb-1">
            <AlertTriangle className={`w-3.5 h-3.5 ${stats.totalStationary > 0 ? 'text-red-400' : 'text-green-400'}`} />
            <span className="text-[10px] text-slate-400">Stationary</span>
          </div>
          <div className={`font-mono-jet text-2xl font-bold ${
            stats.totalStationary > 0 ? 'text-red-400' : 'text-green-400'
          }`}>{stats.totalStationary}</div>
        </div>
      </div>

      {/* Per-class breakdown with progress bar */}
      <div className="space-y-2.5">
        <div className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest flex items-center gap-2">
          <Truck className="w-3.5 h-3.5" />
          Breakdown Kendaraan
        </div>

        {stats.byClass.length > 0 ? (
          stats.byClass.map(({ className, count, stationary, pct }) => {
            const color = CLASS_COLORS[className] || '#64748b';
            return (
              <div key={className} className="space-y-1.5">
                <div className="flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2 min-w-0">
                    <span style={{ color }} className="flex-shrink-0">
                      {CLASS_ICONS[className] ?? <Car className="w-3.5 h-3.5" />}
                    </span>
                    <span className="text-slate-300 capitalize truncate">{className}</span>
                    {stationary > 0 && (
                      <span className="text-[10px] bg-red-500/20 text-red-400 border border-red-500/30
                                       px-1.5 py-0.5 rounded-full font-semibold animate-pulse">
                        ⚠ {stationary} diam
                      </span>
                    )}
                  </div>
                  <span className="font-mono-jet font-bold text-slate-200">{count}</span>
                </div>
                {/* Progress bar */}
                <div className="h-1.5 rounded-full bg-white/5 overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all duration-700 shadow-lg"
                    style={{ width: `${pct}%`, background: color, boxShadow: `0 0 8px ${color}` }}
                  />
                </div>
              </div>
            );
          })
        ) : (
          <div className="text-xs text-slate-600 italic py-3 text-center">
            Belum ada kendaraan terdeteksi
          </div>
        )}
      </div>

      {/* Critical banner */}
      {criticalCount > 0 && (
        <div className="glass-panel-red p-3 rounded-xl animate-alert-flash border-2 border-red-500">
          <div className="text-xs font-bold text-red-300 flex items-center gap-2">
            <span className="text-lg">🚨</span>
            {criticalCount} objek STATIONARY — potensi kemacetan perlintasan!
          </div>
        </div>
      )}
    </div>
  );
};
