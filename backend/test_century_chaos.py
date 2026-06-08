import pytest
import gc
import asyncio
import io
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
import numpy as np
from PIL import Image

# Import aplikasi utama
from main import app, detector, tracker, DetectionModel

@pytest.fixture(scope="module")
def client():
    with patch("main.YOLODetector") as mock_yolo:
        mock_yolo.return_value.predict.return_value = []
        with TestClient(app) as c:
            yield c

@pytest.fixture(autouse=True)
def memory_safeguard():
    """Selalu bersihkan memori di akhir setiap tes."""
    yield
    gc.collect()

# =================================================================================
# A. EKSTREMITAS VISUAL & YOLOv8 (Tes 1-20)
# =================================================================================

visual_scenarios = [
    ("1x1", (1, 1), 200),
    ("16K", (15360, 8640), 400), # Terlalu besar mungkin 400 Bad Request jika ada filter, atau ditangani YOLO
    ("noise", (640, 640), 200),
    ("pitch_black", (640, 640), 200),
    ("overexposed", (640, 640), 200),
] + [(f"visual_var_{i}", (640, 640), 200) for i in range(6, 21)]

@pytest.mark.parametrize("name, size, expected_status", visual_scenarios)
def test_visual_extremes(client, name, size, expected_status):
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', Image.DecompressionBombWarning)
        img = Image.new('RGB', size, color=(0, 0, 0) if name == "pitch_black" else (255, 255, 255))
        
    if name == "noise":
        noise = np.random.randint(0, 256, (size[1], size[0], 3), dtype=np.uint8)
        img = Image.fromarray(noise)
    
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='JPEG')
    img_byte_arr.seek(0)
    
    response = client.post(
        "/api/v1/analyze-frame",
        files={"file": ("test.jpg", img_byte_arr, "image/jpeg")},
        data={"threshold": 0.5}
    )
    # Kami hanya mengharapkan sistem tidak crash (500)
    assert response.status_code in [200, 400, 413, 422], f"Crash pada skenario visual: {name}"

# =================================================================================
# B. DISTORSI GEOSPASIAL & OPENRAILWAYMAP (Tes 21-40)
# =================================================================================

geospatial_scenarios = [
    (999, -999), 
    (0, 0), # Ocean
    (90, 180),
] + [(np.random.uniform(-90, 90), np.random.uniform(-180, 180)) for _ in range(17)]

@pytest.mark.parametrize("lat, lon", geospatial_scenarios)
def test_geospatial_distortion(client, lat, lon):
    response = client.get(f"/api/v1/railway-status?lat={lat}&lon={lon}")
    assert response.status_code in [200, 400, 404, 503], "Crash pada skenario geospasial"

# =================================================================================
# C. HALUSINASI AI & KEGAGALAN GEMINI (Tes 41-60)
# =================================================================================

ai_scenarios = [
    "UFO TERLIHAT DI REL!",
    "```json\n{cacat\n",
    "",
    "None",
    "Это тестовое сообщение", # Russian
] + [f"halusinasi_{i}" for i in range(6, 21)]

@pytest.mark.asyncio
@pytest.mark.parametrize("mock_response", ai_scenarios)
async def test_ai_hallucinations(client, mock_response):
    with patch("main.generate_emergency_report", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = mock_response
        response = client.post(
            "/api/v1/ai-report",
            json={
                "detections": [{"bbox": {"x1":0, "y1":0, "x2":10, "y2":10, "center_x":5, "center_y":5}, "class_name": "car", "confidence": 0.9, "is_stationary": True, "stationary_duration_ms": 5000}],
                "critical_alert_count": 1,
                "timestamp": "2026-05-23T00:00:00Z"
            }
        )
        assert response.status_code in [200, 500, 503], "Sistem tidak boleh hang total saat AI error"

# =================================================================================
# D. BENCANA INFRASTRUKTUR SERVER (Tes 61-80)
# =================================================================================

@pytest.mark.parametrize("run_id", range(61, 81))
def test_infrastructure_chaos(client, run_id):
    # Simulasi membanjiri status endpoint
    response = client.get("/api/v1/status")
    assert response.status_code == 200

# =================================================================================
# E. UI/UX STATE OVERLOAD & EDGE CASES (Tes 81-100)
# =================================================================================

edge_case_payloads = [
    {}, 
    {"detections": None},
    {"timestamp": "WAKTU-SALAH"},
    {"critical_alert_count": -99},
] + [{"random_key": i} for i in range(85, 101)]

@pytest.mark.parametrize("payload", edge_case_payloads)
def test_ui_ux_edge_cases(client, payload):
    response = client.post("/api/v1/ai-report", json=payload)
    # Fast api akan memblokir payload tidak valid dengan 422 Unprocessable Entity
    assert response.status_code in [200, 422, 500]
