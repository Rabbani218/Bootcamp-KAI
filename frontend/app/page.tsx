'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Activity, RefreshCw, Settings, Bell, BellOff,
  Server, ServerOff, Cpu, AlertTriangle, Volume2, Radio, Sun, Moon,
} from 'lucide-react';
import { useTheme } from 'next-themes';
import { checkHealth, resetTracker } from '@/lib/api';
import { VideoCapture }   from '@/components/dashboard/VideoCapture';
import { StatusIndicator } from '@/components/dashboard/StatusIndicator';
import { Statistics }     from '@/components/dashboard/Statistics';
import { EventLog }       from '@/components/dashboard/EventLog';
import { AiReportPanel }  from '@/components/dashboard/AiReportPanel';
import { HistoryPanel }   from '@/components/dashboard/HistoryPanel';
import { SettingsModal }  from '@/components/dashboard/SettingsModal';
import type { AnalyzeFrameResponse, LogEntry } from '@/lib/types';

const LOG_CAP  = 50;
const RETRY_MS = 15_000;

const fadeUp = {
  hidden: { opacity: 0, y: 20 },
  show:   { opacity: 1, y: 0, transition: { duration: 0.4, ease: 'easeOut' } },
};

const stagger = {
  show: { transition: { staggerChildren: 0.07 } },
};

function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  if (!mounted) return <div className="w-8 h-8" />;
  const isDark = theme === 'dark';
  return (
    <button
      onClick={() => setTheme(isDark ? 'light' : 'dark')}
      title={isDark ? 'Mode Terang' : 'Mode Gelap'}
      className={`p-2 rounded-lg border transition-all duration-300 ${
        isDark
          ? 'bg-kci-blue/20 border-kci-blue/40 text-kci-orange hover:bg-kci-blue/40'
          : 'bg-kci-orange/10 border-kci-orange/30 text-kci-red hover:bg-kci-orange/20'
      }`}
    >
      {isDark ? <Sun className="w-3.5 h-3.5" /> : <Moon className="w-3.5 h-3.5" />}
    </button>
  );
}

function DashboardInner() {
  const [currentAnalysis, setCurrentAnalysis] = useState<AnalyzeFrameResponse | null>(null);
  const [logs,            setLogs]            = useState<LogEntry[]>([]);
  const [cctvDown,        setCctvDown]        = useState(false);
  const [isOnline,        setIsOnline]        = useState(false);
  const [totalAlerts,     setTotalAlerts]     = useState(0);
  const [frameCount,      setFrameCount]      = useState(0);
  const [threshold,       setThreshold]       = useState(0.5);
  const [soundOn,         setSoundOn]         = useState(true);
  const [showSettings,    setShowSettings]    = useState(false);
  const [showMap,         setShowMap]         = useState(true);
  const [aiReport,        setAiReport]        = useState<string | null>(null);
  const [aiLoading,       setAiLoading]       = useState(false);
  const [alertPlayed,     setAlertPlayed]     = useState(false);
  const [isCritical,      setIsCritical]      = useState(false);
  const retryRef = useRef<NodeJS.Timeout | null>(null);

  const addLog = useCallback((type: LogEntry['type'], message: string, response?: AnalyzeFrameResponse) => {
    setLogs((prev) => {
      const entry: LogEntry = {
        id: `${Date.now()}-${Math.random()}`,
        timestamp: new Date(), type, message,
        detections: response?.detections,
        alertCount: response?.critical_alert_count,
      };
      const updated = [...prev, entry];
      return updated.length > LOG_CAP ? updated.slice(updated.length - LOG_CAP) : updated;
    });
  }, []);

  const playBeep = useCallback(() => {
    if (!soundOn) return;
    try {
      const audio = new Audio('/Warning.mp3');
      audio.play().catch(() => {});
    } catch {}
  }, [soundOn]);

  const fetchAiReport = useCallback(async (response: AnalyzeFrameResponse) => {
    setAiLoading(true);
    const apiBase = process.env.NEXT_PUBLIC_API_URL || 'https://alex-universe11-bootcamp-ubsi-kai.hf.space';
    try {
      const res = await fetch(`${apiBase}/api/v1/ai-report`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          detections: response.detections,
          critical_alert_count: response.critical_alert_count,
          timestamp: response.timestamp,
        }),
      });
      if (res.ok) { const data = await res.json(); setAiReport(data.report ?? '—'); }
    } catch {
      setAiReport('LLM tidak tersedia');
    } finally { setAiLoading(false); }
  }, []);

  const handleFrameAnalyzed = useCallback((response: AnalyzeFrameResponse) => {
    setCurrentAnalysis(response);
    setCctvDown(false);
    setFrameCount((n) => n + 1);
    if (response.detections.length > 0)
      addLog('detection', `${response.detections.length} objek terdeteksi`, response);
    if (response.alert_triggered) {
      setTotalAlerts((n) => n + 1);
      setIsCritical(true);
      addLog('alert', `🚨 CRITICAL ALERT — ${response.critical_alert_count} stationary`, response);
      setAlertPlayed(true);
      playBeep();
      if ('Notification' in window && Notification.permission === 'granted')
        new Notification('🚨 NusaRail CRITICAL ALERT', { body: `${response.critical_alert_count} kendaraan stationary!`, tag: 'nusarail' });
      fetchAiReport(response);
    } else {
      setIsCritical(false);
    }
  }, [addLog, playBeep, fetchAiReport]);

  const handleError = useCallback((msg: string) => {
    setCctvDown(true); addLog('error', `API Error: ${msg}`);
  }, [addLog]);

  const handleReset = useCallback(async () => {
    try { await resetTracker(); addLog('info', '🔄 Tracker direset'); setTotalAlerts(0); setAiReport(null); setIsCritical(false); }
    catch { addLog('error', 'Gagal mereset tracker'); }
  }, [addLog]);

  useEffect(() => {
    const probe = async () => {
      try {
        await checkHealth();
        setIsOnline(true); setCctvDown(false);
        addLog('info', '✅ Backend terhubung');
        if (retryRef.current) { clearInterval(retryRef.current); retryRef.current = null; }
      } catch {
        setIsOnline(false); setCctvDown(true);
        addLog('error', '❌ Backend offline — retry 15s');
        if (!retryRef.current) {
          retryRef.current = setInterval(async () => {
            try {
              await checkHealth();
              setIsOnline(true); setCctvDown(false);
              addLog('info', '✅ Backend reconnected');
              if (retryRef.current) { clearInterval(retryRef.current); retryRef.current = null; }
            } catch {}
          }, RETRY_MS);
        }
      }
    };
    probe();
    if ('Notification' in window && Notification.permission === 'default')
      Notification.requestPermission();
    return () => { if (retryRef.current) clearInterval(retryRef.current); };
  }, []);

  return (
    <div className={`min-h-screen flex flex-col transition-colors duration-500 relative
      dark:bg-[#050d1a] bg-slate-50 dark:grid-bg
      ${isCritical ? 'dark:animate-alert-flash' : ''}`
    }>
      {/* Background ambient glow */}
      <div className="fixed inset-0 pointer-events-none bg-[radial-gradient(ellipse_at_top_right,_var(--tw-gradient-stops))] from-kci-blue/10 dark:from-neon-cyan/5 via-transparent to-transparent opacity-60 z-0"></div>

      {/* ── Header ── */}
      <header className="sticky top-0 z-30 border-b border-kci-blue/10 dark:border-white/5
        bg-white/80 dark:bg-[#050d1a]/80 backdrop-blur-xl shadow-sm">
        <div className="px-4 md:px-6 py-3 flex items-center gap-3 flex-wrap">

          {/* Logo / Brand */}
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg overflow-hidden border border-kci-red/30">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/Logo 2.png" alt="NusaRail" className="w-full h-full object-contain" />
            </div>
            <div className="hidden sm:block">
              <div className="text-sm font-black tracking-tight text-kci-red dark:text-kci-orange">NusaRail</div>
              <div className="text-[9px] text-kci-blue dark:text-slate-500 font-mono uppercase tracking-widest">Vision System</div>
            </div>
          </div>

          {/* Live metrics */}
          <div className="hidden md:flex items-center gap-3 text-[11px] font-mono ml-2">
            <div className="px-3 py-1.5 rounded-lg bg-cyan-500/10 border border-cyan-500/20 flex items-center gap-2">
              <Radio className="w-3 h-3 text-cyan-500 dark:text-cyan-400" />
              <span className="text-slate-500">Frames</span>
              <span className="text-cyan-600 dark:text-cyan-300 font-bold">{frameCount}</span>
            </div>
            <div className={`px-3 py-1.5 rounded-lg flex items-center gap-2 ${
              totalAlerts > 0 ? 'bg-kci-red/10 border border-kci-red/30' : 'bg-green-500/10 border border-green-500/20'
            }`}>
              <Volume2 className={`w-3 h-3 ${totalAlerts > 0 ? 'text-kci-red' : 'text-green-500'}`} />
              <span className="text-slate-500">Alerts</span>
              <span className={`font-bold ${totalAlerts > 0 ? 'text-kci-red' : 'text-green-600 dark:text-green-300'}`}>{totalAlerts}</span>
            </div>
            <div className="px-3 py-1.5 rounded-lg bg-kci-orange/10 border border-kci-orange/30 flex items-center gap-2">
              <Activity className="w-3 h-3 text-kci-orange animate-pulse" />
              <span className="text-slate-500">Threshold</span>
              <span className="text-kci-orange font-bold">{Math.round(threshold * 100)}%</span>
            </div>
          </div>

          <div className="ml-auto flex items-center gap-2">
            {/* Theme toggle */}
            <ThemeToggle />

            {/* Sound toggle */}
            <button
              onClick={() => setSoundOn((s) => !s)}
              className={`p-2 rounded-lg border transition-all ${
                soundOn
                  ? 'bg-green-500/10 border-green-500/30 text-green-500'
                  : 'bg-slate-500/10 border-slate-300 dark:border-slate-500/20 text-slate-400'
              }`}
            >
              {soundOn ? <Bell className="w-3.5 h-3.5 animate-pulse" /> : <BellOff className="w-3.5 h-3.5" />}
            </button>

            {/* Settings */}
            <button
              onClick={() => setShowSettings(true)}
              className="p-2 rounded-lg bg-kci-blue/10 hover:bg-kci-blue/20 border border-kci-blue/30 transition-all"
            >
              <Settings className="w-3.5 h-3.5 text-kci-blue dark:text-slate-400" />
            </button>

            {/* Reset */}
            <button
              id="reset-tracker-btn"
              onClick={handleReset}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg
                bg-white/50 dark:bg-white/5 hover:bg-white/80 dark:hover:bg-white/10
                border border-slate-200 dark:border-white/10
                text-slate-600 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200 transition-all"
            >
              <RefreshCw className="w-3.5 h-3.5" /> Reset
            </button>

            {/* Online badge */}
            <div className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-mono font-bold ${
              isOnline
                ? 'border-green-500/30 bg-green-500/10 text-green-600 dark:text-green-300'
                : 'border-kci-red/30 bg-kci-red/10 text-kci-red'
            }`}>
              {isOnline ? <Server className="w-3.5 h-3.5 animate-pulse" /> : <ServerOff className="w-3.5 h-3.5" />}
              <span className="hidden sm:inline">{isOnline ? '● ONLINE' : '● OFFLINE'}</span>
            </div>
          </div>
        </div>
      </header>

      {/* ── CCTV Down Banner ── */}
      <AnimatePresence>
        {cctvDown && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            id="cctv-disconnected-banner"
          >
            <div className="flex justify-between items-center bg-red-600 px-6 py-3 shadow-[0_0_15px_rgba(220,38,38,0.5)]">
              <div className="flex items-center space-x-3">
                <AlertTriangle className="text-white animate-pulse" size={24} />
                <div>
                  <h2 className="text-white font-bold tracking-wider">KONEKSI BACKEND TERPUTUS</h2>
                  <p className="text-red-200 text-sm">Menghubungkan Ulang ke Server... (retry setiap 15 detik)</p>
                </div>
              </div>
              <div className="text-xs font-mono text-red-300">alex-universe11-bootcamp-ubsi-kai.hf.space</div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Alert sound strip ── */}
      <AnimatePresence>
        {alertPlayed && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="px-6 py-2 bg-kci-orange/20 border-b border-kci-orange/40 flex items-center gap-3"
          >
            <span className="text-xs text-kci-orange font-bold">⚠ Sistem Alarm Aktif — CRITICAL ALERT terdeteksi</span>
            <button onClick={() => setAlertPlayed(false)} className="ml-auto text-xs text-slate-400 hover:text-slate-200">Tutup</button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Main Grid ── */}
      <motion.div
        className="flex-1 p-4 md:p-6 lg:p-8 max-w-[1600px] mx-auto w-full z-10"
        variants={stagger}
        initial="hidden"
        animate="show"
      >
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 md:gap-6">

          {/* Left col (Video + AI + History) */}
          <div className="lg:col-span-2 space-y-6">
            <motion.section
              variants={fadeUp}
              className={`rounded-3xl p-6 md:p-8 border transition-all duration-500
                bg-white/70 dark:bg-[#0a1628]/60 backdrop-blur-xl shadow-sm hover:shadow-md
                ${isCritical
                  ? 'border-kci-red/60 shadow-[0_0_30px_rgba(237,28,36,0.15)]'
                  : 'border-kci-blue/10 dark:border-white/10 shadow-[0_4px_40px_rgba(0,0,0,0.03)] dark:shadow-[0_4px_40px_rgba(0,0,0,0.2)]'
                }`}
            >
              <div className="flex items-center gap-2 mb-4">
                <Activity className={`w-4 h-4 ${isCritical ? 'text-kci-red animate-pulse' : 'text-neon-cyan animate-neon-glow'}`} />
                <h2 className="text-sm font-bold text-slate-700 dark:text-slate-200">Video Stream & Frame Capture</h2>
                {isCritical && (
                  <span className="ml-auto px-2 py-0.5 rounded-full text-[10px] font-black bg-kci-red text-white animate-pulse">
                    CRITICAL ALERT
                  </span>
                )}
              </div>
              <VideoCapture
                onFrameAnalyzed={handleFrameAnalyzed}
                onError={handleError}
                threshold={threshold}
              />
            </motion.section>

            <motion.section variants={fadeUp} className="rounded-3xl p-6 border bg-white/70 dark:bg-[#0a1628]/60 backdrop-blur-xl border-kci-blue/10 dark:border-white/10 shadow-sm hover:shadow-md transition-all">
              <AiReportPanel report={aiReport} loading={aiLoading} />
            </motion.section>

            <motion.section variants={fadeUp} className="rounded-3xl p-6 border bg-white/70 dark:bg-[#0a1628]/60 backdrop-blur-xl border-kci-blue/10 dark:border-white/10 shadow-sm hover:shadow-md transition-all">
              <HistoryPanel />
            </motion.section>
          </div>

          {/* Right sidebar */}
          <aside className="space-y-6">
            <motion.section variants={fadeUp} className="rounded-3xl p-6 border bg-white/70 dark:bg-[#0a1628]/60 backdrop-blur-xl border-kci-blue/10 dark:border-white/10 shadow-sm hover:shadow-md transition-all">
              <h2 className="text-[10px] font-bold text-kci-blue dark:text-slate-500 uppercase tracking-widest mb-5">⚡ Status Sistem</h2>
              <StatusIndicator analysis={currentAnalysis} />
            </motion.section>

            <motion.section variants={fadeUp} className="rounded-3xl p-6 border bg-white/70 dark:bg-[#0a1628]/60 backdrop-blur-xl border-kci-blue/10 dark:border-white/10 shadow-sm hover:shadow-md transition-all">
              <h2 className="text-[10px] font-bold text-kci-blue dark:text-slate-500 uppercase tracking-widest mb-5">📊 Statistik Kendaraan</h2>
              <Statistics
                detections={currentAnalysis?.detections || []}
                criticalCount={currentAnalysis?.critical_alert_count || 0}
              />
            </motion.section>

            <motion.section variants={fadeUp} className="rounded-3xl p-6 border bg-white/70 dark:bg-[#0a1628]/60 backdrop-blur-xl border-kci-blue/10 dark:border-white/10 shadow-sm hover:shadow-md transition-all">
              <EventLog logs={logs} />
            </motion.section>
          </aside>
        </div>
      </motion.div>

      {/* ── Footer ── */}
      <footer className="border-t border-kci-blue/10 dark:border-white/5 px-6 py-3
        flex justify-between items-center text-[10px] text-slate-400 font-mono">
        <div className="flex items-center gap-3">
          <span>NusaRail Vision v4.0.0 · YOLOv8 + Gemini + SQLite</span>
          <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-kci-blue/10 border border-kci-blue/20">
            <div className="w-1.5 h-1.5 rounded-full bg-kci-blue" />
            <span className="text-kci-blue">KAI Commuter System</span>
          </div>
        </div>
        <span className={`font-bold px-3 py-1 rounded-lg ${
          isOnline
            ? 'text-green-600 dark:text-green-300 bg-green-500/10 border border-green-500/20'
            : 'text-kci-red bg-kci-red/10 border border-kci-red/20'
        }`}>
          🔗 API {isOnline ? '● ONLINE' : '● OFFLINE'}
        </span>
      </footer>

      {/* ── Settings Modal ── */}
      <AnimatePresence>
        {showSettings && (
          <SettingsModal
            threshold={threshold}
            onThresholdChange={setThreshold}
            soundOn={soundOn}
            onSoundToggle={() => setSoundOn((s) => !s)}
            showMap={showMap}
            onMapToggle={() => setShowMap((s) => !s)}
            onClose={() => setShowSettings(false)}
          />
        )}
      </AnimatePresence>
    </div>
  );
}

// ─── Error Boundary ──────────────────────────────────────────────────────────
import React from 'react';

class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { hasError: boolean; msg: string }
> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { hasError: false, msg: '' };
  }
  static getDerivedStateFromError(e: Error) {
    return { hasError: true, msg: e.message };
  }
  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen dark:bg-[#050d1a] bg-slate-100 flex items-center justify-center p-8">
          <div className="rounded-2xl p-10 max-w-md w-full text-center space-y-6 border border-kci-red/30 bg-white dark:bg-[#0a1628] shadow-lg">
            <AlertTriangle className="w-16 h-16 text-kci-red mx-auto" />
            <div>
              <h2 className="text-2xl font-black text-kci-red mb-2">SISTEM ERROR</h2>
              <p className="text-xs text-slate-400 font-mono">{this.state.msg}</p>
            </div>
            <button
              onClick={() => this.setState({ hasError: false, msg: '' })}
              className="px-6 py-2.5 rounded-xl bg-kci-red/20 border border-kci-red/40
                text-kci-red font-semibold hover:bg-kci-red/30 transition-all"
            >
              Hubungkan Ulang
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

export default function Dashboard() {
  return (
    <ErrorBoundary>
      <DashboardInner />
    </ErrorBoundary>
  );
}
