import subprocess
import time
import psutil

def check_process_exists(name_keywords):
    """Cek apakah ada proses yang mengandung keyword tertentu di command line-nya."""
    found = []
    for p in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmd = p.info.get('cmdline')
            if cmd:
                cmd_str = " ".join(cmd).lower()
                if all(k.lower() in cmd_str for k in name_keywords):
                    found.append(p.info['pid'])
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return found

def test_graceful_shutdown():
    print("[TEST] Memulai Desktop Launcher (app.py) di background...")
    launcher = subprocess.Popen(["python", "app.py"])
    
    # Tunggu beberapa detik agar app.py menyalakan backend & frontend
    time.sleep(10)
    
    # Verifikasi server berjalan (uvicorn & next.js)
    backend_pids = check_process_exists(["uvicorn", "main:app"])
    frontend_pids = check_process_exists(["npm", "run", "dev"])
    
    print(f"[STATUS] PIDs Backend: {backend_pids}")
    print(f"[STATUS] PIDs Frontend: {frontend_pids}")
    
    if not backend_pids and not frontend_pids:
        print("[!] Peringatan: Proses backend/frontend mungkin gagal menyala. Lanjut tes shutdown.")
        
    print("[TEST] Mengirim sinyal terminate ke launcher...")
    import sys
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(launcher.pid)], capture_output=True)
    else:
        launcher.terminate()
    
    try:
        launcher.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
    time.sleep(3) # Tunggu OS membersihkan resources
    
    # Cek apakah ada yang bocor/zombie
    backend_pids_after = check_process_exists(["uvicorn", "main:app"])
    frontend_pids_after = check_process_exists(["node", "frontend"]) # Node processes for frontend
    
    if not backend_pids_after and not frontend_pids_after:
        print("[SUCCESS] Graceful Shutdown berhasil! Tidak ada proses orphan/zombie.")
    else:
        print(f"[FAIL] Memory Leak / Orphan Process terdeteksi!")
        print(f"Bocor Backend PIDs: {backend_pids_after}")
        print(f"Bocor Frontend PIDs: {frontend_pids_after}")

if __name__ == "__main__":
    test_graceful_shutdown()
