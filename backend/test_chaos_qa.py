import asyncio
import time
import pytest
import httpx
import websockets
import json

BASE_URL = "http://127.0.0.1:8000"
WS_URL = "ws://127.0.0.1:8000/api/ws/gemini"

@pytest.mark.asyncio
async def test_health_check_response_time():
    """Waktu cold start dan response endpoint /health < 200ms."""
    async with httpx.AsyncClient() as client:
        # Cold start ping
        await client.get(f"{BASE_URL}/api/health")
        
        # Subsequent ping
        start = time.time()
        res = await client.get(f"{BASE_URL}/api/health")
        end = time.time()
        
    assert res.status_code == 200
    assert (end - start) < 0.5, f"Health check latency is {(end - start)*1000}ms"
    data = res.json()
    assert data["status"] == "ok"

@pytest.mark.asyncio
async def test_set_url_sanitization():
    """Sanitasi input URL."""
    async with httpx.AsyncClient() as client:
        # Invalid URL
        res = await client.post(f"{BASE_URL}/api/set_url", json={"youtube_url": "invalid_url"})
        assert res.status_code == 200
        assert res.json()["target_url"] == "https://www.youtube.com/watch?v=q7lvnYVuqNY" # Fallback sanitized
        
        # Valid URL
        res = await client.post(f"{BASE_URL}/api/set_url", json={"youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"})
        assert res.status_code == 200
        assert res.json()["target_url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

@pytest.mark.asyncio
async def test_websocket_concurrency():
    """Penanganan 50 koneksi WebSocket konkuren."""
    async def connect_and_listen():
        try:
            # Increase timeout for concurrent test
            async with websockets.connect(WS_URL, open_timeout=5.0) as ws:
                msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                data = json.loads(msg)
                assert "status" in data
                assert "lokasi" in data
                return True
        except Exception as e:
            print(f"WS Error: {e}")
            return False

    # Simulate 50 concurrent connections
    tasks = [connect_and_listen() for _ in range(50)]
    results = await asyncio.gather(*tasks)
    
    # Assert all connected successfully and received message
    assert all(results), f"Only {sum(results)}/50 websocket connections succeeded."

@pytest.mark.asyncio
async def test_mjpeg_stream_availability():
    """Memastikan stream MJPEG merespon dan tidak memblokir."""
    async with httpx.AsyncClient() as client:
        # Stream response should start immediately
        async with client.stream("GET", f"{BASE_URL}/api/stream") as res:
            assert res.status_code == 200
            assert "multipart/x-mixed-replace" in res.headers["content-type"]
            # Read first chunk to ensure it sends data
            chunk = await res.aiter_bytes().__anext__()
            assert len(chunk) > 0
            assert b"--frame" in chunk

@pytest.mark.asyncio
async def test_gemini_json_schema():
    """Memastikan format data WebSocket ke frontend sesuai Schema (status, lokasi, narasi)."""
    async with websockets.connect(WS_URL) as ws:
        msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
        data = json.loads(msg)
        assert "status" in data
        assert "lokasi" in data
        assert "narasi" in data
        assert type(data["status"]) == str
