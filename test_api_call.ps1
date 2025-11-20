# Test script to verify backend API is accessible and file export works

Write-Host "Testing backend health endpoint..."
try {
    $health = Invoke-RestMethod -Uri "http://localhost:8000/health" -Method Get
    Write-Host "✓ Backend is healthy: $($health.status)" -ForegroundColor Green
} catch {
    Write-Host "✗ Backend health check failed: $_" -ForegroundColor Red
    exit 1
}

Write-Host "`nTesting IV simulation stream endpoint..."

# Minimal test payload - use JSON string directly to avoid PowerShell conversion issues
$payload = @'
{
    "plasma": {
        "ne": 1e16,
        "te_eV": 3.0,
        "vs": 0.0,
        "gas_type": "argon",
        "mi_custom": null
    },
    "probe": {
        "area": 1e-4,
        "radius": 0.005,
        "length": 0.01,
        "capacitance": 1e-12
    },
    "model": "oml",
    "rf": {
        "frequency_hz": 13560000.0,
        "te_amplitude_ev": 0.5,
        "ne_amplitude": 0.1,
        "vs_amplitude_v": 10.0
    },
    "time_range": {
        "total_time_s": 1e-6,
        "dt_s": 1e-9,
        "voltage_step_rf_cycles": null
    },
    "vp_initial": -20.0,
    "vp_final": 20.0,
    "integrator": "rk4"
}
'@

Write-Host "Sending request to /api/iv/dynamic/stream..."
Write-Host "Payload: $($payload.Substring(0, [Math]::Min(200, $payload.Length)))..."

try {
    # Use curl to test the streaming endpoint
    $response = curl.exe -X POST "http://localhost:8000/api/iv/dynamic/stream" `
        -H "Content-Type: application/json" `
        -d $payload `
        --no-buffer `
        -s `
        -w "`n%{http_code}"
    
    $statusCode = $response[-1]
    Write-Host "`nHTTP Status Code: $statusCode"
    
    if ($statusCode -eq "200") {
        Write-Host "✓ Stream endpoint responded successfully" -ForegroundColor Green
        Write-Host "`nFirst few lines of response:"
        $response[0..([Math]::Min(5, $response.Length - 2))] | ForEach-Object { Write-Host $_ }
    } else {
        Write-Host "✗ Unexpected status code" -ForegroundColor Red
        Write-Host "Response: $response"
    }
} catch {
    Write-Host "✗ Request failed: $_" -ForegroundColor Red
}

Write-Host "`n`nChecking for exported files..."
$exportDir = "c:\Users\30655\Desktop\techTools\probe\iv_exports"
$txtFiles = Get-ChildItem -Path $exportDir -Filter *.txt -ErrorAction SilentlyContinue | 
    Sort-Object LastWriteTime -Descending | 
    Select-Object -First 5

if ($txtFiles) {
    Write-Host "✓ Found exported files:" -ForegroundColor Green
    $txtFiles | Format-Table Name, Length, LastWriteTime -AutoSize
} else {
    Write-Host "✗ No .txt files found in $exportDir" -ForegroundColor Red
}
