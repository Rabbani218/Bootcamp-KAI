'use client';

import React, { useRef, useEffect } from 'react';
import { Terminal, AlertCircle, Info, AlertTriangle, Radio, Zap, CheckCircle } from 'lucide-react';
import type { LogEntry } from '@/lib/types';

interface EventLogProps { logs: LogEntry[]; }

const TYPE_CONFIG: Record<LogEntry['type'], { icon: React.ReactNode; color: string; bg: string; label: string }> = {
  alert:     { 
    icon: <Zap className="w-3 h-3 flex-shrink-0" />,   
    color: 'text-red-400', 
    bg: 'bg-red-500/10 border border-red-500/20', 
    label: '🚨 ALERT'
  },
  detection: { 
    icon: <Radio className="w-3 h-3 flex-shrink-0" />,         
    color: 'text-cyan-400', 
    bg: 'bg-cyan-500/10 border border-cyan-500/20',
    label: '📡 DETECT'
  },
  error:     { 
    icon: <AlertTriangle className="w-3 h-3 flex-shrink-0" />, 
    color: 'text-amber-400',  
    bg: 'bg-amber-500/10 border border-amber-500/20',
    label: '⚠ ERROR'
  },
  info:      { 
    icon: <CheckCircle className="w-3 h-3 flex-shrink-0" />,          
    color: 'text-green-400', 
    bg: 'bg-green-500/10 border border-green-500/20',
    label: '✓ INFO'
  },
};

export const EventLog: React.FC<EventLogProps> = ({ logs }) => {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [logs]);

  return (
    <div className="flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-center gap-2">
        <Terminal className="w-4 h-4 text-slate-500" />
        <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest">
          Event Log
        </span>
        <span className="ml-auto font-mono-jet text-[10px] text-slate-600">
          {logs.length}/50
        </span>
      </div>

      {/* Terminal window */}
      <div className="glass-panel border-white/5 rounded-xl overflow-hidden">
        {/* Terminal title bar */}
        <div className="flex items-center gap-2 px-3 py-2 border-b border-white/5 bg-white/2">
          <div className="w-2.5 h-2.5 rounded-full bg-red-500/60" />
          <div className="w-2.5 h-2.5 rounded-full bg-amber-400/60" />
          <div className="w-2.5 h-2.5 rounded-full bg-green-400/60" />
          <span className="ml-2 text-[10px] text-slate-600 font-mono-jet">nusarail-event.log</span>
        </div>

        {/* Log entries */}
        <div
          ref={scrollRef}
          className="overflow-y-auto max-h-[240px] p-2 space-y-1 font-mono-jet text-[11px]"
        >
          {logs.length > 0 ? (
            [...logs].reverse().map((log) => {
              const cfg = TYPE_CONFIG[log.type] ?? TYPE_CONFIG.info;
              return (
                <div
                  key={log.id}
                  className={`flex items-start gap-2 px-2 py-1.5 rounded ${cfg.bg} animate-fade-in hover:bg-opacity-20 transition-all`}
                >
                  <span className={`${cfg.color} font-bold text-xs flex-shrink-0`}>{cfg.label}</span>
                  <span className={cfg.color}>{cfg.icon}</span>
                  <span className="text-slate-500 flex-shrink-0 tabular-nums">
                    {log.timestamp.toLocaleTimeString('id-ID', { hour12: false })}
                  </span>
                  <span className="text-slate-300 flex-1 break-all leading-tight">{log.message}</span>
                </div>
              );
            })
          ) : (
            <div className="text-slate-600 italic px-2 py-4 text-center">
              Menunggu event...
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
