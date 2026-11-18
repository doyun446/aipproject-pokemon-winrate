@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Python environment missing. Follow setup in README.md.
    pause
    exit /b 1
)
if not exist "model\model.pt" (
    echo Trained model missing. Follow training in README.md.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m streamlit run app.py
if errorlevel 1 pause
