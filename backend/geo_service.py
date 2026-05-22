import math
import os
import sqlite3
import json
import google.generativeai as genai
import PIL.Image

DB_PATH = os.path.join(os.path.dirname(__file__), "local_railways.db")

def haversine_distance(lat1, lon1, lat2, lon2):
    """
    Menghitung jarak antara dua koordinat latitude dan longitude
    menggunakan formula haversine (dalam meter).
    """
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2.0) ** 2 + \
        math.cos(phi1) * math.cos(phi2) * \
        math.sin(delta_lambda / 2.0) ** 2
    
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def find_nearest_railway(lat, lon):
    """
    Melakukan query ke local_railways.db untuk mencari titik rel terdekat.
    """
    if not os.path.exists(DB_PATH):
        import requests
        try:
            overpass_url = os.getenv("OVERPASS_API_URL", "http://overpass-api.de/api/interpreter")
            query = f"""
            [out:json][timeout:10];
            node["railway"](around:1000,{lat},{lon});
            out body;
            """
            headers = {'User-Agent': 'NusaRail_ServerlessFallback/1.0'}
            response = requests.post(overpass_url, data={'data': query}, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                elements = data.get("elements", [])
                if elements:
                    el = elements[0]
                    dist = haversine_distance(lat, lon, el.get("lat"), el.get("lon"))
                    return {
                        "id": el.get("id"),
                        "lat": el.get("lat"),
                        "lon": el.get("lon"),
                        "distance_meters": round(dist, 2),
                        "tags": el.get("tags", {})
                    }
        except Exception as e:
            print(f"[GEO-SERVICE] Fallback Overpass API Error: {e}")
            return {"error": "Serverless API Fallback Gagal"}
        return {"error": "Database lokal tidak ditemukan, dan API Fallback kosong"}
        
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id, lat, lon, tags FROM nodes WHERE lat IS NOT NULL AND lon IS NOT NULL")
        
        min_dist = float('inf')
        nearest_node = None
        
        for row in cursor.fetchall():
            node_id, n_lat, n_lon, tags = row
            dist = haversine_distance(lat, lon, n_lat, n_lon)
            if dist < min_dist:
                min_dist = dist
                nearest_node = {
                    "id": node_id,
                    "lat": n_lat,
                    "lon": n_lon,
                    "distance_meters": round(dist, 2),
                    "tags": json.loads(tags)
                }
        
        conn.close()
        return nearest_node
    except Exception as e:
        print(f"[GEO-SERVICE] Error finding nearest railway: {e}")
        return None

# Variabel global untuk menyimpan hasil analisis Gemini terakhir agar bisa ditarik Frontend
latest_gemini_report = "Menunggu trigger anomali..."

def analyze_anomaly_with_gemini(image_path, context_data):
    """
    Memanggil Gemini API untuk analisis gambar TKP kecelakaan secara asynchronous.
    """
    global latest_gemini_report
    latest_gemini_report = "Sedang menganalisis gambar dengan Gemini..."
    
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not gemini_key:
        latest_gemini_report = "API Key Gemini kosong."
        return
        
    try:
        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        img = PIL.Image.open(image_path)
        
        context_str = f"Konteks Lokasi: Jarak {context_data.get('distance_meters', 'Unknown')}m dari titik rel terdekat (ID: {context_data.get('id', 'Unknown')})." if context_data else "Lokasi rel tidak diketahui."
        prompt = f"Anda adalah AI Keselamatan Kereta. Analisis gambar CCTV ini. Buat laporan darurat 2 kalimat dalam bahasa Indonesia berdasarkan konteks lokasi yang diberikan. {context_str}"
        
        response = model.generate_content([prompt, img])
        latest_gemini_report = response.text.strip()
        print(f"[GEMINI] Laporan Selesai: {latest_gemini_report}")
    except Exception as e:
        print(f"[GEMINI] Error: {e}")
        latest_gemini_report = f"Gagal menganalisis dengan Gemini: {e}"
