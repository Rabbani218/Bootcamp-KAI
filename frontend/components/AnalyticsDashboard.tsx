"use client";

import { useEffect, useState } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { AlertTriangle, Clock, MapPin, Camera, Download, Server, Car } from 'lucide-react';

interface Incident {
  id: number;
  timestamp: number;
  lokasi: string;
  jenis: string;
  snapshot_url: string;
}

export default function AnalyticsDashboard({ backendUrl }: { backendUrl: string }) {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [loading, setLoading] = useState(true);
  const [sysStatus, setSysStatus] = useState({ uptime: 0, active_objects: 0 });

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [incRes, statRes] = await Promise.all([
          fetch(`${backendUrl}/api/incidents`).catch(()=>null),
          fetch(`${backendUrl}/api/status`).catch(()=>null)
        ]);

        if (incRes) {
          const data = await incRes.json();
          if (Array.isArray(data)) setIncidents(data);
        }
        if (statRes) {
          const data = await statRes.json();
          setSysStatus({ uptime: data.uptime || 0, active_objects: data.active_objects || 0 });
        }
      } catch (err) {
        console.error(err);
      } finally {
        setLoading(false);
      }
    };
    
    fetchData();
    const iv = setInterval(fetchData, 5000);
    return () => clearInterval(iv);
  }, [backendUrl]);

  const handleExportCSV = () => {
    if (incidents.length === 0) return;
    
    let csvContent = "data:text/csv;charset=utf-8,";
    csvContent += "ID,Waktu,Lokasi,Jenis,URL Foto\n";
    
    incidents.forEach(inc => {
      const timeStr = new Date(inc.timestamp * 1000).toLocaleString();
      csvContent += `${inc.id},"${timeStr}","${inc.lokasi}","${inc.jenis}","${backendUrl}${inc.snapshot_url}"\n`;
    });
    
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", `nusarail_report_${Date.now()}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const formatUptime = (seconds: number) => {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    return `${h}h ${m}m ${s}s`;
  };

  // Transform data for chart (Count incidents per hour/minute)
  const chartData = incidents.reduce((acc: any[], curr) => {
    const date = new Date(curr.timestamp * 1000);
    const timeLabel = `${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`;
    
    const existing = acc.find(item => item.time === timeLabel);
    if (existing) {
      existing.count += 1;
    } else {
      acc.unshift({ time: timeLabel, count: 1 }); // unshift to keep chronological left-to-right
    }
    return acc;
  }, []);

  // Sort chartData chronologically
  chartData.sort((a, b) => a.time.localeCompare(b.time));

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="bg-gray-900 border border-gray-800 p-6 rounded-xl shadow-lg">
          <div className="text-gray-400 text-sm font-medium mb-1">Total Insiden</div>
          <div className="text-3xl font-bold text-red-400">{incidents.length}</div>
        </div>
        <div className="bg-gray-900 border border-gray-800 p-6 rounded-xl shadow-lg">
          <div className="text-gray-400 text-sm font-medium mb-1 flex items-center gap-1">
            <Server className="w-4 h-4" /> Uptime Server
          </div>
          <div className="text-xl font-semibold text-white mt-1">
            {formatUptime(sysStatus.uptime)}
          </div>
        </div>
        <div className="bg-gray-900 border border-gray-800 p-6 rounded-xl shadow-lg">
          <div className="text-gray-400 text-sm font-medium mb-1 flex items-center gap-1">
            <Car className="w-4 h-4" /> Kendaraan Dilacak
          </div>
          <div className="text-2xl font-bold text-emerald-400">{sysStatus.active_objects}</div>
        </div>
        <div className="bg-gray-900 border border-gray-800 p-6 rounded-xl shadow-lg flex flex-col justify-center">
          <button 
            onClick={handleExportCSV}
            className="w-full py-3 px-4 bg-gray-800 hover:bg-gray-700 text-white font-medium rounded-lg transition-colors border border-gray-700 hover:border-gray-500 flex items-center justify-center gap-2"
          >
            <Download className="w-4 h-4" /> Export CSV Laporan
          </button>
        </div>
      </div>

      <div className="bg-gray-900 border border-gray-800 p-6 rounded-xl shadow-lg">
        <h3 className="text-lg font-semibold text-white mb-6 flex items-center gap-2">
          <AlertTriangle className="w-5 h-5 text-yellow-500" />
          Tren Insiden Harian
        </h3>
        <div className="h-64 w-full">
          {chartData.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                <XAxis dataKey="time" stroke="#9CA3AF" />
                <YAxis stroke="#9CA3AF" allowDecimals={false} />
                <Tooltip 
                  contentStyle={{ backgroundColor: '#1F2937', border: 'none', borderRadius: '0.5rem', color: '#fff' }}
                  itemStyle={{ color: '#34D399' }}
                />
                <Line type="monotone" dataKey="count" stroke="#34D399" strokeWidth={3} dot={{ fill: '#34D399' }} />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-full flex items-center justify-center text-gray-500">
              Belum ada data insiden untuk ditampilkan.
            </div>
          )}
        </div>
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-xl shadow-lg overflow-hidden">
        <div className="p-4 border-b border-gray-800">
          <h3 className="text-lg font-semibold text-white">Log Insiden Real-time</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm text-gray-300">
            <thead className="text-xs uppercase bg-gray-800/50 text-gray-400">
              <tr>
                <th className="px-6 py-4">Waktu</th>
                <th className="px-6 py-4">Lokasi</th>
                <th className="px-6 py-4">Jenis Bahaya</th>
                <th className="px-6 py-4 text-center">Snapshot Bukti</th>
              </tr>
            </thead>
            <tbody>
              {loading && incidents.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-6 py-8 text-center text-gray-500">Memuat log...</td>
                </tr>
              ) : incidents.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-6 py-8 text-center text-gray-500">Database kosong. Belum ada insiden tercatat.</td>
                </tr>
              ) : (
                incidents.map((inc) => (
                  <tr key={inc.id} className="border-b border-gray-800 hover:bg-gray-800/30 transition-colors">
                    <td className="px-6 py-4 font-medium text-white flex items-center gap-2">
                      <Clock className="w-4 h-4 text-blue-400" />
                      {new Date(inc.timestamp * 1000).toLocaleString()}
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-2">
                        <MapPin className="w-4 h-4 text-gray-500" />
                        {inc.lokasi}
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <span className="bg-red-900/40 text-red-400 border border-red-800 px-3 py-1 rounded-full text-xs font-medium">
                        {inc.jenis}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-center">
                      <a 
                        href={`${backendUrl}${inc.snapshot_url}`} 
                        target="_blank" 
                        rel="noreferrer"
                        className="inline-flex items-center gap-2 text-blue-400 hover:text-blue-300 transition-colors"
                      >
                        <Camera className="w-4 h-4" /> Lihat Foto
                      </a>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
