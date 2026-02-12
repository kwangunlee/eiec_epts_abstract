@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [1/2] 필요한 패키지 확인 중...
python -m pip install -r requirements_app.txt -q
if errorlevel 1 (
    echo 패키지 설치에 실패했습니다. Python이 설치되어 있는지 확인해 주세요.
    pause
    exit /b 1
)
echo [2/2] EPIC 초록 앱을 시작합니다. 브라우저가 자동으로 열립니다.
echo 종료하려면 이 창을 닫거나 Ctrl+C를 누르세요.
echo.
streamlit run app.py
pause
