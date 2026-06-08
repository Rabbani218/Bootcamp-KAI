"""
Analisis Gemini API terhadap video Kalibata menggunakan metadata + thumbnail
Zero-Hallucination: hanya menganalisis data yang benar-benar tersedia
"""
import os, json, warnings
warnings.filterwarnings("ignore")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

API_KEY = "AIzaSyCCNLkAMh6VmZuaoG1LuqkAa9O0cMA-hVA"

PROMPT = """
Kamu adalah Core Vision Agent untuk Sistem Peringatan Dini Infrastruktur Kereta Api.

Saya menyediakan FAKTA TERVERIFIKASI dari metadata video YouTube berikut (bukan halusinasi):
- Judul Video: "Mobil macet di tengah rel disaat kereta mau Lewat di Kalibata Jaksel"
- Channel: INFO KRIMINAL NUSANTARA
- Tanggal Upload: 6 November 2021 (Jumat sore, 5 November 2021)
- Durasi Total: 60 detik
- Deskripsi Resmi YouTube (verbatim):
  "SEBUAH MOBIL TIBA-TIBA MOGOK DI TENGAH REL PERLINTASAN KERETA API STASIUN DUREN KALIBATA
   Beredar rekaman video yg memperlihatkan sebuah mobil tiba-tiba mogok di tengah tengah rel
   pintu perlintasan kereta api stasiun Duren Kalibata, Jaksel, Jumat sore (5/11).
   Terlihat warga sekitar yang membantu mendorong mobil tersebut agar keluar dari rel kereta.
   Tidak lama setelah mobil berhasil lolos keluar dari rel tiba tiba terlihat kereta KRL
   yg melewati perlintasan kereta tersebut.
   Beruntungnya mobil tersebut lolos dari tabrakan berkat bantuan para warga yang dengan cepat membantu."

Thumbnail (frame awal video) terlampir — terlihat:
- Malam hari / kondisi gelap (pencahayaan buatan dari lampu jalan/sinyal)
- Mobil biru (terlihat di kiri atas thumbnail) di area rel
- Beberapa orang berpakaian merah dan putih (helm) mendorong/membantu
- Tiang sinyal perlintasan berwarna kuning/oranye di kanan (terlihat lampu merah aktif)
- Jalan aspal basah/malam
- Teks "ST" di pojok kanan atas (mungkin bagian dari tulisan "STOP" atau nama stasiun)

Berdasarkan HANYA fakta-fakta di atas (DILARANG mengarang timestamp yang tidak terverifikasi),
buat analisis JSON dengan estimasi timestamp berbasis logika naratif deskripsi video.

PENTING: Karena video tidak bisa diunduh langsung, berikan estimasi timestamp SEBAGAI RANGE
dengan label "estimated_range" dan jelaskan metodologi inferensinya.

Format output (JSON saja, tanpa penjelasan tambahan):
{
  "system_status": "CRITICAL_ALERT",
  "data_source": "yt-dlp metadata + YouTube description + thumbnail analysis",
  "confidence_level": "MEDIUM — based on verified metadata, not direct frame analysis",
  "location_context": {
    "name": "Perlintasan KA Stasiun Duren Kalibata",
    "kota": "Jakarta Selatan",
    "koordinat_estimasi": "[-6.2552, 106.8472]",
    "kondisi_perlintasan": "<analisis dari thumbnail>",
    "waktu_kejadian": "Jumat sore/malam, 5 November 2021"
  },
  "temporal_log": {
    "T0_stationary_vehicle": {
      "description": "Mobil mogok pertama kali di tengah rel",
      "estimated_range_seconds": "<estimasi berdasarkan narasi>",
      "timestamp_mm_ss": "<estimasi>",
      "methodology": "<jelaskan cara inferensi>"
    },
    "T1_crowd_response": {
      "description": "Warga mulai berkerumun dan mendorong mobil",
      "estimated_range_seconds": "<estimasi>",
      "timestamp_mm_ss": "<estimasi>",
      "methodology": "<jelaskan cara inferensi>"
    },
    "T2_train_visible": {
      "description": "KRL Commuter Line pertama kali masuk frame",
      "estimated_range_seconds": "<estimasi>",
      "timestamp_mm_ss": "<estimasi>",
      "methodology": "<jelaskan cara inferensi>"
    },
    "T3_golden_window": {
      "delta_seconds": "<T2 - T0>",
      "interpretation": "Jendela Waktu Emas untuk evakuasi",
      "risk_level": "<CRITICAL/HIGH/MEDIUM>"
    }
  },
  "audio_analysis": {
    "siren_palang": "<analisis berdasarkan visual thumbnail>",
    "klakson_semboyan35": "<analisis>",
    "kepanikan_warga": "<analisis>",
    "note": "Audio tidak dapat diverifikasi langsung — estimasi berbasis konteks visual"
  },
  "infrastructure_analysis": {
    "palang_pintu": "<ada/tidak/rusak — dari thumbnail>",
    "sinyal_aktif": "<analisis lampu di thumbnail>",
    "perlintasan_type": "<resmi/liar>",
    "visibility_malam": "<analisis>"
  },
  "yolo_simulation": {
    "detected_objects": [
      {"class": "car", "status": "STATIONARY_ON_TRACK", "confidence_simulated": 0.94},
      {"class": "person", "count_estimated": "4-8", "status": "PUSHING_VEHICLE"},
      {"class": "train", "status": "INCOMING", "confidence_simulated": 0.91}
    ],
    "stall_detection_logic": "displacement < 20px per 5s = MOGOK",
    "golden_window_action": "Kirim sinyal darurat ke masinis KA terdekat"
  },
  "action_recommendation": "EVAKUASI SEGERA — Kirim sinyal darurat ke masinis KA terdekat. Aktifkan palang pintu darurat. Hubungi 119/KAI Emergency."
}
"""

from google import genai
from google.genai import types
from PIL import Image

client = genai.Client(api_key=API_KEY)

# Baca thumbnail
img = Image.open("frame_analisis_kalibata/thumb.webp")

response = client.models.generate_content(
    model="gemini-2.0-flash",
    contents=[
        types.Part.from_bytes(
            data=open("frame_analisis_kalibata/thumb.webp","rb").read(),
            mime_type="image/webp"
        ),
        PROMPT
    ]
)

text = response.text.strip()
# Bersihkan markdown
if "```" in text:
    parts = text.split("```")
    for p in parts:
        if p.strip().startswith("{") or p.strip().startswith("json\n{"):
            text = p.strip()
            if text.startswith("json"):
                text = text[4:].strip()
            break

print(text)
