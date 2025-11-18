#!/usr/bin/env pwsh
# Start the backend and frontend servers

Write-Host "Starting backend server..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd backend; uvicorn app.main:app --reload --port 8000"

Write-Host "Backend started on http://localhost:8000" -ForegroundColor Green
Write-Host "You can now test the frontend at http://localhost:5174" -ForegroundColor Green
