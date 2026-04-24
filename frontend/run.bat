@echo off
echo Installing dependencies...
cd /d %~dp0
npm install

echo.
echo Starting Agent-Pilot Frontend...
echo.
npm run dev
