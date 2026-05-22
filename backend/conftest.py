"""
pytest configuration dan test utilities untuk Traffic Anomaly Detection Backend
"""

import pytest
import numpy as np
from pathlib import Path
from PIL import Image
import cv2
from io import BytesIO


@pytest.fixture
def sample_image():
    """Create sample test image (dummy image untuk testing)"""
    image_array = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
    return image_array


@pytest.fixture
def sample_image_bytes():
    """Create sample image as bytes untuk file upload"""
    image_array = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
    image_pil = Image.fromarray(cv2.cvtColor(image_array, cv2.COLOR_BGR2RGB))
    img_bytes = BytesIO()
    image_pil.save(img_bytes, format='JPEG')
    img_bytes.seek(0)
    return img_bytes.getvalue()


@pytest.fixture
def sample_detections():
    """Create sample YOLOv8 detections untuk testing tracker"""
    return [
        {
            'class_name': 'car',
            'confidence': 0.95,
            'bbox': {'x1': 100, 'y1': 150, 'x2': 300, 'y2': 400},
            'center_x': 200,
            'center_y': 275
        },
        {
            'class_name': 'motorcycle',
            'confidence': 0.87,
            'bbox': {'x1': 400, 'y1': 200, 'x2': 500, 'y2': 350},
            'center_x': 450,
            'center_y': 275
        }
    ]


pytest_plugins = []


def pytest_configure(config):
    """Register custom markers"""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests"
    )
