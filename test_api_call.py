"""Test script to verify backend API and file export"""
import requests
import json
from pathlib import Path

API_BASE = "http://localhost:8000"

print("Testing backend health endpoint...")
try:
    response = requests.get(f"{API_BASE}/health")
    print(f"✓ Backend is healthy: {response.json()}")
except Exception as e:
    print(f"✗ Backend health check failed: {e}")
    exit(1)

print("\nTesting IV simulation stream endpoint...")

payload = {
    "plasma": {
        "ne": 1e16,
        "te_eV": 3.0,
        "vs": 0.0,
        "gas_type": "Ar",  # Must be 'H', 'Ar' or 'custom'
        "mi_custom": None
    },
    "probe": {
        "area": 1e-4,
        "radius": 0.005,
        "length": 0.01,
        "capacitance": 1e-12
    },
    "model": "OML",  # Must be 'OML', 'ABR', 'BRL' or 'ChildLangmuir'
    "rf": {
        "frequency_hz": 13.56e6,
        "te_amplitude_ev": 0.5,
        "ne_amplitude": 0.1,
        "vs_amplitude_v": 10.0
    },
    "time_range": {
        "total_time_s": 1e-6,
        "dt_s": 1e-9,
        "voltage_step_rf_cycles": None
    },
    "vp_initial": -20.0,
    "vp_final": 20.0,
    "integrator": "rk4"
}

print(f"Sending request to {API_BASE}/api/iv/dynamic/stream...")
try:
    response = requests.post(
        f"{API_BASE}/api/iv/dynamic/stream",
        json=payload,
        stream=True,
        timeout=30
    )
    
    print(f"Status code: {response.status_code}")
    
    if response.status_code == 200:
        print("✓ Stream endpoint responded successfully")
        print("\nFirst few chunks:")
        chunk_count = 0
        for line in response.iter_lines():
            if line:
                decoded = line.decode('utf-8')
                if decoded.startswith('data: '):
                    chunk_count += 1
                    data = json.loads(decoded[6:])
                    if 'vp' in data:
                        print(f"  Chunk {chunk_count}: {len(data['vp'])} data points, progress: {data.get('progress', 'N/A')}")
                    elif 'metadata' in data:
                        print(f"  Metadata: {data['metadata']}")
                    elif 'error' in data:
                        print(f"  ERROR: {data['error']}")
                    
                    if chunk_count >= 3:
                        break
        print(f"\nReceived {chunk_count} chunks before stopping")
    else:
        print(f"✗ Unexpected status code: {response.status_code}")
        print(f"Response: {response.text}")
except Exception as e:
    print(f"✗ Request failed: {e}")
    import traceback
    traceback.print_exc()

print("\n\nChecking for exported files...")
export_dir = Path(r"c:\Users\30655\Desktop\techTools\probe\iv_exports")
txt_files = sorted(export_dir.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)[:5]

if txt_files:
    print("✓ Found exported files:")
    for f in txt_files:
        stat = f.stat()
        print(f"  {f.name}: {stat.st_size} bytes, modified {stat.st_mtime}")
else:
    print(f"✗ No .txt files found in {export_dir}")
