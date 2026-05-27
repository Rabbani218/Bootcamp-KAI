import os
import sys
import time
import pytest
import psutil
from pathlib import Path
from unittest.mock import MagicMock

# Daftarkan folder backend ke sys.path
BACKEND_DIR = Path(__file__).parent.parent.parent / "backend"
sys.path.append(str(BACKEND_DIR))

from main import VideoStreamer

# Path video dummy
TESTER_DIR = Path(__file__).parent.parent.parent / "Tester"
VIDEO_NAME = "Mobil macet di tengah rel disaat kereta mau Lewat di Kalibata Jaksel.mp4"
VIDEO_PATH = str(TESTER_DIR / VIDEO_NAME)

class MockTensor:
    def __init__(self, data):
        self.data = data
    def cpu(self):
        return self
    def tolist(self):
        return self.data
    def numpy(self):
        return self
    def astype(self, dtype):
        return self

class MockBox:
    def __init__(self):
        # Format Ultralytics: xyxy, conf, cls, id
        self.xyxy = [MockTensor([100, 100, 300, 300])] 
        self.conf = [0.9]
        self.cls = [2] # 2 = car
        self.id = [777] # Track ID

class MockResult:
    def __init__(self):
        self.boxes = [MockBox()]
        self.names = {2: 'car'}
        
    def plot(self, **kwargs):
        # Return dummy frame
        import numpy as np
        return np.zeros((480, 640, 3), dtype=np.uint8)

@pytest.fixture(scope="module")
def yolo_model_mock():
    """Fixture untuk mem-bypass PyTorch/ONNX yang rusak menggunakan Mock."""
    mock_model = MagicMock()
    mock_model.names = {2: 'car'}
    mock_model.track.return_value = [MockResult()]
    mock_model.predict.return_value = [MockResult()]
    yield mock_model

def test_yolo_logic_and_memory(yolo_model_mock):
    """
    Assert 1: YOLO Tracking Logika Aktif (Menerima Track ID 777)
    Assert 2: Logika "Kendaraan Terjebak" berfungsi (centroid menetap > 5 detik)
    Assert 3: Memory Profiling tidak melonjak tajam
    """
    # Override cv2.resize dan konversi di main.py agar tidak memanggil pytorch .numpy() 
    # Karena kita sudah me-mock return valuenya.
    streamer = VideoStreamer(VIDEO_PATH, "upload", yolo_model_mock)
    streamer.start()
    
    time.sleep(1) # Tunggu inisialisasi
    
    stationary_detected = False
    track_id_found      = False
    
    process = psutil.Process(os.getpid())
    mem_start = process.memory_info().rss
    
    start_time = time.time()
    
    try:
        # Kita butuh > 5 detik agar sistem melabelinya sebagai "Mogok"
        while time.time() - start_time < 10:
            dets = streamer.get_latest_detections()
            if dets:
                for d in dets:
                    if d.get("track_id") == 777:
                        track_id_found = True
                    
                    if d.get("mogok") is True:
                        stationary_detected = True
                        break
            
            if stationary_detected:
                break
                
            time.sleep(0.5)
    finally:
        streamer.stop()
        
    mem_end = process.memory_info().rss
    mem_diff_mb = (mem_end - mem_start) / (1024 * 1024)
    
    print(f"\n--- HASIL TEST AUTOMATION ---")
    print(f"Lama pengecekan : {time.time() - start_time:.2f} detik")
    print(f"Memory Naik     : {mem_diff_mb:.2f} MB")
    
    assert track_id_found, "ByteTrack ID gagal diekstrak dari model tracking!"
    assert stationary_detected, "Gagal mendeteksi kendaraan terjebak (mogok) dalam > 5 detik!"
    assert mem_diff_mb < 1500, f"Memory leak terdeteksi! RAM melonjak {mem_diff_mb:.2f} MB"

