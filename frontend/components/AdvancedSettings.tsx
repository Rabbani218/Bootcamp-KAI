"use client";

import { useState } from 'react';
import { ShieldAlert, Send, Map, Save, ServerCrash } from 'lucide-react';

interface Point {
  x: number;
  y: number;
}

export default function AdvancedSettings({ backendUrl }: { backendUrl: string }) {
  const [telegramToken, setTelegramToken] = useState("");
  const [telegramChatId, setTelegramChatId] = useState("");
  const [isSavingTg, setIsSavingTg] = useState(false);
  
  const [djkaWebhook, setDjkaWebhook] = useState("https://httpbin.org/post");
  const [mqttBroker, setMqttBroker] = useState("test.mosquitto.org");
  const [isSavingIntegration, setIsSavingIntegration] = useState(false);

  // Default polygon coordinates (relative 0.0 - 1.0)
  const [polygon, setPolygon] = useState<Point[]>([
    { x: 0.2, y: 0.3 },
    { x: 0.8, y: 0.3 },
    { x: 0.9, y: 0.9 },
    { x: 0.1, y: 0.9 },
  ]);
  const [isSavingPoly, setIsSavingPoly] = useState(false);

  const handleSaveTelegram = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSavingTg(true);
    try {
      const res = await fetch(`${backendUrl}/api/set_telegram`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: telegramToken, chat_id: telegramChatId })
      });
      if (res.ok) {
        alert("Konfigurasi Telegram Berhasil Disimpan!");
      }
    } catch (err) {
      alert("Gagal menyimpan konfigurasi Telegram.");
    }
    setIsSavingTg(false);
  };
  
  const handleSaveIntegrations = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSavingIntegration(true);
    try {
      const res = await fetch(`${backendUrl}/api/set_integrations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ djka_webhook: djkaWebhook, mqtt_broker: mqttBroker })
      });
      if (res.ok) {
        alert("Integrasi DJKA & Sistem Persinyalan IoT Berhasil Diterapkan!");
      }
    } catch (err) {
      alert("Gagal menyimpan konfigurasi Integrasi.");
    }
    setIsSavingIntegration(false);
  };

  const handleSavePolygon = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSavingPoly(true);
    try {
      const res = await fetch(`${backendUrl}/api/set_polygon`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ points: polygon })
      });
      if (res.ok) {
        alert("Zona Bahaya (Geo-Fencing) Berhasil Diterapkan ke AI Engine!");
      }
    } catch (err) {
      alert("Gagal menyimpan zona bahaya.");
    }
    setIsSavingPoly(false);
  };

  const handlePointChange = (index: number, axis: 'x' | 'y', value: string) => {
    let val = parseFloat(value);
    if (isNaN(val)) val = 0;
    if (val > 1) val = 1;
    if (val < 0) val = 0;
    
    const newPoly = [...polygon];
    newPoly[index][axis] = val;
    setPolygon(newPoly);
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
      
      {/* Geo-Fencing Panel */}
      <div className="bg-gray-900 border border-gray-800 p-6 rounded-xl shadow-lg">
        <h3 className="text-xl font-bold text-white mb-2 flex items-center gap-2">
          <Map className="w-6 h-6 text-blue-400" />
          Geo-Fencing (Zona Bahaya)
        </h3>
        <p className="text-gray-400 text-sm mb-6">
          Tentukan poligon 4-titik (format relatif 0.0 - 1.0) untuk mendefinisikan area perlintasan kereta. YOLO AI hanya akan memicu peringatan jika kendaraan berada di dalam zona ini.
        </p>

        <form onSubmit={handleSavePolygon} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            {polygon.map((pt, i) => (
              <div key={i} className="bg-gray-800/50 p-3 rounded-lg border border-gray-700">
                <div className="text-xs text-gray-500 font-medium mb-2">Titik {i + 1}</div>
                <div className="flex gap-2">
                  <div>
                    <label className="text-xs text-gray-400 block mb-1">X (0-1)</label>
                    <input 
                      type="number" step="0.01" min="0" max="1" required
                      value={pt.x} onChange={(e) => handlePointChange(i, 'x', e.target.value)}
                      className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm text-white focus:border-blue-500"
                    />
                  </div>
                  <div>
                    <label className="text-xs text-gray-400 block mb-1">Y (0-1)</label>
                    <input 
                      type="number" step="0.01" min="0" max="1" required
                      value={pt.y} onChange={(e) => handlePointChange(i, 'y', e.target.value)}
                      className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm text-white focus:border-blue-500"
                    />
                  </div>
                </div>
              </div>
            ))}
          </div>
          
          <button 
            type="submit" disabled={isSavingPoly}
            className="w-full bg-blue-600 hover:bg-blue-700 text-white font-medium py-2 rounded-lg transition flex items-center justify-center gap-2 disabled:opacity-50"
          >
            <Save className="w-4 h-4" />
            {isSavingPoly ? 'Menyimpan...' : 'Terapkan Zona Bahaya'}
          </button>
        </form>
      </div>

      <div className="space-y-6">
        {/* Integrasi DJKA & IoT */}
        <div className="bg-gray-900 border border-gray-800 p-6 rounded-xl shadow-lg">
          <h3 className="text-xl font-bold text-white mb-2 flex items-center gap-2">
            <ServerCrash className="w-6 h-6 text-blue-400" />
            Integrasi Server DJKA & Persinyalan
          </h3>
          <p className="text-gray-400 text-sm mb-6">
            Konfigurasi koneksi ke server pusat DJKA (via HTTP Webhook) dan broker IoT MQTT untuk persinyalan perlintasan sirine.
          </p>

          <form onSubmit={handleSaveIntegrations} className="space-y-4">
            <div>
              <label className="text-sm font-medium text-gray-300 block mb-2">DJKA Webhook URL</label>
              <input 
                type="url" required
                value={djkaWebhook} onChange={(e) => setDjkaWebhook(e.target.value)}
                placeholder="https://httpbin.org/post"
                className="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-4 py-2 focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label className="text-sm font-medium text-gray-300 block mb-2">MQTT Broker (Host)</label>
              <input 
                type="text" required
                value={mqttBroker} onChange={(e) => setMqttBroker(e.target.value)}
                placeholder="test.mosquitto.org"
                className="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-4 py-2 focus:outline-none focus:border-blue-500"
              />
            </div>
            
            <button 
              type="submit" disabled={isSavingIntegration}
              className="w-full bg-blue-600 hover:bg-blue-700 text-white font-medium py-2 rounded-lg transition flex items-center justify-center gap-2 mt-4 disabled:opacity-50"
            >
              <Save className="w-4 h-4" />
              {isSavingIntegration ? 'Menghubungkan Ulang...' : 'Simpan & Reconnect'}
            </button>
          </form>
        </div>

        {/* Telegram Bot Panel */}
        <div className="bg-gray-900 border border-gray-800 p-6 rounded-xl shadow-lg">
          <h3 className="text-xl font-bold text-white mb-2 flex items-center gap-2">
            <Send className="w-6 h-6 text-blue-400" />
            Notifikasi Telegram Bot
          </h3>
          <p className="text-gray-400 text-sm mb-6">
            Masukkan Token Bot dan Chat ID untuk mengirimkan foto snapshot kejadian secara real-time ke grup Telegram.
          </p>

          <form onSubmit={handleSaveTelegram} className="space-y-4">
            <div>
              <label className="text-sm font-medium text-gray-300 block mb-2">Bot Token API</label>
              <input 
                type="password" required
                value={telegramToken} onChange={(e) => setTelegramToken(e.target.value)}
                placeholder="7xxxxxxxxx:AAHxxxxxxxxxxxxxxxxxxxxxxxxx"
                className="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-4 py-2 focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label className="text-sm font-medium text-gray-300 block mb-2">Chat ID (Grup/User)</label>
              <input 
                type="text" required
                value={telegramChatId} onChange={(e) => setTelegramChatId(e.target.value)}
                placeholder="-100xxxxxxxxxx"
                className="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-4 py-2 focus:outline-none focus:border-blue-500"
              />
            </div>

            <div className="bg-blue-900/20 border border-blue-900/50 rounded-lg p-3 flex items-start gap-3 mt-4">
              <ShieldAlert className="w-5 h-5 text-blue-400 shrink-0 mt-0.5" />
              <p className="text-xs text-blue-300 leading-relaxed">
                Token tidak disimpan secara permanen di database, melainkan di <i>memory state</i>. Jika server *Cold Start*, Anda perlu memasukkannya kembali.
              </p>
            </div>
            
            <button 
              type="submit" disabled={isSavingTg}
              className="w-full bg-blue-600 hover:bg-blue-700 text-white font-medium py-2 rounded-lg transition flex items-center justify-center gap-2 mt-4 disabled:opacity-50"
            >
              <Save className="w-4 h-4" />
              {isSavingTg ? 'Menyimpan...' : 'Aktifkan Bot Telegram'}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
