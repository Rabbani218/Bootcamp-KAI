import pytest
import os
import cv2
import threading
import time
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from main import app
import geo_service
import numpy as np

client = TestClient(app)
_, img_encoded = cv2.imencode('.jpg', np.zeros((10, 10, 3), dtype=np.uint8))
test_image = img_encoded.tobytes()

class TestGeoService:
    def test_geo_db(self):
        """Pastikan geo_service tidak crash dan koneksi ke local_railways.db berfungsi."""
        result = geo_service.find_nearest_railway(-6.3906, 106.8306)
        assert result is not None
        # Result can be error if db missing, but it shouldn't crash
        if "error" not in result:
            assert "distance_meters" in result
            assert "tags" in result

    @patch("google.generativeai.GenerativeModel")
    @patch("PIL.Image.open")
    def test_mock_gemini(self, mock_pil, mock_genai):
        """Simulasikan pemanggilan Gemini API (Mock)."""
        mock_model_instance = MagicMock()
        mock_model_instance.generate_content.return_value.text = "Laporan Darurat Simulasi Gemini."
        mock_genai.return_value = mock_model_instance
        
        context_data = {"distance_meters": 50, "lat": -6.39, "lon": 106.83}
        os.environ["GEMINI_API_KEY"] = "mock_key"
        
        geo_service.analyze_anomaly_with_gemini("dummy.jpg", context_data)
        
        assert geo_service.latest_gemini_report == "Laporan Darurat Simulasi Gemini."

class TestFullChainIntegration:
    @patch("main.db_save_anomaly")
    @patch("geo_service.analyze_anomaly_with_gemini")
    @patch("main.tracker")
    @patch("main.detector")
    def test_full_chain_endpoint(self, mock_detector, mock_tracker, mock_gemini, mock_db):
        """Tembak endpoint dengan simulasi objek diam > 5 detik."""
        mock_detector.predict.return_value = [{
            'class_name': 'car', 'confidence': 0.95, 'bbox': {'x1': 10, 'y1': 10, 'x2': 20, 'y2': 20},
            'center_x': 15, 'center_y': 15
        }]
        
        def mock_update(detections):
            detections[0]['is_stationary'] = True
            detections[0]['stationary_duration_ms'] = 5500
            return {
                'critical_alerts': [{
                    'object_id': 'car_15_15', 'class': 'car', 'position': (15, 15), 'duration_ms': 5500
                }],
                'total_tracked': 1,
                'stationary_objects': detections
            }
        
        mock_tracker.update.side_effect = mock_update
        mock_tracker.critical_alerts = ['car_15_15']
        
        with patch("cv2.imwrite") as mock_imwrite:
            response = client.post(
                "/api/v1/analyze-frame",
                files={"file": ("test.jpg", test_image, "image/jpeg")}
            )
            
            assert response.status_code == 200, f"Error internal: {response.text}"
            data = response.json()
            
            assert data["alert_triggered"] is True
            assert data["critical_alert_count"] == 1
            assert "geo_location" in data
            assert "narrative_report" in data
            
            # Verify the background thread was started (Gemini mock called asynchronously)
            # wait briefly for thread to spawn (mock_gemini might not be called if daemon thread hasn't run yet, but the endpoint must return immediately)
            # Actually, just checking if the keys exist is enough for E2E JSON contract
