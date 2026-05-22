'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { DatabaseZap, RefreshCw, AlertTriangle, Clock, MapPin } from 'lucide-react';
import axios from 'axios';

interface AnomalyRecord {
  id: number;
  timestamp: string;
  vehicle_class: string;
  duration_ms: number;
  position_x: number;
  position_y: number;
  evidence_path: string | null;
  ai_report: string | null;
}

const API = process.env.NEXT_PUBLIC_API_URL || 'https://alex-universe11-bootcamp-ubsi-kai.hf.space';

export const HistoryPanel: React.FC = () => {
  const [records, setRecords] = useState<AnomalyRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const fetchHistory = useCallback(async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API}/api/v1/history?limit=50`);
      setRecords(res.data.records || []);
      setLastRefresh(new Date());
    } catch {
      // silent — panel stays empty if backend down
    } finally {
      setLoading(false);
    }
  }, []);

  // Auto-refresh every 30 s
  useEffect(() => {
    fetchHistory();
    const id = setInterval(fetchHistory, 30_000);
    return () => clearInterval(id);
  }, [fetchHistory]);

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-center gap-2">
        <DatabaseZap className="w-4 h-4 text-violet-400" />
        <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest flex-1">
          Riwayat Anomali (SQLite)
        </span>
        <button
          onClick={fetchHistory}
          className="p-1 rounded hover:bg-white/10 transition-colors"
          title="Refresh"
        >
          <RefreshCw className={`w-3 h-3 text-slate-500 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Table */}
      <div className="glass-panel rounded-xl border border-violet-500/15 overflow-hidden">
        {/* Column headers */}
        <div className="grid grid-cols-4 gap-2 px-3 py-2 border-b border-white/5
                        text-[10px] font-semibold text-slate-500 uppercase tracking-wider">
          <div>Waktu</div>
          <div>Kendaraan</div>
          <div>Durasi</div>
          <div>Posisi</div>
        </div>

        {/* Rows */}
        <div className="overflow-y-auto max-h-[260px]">
          {records.length > 0 ? (
            records.map((rec) => (
              <div
                key={rec.id}
                className="grid grid-cols-4 gap-2 px-3 py-2 border-b border-white/3
                           hover:bg-white/3 transition-colors text-[11px] font-mono-jet"
              >
                <div className="text-slate-400 flex items-center gap-1 truncate">
                  <Clock className="w-2.5 h-2.5 flex-shrink-0 text-slate-600" />
                  {new Date(rec.timestamp).toLocaleTimeString('id-ID')}
                </div>
                <div className="flex items-center gap-1">
                  <AlertTriangle className="w-2.5 h-2.5 text-amber-400 flex-shrink-0" />
                  <span className="capitalize text-amber-300">{rec.vehicle_class}</span>
                </div>
                <div className={`font-bold ${rec.duration_ms > 5000 ? 'text-red-400' : 'text-slate-300'}`}>
                  {(rec.duration_ms / 1000).toFixed(1)}s
                </div>
                <div className="text-slate-500 flex items-center gap-1 truncate">
                  <MapPin className="w-2.5 h-2.5 flex-shrink-0" />
                  {rec.position_x.toFixed(0)},{rec.position_y.toFixed(0)}
                </div>
              </div>
            ))
          ) : (
            <div className="text-center text-xs text-slate-600 italic py-8">
              {loading ? 'Memuat data...' : 'Belum ada kejadian tercatat'}
            </div>
          )}
        </div>
      </div>

      {/* Footer */}
      {lastRefresh && (
        <div className="text-[10px] text-slate-600 font-mono-jet">
          Diperbarui: {lastRefresh.toLocaleTimeString('id-ID')}
          &nbsp;·&nbsp;{records.length} record
        </div>
      )}
    </div>
  );
};
