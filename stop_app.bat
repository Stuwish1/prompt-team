@echo off
echo Stoppar Prompt Team...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8001"') do taskkill /PID %%a /F 2>nul
echo Klart.
timeout /t 2 /nobreak >nul
