'use client';

import React from 'react';
import { BrainCircuit, Loader2, FileText } from 'lucide-react';

interface AiReportPanelProps {
  report: string | null;
  loading: boolean;
}

export const AiReportPanel: React.FC<AiReportPanelProps> = ({ report, loading }) => {
  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-center gap-2">
        <BrainCircuit className="w-4 h-4 text-violet-400" />
        <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest">
          AI Emergency Report
        </span>
        {loading && (
          <Loader2 className="w-3.5 h-3.5 text-violet-400 animate-spin ml-auto" />
        )}
      </div>

      {/* Panel */}
      <div className="glass-panel rounded-xl border border-violet-500/20 p-4 min-h-[100px]
                      bg-violet-500/5">
        {loading ? (
          <div className="flex flex-col items-center justify-center h-20 gap-2">
            <Loader2 className="w-5 h-5 text-violet-400 animate-spin" />
            <span className="text-xs text-slate-500">LLM sedang menganalisis insiden...</span>
          </div>
        ) : report ? (
          <div className="flex gap-2.5">
            <FileText className="w-4 h-4 text-violet-400 flex-shrink-0 mt-0.5" />
            <p className="text-xs text-slate-300 leading-relaxed font-medium">{report}</p>
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center h-16 gap-1.5 text-slate-600">
            <BrainCircuit className="w-6 h-6 opacity-30" />
            <span className="text-xs italic">Laporan AI muncul saat CRITICAL ALERT</span>
          </div>
        )}
      </div>

      {/* Ollama info */}
      <div className="text-[10px] text-slate-600 font-mono-jet flex items-center gap-1.5">
        <span className="w-1.5 h-1.5 rounded-full bg-violet-500 inline-block dot-pulse" />
        Ollama LLM · localhost:11434
      </div>
    </div>
  );
};
