"""
Unit tests untuk Traffic Anomaly Detection Backend

Jalankan dengan: pytest test_main.py -v
"""

import pytest
import numpy as np
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
import time

# Import aplikasi FastAPI
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
        tracker = TemporalAnomalyTracker()
        
        obj_id_1 = tracker._calculate_object_id(100.5, 200.3, 'car')
        obj_id_2 = tracker._calculate_object_id(101.2, 201.1, 'car')
        
        # Kedua objek dalam tolerance radius, seharusnya punya ID yang sama
        assert obj_id_1 == obj_id_2
    
    def test_position_tolerance_check(self):
        """Test toleransi posisi"""
        tracker = TemporalAnomalyTracker(position_tolerance_pixels=20)
        
        pos1 = (100, 200)
        pos2_within = (110, 210)  # Distance ~ 14.14 < 20
        pos2_outside = (130, 230)  # Distance ~ 42.43 > 20
        
        assert tracker._is_within_tolerance(pos1, pos2_within) == True
        assert tracker._is_within_tolerance(pos1, pos2_outside) == False
    
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
        
        assert 'stationary_objects' in result
        assert 'critical_alerts' in result
        assert 'total_tracked' in result
        assert result['total_tracked'] == 1
    
    def test_critical_alert_trigger(self):
        """Test CRITICAL_ALERT dipicu ketika objek diam >5 detik"""
        tracker = TemporalAnomalyTracker(
            stationary_threshold_ms=100,  # 100ms untuk testing
            position_tolerance_pixels=50  # Large tolerance untuk consistency
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
        
        # Update beberapa kali dalam waktu singkat
        result1 = tracker.update(detections)
        assert len(result1['critical_alerts']) == 0
        
        time.sleep(0.15)  # Sleep 150ms > threshold 100ms
        
        result2 = tracker.update(detections)  # Same position
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
        assert data['name'] == 'Traffic Anomaly Detection Backend'
        assert 'endpoints' in data


class TestAnalyzeFrameEndpoint:
    """Test main analyze-frame endpoint"""
    
    @patch('main.detector')
    @patch('main.tracker')
    def test_analyze_frame_with_image(self, mock_tracker, mock_detector, client, sample_image_bytes):
        """Test POST /api/v1/analyze-frame dengan gambar valid"""
        # Mock detector.predict
        mock_detector.predict.return_value = [
            {
                'class_name': 'car',
                'confidence': 0.95,
                'bbox': {'x1': 100, 'y1': 150, 'x2': 300, 'y2': 400},
                'center_x': 200,
                'center_y': 275
            }
        ]
        
        # Mock tracker.update
        mock_tracker.update.return_value = {
            'stationary_objects': [],
            'critical_alerts': [],
            'total_tracked': 1
        }
        mock_tracker.critical_alerts = []
        
        # Upload gambar
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
    
    def test_analyze_frame_invalid_file_type(self, client):
        """Test POST /api/v1/analyze-frame dengan file type salah"""
        response = client.post(
            "/api/v1/analyze-frame",
            files={"file": ("test.txt", b"not an image", "text/plain")}
        )
        
        assert response.status_code == 400
        data = response.json()
        assert data['status'] == 'error'
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
        
        # Verify tracker was cleared
        mock_tracker.tracked_objects.clear.assert_called()
        mock_tracker.critical_alerts.clear.assert_called()


# ============================================================================
# Test CORS Configuration
# ============================================================================

class TestCORSConfiguration:
    """Test CORS middleware configuration"""
    
    def test_cors_headers_present(self, client):
        """Test CORS headers ada di response"""
        response = client.get(
            "/api/health",
            headers={"Origin": "http://localhost:3000"}
        )
        
        assert response.status_code == 200
        # CORS headers should be present
        assert "access-control-allow-origin" in response.headers or \
               "access-control-allow-credentials" in response.headers


# ============================================================================
# Integration Tests
# ============================================================================

class TestIntegration:
    """Integration tests untuk full workflow"""
    
    @patch('main.detector')
    @patch('main.tracker')
    def test_full_anomaly_detection_flow(self, mock_tracker, mock_detector, 
                                         client, sample_image_bytes):
        """Test full flow dari upload gambar hingga alert"""
        
        # Setup mocks
        mock_detector.predict.return_value = [
            {
                'class_name': 'car',
                'confidence': 0.92,
                'bbox': {'x1': 100, 'y1': 150, 'x2': 300, 'y2': 400},
                'center_x': 200,
                'center_y': 275
            }
        ]
        
        mock_tracker.update.return_value = {
            'stationary_objects': [
                {
                    'class_name': 'car',
                    'confidence': 0.92,
                    'bbox': {'x1': 100, 'y1': 150, 'x2': 300, 'y2': 400},
                    'center_x': 200,
                    'center_y': 275,
                    'is_stationary': True,
                    'stationary_duration_ms': 5500
                }
            ],
            'critical_alerts': [{
                'object_id': 'car_200_280',
                'class': 'car',
                'position': (200, 275),
                'duration_ms': 5500
            }],
            'total_tracked': 1
        }
        mock_tracker.critical_alerts = ['car_200_280']
        
        # Send request
        response = client.post(
            "/api/v1/analyze-frame",
            files={"file": ("test.jpg", sample_image_bytes, "image/jpeg")}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify response
        assert data['alert_triggered'] == True
        assert data['critical_alert_count'] == 1
        assert len(data['detections']) == 1
        assert data['detections'][0]['is_stationary'] == True


# ============================================================================
# Benchmark Tests
# ============================================================================

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
            'stationary_objects': [],
            'critical_alerts': [],
            'total_tracked': 0
        }
        mock_tracker.critical_alerts = []
        
        response = client.post(
            "/api/v1/analyze-frame",
            files={"file": ("test.jpg", sample_image_bytes, "image/jpeg")}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Inference time should be reasonable
        assert data['inference_time_ms'] < 1000  # Less than 1 second


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
