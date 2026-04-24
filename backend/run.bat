@echo off
echo Installing dependencies...
cd /d %~dp0
pip install -r requirements.txt

echo.
echo Starting Agent-Pilot Backend...
echo.
python main.py
