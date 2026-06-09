@echo off
echo.
echo  ╔══════════════════════════════╗
echo  ║       PROMPT TEAM            ║
echo  ║   AI-granskningsteam         ║
echo  ╚══════════════════════════════╝
echo.
echo  Startar pa http://localhost:8001
echo.
cd /d "%~dp0"
pip install fastapi uvicorn anthropic --quiet 2>nul
python app.py
pause
