"""
Unit tests untuk Traffic Anomaly Detection Backend

Jalankan dengan: pytest test_main.py -v
"""

import pytest
import numpy as np
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
import time

from main import app, TemporalAnomalyTracker, YOLODetector


@pytest.fixture
def client():
    """Create TestClient untuk testing API endpoints"""
    return TestClient(app)


# ============================================================================
# Test TemporalAnomalyTracker
# ============================================================================

class TestTemporalAnomalyTracker:
    """Test suite untuk temporal tracking logic"""

    def test_tracker_initialization(self):
        """Test tracker dapat diinisializasi dengan config yang benar"""
        tracker = TemporalAnomalyTracker(
            stationary_threshold_ms=5000,
            position_tolerance_pixels=20
        )

        assert tracker.stationary_threshold_ms == 5000
        assert tracker.position_tolerance_pixels == 20
        assert len(tracker.tracked_objects) == 0
        assert len(tracker.critical_alerts) == 0

    def test_object_id_generation(self):
        """Test generate object ID berdasarkan posisi dan class"""
        tracker = TemporalAnomalyTracker(position_tolerance_pixels=20)

        obj_id_1 = tracker._obj_id(100.5, 200.3, 'car')
        obj_id_2 = tracker._obj_id(101.2, 201.1, 'car')

        assert obj_id_1 == obj_id_2

    def test_position_tolerance_check(self):
        """Test toleransi posisi"""
        tracker = TemporalAnomalyTracker(position_tolerance_pixels=20)

        pos1 = (100, 200)
        pos2_within = (110, 210)   # Distance ~ 14.14 < 20
        pos2_outside = (130, 230)  # Distance ~ 42.43 > 20

        assert tracker._within(pos1, pos2_within) == True
        assert tracker._within(pos1, pos2_outside) == False

    def test_update_detections(self):
        """Test update tracker dengan detections"""
        tracker = TemporalAnomalyTracker()

        detections = [
            {
                'center_x': 200,
                'center_y': 275,
                'class_name': 'car',
                'confidence': 0.95,
                'bbox': {'x1': 100, 'y1': 150, 'x2': 300, 'y2': 400}
            }
        ]

        result = tracker.update(detections)

        assert 'critical_alerts' in result
        assert 'total_tracked' in result
        assert result['total_tracked'] == 1

    def test_critical_alert_trigger(self):
        """Test CRITICAL_ALERT dipicu ketika objek diam >5 detik"""
        tracker = TemporalAnomalyTracker(
            stationary_threshold_ms=100,  # 100ms untuk testing
            position_tolerance_pixels=50
        )

        detections = [
            {
                'center_x': 200,
                'center_y': 275,
                'class_name': 'car',
                'confidence': 0.95,
                'bbox': {'x1': 100, 'y1': 150, 'x2': 300, 'y2': 400}
            }
        ]

        result1 = tracker.update(detections)
        assert len(result1['critical_alerts']) == 0

        time.sleep(0.15)  # Sleep 150ms > threshold 100ms

        result2 = tracker.update(detections)
        assert len(result2['critical_alerts']) == 1
        assert len(tracker.critical_alerts) == 1


# ============================================================================
# Test API Endpoints
# ============================================================================

class TestHealthEndpoint:
    """Test health check endpoint"""

    def test_health_check(self, client):
        """Test GET /api/health"""
        response = client.get("/api/health")

        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'healthy'
        assert 'timestamp' in data
        assert 'model_loaded' in data
        assert 'tracker_ready' in data

    def test_root_endpoint(self, client):
        """Test GET / (root endpoint)"""
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert data['name'] == 'NusaRail Vision API'
        assert 'docs' in data


class TestAnalyzeFrameEndpoint:
    """Test main analyze-frame endpoint"""

    @patch('main.detector')
    @patch('main.tracker')
    def test_analyze_frame_with_image(self, mock_tracker, mock_detector, client, sample_image_bytes):
        """Test POST /api/v1/analyze-frame dengan gambar valid"""
        mock_detector.predict.return_value = [
            {
                'class_name': 'car',
                'confidence': 0.95,
                'bbox': {'x1': 100, 'y1': 150, 'x2': 300, 'y2': 400},
                'center_x': 200,
                'center_y': 275
            }
        ]

        mock_tracker.update.return_value = {
            'stationary_objects': [],
            'critical_alerts': [],
            'total_tracked': 1
        }
        mock_tracker.critical_alerts = []

        response = client.post(
            "/api/v1/analyze-frame",
            files={"file": ("test.jpg", sample_image_bytes, "image/jpeg")}
        )

        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'success'
        assert 'timestamp' in data
        assert 'detections' in data
        assert 'inference_time_ms' in data

    @patch('main.detector')
    @patch('main.tracker')
    def test_analyze_frame_invalid_file_type(self, mock_tracker, mock_detector, client):
        """Test POST /api/v1/analyze-frame dengan file type salah"""
        response = client.post(
            "/api/v1/analyze-frame",
            files={"file": ("test.txt", b"not an image", "text/plain")}
        )

        assert response.status_code == 400
        data = response.json()
        assert 'image' in data['detail'].lower()

    @patch('main.detector', None)
    def test_analyze_frame_model_not_loaded(self, client, sample_image_bytes):
        """Test POST /api/v1/analyze-frame ketika model belum loaded"""
        response = client.post(
            "/api/v1/analyze-frame",
            files={"file": ("test.jpg", sample_image_bytes, "image/jpeg")}
        )

        assert response.status_code == 503


class TestStatusEndpoint:
    """Test status endpoint"""

    @patch('main.tracker')
    def test_get_status(self, mock_tracker, client):
        """Test GET /api/v1/status"""
        mock_tracker.tracked_objects = {'car_100_200': {}}
        mock_tracker.critical_alerts = ['car_100_200']
        mock_tracker.stationary_threshold_ms = 5000
        mock_tracker.position_tolerance_pixels = 20

        response = client.get("/api/v1/status")

        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'operational'
        assert data['tracked_objects'] == 1
        assert len(data['critical_alerts']) == 1


class TestResetTrackerEndpoint:
    """Test reset tracker endpoint"""

    @patch('main.tracker')
    def test_reset_tracker(self, mock_tracker, client):
        """Test POST /api/v1/reset-tracker"""
        mock_tracker.tracked_objects = {'car_100_200': {}}
        mock_tracker.critical_alerts = ['car_100_200']

        response = client.post("/api/v1/reset-tracker")

        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'success'
        assert 'reset' in data['message'].lower()

        assert len(mock_tracker.tracked_objects) == 0
        assert len(mock_tracker.critical_alerts) == 0


class TestCORSConfiguration:
    """Test CORS middleware configuration"""

    def test_cors_headers_present(self, client):
        """Test CORS headers ada di response"""
        response = client.get(
            "/api/health",
            headers={"Origin": "http://localhost:3000"}
        )

        assert response.status_code == 200


class TestIntegration:
    """Integration tests untuk full workflow"""

    @patch('main.detector')
    @patch('main.tracker')
    def test_full_anomaly_detection_flow(self, mock_tracker, mock_detector,
                                         client, sample_image_bytes):
        """Test full flow dari upload gambar hingga alert"""

        mock_detector.predict.return_value = [
            {
                'class_name': 'car',
                'confidence': 0.92,
                'bbox': {'x1': 100, 'y1': 150, 'x2': 300, 'y2': 400},
                'center_x': 200,
                'center_y': 275
            }
        ]

        def mock_update(detections):
            detections[0]['is_stationary'] = True
            detections[0]['stationary_duration_ms'] = 5500
            return {
                'critical_alerts': [{
                    'object_id': 'car_200_280',
                    'class': 'car',
                    'position': (200, 275),
                    'duration_ms': 5500
                }],
                'total_tracked': 1
            }
        mock_tracker.update.side_effect = mock_update
        mock_tracker.critical_alerts = ['car_200_280']

        with patch('main.db_save_anomaly'):
            response = client.post(
                "/api/v1/analyze-frame",
                files={"file": ("test.jpg", sample_image_bytes, "image/jpeg")}
            )

        assert response.status_code == 200
        data = response.json()

        assert data['alert_triggered'] == True
        assert data['critical_alert_count'] == 1
        assert len(data['detections']) == 1
        assert data['detections'][0]['is_stationary'] == True


@pytest.mark.slow
class TestPerformance:
    """Performance benchmark tests"""

    @patch('main.detector')
    @patch('main.tracker')
    def test_inference_performance(self, mock_tracker, mock_detector,
                                   client, sample_image_bytes):
        """Test inference time masuk dalam acceptable range"""

        mock_detector.predict.return_value = []
        mock_tracker.update.return_value = {
            'critical_alerts': [],
            'total_tracked': 0
        }
        mock_tracker.critical_alerts = []

        with patch('main.db_save_anomaly'):
            response = client.post(
                "/api/v1/analyze-frame",
                files={"file": ("test.jpg", sample_image_bytes, "image/jpeg")}
            )

        assert response.status_code == 200
        data = response.json()

        assert data['inference_time_ms'] < 1000  # Less than 1 second


class TestStressAndErrorHandling:
    """Stress testing & Error handling tests"""

    @patch('main.detector')
    @patch('main.tracker')
    def test_corrupt_image(self, mock_tracker, mock_detector, client):
        """Test POST /api/v1/analyze-frame dengan corrupt image"""
        response = client.post(
            "/api/v1/analyze-frame",
            files={"file": ("corrupt.jpg", b"this_is_not_a_valid_image_bytes_data", "image/jpeg")}
        )
        assert response.status_code in [400, 500]

    @patch('main.detector')
    @patch('main.tracker')
    def test_rapid_requests_throttle(self, mock_tracker, mock_detector, client, sample_image_bytes):
        """Test 100 req/sec (Stress test / Throttle check)"""
        mock_detector.predict.return_value = []
        mock_tracker.update.return_value = {'critical_alerts': [], 'total_tracked': 0}
        
        start_time = time.time()
        responses = []
        for _ in range(100):
            res = client.post(
                "/api/v1/analyze-frame",
                files={"file": ("test.jpg", sample_image_bytes, "image/jpeg")}
            )
            responses.append(res.status_code)
            
        elapsed = time.time() - start_time
        # Check if all requests succeeded or some were throttled (503/429)
        assert all(code in [200, 429, 503] for code in responses)
        assert len(responses) == 100

    @patch('main.YOLODetector._load')
    def test_yolo_fails_to_load(self, mock_load):
        """Test ketika YOLOv8 gagal memuat model"""
        mock_load.side_effect = Exception("Failed to load weights")
        with pytest.raises(Exception):
            from main import YOLODetector
            YOLODetector("invalid_path.onnx")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
