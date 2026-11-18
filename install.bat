@echo off
cd /d "%~dp0"
echo Installing BrakePoint requirements...
python -m pip install -r requirements.txt
echo.
echo Done. Use record.bat while driving, then analyze.bat.
pause
