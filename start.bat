@echo off
cd /d "%~dp0"
pip install fastapi uvicorn anthropic httpx openai --quiet 2>nul
start "" /min cmd /c "python app.py"
timeout /t 2 /nobreak >nul
start http://localhost:8001
