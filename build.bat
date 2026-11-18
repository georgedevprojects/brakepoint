@echo off
cd /d "%~dp0"
echo Building BrakePoint.exe ...
python -m pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --onefile --windowed --name BrakePoint --add-data "report_template.html;." brakepoint_app.py
echo.
echo Done: dist\BrakePoint.exe
pause
